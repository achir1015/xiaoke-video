; 小柯影音剪輯助手 — Windows 安裝程式（Inno Setup 6）
#ifndef AppVer
  #define AppVer "1.0.0"
#endif
#define AppName "小柯影音剪輯助手"
#define AppExe "XiaokeVideo.exe"

[Setup]
AppId={{6E3B1C5A-9F2D-4C7B-8A11-5D0F2B7C9E41}
AppName={#AppName}
AppVersion={#AppVer}
AppVerName={#AppName} {#AppVer}
AppPublisher=achir1015
AppPublisherURL=https://github.com/achir1015/xiaoke-video
AppSupportURL=https://github.com/achir1015/xiaoke-video/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; 不需要系統管理員權限；安裝時可以自己選資料夾，例如 E:\小柯影音剪輯助手
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline dialog
OutputDir=..\dist-installer
OutputBaseFilename=XiaokeVideo-Setup-{#AppVer}
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763

[Languages]
#ifexist "ChineseTraditional.isl"
Name: "cht"; MessagesFile: "ChineseTraditional.isl"
#else
Name: "en"; MessagesFile: "compiler:Default.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "在桌面建立捷徑"; GroupDescription: "其他捷徑："

[Files]
Source: "..\dist\XiaokeVideo\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autoprograms}\解除安裝 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "立即啟動 {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
// Windows 11 內建 WebView2；舊電腦沒有時提醒使用者安裝
function WebView2Installed(): Boolean;
var v: String;
begin
  Result :=
    RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', v) or
    RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', v) or
    RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', v);
  if Result then Result := (v <> '') and (v <> '0.0.0.0');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and (not WizardSilent) and (not WebView2Installed()) then
    MsgBox('這台電腦沒有偵測到 Microsoft Edge WebView2 執行階段。' #13#10 +
           'Windows 11 通常已內建；若程式打不開，請到 https://go.microsoft.com/fwlink/p/?LinkId=2124703 安裝。',
           mbInformation, MB_OK);
end;
