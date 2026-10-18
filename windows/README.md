# 小柯影音剪輯助手 — Windows 11 版

用 Python（[pywebview](https://pywebview.flowrl.com/) + PyInstaller）把網頁版包成 Windows 應用程式，
畫面由 Windows 11 內建的 Microsoft Edge WebView2 顯示，再用 Inno Setup 做成中文安裝程式。

## 下載安裝

到 [Releases](https://github.com/achir1015/xiaoke-video/releases) 下載 `XiaokeVideo-Setup-版本.exe`，
執行後可自選安裝位置（例如 `E:\小柯影音剪輯助手`），不需要系統管理員權限。

## 桌面版多了什麼

- 開始功能表、桌面捷徑、工作列圖示，像一般 App 一樣開啟
- 匯出影片、SRT、專案檔時跳出 Windows「另存新檔」視窗，預設存到「影片\小柯影音剪輯助手」
- 檔案一樣只在電腦裡處理，不會上傳

## 自己建置

需要 Windows、Python 3.12 與 Inno Setup 6：

```powershell
cd windows
powershell -ExecutionPolicy Bypass -File build.ps1
```

## 安裝後自我測試

```powershell
"E:\小柯影音剪輯助手\XiaokeVideo.exe" --selftest "$env:TEMP\kk\report.json"
```

會自動開啟 App、執行剪輯指令（片頭、貼圖、字幕動畫、轉場、分割、復原）、匯出一支 2 秒影片、截圖，
並把結果寫進 `report.json`。

## 程式結構

| 類別 | 用途 |
|---|---|
| `AppInfo` | 名稱、版本、資料夾位置 |
| `SaveSession` | 一次「另存新檔」：網頁把檔案分段傳來，Python 寫入 |
| `DesktopBridge` | 網頁可呼叫的 Python 功能（`window.pywebview.api`） |
| `SelfTest` | 安裝後自動測試 |
