"""FTP diagnostics for the daily work report handoff server.

This script avoids importing the PySide2 UI so it can run on machines that only
need to verify FTP connectivity and upload behavior.
"""
import argparse
import ast
import ftplib
import posixpath
import socket
import tempfile
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
MAIN_PY = APP_ROOT / "main.py"


def load_config():
    tree = ast.parse(MAIN_PY.read_text(encoding="utf-8"))
    values = {}
    wanted = {
        "FTP_HOST",
        "FTP_PORT",
        "FTP_USER",
        "FTP_PASSWORD",
        "FTP_ROOT_DIR",
        "FTP_USER_DB_DIR",
        "FTP_DAILY_DATA_DIR",
        "FTP_DAILY_SUMMARY_DIR",
    }
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in wanted:
                values[name] = eval_config_value(node.value, values)
    return values


def eval_config_value(node, values):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in values:
        return values[node.id]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return eval_config_value(node.left, values) + eval_config_value(node.right, values)
    raise ValueError("unsupported config expression: " + ast.dump(node))


def ensure_ftp_directory(ftp, directory):
    normalized_directory = "/".join(segment for segment in directory.split("/") if segment)
    if not normalized_directory:
        return
    try:
        ftp.cwd(normalized_directory)
        return
    except ftplib.error_perm:
        pass
    for part in normalized_directory.split("/"):
        try:
            ftp.cwd(part)
        except ftplib.error_perm:
            ftp.mkd(part)
            ftp.cwd(part)


def connect_ftp(config, timeout):
    ftp = ftplib.FTP()
    ftp.encoding = "utf-8"
    ftp.connect(config["FTP_HOST"], config["FTP_PORT"], timeout=timeout)
    ftp.login(config["FTP_USER"], config["FTP_PASSWORD"])
    ftp.set_pasv(True)
    return ftp


def check_step(label, func):
    try:
        result = func()
    except Exception as exc:
        print("FAIL {0}: {1}: {2}".format(label, type(exc).__name__, exc))
        return False
    if result:
        print("OK   {0}: {1}".format(label, result))
    else:
        print("OK   {0}".format(label))
    return True


def main():
    parser = argparse.ArgumentParser(description="Check FTP connectivity, folders, and optional upload behavior.")
    parser.add_argument("--timeout", type=int, default=10, help="network timeout in seconds")
    parser.add_argument("--upload-test", action="store_true", help="upload and delete a small CSV test file")
    parser.add_argument("--remote-dir", help="override upload-test target directory")
    args = parser.parse_args()

    config = load_config()
    host = config["FTP_HOST"]
    port = config["FTP_PORT"]

    ok = check_step("tcp {0}:{1}".format(host, port), lambda: socket.create_connection((host, port), args.timeout).close())
    if not ok:
        print("HINT 網路層無法連到 FTP；請先確認 VPN/內網、IP、port 21、防火牆或路由。")
        return 1

    ok = check_step("login and root listing", lambda: _login_listing(config, args.timeout))
    if not ok:
        return 1

    for key in ("FTP_ROOT_DIR", "FTP_USER_DB_DIR", "FTP_DAILY_DATA_DIR", "FTP_DAILY_SUMMARY_DIR"):
        if not check_step("ensure directory " + config[key], lambda key=key: _ensure_dir(config, args.timeout, config[key])):
            return 1

    if args.upload_test:
        remote_dir = args.remote_dir or config["FTP_ROOT_DIR"]
        if not check_step("upload test to " + remote_dir, lambda: _upload_test(config, args.timeout, remote_dir)):
            return 1

    return 0


def _login_listing(config, timeout):
    with connect_ftp(config, timeout) as ftp:
        pwd = ftp.pwd()
        names = ftp.nlst()
        return "pwd={0}, entries={1}".format(pwd, len(names))


def _ensure_dir(config, timeout, remote_dir):
    with connect_ftp(config, timeout) as ftp:
        ensure_ftp_directory(ftp, remote_dir)
        return "pwd=" + ftp.pwd()


def _upload_test(config, timeout, remote_dir):
    remote_name = "ftp_diagnostics_upload_test.csv"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", suffix=".csv", delete=False) as stream:
        stream.write("status,message\nOK,diagnostic upload test\n")
        local_path = Path(stream.name)
    try:
        with connect_ftp(config, timeout) as ftp:
            ensure_ftp_directory(ftp, remote_dir)
            with local_path.open("rb") as stream:
                ftp.storbinary("STOR " + remote_name, stream)
            names = [posixpath.basename(name) for name in ftp.nlst()]
            if remote_name not in names:
                raise RuntimeError("uploaded file not visible in nlst")
            ftp.delete(remote_name)
            return "stored, listed, deleted " + remote_name
    finally:
        local_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
