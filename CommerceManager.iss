; Commerce Manager - Inno Setup installer script
;
; Requires Inno Setup (free): https://jrsoftware.org/isdl.php
; 1. Build the .exe first:  pyinstaller CommerceManager.spec
; 2. Open this file in Inno Setup and click Compile (or run
;    "ISCC.exe CommerceManager.iss" from the command line)
; 3. The installer appears in installer_output\CommerceManager-Setup.exe

#define MyAppName "Commerce Manager"
#define MyAppVersion "1.0"
#define MyAppPublisher "Votre Commerce"
#define MyAppExeName "CommerceManager.exe"

[Setup]
; Unique app ID - do not change this after your first release, or
; Windows will treat updates as a different program.
AppId={C1EBE4BA-2966-4FF2-87AC-3CA49C2E56E3}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=CommerceManager-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
; Uncomment and point at your own icon if you have one:
; SetupIconFile=assets\icon.ico

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\CommerceManager.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstaller {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

; The database (caisse.db) is created next to the .exe on first run,
; inside the install folder - so uninstalling can optionally offer to
; keep or remove it. This keeps user data separate from program files
; is the more common pattern, but for a small single-user shop this
; keeps everything in one folder, which is simpler to back up.
