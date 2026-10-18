# 在 Windows 上手動建置：在 windows 資料夾執行  powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python -m pip install -r requirements.txt
# 準備網頁資源
Remove-Item -Recurse -Force web -ErrorAction SilentlyContinue
New-Item -ItemType Directory web | Out-Null
Copy-Item ..\index.html web\
Copy-Item ..\favicon.svg, ..\favicon-32.png, ..\favicon-16.png, ..\apple-touch-icon.png, ..\manifest.webmanifest web\
Copy-Item -Recurse ..\icons web\icons
# 打包成資料夾版執行檔
python -m PyInstaller --noconfirm --clean --windowed --name XiaokeVideo --icon app.ico `
  --add-data "web;web" --distpath ..\dist --workpath ..\build app.py
# 中文安裝介面
if (-not (Test-Path ChineseTraditional.isl)) {
  try { Invoke-WebRequest "https://raw.githubusercontent.com/jrsoftware/issrc/main/Files/Languages/Unofficial/ChineseTraditional.isl" -OutFile ChineseTraditional.isl } catch { Write-Host "下載中文語系失敗，改用英文介面" }
}
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") |
  Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { choco install innosetup -y --no-progress; $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
& $iscc installer.iss
Write-Host "完成：..\dist-installer"
