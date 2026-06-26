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

from PySide2.QtCore import QDate, Qt
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
REPORT_CACHE_DIR = APP_DIR / "reports"


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
        self.registered_employee_id = employee_id
        QMessageBox.information(self, "完成", "人員註冊完成。")
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
        QMessageBox.information(self, "完成", "密碼已更新。")
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()
        self.users = load_user_db()
        self.current_user = None
        self.setWindowTitle("每日工作匯報")
        self.resize(900, 680)
        self._build_ui()

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
        self.logout_button.setEnabled(False)
        self.change_password_button.setEnabled(False)
        self.login_button.clicked.connect(self.login)
        self.register_button.clicked.connect(self.open_register_dialog)
        self.logout_button.clicked.connect(self.logout)
        self.change_password_button.clicked.connect(self.open_change_password)
        login_layout.addWidget(QLabel("工號"), 0, 0)
        login_layout.addWidget(self.employee_id_input, 0, 1)
        login_layout.addWidget(QLabel("密碼"), 1, 0)
        login_layout.addWidget(self.password_input, 1, 1)
        login_layout.addWidget(self.login_button, 0, 2)
        login_layout.addWidget(self.register_button, 0, 3)
        login_layout.addWidget(self.logout_button, 1, 2)
        login_layout.addWidget(self.change_password_button, 1, 3)

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
        self.machine_input = QLineEdit()
        self.work_summary = QTextEdit()
        self.issue_notes = QTextEdit()
        self.next_shift_notes = QTextEdit()
        report_layout.addRow("機台/線別", self.machine_input)
        report_layout.addRow("今日工作內容", self.work_summary)
        report_layout.addRow("異常/待處理事項", self.issue_notes)
        report_layout.addRow("交接備註", self.next_shift_notes)

        self.status_label = QLabel("請輸入工號與密碼登入；未註冊者請先註冊。")
        self.status_label.setWordWrap(True)
        self.save_button = QPushButton("儲存並上傳FTP")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_report)

        layout.addWidget(login_group)
        layout.addWidget(date_group)
        layout.addWidget(report_group)
        layout.addWidget(self.status_label)
        layout.addWidget(self.save_button, alignment=Qt.AlignRight)
        self.setCentralWidget(central)

    def open_register_dialog(self):
        dialog = RegisterDialog(self.users, self)
        if dialog.exec_() == QDialog.Accepted and dialog.registered_employee_id:
            self.employee_id_input.setText(dialog.registered_employee_id)
            self.password_input.clear()
            self.status_label.setText("註冊完成，請輸入密碼登入。")

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
        self.login_button.setEnabled(False)
        self.register_button.setEnabled(False)
        self.employee_id_input.setEnabled(False)
        self.status_label.setText("已登入：{name} ({employee_id})".format(**user))
        self.load_selected_report()

    def logout(self):
        self.current_user = None
        self.clear_report_fields()
        self.save_button.setEnabled(False)
        self.logout_button.setEnabled(False)
        self.change_password_button.setEnabled(False)
        self.login_button.setEnabled(True)
        self.register_button.setEnabled(True)
        self.employee_id_input.setEnabled(True)
        self.status_label.setText("已登出。")

    def open_change_password(self):
        if not self.current_user:
            return
        dialog = ChangePasswordDialog(self.users, self.current_user, self)
        dialog.exec_()

    def selected_report_date(self):
        selected_date = self.calendar.selectedDate()
        return "{0:04d}-{1:02d}-{2:02d}".format(
            selected_date.year(), selected_date.month(), selected_date.day()
        )

    def report_file_path(self, report_date):
        filename = "{date}_{employee_id}_{name}.csv".format(
            date=report_date.replace("-", ""),
            employee_id=self.current_user["employee_id"],
            name=self.current_user["name"],
        )
        return REPORT_CACHE_DIR / filename

    def clear_report_fields(self):
        self.machine_input.clear()
        self.work_summary.clear()
        self.issue_notes.clear()
        self.next_shift_notes.clear()

    def load_selected_report(self):
        if not self.current_user:
            return

        report_date = self.selected_report_date()
        local_file = self.report_file_path(report_date)
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
        self.machine_input.setText(report.get("機台/線別", ""))
        self.work_summary.setPlainText(report.get("今日工作內容", ""))
        self.issue_notes.setPlainText(report.get("異常/待處理事項", ""))
        self.next_shift_notes.setPlainText(report.get("交接備註", ""))
        self.status_label.setText("已載入 {0} 的報告：{1}".format(report_date, local_file.name))

    def save_report(self):
        if not self.current_user:
            QMessageBox.warning(self, "錯誤", "請先登入。")
            return
        if not self.work_summary.toPlainText().strip():
            QMessageBox.warning(self, "錯誤", "請填寫今日工作內容。")
            return

        REPORT_CACHE_DIR.mkdir(exist_ok=True)
        now = datetime.now()
        report_date = self.selected_report_date()
        local_file = self.report_file_path(report_date)
        with local_file.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["報告日期", "填寫時間", "姓名", "工號", "機台/線別", "今日工作內容", "異常/待處理事項", "交接備註"])
            writer.writerow([
                report_date,
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
        self.status_label.setText("已上傳：{0}".format(local_file.name))


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
