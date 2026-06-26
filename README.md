# 每日工作匯報 PySide2 UI

此專案提供 Python 3.8.10 / PySide2 桌面程式，讓預先建檔的人員以密碼登入、填寫每日工作匯報，並將 CSV 上傳到指定 FTP 交接資料夾。

## FTP 設定

程式預設連線資訊如下：

- FTP：`ftp://192.168.153.7`
- 帳號：`User`
- 密碼：`123456`
- 資料夾：`Largan_Machine_data/個人資夾/@交接資料/每日工作匯報`

## 使用方式

1. 建立 Python 3.8.10 環境。
2. 安裝套件：
   ```bash
   pip install -r requirements.txt
   ```
3. 啟動程式：
   ```bash
   python main.py
   ```
4. 選擇人員，使用預設密碼 `0000` 登入。
5. 登入後可使用「更改密碼」更新個人密碼。
6. 填寫工作內容後按「儲存並上傳FTP」。

## 人員名單

人名與工號請維護在獨立的 `staff.json`，不要修改程式碼。檔案格式如下：

```json
[
  {
    "name": "王小明",
    "employee_id": "A0001"
  }
]
```

首次執行會依照 `staff.json` 建立 `users.json`，後續密碼雜湊會保存在 `users.json`。若 `staff.json` 新增、移除或更名人員，下次啟動程式時會同步登入名單；既有人員密碼會保留，新進人員使用預設密碼 `0000`。

## 本機備份

每次送出會先在 `reports/` 建立 CSV 備份，再上傳至 FTP。若 FTP 連線失敗，程式會保留本機 CSV 並顯示錯誤訊息。
