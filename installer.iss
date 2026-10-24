#define MyAppName "RSV4 CAN Studio"
#define MyAppVersion "0.5"
#define MyAppExeName "RSV4_CAN_Studio.exe"
[Setup]
AppId={{DA30B624-91CE-40A6-B6D4-0D7AAB1729B0}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\RSV4 CAN Studio
DefaultGroupName={#MyAppName}
OutputDir=installer
OutputBaseFilename=RSV4_CAN_Studio_Setup
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
Filename: "{app}\{#MyAppExeName}"; Description: "Lancer RSV4 CAN Studio"; Flags: nowait postinstall skipifsilent
