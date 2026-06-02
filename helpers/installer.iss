; BDO Loot Tracker — Inno Setup installer script
;
; Build locally:
;   iscc installer.iss /DMyAppVersion=0.4.0
;
; In CI the version is passed via /DMyAppVersion=${{ env.VERSION }} — see
; .github/workflows/release.yml.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName      "BDO Loot Tracker"
#define MyAppPublisher "janhnguyen"
#define MyAppExeName   "BDO-Loot-Tracker.exe"
#define MyAppSourceDir "..\dist\BDO-Loot-Tracker"

[Setup]
; Changing AppId will break upgrade detection — keep it stable forever.
AppId={{F3A2C8D1-7E4B-4F0A-B6C9-E1D3F5A72048}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; No UAC prompt — installs to per-user AppData
DefaultDirName={localappdata}\BDO-Loot-Tracker
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
; Re-running the installer over an existing install silently upgrades
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no
OutputDir=installer_output
OutputBaseFilename=BDO-Loot-Tracker-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Main executable
Source: "{#MyAppSourceDir}\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; All bundled dependencies
Source: "{#MyAppSourceDir}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

; Items folder sits next to the exe so users can inspect/edit CSVs
Source: "{#MyAppSourceDir}\items\*"; DestDir: "{app}\items"; Flags: ignoreversion recursesubdirs createallsubdirs

; Default config — only written on first install; upgrades preserve the user's .env
Source: "{#MyAppSourceDir}\.env"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{group}\{#MyAppName}";          Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}";    Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; \
  Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; \
  Flags: nowait postinstall
