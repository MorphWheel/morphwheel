; Morphwheel installer (phase-4 section 8.2, phase-2 section 3.7). Inno Setup 6.3 or later.
;
; Rules:
; - Per-user, no UAC: PrivilegesRequired=lowest, into {localappdata}\Programs\Morphwheel ({autopf}
;   maps to the user form under lowest). A Setup or uninstaller that runs with a full elevated token
;   is refused (InitializeSetup/InitializeUninstall): it would install into the administrator's
;   profile and write the administrator's Run value, the trap the whole design avoids.
; - "Launch" at the end runs as the original user (runasoriginaluser, phase-2 section 3.7) and is
;   skipped in silent mode (winget).
; - One instance (RD-23c): AppMutex is the app's exact mutex name, Local\Morphwheel; Setup and the
;   uninstaller refuse to run while the app runs.
; - Start with Windows (RD-23): the task writes HKCU\...\Run\Morphwheel exactly as the app does
;   (the exe path, quoted only when it has a space: subprocess.list2cmdline's rule for one argument;
;   a Windows path can't contain a quote or a tab). The task is unchecked on a fresh install (the
;   app's default), mirrors the registry once on an upgrade unless /TASKS or /MERGETASKS was given,
;   and is an exact setter: checked writes the value (and clears Task Manager's StartupApproved
;   mark when the value is new, as the app's toggle does); unchecked in an interactive run deletes
;   the value and the mark; unchecked in a silent run changes nothing (a silent upgrade must not turn
;   autostart off).
; - The uninstaller deletes the Run value and the mark, and asks (not when silent, default No)
;   whether to delete the user's data as well: settings and plugins ({userappdata}\Morphwheel) and
;   logs and downloaded engines ({localappdata}\Morphwheel). Converted files are never touched.
; - Upgrades clean {app}\_internal first: a PyInstaller folder is one artifact, and a stale Qt plugin
;   left behind would be loaded (the S0 trim and the spec's keep-list must survive an upgrade).
; - The version comes from the built exe's resource, so it never drifts from __version__.
; - A6: pillow-heif is never bundled. The compile fails if the dist carries it.
; - Translatable: every string of ours is a [CustomMessages] entry per language (D3a). The checkbox
;   and "Launch" texts are Inno's own, translated in every .isl.
;
; Compile (after the PyInstaller build):  ISCC.exe packaging\inno\morphwheel.iss
; Override the dist folder:               ISCC.exe /DDistDir=<folder> packaging\inno\morphwheel.iss

#if VER < EncodeVer(6,3,0)
  #error Inno Setup 6.3 or later is required
#endif

#define AppName "Morphwheel"
#define AppPublisher "Morphwheel contributors"
#define AppURL "https://github.com/MorphWheel/morphwheel"
; SourcePath (this script's folder) ends with a backslash.
#ifndef DistDir
  #define DistDir SourcePath + "..\output\dist\morphwheel"
#endif
#define AppExe DistDir + "\morphwheel.exe"
#define WorkerExe DistDir + "\morphwheel-worker.exe"
#define RepoRoot SourcePath + "..\.."
#define Notices RepoRoot + "\THIRD_PARTY_NOTICES.md"

#if !FileExists(AppExe)
  #error The PyInstaller build is missing: run morphwheel.spec first (DistDir + "\morphwheel.exe")
#endif
#if !FileExists(WorkerExe)
  #error The dist has no morphwheel-worker.exe (A5a): not a complete build
#endif
#if DirExists(DistDir + "\_internal\pillow_heif") || FileExists(DistDir + "\_internal\libheif.dll")
  #error pillow-heif is GPLv2 and is never bundled (A6): the dist carries it
#endif

#define AppVersion GetStringFileInfo(AppExe, "ProductVersion")
#define FileVersion GetVersionNumbersString(AppExe)
#define Copyright GetStringFileInfo(AppExe, "LegalCopyright")
#if AppVersion == "" || FileVersion == ""
  #error The exe carries no version resource (file_version_info.txt): the installer would be nameless
#endif

[Setup]
AppId={{5D597E37-BBB5-46D5-853A-E4A925193830}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
AppCopyright={#Copyright}
VersionInfoVersion={#FileVersion}
VersionInfoProductTextVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Setup
VersionInfoCopyright={#Copyright}

DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19045
AppMutex=Local\Morphwheel
CloseApplications=yes
RestartApplications=no
UsePreviousTasks=no

LicenseFile={#RepoRoot}\LICENSE
SetupIconFile={#RepoRoot}\assets\icon\morphwheel.ico
UninstallDisplayIcon={app}\morphwheel.exe
UninstallDisplayName={#AppName}
WizardStyle=modern
ShowLanguageDialog=no

Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
OutputDir={#SourcePath}..\output\installer
OutputBaseFilename=morphwheel-{#AppVersion}-setup

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
english.ElevatedRefused={#AppName} installs for your user account only and must not run as administrator.%nStart it again without "Run as administrator".
english.DeleteDataQuestion=Delete your {#AppName} settings, plugins, logs and downloaded engines too?%n%nThis removes:%n%1%n%2%n%nPlugins you wrote under the plugins folder are deleted with them. Converted files are never touched.

[Tasks]
Name: "autostart"; Description: "{cm:AutoStartProgram,{#AppName}}"; GroupDescription: "{cm:AutoStartProgramGroupDescription}"; Flags: unchecked

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#if FileExists(Notices)
Source: "{#Notices}"; DestDir: "{app}"; Flags: ignoreversion
#endif

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\morphwheel.exe"

[Run]
Filename: "{app}\morphwheel.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall runasoriginaluser skipifsilent

[Code]
const
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';
  ApprovedKey = 'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run';
  RunValueName = 'Morphwheel';
  TOKEN_QUERY = 8;
  TokenElevationType = 18;
  TokenElevationTypeFull = 2;

var
  HadRunValue: Boolean;  { at Setup's start, before anything is written }
  Mirrored: Boolean;     { the tasks page was set from the registry once }

{ ---- the elevation refusal (mirrors platform/system.is_elevated: the full half of a split token) }

function GetCurrentProcess(): THandle;
  external 'GetCurrentProcess@kernel32.dll stdcall';
function OpenProcessToken(ProcessHandle: THandle; DesiredAccess: DWORD; var TokenHandle: THandle): Boolean;
  external 'OpenProcessToken@advapi32.dll stdcall';
function GetTokenInformation(TokenHandle: THandle; InformationClass: Integer; var Information: DWORD; Length: DWORD; var ReturnLength: DWORD): Boolean;
  external 'GetTokenInformation@advapi32.dll stdcall';
function CloseHandle(Handle: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';

function IsFullyElevated(): Boolean;
var
  Token: THandle;
  ElevationType, Needed: DWORD;
begin
  Result := False;
  if OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, Token) then
  begin
    ElevationType := 0;
    if GetTokenInformation(Token, TokenElevationType, ElevationType, SizeOf(ElevationType), Needed) then
      Result := ElevationType = TokenElevationTypeFull;
    CloseHandle(Token);
  end;
end;

function RefuseIfElevated(): Boolean;
begin
  Result := not IsFullyElevated();
  if not Result then
    SuppressibleMsgBox(CustomMessage('ElevatedRefused'), mbError, MB_OK, IDOK);
end;

{ ---- start with Windows (RD-23) }

function RunValue(): String;
var
  Exe: String;
begin
  Exe := ExpandConstant('{app}\morphwheel.exe');
  if Pos(' ', Exe) > 0 then
    Result := '"' + Exe + '"'
  else
    Result := Exe;
end;

function CmdLineSetsTasks(): Boolean;
var
  Tail: String;
begin
  Tail := Uppercase(GetCmdTail());  { /TASKS also covers /MERGETASKS; /LOADINF may carry Tasks= }
  Result := (Pos('/TASKS', Tail) > 0) or (Pos('/LOADINF', Tail) > 0);
end;

procedure DeleteRunValue();
begin
  if RegValueExists(HKCU, RunKey, RunValueName) then
    RegDeleteValue(HKCU, RunKey, RunValueName);
  if RegValueExists(HKCU, ApprovedKey, RunValueName) then
    RegDeleteValue(HKCU, ApprovedKey, RunValueName);
end;

procedure ApplyAutostartTask();
begin
  if WizardIsTaskSelected('autostart') then
  begin
    if not RegWriteStringValue(HKCU, RunKey, RunValueName, RunValue()) then
      Log('autostart: the Run value could not be written');
    if not HadRunValue and RegValueExists(HKCU, ApprovedKey, RunValueName) then
      RegDeleteValue(HKCU, ApprovedKey, RunValueName);  { a fresh "on" clears a stale Disable }
  end
  else if not WizardSilent then
    DeleteRunValue();  { an explicit "off"; a silent run leaves the user's choice alone }
end;

{ ---- events }

function InitializeSetup(): Boolean;
begin
  Result := RefuseIfElevated();
  HadRunValue := RegValueExists(HKCU, RunKey, RunValueName);
  Mirrored := False;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpSelectTasks) and not Mirrored then
  begin
    Mirrored := True;
    if HadRunValue and not CmdLineSetsTasks() then
      WizardSelectTasks('autostart');
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    ApplyAutostartTask();
end;

function InitializeUninstall(): Boolean;
begin
  Result := RefuseIfElevated();
end;

procedure DeleteUserData();
var
  ConfigDir, DataDir: String;
begin
  ConfigDir := ExpandConstant('{userappdata}\' + '{#AppName}');
  DataDir := ExpandConstant('{localappdata}\' + '{#AppName}');
  if MsgBox(FmtMessage(CustomMessage('DeleteDataQuestion'), [ConfigDir, DataDir]), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
  begin
    if DirExists(ConfigDir) and not DelTree(ConfigDir, True, True, True) then
      Log('uninstall: could not delete ' + ConfigDir);
    if DirExists(DataDir) and not DelTree(DataDir, True, True, True) then
      Log('uninstall: could not delete ' + DataDir);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    DeleteRunValue();
    if not UninstallSilent then
      DeleteUserData();
  end;
end;
