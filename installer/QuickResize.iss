; Installs the portable folder build into Program Files. Built by build-installer.ps1.
#ifndef AppVersion
  #error AppVersion must be supplied by build-installer.ps1
#endif
#ifndef PayloadRoot
  #error PayloadRoot must be supplied by build-installer.ps1
#endif
[Setup]
; Never change AppId: updates find the existing installation by it.
AppId={{00042F4C-DF8F-4BC8-AA60-31FD6C0CA790}
AppName=QuickResize
AppVersion={#AppVersion}
AppVerName=QuickResize {#AppVersion}
VersionInfoVersion={#AppVersion}
AppPublisher=QuickResize
AppPublisherURL=https://github.com/dgoldwas/QuickResize
AppUpdatesURL=https://github.com/dgoldwas/QuickResize/releases
DefaultDirName={autopf}\QuickResize
UsePreviousAppDir=no
DisableDirPage=yes
DefaultGroupName=QuickResize
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=QuickResize-{#AppVersion}-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\QuickResize.ico
UninstallDisplayIcon={app}\QuickResize.exe
UninstallDisplayName=QuickResize
CloseApplications=yes
RestartApplications=no

[InstallDelete]
; Replace the whole runtime on update rather than mixing files from two builds.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
; The portable notes and any settings from testing the folder build stay out of the installed copy.
Source: "{#PayloadRoot}\*"; DestDir: "{app}"; Excludes: "README.txt,settings.json"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\QuickResize"; Filename: "{app}\QuickResize.exe"
Name: "{autodesktop}\QuickResize"; Filename: "{app}\QuickResize.exe"; Tasks: desktopicon

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\QuickResize.exe"; Description: "Launch QuickResize"; Flags: nowait postinstall skipifsilent
