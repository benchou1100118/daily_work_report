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

from PySide2.QtCore import QDate, QTimer, Qt
from PySide2.QtWidgets import (
    QApplication,
    QCalendarWidget,
    QDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

FTP_HOST = "192.168.153.7"
FTP_PORT = 21
FTP_USER = "User"
FTP_PASSWORD = "123456"
FTP_ROOT_DIR = "Largan_Machine_data/723_daily_work_report"
FTP_USER_DB_DIR = FTP_ROOT_DIR + "/people"
FTP_DAILY_DATA_DIR = FTP_ROOT_DIR + "/daily_data"
SUPER_USER_EMPLOYEE_ID = "1100118"
SORT_ORDER_FILENAME = "daily_report_sort_order.json"

APP_DIR = Path(__file__).resolve().parent
USER_DB_PATH = APP_DIR / "users.json"
REPORT_CACHE_DIR = APP_DIR / "reports"
SORT_ORDER_PATH = APP_DIR / SORT_ORDER_FILENAME


def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def load_user_db():
    """Load registered users from the local user database."""
    if not USER_DB_PATH.exists():
        save_user_db({})
        return {}

    with USER_DB_PATH.open("r", encoding="utf-8") as stream:
        users = json.load(stream)

    if not isinstance(users, dict):
        raise RuntimeError("使用者資料格式錯誤：users.json 必須是物件。")
    return users


def ensure_local_parent(path):
    """Create the local parent folder before writing application-managed files."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def save_user_db(users):
    ensure_local_parent(USER_DB_PATH)
    with USER_DB_PATH.open("w", encoding="utf-8") as stream:
        json.dump(users, stream, ensure_ascii=False, indent=2)


def ensure_ftp_directory(ftp, directory):
    """Create missing FTP folders and change into the final directory.

    Some NAS/Windows FTP servers used for handoff folders do not allow clients
    to change to ``/`` even though the login account can access paths relative
    to its home directory.  Try the configured path directly first, then create
    missing segments from the login directory instead of assuming root access.
    """
    normalized_directory = "/".join(segment for segment in directory.split("/") if segment)
    if not normalized_directory:
        return

    try:
        ftp.cwd(normalized_directory)
        return
    except error_perm:
        pass

    for part in normalized_directory.split("/"):
        try:
            ftp.cwd(part)
        except error_perm:
            ftp.mkd(part)
            ftp.cwd(part)


def open_ftp_connection():
    """Open an FTP connection using settings that work with common NAS servers.

    The connection flow intentionally mirrors the standard ftplib pattern:
    create the FTP client, connect to host/port with a timeout, then login.
    Keeping the port explicit makes the UI status check match manual FTP
    troubleshooting steps used by operators.
    """
    ftp = FTP()
    ftp.encoding = "utf-8"
    ftp.connect(FTP_HOST, FTP_PORT, timeout=30)
    ftp.login(FTP_USER, FTP_PASSWORD)
    ftp.set_pasv(True)
    return ftp


def check_ftp_connection():
    """Verify FTP login, current directory, listing, and app folders.

    This is the same confirmation mechanism operators use manually: connect to
    host/port, login, confirm ``pwd()``, list the starting directory, then enter
    or create the required handoff folders.  Each configured folder is checked
    with a fresh FTP session because the handoff server is commonly opened as
    ``ftp://User@192.168.153.7/Largan_Machine_data`` and treats paths as
    relative to the login location.  Reusing one session after entering the
    report folder would make the next check resolve from that nested folder.
    """
    with open_ftp_connection() as ftp:
        ftp.pwd()
        ftp.nlst()

    for remote_dir in (FTP_ROOT_DIR, FTP_USER_DB_DIR, FTP_DAILY_DATA_DIR):
        with open_ftp_connection() as ftp:
            ensure_ftp_directory(ftp, remote_dir)
            ftp.pwd()


def upload_to_ftp(local_file, remote_dir):
    """Upload a file and overwrite the remote copy as safely as possible."""
    with open_ftp_connection() as ftp:
        ensure_ftp_directory(ftp, remote_dir)
        remote_name = posixpath.basename(str(local_file))
        temp_remote_name = remote_name + ".uploading"
        with open(local_file, "rb") as stream:
            ftp.storbinary("STOR " + temp_remote_name, stream)

        try:
            ftp.delete(remote_name)
        except error_perm:
            pass

        try:
            ftp.rename(temp_remote_name, remote_name)
        except Exception:
            try:
                ftp.delete(temp_remote_name)
            except error_perm:
                pass
            raise


def download_from_ftp(remote_dir, remote_name, local_file):
    """Download one FTP file into local_file."""
    ensure_local_parent(local_file)
    with open_ftp_connection() as ftp:
        ensure_ftp_directory(ftp, remote_dir)
        with open(local_file, "wb") as stream:
            ftp.retrbinary("RETR " + remote_name, stream.write)


def list_ftp_files(remote_dir):
    """Return file names in an FTP directory."""
    with open_ftp_connection() as ftp:
        ensure_ftp_directory(ftp, remote_dir)
        return [posixpath.basename(name) for name in ftp.nlst()]


def upload_user_db_to_ftp():
    """Upload the locally saved user database to FTP after local persistence."""
    upload_to_ftp(USER_DB_PATH, FTP_USER_DB_DIR)


def month_folder(report_date):
    """Return YYYYMM folder name for a report date string formatted as YYYY-MM-DD."""
    return report_date[:7].replace("-", "")


def employee_report_remote_dir(employee_id, report_date):
    """Return the FTP folder for one employee's reports in a specific month."""
    return posixpath.join(FTP_DAILY_DATA_DIR, employee_id, month_folder(report_date))


def load_sort_order():
    """Load the shared summary ordering; missing or malformed files fall back to empty order."""
    if not SORT_ORDER_PATH.exists():
        return {"order": [], "updated_at": "", "updated_by": ""}
    try:
        with SORT_ORDER_PATH.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
    except (IOError, ValueError):
        return {"order": [], "updated_at": "", "updated_by": ""}
    if not isinstance(payload, dict) or not isinstance(payload.get("order"), list):
        return {"order": [], "updated_at": "", "updated_by": ""}
    return payload


def save_sort_order(order, user):
    """Persist sort order locally before it is uploaded to FTP."""
    payload = {
        "order": order,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "updated_by": "{0} ({1})".format(user["name"], user["employee_id"]) if user else "",
    }
    ensure_local_parent(SORT_ORDER_PATH)
    with SORT_ORDER_PATH.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
    return payload


class RegisterDialog(QDialog):
    def __init__(self, users, parent=None):
        super(RegisterDialog, self).__init__(parent)
        self.users = users
        self.registered_employee_id = None
        self.setWindowTitle("註冊人員")

        self.name_input = QLineEdit()
        self.employee_id_input = QLineEdit()
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.confirm_password_input = QLineEdit()
        self.confirm_password_input.setEchoMode(QLineEdit.Password)

        form = QFormLayout()
        form.addRow("姓名", self.name_input)
        form.addRow("工號", self.employee_id_input)
        form.addRow("密碼", self.password_input)
        form.addRow("確認密碼", self.confirm_password_input)

        register_button = QPushButton("註冊")
        cancel_button = QPushButton("取消")
        register_button.clicked.connect(self.register_user)
        cancel_button.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(register_button)
        buttons.addWidget(cancel_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)

    def register_user(self):
        name = self.name_input.text().strip()
        employee_id = self.employee_id_input.text().strip()
        password = self.password_input.text()
        confirm_password = self.confirm_password_input.text()

        if not name or not employee_id:
            QMessageBox.warning(self, "錯誤", "姓名與工號不可空白。")
            return
        if employee_id in self.users:
            QMessageBox.warning(self, "錯誤", "此工號已註冊。")
            return
        if not password:
            QMessageBox.warning(self, "錯誤", "密碼不可空白。")
            return
        if password != confirm_password:
            QMessageBox.warning(self, "錯誤", "兩次輸入的密碼不一致。")
            return

        self.users[employee_id] = {
            "name": name,
            "employee_id": employee_id,
            "password_hash": hash_password(password),
        }
        save_user_db(self.users)
        try:
            upload_user_db_to_ftp()
        except Exception as exc:  # UI boundary: local registration remains available.
            QMessageBox.warning(
                self,
                "FTP上傳失敗",
                "人員資料已先儲存在本機，但上傳FTP失敗：\n{0}".format(exc),
            )
        else:
            QMessageBox.information(self, "完成", "人員註冊完成，且已上傳FTP。")
        self.registered_employee_id = employee_id
        self.accept()


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
        try:
            upload_user_db_to_ftp()
        except Exception as exc:  # UI boundary: local password change remains available.
            QMessageBox.warning(
                self,
                "FTP上傳失敗",
                "密碼已先更新在本機，但上傳FTP失敗：\n{0}".format(exc),
            )
        else:
            QMessageBox.information(self, "完成", "密碼已更新，且已上傳FTP。")
        self.accept()


class DeleteUserDialog(QDialog):
    def __init__(self, users, current_user, parent=None):
        super(DeleteUserDialog, self).__init__(parent)
        self.users = users
        self.current_user = current_user
        self.deleted_employee_ids = []
        self.setWindowTitle("刪除人員名單")
        self.resize(420, 320)

        hint = QLabel("請選擇要刪除的人員。super user 本身不可刪除。")
        hint.setWordWrap(True)

        self.user_table = QTableWidget(0, 2)
        self.user_table.setHorizontalHeaderLabels(["姓名", "工號"])
        self.user_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.user_table.setSelectionMode(QTableWidget.SingleSelection)
        self.user_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.refresh_user_table()

        delete_button = QPushButton("刪除選取人員")
        close_button = QPushButton("關閉")
        delete_button.clicked.connect(self.delete_selected_user)
        close_button.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(delete_button)
        buttons.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.user_table)
        layout.addLayout(buttons)

    def refresh_user_table(self):
        rows = sorted(self.users.values(), key=lambda user: user.get("employee_id", ""))
        self.user_table.setRowCount(len(rows))
        for row_index, user in enumerate(rows):
            self.user_table.setItem(row_index, 0, QTableWidgetItem(user.get("name", "")))
            self.user_table.setItem(row_index, 1, QTableWidgetItem(user.get("employee_id", "")))
        self.user_table.resizeColumnsToContents()

    def delete_selected_user(self):
        selected_row = self.user_table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "錯誤", "請先選擇要刪除的人員。")
            return

        employee_item = self.user_table.item(selected_row, 1)
        if employee_item is None:
            return
        employee_id = employee_item.text()
        if employee_id == SUPER_USER_EMPLOYEE_ID:
            QMessageBox.warning(self, "錯誤", "不可刪除 super user。")
            return

        user = self.users.get(employee_id)
        if not user:
            QMessageBox.warning(self, "錯誤", "找不到選取的人員資料。")
            return

        reply = QMessageBox.question(
            self,
            "確認刪除",
            "確定要刪除 {0} ({1}) 嗎？".format(user.get("name", ""), employee_id),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        del self.users[employee_id]
        save_user_db(self.users)
        try:
            upload_user_db_to_ftp()
        except Exception as exc:  # UI boundary: local deletion remains available.
            QMessageBox.warning(
                self,
                "FTP上傳失敗",
                "人員已先從本機名單刪除，但上傳FTP失敗：\n{0}".format(exc),
            )
        else:
            QMessageBox.information(self, "完成", "人員已刪除，且已上傳FTP。")
        self.deleted_employee_ids.append(employee_id)
        self.refresh_user_table()


class SummaryTableWidget(QTableWidget):
    """Table widget that reorders whole rows without leaving blank cells."""

    def __init__(self, *args, **kwargs):
        super(SummaryTableWidget, self).__init__(*args, **kwargs)
        self.order_changed_callback = None

    def dropEvent(self, event):
        if self.dragDropMode() != QTableWidget.InternalMove or not self.selectedItems():
            super(SummaryTableWidget, self).dropEvent(event)
            return

        source_row = self.currentRow()
        if source_row < 0:
            super(SummaryTableWidget, self).dropEvent(event)
            return

        target_row = self.rowAt(event.pos().y())
        if target_row < 0:
            target_row = self.rowCount()
        if target_row == source_row or target_row == source_row + 1:
            event.accept()
            return

        row_items = []
        for column in range(self.columnCount()):
            item = self.takeItem(source_row, column)
            row_items.append(item if item is not None else QTableWidgetItem(""))

        self.removeRow(source_row)
        if source_row < target_row:
            target_row -= 1

        self.insertRow(target_row)
        for column, item in enumerate(row_items):
            self.setItem(target_row, column, item)
        self.selectRow(target_row)
        event.accept()

        if self.order_changed_callback:
            self.order_changed_callback()


class MainWindow(QMainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()
        self.users = load_user_db()
        self.current_user = None
        self.summary_rows = []
        self.ftp_connected = False
        self.setWindowTitle("每日工作匯報")
        self.resize(900, 680)
        self._build_ui()
        self.summary_timer = QTimer(self)
        self.summary_timer.setInterval(60 * 1000)
        self.summary_timer.timeout.connect(self.refresh_daily_summary)
        self.summary_timer.start()
        self.initialize_ftp_connection()
        self.refresh_daily_summary(show_errors=False)

    def _build_ui(self):
        central = QWidget()
        layout = QVBoxLayout(central)

        login_group = QGroupBox("人員登入 / 註冊")
        login_layout = QGridLayout(login_group)
        self.employee_id_input = QLineEdit()
        self.employee_id_input.setPlaceholderText("請輸入工號")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.login_button = QPushButton("登入")
        self.register_button = QPushButton("註冊新人員")
        self.logout_button = QPushButton("登出")
        self.change_password_button = QPushButton("更改密碼")
        self.admin_register_button = QPushButton("新增註冊人員")
        self.delete_user_button = QPushButton("刪除人員")
        self.logout_button.setEnabled(False)
        self.change_password_button.setEnabled(False)
        self.admin_register_button.setVisible(False)
        self.delete_user_button.setVisible(False)
        self.delete_user_button.setEnabled(False)
        self.login_button.clicked.connect(self.login)
        self.register_button.clicked.connect(self.open_register_dialog)
        self.logout_button.clicked.connect(self.logout)
        self.change_password_button.clicked.connect(self.open_change_password)
        self.admin_register_button.clicked.connect(self.open_admin_register_dialog)
        self.delete_user_button.clicked.connect(self.open_delete_user_dialog)
        login_layout.addWidget(QLabel("工號"), 0, 0)
        login_layout.addWidget(self.employee_id_input, 0, 1)
        login_layout.addWidget(QLabel("密碼"), 1, 0)
        login_layout.addWidget(self.password_input, 1, 1)
        login_layout.addWidget(self.login_button, 0, 2)
        login_layout.addWidget(self.register_button, 0, 3)
        login_layout.addWidget(self.logout_button, 1, 2)
        login_layout.addWidget(self.change_password_button, 1, 3)
        login_layout.addWidget(self.admin_register_button, 2, 2)
        login_layout.addWidget(self.delete_user_button, 2, 3)

        self.tabs = QTabWidget()
        edit_tab = QWidget()
        edit_layout = QVBoxLayout(edit_tab)

        date_group = QGroupBox("日期")
        date_layout = QVBoxLayout(date_group)
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(True)
        self.calendar.setSelectedDate(QDate.currentDate())
        self.calendar.selectionChanged.connect(self.load_selected_report)
        date_layout.addWidget(QLabel("點選日期即可載入該日已儲存/已上傳內容；儲存時會以選取日期覆蓋同日報告。"))
        date_layout.addWidget(self.calendar)

        report_group = QGroupBox("工作內容")
        report_layout = QFormLayout(report_group)
        self.work_summary = QTextEdit()
        self.issue_notes = QTextEdit()
        self.next_shift_notes = QTextEdit()
        report_layout.addRow("今日工作內容", self.work_summary)
        report_layout.addRow("異常/待處理事項", self.issue_notes)
        report_layout.addRow("交接備註", self.next_shift_notes)

        edit_layout.addWidget(date_group)
        edit_layout.addWidget(report_group)

        summary_tab = QWidget()
        summary_layout = QVBoxLayout(summary_tab)
        self.summary_hint = QLabel("顯示當日已註冊人員的當日工作資訊，每 1 分鐘自動更新一次。")
        self.summary_hint.setWordWrap(True)
        self.summary_table = SummaryTableWidget(0, 6)
        self.summary_table.setHorizontalHeaderLabels([
            "排序", "姓名", "工號", "今日工作內容", "異常/待處理事項", "交接備註"
        ])
        self.summary_table.setDragDropMode(QTableWidget.InternalMove)
        self.summary_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.summary_table.setSelectionMode(QTableWidget.SingleSelection)
        self.summary_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.summary_table.order_changed_callback = self.on_summary_order_changed
        self.refresh_summary_button = QPushButton("立即更新")
        self.refresh_summary_button.clicked.connect(self.refresh_daily_summary)
        summary_layout.addWidget(self.summary_hint)
        summary_layout.addWidget(self.summary_table)
        summary_layout.addWidget(self.refresh_summary_button, alignment=Qt.AlignRight)

        self.tabs.addTab(edit_tab, "登打資料")
        self.tabs.addTab(summary_tab, "當日統整")

        ftp_status_layout = QHBoxLayout()
        self.ftp_status_label = QLabel("FTP狀態：尚未檢查")
        self.ftp_status_label.setWordWrap(True)
        self.recheck_ftp_button = QPushButton("重新確認FTP")
        self.recheck_ftp_button.clicked.connect(self.recheck_ftp_connection)
        ftp_status_layout.addWidget(self.ftp_status_label, 1)
        ftp_status_layout.addWidget(self.recheck_ftp_button)
        self.status_label = QLabel("請輸入工號與密碼登入；未註冊者請先註冊。")
        self.status_label.setWordWrap(True)
        self.upload_path_label = QLabel("")
        self.upload_path_label.setWordWrap(True)
        self.upload_path_label.setVisible(False)
        self.save_button = QPushButton("儲存並上傳FTP")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_report)

        layout.addWidget(login_group)
        layout.addWidget(self.tabs)
        layout.addLayout(ftp_status_layout)
        layout.addWidget(self.status_label)
        layout.addWidget(self.upload_path_label)
        layout.addWidget(self.save_button, alignment=Qt.AlignRight)
        self.setCentralWidget(central)

    def set_ftp_connected(self, connected, detail=""):
        self.ftp_connected = connected
        if connected:
            text = "FTP狀態：FTP連線中"
        else:
            text = "FTP狀態：FTP未連線使用本機"
        if detail:
            text = "{0}（{1}）".format(text, detail)
        self.ftp_status_label.setText(text)
        self.update_upload_path_label()

    def initialize_ftp_connection(self):
        try:
            check_ftp_connection()
        except Exception as exc:
            self.set_ftp_connected(False, str(exc))
        else:
            self.set_ftp_connected(True)

    def recheck_ftp_connection(self):
        self.recheck_ftp_button.setEnabled(False)
        self.status_label.setText("正在重新確認FTP連線、目前目錄、清單與必要資料夾...")
        QApplication.processEvents()
        try:
            check_ftp_connection()
        except Exception as exc:
            self.set_ftp_connected(False, str(exc))
            QMessageBox.warning(self, "FTP確認失敗", "FTP重新確認失敗：\n{0}".format(exc))
            self.status_label.setText("FTP重新確認失敗，已維持本機備份模式。")
        else:
            self.set_ftp_connected(True, "已確認登入、目錄清單與必要資料夾")
            self.status_label.setText("FTP重新確認完成，可正常同步與上傳。")
        finally:
            self.recheck_ftp_button.setEnabled(True)

    def open_register_dialog(self):
        dialog = RegisterDialog(self.users, self)
        if dialog.exec_() == QDialog.Accepted and dialog.registered_employee_id:
            self.employee_id_input.setText(dialog.registered_employee_id)
            self.password_input.clear()
            self.status_label.setText("註冊完成，請輸入密碼登入。")

    def open_admin_register_dialog(self):
        if not self.is_super_user():
            QMessageBox.warning(self, "權限不足", "只有 super user 可以新增註冊人員。")
            return
        dialog = RegisterDialog(self.users, self)
        if dialog.exec_() == QDialog.Accepted and dialog.registered_employee_id:
            self.status_label.setText("super user 已新增註冊人員：{0}".format(dialog.registered_employee_id))
            self.refresh_daily_summary(show_errors=False)

    def update_super_user_controls(self):
        is_super = self.is_super_user()
        self.admin_register_button.setVisible(is_super)
        self.admin_register_button.setEnabled(is_super)
        self.delete_user_button.setVisible(is_super)
        self.delete_user_button.setEnabled(is_super)

    def login(self):
        employee_id = self.employee_id_input.text().strip()
        password = self.password_input.text()
        user = self.users.get(employee_id)
        if not user:
            QMessageBox.warning(self, "登入失敗", "查無此工號，請先註冊。")
            return
        if user["password_hash"] != hash_password(password):
            QMessageBox.warning(self, "登入失敗", "密碼不正確。")
            return
        self.current_user = user
        self.password_input.clear()
        self.save_button.setEnabled(True)
        self.logout_button.setEnabled(True)
        self.change_password_button.setEnabled(True)
        self.update_super_user_controls()
        self.update_upload_path_label()
        self.login_button.setEnabled(False)
        self.register_button.setEnabled(False)
        self.employee_id_input.setEnabled(False)
        self.status_label.setText("已登入：{name} ({employee_id})".format(**user))
        self.load_selected_report()
        self.refresh_daily_summary(show_errors=False)

    def logout(self):
        self.current_user = None
        self.clear_report_fields()
        self.save_button.setEnabled(False)
        self.logout_button.setEnabled(False)
        self.change_password_button.setEnabled(False)
        self.update_super_user_controls()
        self.update_upload_path_label()
        self.login_button.setEnabled(True)
        self.register_button.setEnabled(True)
        self.employee_id_input.setEnabled(True)
        self.status_label.setText("已登出。")
        self.refresh_daily_summary(show_errors=False)

    def open_change_password(self):
        if not self.current_user:
            return
        dialog = ChangePasswordDialog(self.users, self.current_user, self)
        dialog.exec_()

    def open_delete_user_dialog(self):
        if not self.is_super_user():
            QMessageBox.warning(self, "權限不足", "只有 super user 可以刪除人員名單。")
            return
        dialog = DeleteUserDialog(self.users, self.current_user, self)
        dialog.exec_()
        if dialog.deleted_employee_ids:
            self.refresh_daily_summary(show_errors=False)

    def selected_report_date(self):
        selected_date = self.calendar.selectedDate()
        return "{0:04d}-{1:02d}-{2:02d}".format(
            selected_date.year(), selected_date.month(), selected_date.day()
        )

    def report_filename(self, report_date):
        return "{date}_{employee_id}.csv".format(
            date=report_date.replace("-", ""),
            employee_id=self.current_user["employee_id"],
        )

    def report_file_path(self, report_date):
        return (
            REPORT_CACHE_DIR
            / self.current_user["employee_id"]
            / month_folder(report_date)
            / self.report_filename(report_date)
        )

    def legacy_report_file_paths(self, report_date):
        date_prefix = report_date.replace("-", "")
        plain_filename = "{date}_{employee_id}.csv".format(
            date=date_prefix,
            employee_id=self.current_user["employee_id"],
        )
        named_filename = "{date}_{employee_id}_{name}.csv".format(
            date=date_prefix,
            employee_id=self.current_user["employee_id"],
            name=self.current_user["name"],
        )
        return [REPORT_CACHE_DIR / plain_filename, REPORT_CACHE_DIR / named_filename]

    def is_super_user(self):
        return bool(self.current_user and self.current_user.get("employee_id") == SUPER_USER_EMPLOYEE_ID)


    def update_upload_path_label(self):
        """Show super user where the selected report will be uploaded."""
        if not self.is_super_user() or not self.ftp_connected:
            self.upload_path_label.clear()
            self.upload_path_label.setVisible(False)
            return

        report_date = self.selected_report_date()
        local_file = self.report_file_path(report_date)
        remote_dir = employee_report_remote_dir(self.current_user["employee_id"], report_date)
        remote_path = posixpath.join(remote_dir, local_file.name)
        self.upload_path_label.setText(
            "super user FTP上傳資訊：要上傳的本機檔案：{0}；上傳到FTP：{1}".format(
                local_file, remote_path
            )
        )
        self.upload_path_label.setVisible(True)

    def clear_report_fields(self):
        self.work_summary.clear()
        self.issue_notes.clear()
        self.next_shift_notes.clear()

    def load_selected_report(self):
        if not self.current_user:
            return

        self.update_upload_path_label()
        report_date = self.selected_report_date()
        local_file = self.report_file_path(report_date)
        if not local_file.exists():
            for legacy_file in self.legacy_report_file_paths(report_date):
                if legacy_file.exists():
                    local_file = legacy_file
                    break

        if not local_file.exists():
            self.clear_report_fields()
            self.status_label.setText(
                "已登入：{name} ({employee_id})；{date} 尚無本機報告。".format(
                    date=report_date, **self.current_user
                )
            )
            return

        try:
            with local_file.open("r", encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
        except Exception as exc:
            QMessageBox.warning(self, "讀取失敗", "無法讀取本機報告：\n{0}".format(exc))
            return

        if not rows:
            self.clear_report_fields()
            return

        report = rows[-1]
        self.work_summary.setPlainText(report.get("今日工作內容", ""))
        self.issue_notes.setPlainText(report.get("異常/待處理事項", ""))
        self.next_shift_notes.setPlainText(report.get("交接備註", ""))
        self.status_label.setText("已載入 {0} 的報告：{1}".format(report_date, local_file.name))

    def today_report_date(self):
        today = QDate.currentDate()
        return "{0:04d}-{1:02d}-{2:02d}".format(today.year(), today.month(), today.day())

    def sync_today_reports_from_ftp(self, report_date):
        """Download today's report CSV files from daily_data/<工號>/<YYYYMM>."""
        REPORT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        prefix = report_date.replace("-", "")
        month = month_folder(report_date)
        for employee_id in list_ftp_files(FTP_DAILY_DATA_DIR):
            remote_dir = employee_report_remote_dir(employee_id, report_date)
            try:
                remote_names = list_ftp_files(remote_dir)
            except Exception:
                continue
            for remote_name in remote_names:
                if remote_name.startswith(prefix) and remote_name.endswith(".csv"):
                    local_file = REPORT_CACHE_DIR / employee_id / month / remote_name
                    download_from_ftp(remote_dir, remote_name, local_file)
        try:
            download_from_ftp(FTP_ROOT_DIR, SORT_ORDER_FILENAME, SORT_ORDER_PATH)
        except Exception:
            pass

    def read_report_csv(self, path):
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        return rows[-1] if rows else None

    def collect_today_summary(self, report_date):
        prefix = report_date.replace("-", "")
        reports_by_employee = {}
        if REPORT_CACHE_DIR.exists():
            for path in REPORT_CACHE_DIR.rglob(prefix + "_*.csv"):
                try:
                    report = self.read_report_csv(path)
                except Exception:
                    continue
                if report:
                    reports_by_employee[report.get("工號", "")] = report

        rows = []
        for employee_id, user in self.users.items():
            report = reports_by_employee.get(employee_id, {})
            rows.append({
                "employee_id": employee_id,
                "name": user.get("name", ""),
                "summary": report.get("今日工作內容", ""),
                "issues": report.get("異常/待處理事項", ""),
                "handoff": report.get("交接備註", ""),
            })

        order = load_sort_order().get("order", [])
        order_index = {employee_id: index for index, employee_id in enumerate(order)}
        rows.sort(key=lambda row: (order_index.get(row["employee_id"], len(order_index)), row["employee_id"]))
        return rows

    def refresh_daily_summary(self, show_errors=True):
        report_date = self.today_report_date()
        try:
            self.sync_today_reports_from_ftp(report_date)
        except Exception as exc:
            self.set_ftp_connected(False, str(exc))
            if show_errors:
                self.status_label.setText("FTP同步失敗，已改用本機資料更新統整：{0}".format(exc))
        else:
            self.set_ftp_connected(True)

        self.summary_rows = self.collect_today_summary(report_date)
        self.summary_table.blockSignals(True)
        self.summary_table.setRowCount(len(self.summary_rows))
        for row_index, row in enumerate(self.summary_rows):
            values = [
                str(row_index + 1), row["name"], row["employee_id"],
                row["summary"], row["issues"], row["handoff"],
            ]
            for column, value in enumerate(values):
                self.summary_table.setItem(row_index, column, QTableWidgetItem(value))
        self.summary_table.resizeColumnsToContents()
        self.summary_table.blockSignals(False)
        drag_text = "可拖曳調整排序並上拋FTP。" if self.is_super_user() else "僅 super user（工號 1100118）可拖曳調整排序。"
        self.summary_table.setDragEnabled(self.is_super_user())
        self.summary_table.setAcceptDrops(self.is_super_user())
        self.summary_hint.setText("{0} 統整完成，共 {1} 位已註冊人員；每 1 分鐘自動更新一次，{2}".format(
            report_date, len(self.summary_rows), drag_text
        ))

    def on_summary_order_changed(self):
        if not self.is_super_user():
            self.refresh_daily_summary(show_errors=False)
            return
        order = []
        for row_index in range(self.summary_table.rowCount()):
            item = self.summary_table.item(row_index, 2)
            if item:
                order.append(item.text())
        # Multi-user note: refresh remote order immediately before writing so the
        # upload is based on the newest available FTP copy, then publish one JSON.
        try:
            download_from_ftp(FTP_ROOT_DIR, SORT_ORDER_FILENAME, SORT_ORDER_PATH)
        except Exception:
            pass
        save_sort_order(order, self.current_user)
        try:
            upload_to_ftp(SORT_ORDER_PATH, FTP_ROOT_DIR)
        except Exception as exc:
            self.set_ftp_connected(False, str(exc))
            QMessageBox.warning(self, "排序上拋失敗", "排序已先儲存在本機，但上拋FTP失敗：\n{0}".format(exc))
        else:
            self.set_ftp_connected(True)
            self.status_label.setText("排序已由 super user 上拋FTP。")
        self.refresh_daily_summary(show_errors=False)

    def save_report(self):
        if not self.current_user:
            QMessageBox.warning(self, "錯誤", "請先登入。")
            return
        if not self.work_summary.toPlainText().strip():
            QMessageBox.warning(self, "錯誤", "請填寫今日工作內容。")
            return

        now = datetime.now()
        self.update_upload_path_label()
        report_date = self.selected_report_date()
        local_file = self.report_file_path(report_date)
        local_file.parent.mkdir(parents=True, exist_ok=True)
        with local_file.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["報告日期", "填寫時間", "姓名", "工號", "今日工作內容", "異常/待處理事項", "交接備註"])
            writer.writerow([
                report_date,
                now.strftime("%Y-%m-%d %H:%M:%S"),
                self.current_user["name"],
                self.current_user["employee_id"],
                self.work_summary.toPlainText(),
                self.issue_notes.toPlainText(),
                self.next_shift_notes.toPlainText(),
            ])

        try:
            upload_to_ftp(
                local_file,
                employee_report_remote_dir(self.current_user["employee_id"], report_date),
            )
        except Exception as exc:  # UI boundary: show any FTP/file error to the operator.
            self.set_ftp_connected(False, str(exc))
            QMessageBox.critical(self, "上傳失敗", "已本機儲存，但FTP上傳失敗：\n{0}".format(exc))
            self.status_label.setText("本機備份：{0}；FTP上傳失敗。".format(local_file))
            self.refresh_daily_summary(show_errors=False)
            return

        self.set_ftp_connected(True)
        QMessageBox.information(self, "完成", "工作匯報已儲存並上傳FTP。")
        self.status_label.setText("已上傳：{0}；FTP位置：{1}".format(
            local_file.name,
            posixpath.join(employee_report_remote_dir(self.current_user["employee_id"], report_date), local_file.name),
        ))
        self.update_upload_path_label()
        self.refresh_daily_summary(show_errors=False)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
