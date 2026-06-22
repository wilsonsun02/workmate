; Workmate Desktop 安装脚本（Inno Setup）
; 打包前置产物：..\dist\workmate-desktop\...
; 离线 Node 安装包：.\installer-assets\node-v20.19.0-x64.msi

#define BundledNodeMsiName "node-v20.19.0-x64.msi"
#define BundledNodeMsiPath "installer-assets\" + BundledNodeMsiName
#define AppIconFileName "workmate.ico"
#define AppIconSourcePath "installer-assets\" + AppIconFileName
#ifexist BundledNodeMsiPath
  #define HasBundledNode 1
#else
  #define HasBundledNode 0
#endif

[Setup]
AppId={{D8A2A3D7-0F6A-4E40-9B9A-3CF1A9A5E321}
AppName=Workmate Desktop
AppVersion=0.1.0
AppPublisher=Workmate
DefaultDirName={localappdata}\Programs\WorkmateDesktop
DefaultGroupName=Workmate Desktop
OutputDir=..\dist
OutputBaseFilename=WorkmateDesktop-Setup
Compression=lzma
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
PrivilegesRequired=admin
SetupIconFile={#AppIconSourcePath}
UninstallDisplayIcon={app}\{#AppIconFileName}

[Languages]
Name: "chinesesimp"; MessagesFile: "installer-assets\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: unchecked

[Files]
Source: "..\dist\workmate-desktop\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "{#AppIconSourcePath}"; DestDir: "{app}"; Flags: ignoreversion
#if HasBundledNode
Source: "{#BundledNodeMsiPath}"; Flags: dontcopy
#endif

[Icons]
Name: "{group}\Workmate Desktop"; Filename: "{app}\workmate-desktop.exe"; IconFilename: "{app}\{#AppIconFileName}"
Name: "{autodesktop}\Workmate Desktop"; Filename: "{app}\workmate-desktop.exe"; Tasks: desktopicon; IconFilename: "{app}\{#AppIconFileName}"

[Run]
Filename: "{app}\workmate-desktop.exe"; Description: "启动 Workmate Desktop"; Flags: nowait postinstall skipifsilent

[Code]
const
  NodeDownloadUrl = 'https://nodejs.org/zh-cn/download';
  RequiredNodeMajor = 20;
  BundledNodeMsi = '{#BundledNodeMsiName}';
  HasBundledNode = {#HasBundledNode};

function IsCommandAvailable(const Cmd: string): Boolean;
var
  ResultCode: Integer;
begin
  Result :=
    Exec('cmd.exe', '/C where ' + Cmd, '', SW_HIDE, ewWaitUntilTerminated, ResultCode)
    and (ResultCode = 0);
end;

procedure AskOpenNodeDownload(const Reason: string);
var
  Answer: Integer;
  ErrorCode: Integer;
begin
  Answer := MsgBox(Reason + #13#10#13#10 + '是否现在打开 Node.js 下载页面？', mbConfirmation, MB_YESNO);
  if Answer = IDYES then
  begin
    ShellExec('open', NodeDownloadUrl, '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
  end;
end;

function GetNodeVersionByCommand(const CmdLine: string): Integer;
var
  TmpFile: string;
  ResultCode: Integer;
  VersionRawAnsi: AnsiString;
  VersionRaw: string;
  Parsed: Integer;
begin
  Result := -1;
  TmpFile := ExpandConstant('{tmp}\node_version.txt');

  if not Exec(
    'cmd.exe',
    '/C ' + CmdLine + ' > "' + TmpFile + '"',
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  ) then
  begin
    Exit;
  end;

  if (ResultCode <> 0) or (not LoadStringFromFile(TmpFile, VersionRawAnsi)) then
  begin
    Exit;
  end;

  VersionRaw := VersionRawAnsi;

  StringChangeEx(VersionRaw, #13, '', True);
  StringChangeEx(VersionRaw, #10, '', True);
  StringChangeEx(VersionRaw, 'v', '', True);

  if Pos('.', VersionRaw) > 0 then
  begin
    Delete(VersionRaw, Pos('.', VersionRaw), MaxInt);
  end;

  Parsed := StrToIntDef(Trim(VersionRaw), -1);
  if Parsed >= 0 then
  begin
    Result := Parsed;
  end;
end;

function HasQualifiedNodeInPath(): Boolean;
var
  NodeMajor: Integer;
begin
  Result := False;

  if not IsCommandAvailable('node') then
  begin
    Exit;
  end;
  if not IsCommandAvailable('npm') then
  begin
    Exit;
  end;
  if not IsCommandAvailable('npx') then
  begin
    Exit;
  end;

  NodeMajor := GetNodeVersionByCommand('node -v');
  if NodeMajor < RequiredNodeMajor then
  begin
    Exit;
  end;

  Result := True;
end;

function InstallBundledNode(): Boolean;
var
  ResultCode: Integer;
  TmpMsi: string;
begin
  Result := False;
  TmpMsi := ExpandConstant('{tmp}\' + BundledNodeMsi);

  ExtractTemporaryFile(BundledNodeMsi);

  if not Exec(
    'msiexec.exe',
    '/i "' + TmpMsi + '" /qn /norestart',
    '',
    SW_SHOW,
    ewWaitUntilTerminated,
    ResultCode
  ) then
  begin
    MsgBox('执行内置 Node 安装程序失败，请联系运维。', mbError, MB_OK);
    Exit;
  end;

  if (ResultCode = 0) or (ResultCode = 3010) then
  begin
    Result := True;
  end
  else
  begin
    MsgBox(
      Format('内置 Node 安装失败（退出码 %d）。请联系运维或手工安装 Node.js LTS。', [ResultCode]),
      mbError,
      MB_OK
    );
  end;
end;

function InitializeSetup(): Boolean;
var
  Answer: Integer;
begin
  Result := True;

  if HasQualifiedNodeInPath() then
  begin
    Exit;
  end;

  if HasBundledNode = 0 then
  begin
    AskOpenNodeDownload('未检测到可用的 Node.js 环境，且当前安装包未内置离线 Node。请先安装 Node.js LTS（>= 20，且包含 npm/npx），再重新运行安装程序。');
    Result := False;
    Exit;
  end;

  Answer := MsgBox(
    '未检测到可用的 Node.js 环境（要求 Node.js >= 20 且包含 npm/npx）。' + #13#10 +
    '是否使用安装包内置的 Node 离线安装程序自动安装？',
    mbConfirmation,
    MB_YESNO
  );

  if Answer = IDYES then
  begin
    if not InstallBundledNode() then
    begin
      Result := False;
      Exit;
    end;

    MsgBox(
      'Node 离线安装已完成。若首次启动仍提示缺少 Node，请关闭后重新打开应用（让系统 PATH 刷新）。',
      mbInformation,
      MB_OK
    );
    Exit;
  end;

  AskOpenNodeDownload('请先安装 Node.js LTS（>= 20，且包含 npm/npx），再重新运行安装程序。');
  Result := False;
end;
