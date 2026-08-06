#define MyAppName "Creator Intelligence"
#define MyAppVersion "5.0.0-alpha.2"
#define MyAppExeName "CreatorIntelligence.exe"

[Setup]
AppId={{2D54511C-0B91-4B52-AD62-2082638D9307}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\Creator Intelligence
DefaultGroupName={#MyAppName}
OutputDir=..\release
OutputBaseFilename=CreatorIntelligence-{#MyAppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
InfoBeforeFile=privacy.txt

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\CreatorIntelligence\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Only installed program files are removed. Creator workspaces live outside {app} and are preserved.
Type: filesandordirs; Name: "{app}"
