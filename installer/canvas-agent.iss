#ifndef AppVersion
  #define AppVersion "1.2.0"
#endif
#ifndef PayloadDir
  #error Supply the manifest-bound candidate PayloadDir using scripts/build.ps1
#endif
#ifndef DeliveryDir
  #error Supply a new candidate DeliveryDir using scripts/build.ps1
#endif
#ifndef BuildIdentity
  #error Supply the unique BuildIdentity using scripts/build.ps1
#endif
[Setup]
#ifdef TestBuild
AppId={{CD1C7F70-BB51-4162-93E8-01D94D771D12}
DefaultGroupName=Canvas Deadline Agent v1.2 QA
#else
AppId={{8E5AF001-16C4-48FC-B912-D6637CD6F762}
DefaultGroupName=Canvas Deadline Agent v1.2
#endif
AppName=Canvas Deadline Agent
AppVersion={#AppVersion}
#ifdef ReleasePrep
AppVerName=Canvas Deadline Agent {#AppVersion} Beta release candidate
#else
AppVerName=Canvas Deadline Agent {#AppVersion} development candidate
#endif
VersionInfoVersion=1.2.0.0
VersionInfoTextVersion={#BuildIdentity}
DefaultDirName={localappdata}\Programs\CanvasDeadlineAgent-v1.2
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#DeliveryDir}
#ifdef ReleasePrep
OutputBaseFilename=CanvasDeadlineAgent-v{#AppVersion}-Setup
#else
OutputBaseFilename=CanvasDeadlineAgent-Setup-v{#AppVersion}
#endif
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\CanvasDeadlineAgent.exe
CloseApplications=yes
RestartApplications=no
#ifdef ReleasePrep
InfoBeforeFile=release-notice.txt
#else
InfoBeforeFile=install-notice.txt
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs overwritereadonly uninsremovereadonly

[Icons]
Name: "{group}\Canvas Deadline Agent"; Filename: "{app}\CanvasDeadlineAgent.exe"; AppUserModelID: "CanvasDeadlineAgent"
Name: "{autodesktop}\Canvas Deadline Agent"; Filename: "{app}\CanvasDeadlineAgent.exe"; Tasks: desktopicon; AppUserModelID: "CanvasDeadlineAgent"

[Run]
Filename: "{app}\CanvasDeadlineAgent.exe"; Description: "Launch Canvas Deadline Agent"; Flags: nowait postinstall skipifsilent unchecked

[Code]
function GetFileAttributesW(FileName: String): Cardinal;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function HasReparseParent(Directory: String): Boolean;
var
  Attributes: Cardinal;
  Parent: String;
begin
  Result := False;
  Directory := ExpandFileName(Directory);
  while Directory <> '' do begin
    Attributes := GetFileAttributesW(Directory);
    if (Attributes <> $FFFFFFFF) and ((Attributes and $400) <> 0) then begin
      Result := True;
      Exit;
    end;
    Parent := ExtractFileDir(Directory);
    if CompareText(Parent, Directory) = 0 then Exit;
    Directory := Parent;
  end;
end;

function Overlaps(A, B: String): Boolean;
begin
  A := AddBackslash(ExpandFileName(A));
  B := AddBackslash(ExpandFileName(B));
  Result := (CompareText(Copy(A, 1, Length(B)), B) = 0) or
    (CompareText(Copy(B, 1, Length(A)), A) = 0);
end;

function UnsafeTarget(Target: String): Boolean;
var
  LegacyDir: String;
begin
  Result := HasReparseParent(Target) or
    Overlaps(Target, ExpandConstant('{localappdata}\CanvasDeadlineAgent-v1.2')) or
    Overlaps(Target, ExpandConstant('{localappdata}\Programs\CanvasDeadlineAgent-v1.1')) or
    Overlaps(Target, ExpandConstant('{localappdata}\CanvasDeadlineAgent-v1.1')) or
    Overlaps(Target, ExpandConstant('{localappdata}\CanvasDeadlineAgent')) or
    Overlaps(Target, ExpandConstant('{localappdata}\Programs\CanvasDeadlineAgent')) or
    (DirExists(AddBackslash(Target) + 'development') and
      DirExists(AddBackslash(Target) + 'releases'));
  if RegQueryStringValue(HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{C47B8064-831F-4B42-8B86-90E52DB4CE48}_is1',
    'InstallLocation', LegacyDir) and (LegacyDir <> '') then
    Result := Result or Overlaps(Target, LegacyDir);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  RuntimeFiles: array of String;
  Index: Integer;
  VersionMS, VersionLS, MinimumMS, MinimumLS: Cardinal;
begin
  Result := '';
  RuntimeFiles := ['vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll', 'mfc140u.dll'];
  MinimumMS := (14 shl 16) or 44;
  MinimumLS := 35211 shl 16;
  for Index := 0 to GetArrayLength(RuntimeFiles) - 1 do begin
    if not GetVersionNumbers(ExpandConstant('{sys}\') + RuntimeFiles[Index], VersionMS, VersionLS) then begin
      Result := 'Microsoft x64 Visual C++ v14 Runtime 14.44.35211 or later is required. Install it directly from Microsoft, then rerun this installer: https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist . Nothing will be downloaded or installed automatically.';
      Exit;
    end;
    if (VersionMS < MinimumMS) or ((VersionMS = MinimumMS) and (VersionLS < MinimumLS)) then begin
      Result := 'Update the Microsoft x64 Visual C++ v14 Runtime to 14.44.35211 or later directly from Microsoft before installing. This candidate does not bundle Microsoft runtime DLLs.';
      Exit;
    end;
  end;
  if UnsafeTarget(ExpandConstant('{app}')) then
    Result := 'Choose a separate application folder without reparse points. The selected path overlaps user data, an older installation, or a development/release workspace. No files have been replaced.';
end;


function InitializeUninstall(): Boolean;
var
  ExitCode: Integer;
  Parameters: String;
begin
  Parameters := '--remove-task';
#ifdef TestDataDir
  Parameters := Parameters + ' --data-dir ' + AddQuotes('{#TestDataDir}');
#endif
  Result := Exec(ExpandConstant('{app}\CanvasDeadlineAgent.exe'), Parameters,
    ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ExitCode);
  if Result then
    Result := ExitCode = 0;
  if not Result and not UninstallSilent then
    MsgBox('Cannot remove the Canvas scheduled task. Uninstall has stopped and the application is retained. See task-cleanup-result.json in the application data folder for a diagnostic code.', mbError, MB_OK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    if not UninstallSilent then
      MsgBox('v1.2 settings, data and encrypted credentials are retained in ' + ExpandConstant('{localappdata}\CanvasDeadlineAgent-v1.2') + '. Earlier versions remain separate. Review your backup and the privacy/data-removal instructions before deleting your own v1.2 data.', mbInformation, MB_OK);
end;
