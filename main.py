"""Daily work report UI for uploading reports to an FTP handoff folder.

Runtime target: Python 3.8.10 with PySide2 installed.
"""
import csv
import hashlib
import json
import posixpath
import sys
from datetime import datetime
from ftplib import FTP, error_perm
from pathlib import Path

from PySide2.QtCore import Qt
from PySide2.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

FTP_HOST = "192.168.153.7"
FTP_USER = "User"
FTP_PASSWORD = "123456"
FTP_REPORT_DIR = "Largan_Machine_data/個人資夾/@交接資料/每日工作匯報"

APP_DIR = Path(__file__).resolve().parent
USER_DB_PATH = APP_DIR / "users.json"
STAFF_ROSTER_PATH = APP_DIR / "staff.json"
REPORT_CACHE_DIR = APP_DIR / "reports"
DEFAULT_PASSWORD = "0000"


def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def load_staff_roster():
    """Load the staff roster maintained outside of the application code."""
    if not STAFF_ROSTER_PATH.exists():
        raise RuntimeError("找不到人員名單檔案：{0}".format(STAFF_ROSTER_PATH))

    with STAFF_ROSTER_PATH.open("r", encoding="utf-8") as stream:
        staff_roster = json.load(stream)

    if not isinstance(staff_roster, list):
        raise RuntimeError("人員名單格式錯誤：staff.json 必須是人員陣列。")

    normalized_roster = []
    seen_employee_ids = set()
    for index, staff in enumerate(staff_roster, start=1):
        if not isinstance(staff, dict):
            raise RuntimeError("人員名單第 {0} 筆格式錯誤。".format(index))

        name = str(staff.get("name", "")).strip()
        employee_id = str(staff.get("employee_id", "")).strip()
        if not name or not employee_id:
            raise RuntimeError("人員名單第 {0} 筆缺少 name 或 employee_id。".format(index))
        if employee_id in seen_employee_ids:
            raise RuntimeError("人員名單工號重複：{0}".format(employee_id))

        seen_employee_ids.add(employee_id)
        normalized_roster.append({"name": name, "employee_id": employee_id})

    if not normalized_roster:
        raise RuntimeError("人員名單不可為空。")

    return normalized_roster


def ensure_user_db():
    """Create or update the local user password store from staff.json."""
    staff_roster = load_staff_roster()
    existing_users = {}
    if USER_DB_PATH.exists():
        with USER_DB_PATH.open("r", encoding="utf-8") as stream:
            existing_users = json.load(stream)

    users = {}
    changed = set(existing_users.keys()) != {staff["employee_id"] for staff in staff_roster}
    for staff in staff_roster:
        employee_id = staff["employee_id"]
        existing_user = existing_users.get(employee_id, {})
        users[employee_id] = {
            "name": staff["name"],
            "employee_id": employee_id,
            "password_hash": existing_user.get("password_hash", hash_password(DEFAULT_PASSWORD)),
        }
        if existing_user.get("name") != staff["name"]:
            changed = True

    if changed or not USER_DB_PATH.exists():
        save_user_db(users)
    return users


def save_user_db(users):
    with USER_DB_PATH.open("w", encoding="utf-8") as stream:
        json.dump(users, stream, ensure_ascii=False, indent=2)


def ensure_ftp_directory(ftp, directory):
    """Create missing FTP folders and change into the final directory."""
    ftp.cwd("/")
    for part in [segment for segment in directory.split("/") if segment]:
        try:
            ftp.cwd(part)
        except error_perm:
            ftp.mkd(part)
            ftp.cwd(part)


def upload_to_ftp(local_file):
    with FTP(FTP_HOST, timeout=30) as ftp:
        ftp.login(FTP_USER, FTP_PASSWORD)
        ensure_ftp_directory(ftp, FTP_REPORT_DIR)
        remote_name = posixpath.basename(str(local_file))
        with open(local_file, "rb") as stream:
            ftp.storbinary("STOR " + remote_name, stream)


class ChangePasswordDialog(QDialog):
    def __init__(self, users, current_user, parent=None):
        super(ChangePasswordDialog, self).__init__(parent)
        self.users = users
        self.current_user = current_user
        self.setWindowTitle("更改密碼")

        self.old_password = QLineEdit()
        self.old_password.setEchoMode(QLineEdit.Password)
        self.new_password = QLineEdit()
        self.new_password.setEchoMode(QLineEdit.Password)
        self.confirm_password = QLineEdit()
        self.confirm_password.setEchoMode(QLineEdit.Password)

        form = QFormLayout()
        form.addRow("舊密碼", self.old_password)
        form.addRow("新密碼", self.new_password)
        form.addRow("確認新密碼", self.confirm_password)

        save_button = QPushButton("儲存")
        cancel_button = QPushButton("取消")
        save_button.clicked.connect(self.change_password)
        cancel_button.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(save_button)
        buttons.addWidget(cancel_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)

    def change_password(self):
        old_password = self.old_password.text()
        new_password = self.new_password.text()
        confirm_password = self.confirm_password.text()
        user = self.users[self.current_user["employee_id"]]

        if user["password_hash"] != hash_password(old_password):
            QMessageBox.warning(self, "錯誤", "舊密碼不正確。")
            return
        if not new_password:
            QMessageBox.warning(self, "錯誤", "新密碼不可空白。")
            return
        if new_password != confirm_password:
            QMessageBox.warning(self, "錯誤", "兩次輸入的新密碼不一致。")
            return

        user["password_hash"] = hash_password(new_password)
        save_user_db(self.users)
        QMessageBox.information(self, "完成", "密碼已更新。")
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()
        self.users = ensure_user_db()
        self.current_user = None
        self.setWindowTitle("每日工作匯報")
        self.resize(760, 620)
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        layout = QVBoxLayout(central)

        login_group = QGroupBox("人員登入")
        login_layout = QGridLayout(login_group)
        self.user_combo = QComboBox()
        for user in self.users.values():
            self.user_combo.addItem("{name} ({employee_id})".format(**user), user["employee_id"])
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.login_button = QPushButton("登入")
        self.logout_button = QPushButton("登出")
        self.change_password_button = QPushButton("更改密碼")
        self.logout_button.setEnabled(False)
        self.change_password_button.setEnabled(False)
        self.login_button.clicked.connect(self.login)
        self.logout_button.clicked.connect(self.logout)
        self.change_password_button.clicked.connect(self.open_change_password)
        login_layout.addWidget(QLabel("人名/工號"), 0, 0)
        login_layout.addWidget(self.user_combo, 0, 1, 1, 3)
        login_layout.addWidget(QLabel("密碼"), 1, 0)
        login_layout.addWidget(self.password_input, 1, 1)
        login_layout.addWidget(self.login_button, 1, 2)
        login_layout.addWidget(self.logout_button, 1, 3)
        login_layout.addWidget(self.change_password_button, 2, 3)

        report_group = QGroupBox("工作內容")
        report_layout = QFormLayout(report_group)
        self.machine_input = QLineEdit()
        self.work_summary = QTextEdit()
        self.issue_notes = QTextEdit()
        self.next_shift_notes = QTextEdit()
        report_layout.addRow("機台/線別", self.machine_input)
        report_layout.addRow("今日工作內容", self.work_summary)
        report_layout.addRow("異常/待處理事項", self.issue_notes)
        report_layout.addRow("交接備註", self.next_shift_notes)

        self.status_label = QLabel("請先登入；預設密碼為 0000。")
        self.status_label.setWordWrap(True)
        self.save_button = QPushButton("儲存並上傳FTP")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_report)

        layout.addWidget(login_group)
        layout.addWidget(report_group)
        layout.addWidget(self.status_label)
        layout.addWidget(self.save_button, alignment=Qt.AlignRight)
        self.setCentralWidget(central)

    def login(self):
        employee_id = self.user_combo.currentData()
        password = self.password_input.text()
        user = self.users[employee_id]
        if user["password_hash"] != hash_password(password):
            QMessageBox.warning(self, "登入失敗", "密碼不正確。")
            return
        self.current_user = user
        self.password_input.clear()
        self.save_button.setEnabled(True)
        self.logout_button.setEnabled(True)
        self.change_password_button.setEnabled(True)
        self.login_button.setEnabled(False)
        self.user_combo.setEnabled(False)
        self.status_label.setText("已登入：{name} ({employee_id})".format(**user))

    def logout(self):
        self.current_user = None
        self.save_button.setEnabled(False)
        self.logout_button.setEnabled(False)
        self.change_password_button.setEnabled(False)
        self.login_button.setEnabled(True)
        self.user_combo.setEnabled(True)
        self.status_label.setText("已登出。")

    def open_change_password(self):
        if not self.current_user:
            return
        dialog = ChangePasswordDialog(self.users, self.current_user, self)
        dialog.exec_()

    def save_report(self):
        if not self.current_user:
            QMessageBox.warning(self, "錯誤", "請先登入。")
            return
        if not self.work_summary.toPlainText().strip():
            QMessageBox.warning(self, "錯誤", "請填寫今日工作內容。")
            return

        REPORT_CACHE_DIR.mkdir(exist_ok=True)
        now = datetime.now()
        filename = "{date}_{employee_id}_{name}.csv".format(
            date=now.strftime("%Y%m%d_%H%M%S"),
            employee_id=self.current_user["employee_id"],
            name=self.current_user["name"],
        )
        local_file = REPORT_CACHE_DIR / filename
        with local_file.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["填寫時間", "姓名", "工號", "機台/線別", "今日工作內容", "異常/待處理事項", "交接備註"])
            writer.writerow([
                now.strftime("%Y-%m-%d %H:%M:%S"),
                self.current_user["name"],
                self.current_user["employee_id"],
                self.machine_input.text(),
                self.work_summary.toPlainText(),
                self.issue_notes.toPlainText(),
                self.next_shift_notes.toPlainText(),
            ])

        try:
            upload_to_ftp(local_file)
        except Exception as exc:  # UI boundary: show any FTP/file error to the operator.
            QMessageBox.critical(self, "上傳失敗", "已本機儲存，但FTP上傳失敗：\n{0}".format(exc))
            self.status_label.setText("本機備份：{0}；FTP上傳失敗。".format(local_file))
            return

        QMessageBox.information(self, "完成", "工作匯報已儲存並上傳FTP。")
        self.status_label.setText("已上傳：{0}".format(filename))
        self.machine_input.clear()
        self.work_summary.clear()
        self.issue_notes.clear()
        self.next_shift_notes.clear()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
