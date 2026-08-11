#define MyAppName "Creator Intelligence"
#ifndef MyAppVersion
  #define MyAppVersion "5.0.0-alpha.2"
#endif
#ifndef MyAppReleaseRank
  #define MyAppReleaseRank "000050000000000100002"
#endif
#define MyAppExeName "CreatorIntelligence.exe"

[Setup]
AppId={{2D54511C-0B91-4B52-AD62-2082638D9307}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Creator Intelligence
AppPublisherURL=https://github.com/simonwolfy/Creator-Dashboard
AppSupportURL=https://github.com/simonwolfy/Creator-Dashboard/issues
AppUpdatesURL=https://github.com/simonwolfy/Creator-Dashboard/releases
DefaultDirName={autopf}\Creator Intelligence
DefaultGroupName={#MyAppName}
OutputDir=..\release
OutputBaseFilename=CreatorIntelligence-{#MyAppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
InfoBeforeFile=privacy.txt

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Types]
Name: "full"; Description: "Complete installation"

[Components]
Name: "application"; Description: "Creator Intelligence application"; Types: full; Flags: fixed
Name: "application\pythonruntime"; Description: "Private Python runtime and application libraries (required)"; Types: full; Flags: fixed

[Files]
Source: "..\dist\CreatorIntelligence\CreatorIntelligence.exe"; DestDir: "{app}"; Components: application
Source: "..\dist\CreatorIntelligence\_internal\*"; DestDir: "{app}\_internal"; Components: application\pythonruntime; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKCU; Subkey: "Software\Creator Intelligence"; ValueType: string; ValueName: "ReleaseRank"; ValueData: "{#MyAppReleaseRank}"; Flags: uninsdeletevalue uninsdeletekeyifempty

[Code]
function InitializeSetup(): Boolean;
var
  InstalledRank: String;
begin
  Result := True;
  if RegQueryStringValue(HKCU, 'Software\Creator Intelligence', 'ReleaseRank', InstalledRank) then
  begin
    if CompareStr(InstalledRank, '{#MyAppReleaseRank}') > 0 then
    begin
      SuppressibleMsgBox(
        'A newer version of Creator Intelligence is already installed. Uninstall it before installing this older version.',
        mbError,
        MB_OK,
        IDOK
      );
      Result := False;
    end;
  end;
end;
