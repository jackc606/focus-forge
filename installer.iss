; Inno Setup script for Focus Forge.
; Build the app first:  python -m PyInstaller build.spec --clean --noconfirm
; Then compile:         ISCC.exe installer.iss
; Output:               dist\FocusForge-{version}-setup.exe  (per-user install, no admin)
; packaging\release.py syncs MyAppVersion from core\version.py and publishes.

#define MyAppName "Focus Forge"
#define MyAppVersion "0.3.1"
#define MyAppPublisher "Focus Forge"
#define MyAppExeName "FocusForge.exe"

[Setup]
AppId={{A3F2C9D1-4B6E-4E8A-9C2D-7F1B0E5A6C34}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion} (pre-alpha)
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=FocusForge-{#MyAppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#MyAppName} {#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=assets\icon.ico
; Auto-update: close a running Focus Forge before overwriting its files.
; "force" (not "yes") because during a silent auto-update the old exe may
; still be mid-shutdown when Setup checks for locked files; a graceful-only
; close then fails with "Setup was unable to automatically close all
; applications". The [Code] mutex wait below makes force a rare last resort.
CloseApplications=force

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "dist\FocusForge\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; AI Bridge: ship a ready-to-use MCP config next to the exe so Claude Code, opened
; on the install folder, auto-detects the bundled focusforge-mcp.exe server.
Source: "packaging\.mcp.json"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; No skipifsilent: a silent auto-update (setup.exe /SILENT) relaunches the app.
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall

[Code]
{ The auto-updater spawns this installer and THEN quits the app, so Setup
  usually starts while the old FocusForge.exe is still tearing down. main.py
  holds FocusForgeAppMutex for the process lifetime; Windows releases it only
  once the process has fully exited. Wait for that (up to 15s) before Setup's
  locked-file check, so the normal path never needs Restart Manager at all. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Tries: Integer;
begin
  Tries := 0;
  while CheckForMutexes('FocusForgeAppMutex') and (Tries < 75) do
  begin
    Sleep(200);
    Tries := Tries + 1;
  end;
  Result := '';
end;
