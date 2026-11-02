#define MyAppName "TrackLab Electronics"
#define MyAppVersion "0.5"
#define MyAppExeName "TrackLab_Electronics.exe"
[Setup]
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
AppId={{DA30B624-91CE-40A6-B6D4-0D7AAB1729B0}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\TrackLab Electronics
DefaultGroupName={#MyAppName}
OutputDir=installer
OutputBaseFilename=TrackLab_Electronics_Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#MyAppExeName}
[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
[Tasks]
Name: "desktopicon"; Description: "Créer une icône sur le bureau"; GroupDescription: "Raccourcis :"; Flags: checkedonce
[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Lancer TrackLab Electronics"; Flags: nowait postinstall skipifsilent
