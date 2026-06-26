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

人名與工號預先寫在 `main.py` 的 `PRELOADED_USERS`。部署前請將範例名單替換成正式人員名單。首次執行會建立 `users.json`，後續密碼雜湊會保存在該檔案。

## 本機備份

每次送出會先在 `reports/` 建立 CSV 備份，再上傳至 FTP。若 FTP 連線失敗，程式會保留本機 CSV 並顯示錯誤訊息。
