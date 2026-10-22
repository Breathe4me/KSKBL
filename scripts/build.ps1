param([string]$Python = 'python', [string]$ISCC = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe', [string]$DependencyDir = '', [string]$VisualApprovalRecord = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
if (-not $VisualApprovalRecord -or -not (Test-Path -LiteralPath $VisualApprovalRecord)) {
    throw 'Final installer build blocked: actual Windows visual review and explicit user approval are required. Current mode is source/test delivery only.'
}
$visualApproval = Get-Content -LiteralPath $VisualApprovalRecord -Raw | ConvertFrom-Json
if ($visualApproval.approved_by_user -ne $true -or $visualApproval.actual_windows_gui -ne $true) {
    throw 'An offscreen DOM result is not a Windows visual approval.'
}
$previousPythonPath = $env:PYTHONPATH
$previousBuildInfo = $env:CANVAS_BUILD_INFO
$previousVersionInfo = $env:CANVAS_VERSION_INFO
$previousDependencyDir = $env:CANVAS_DEPENDENCY_DIR
if (-not $DependencyDir) { $DependencyDir = Join-Path $projectRoot '.deps' }
$env:CANVAS_DEPENDENCY_DIR = $DependencyDir
$env:PYTHONPATH = "$projectRoot\src;$projectRoot\.ui-deps;$DependencyDir"
$env:PYTHONDONTWRITEBYTECODE = '1'
$candidateBuildId = "1.2.0-dev-" + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss-fff')
$candidateDirectory = Join-Path $projectRoot "build-candidates\$candidateBuildId"
Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath $ISCC)) { throw 'Install Inno Setup 6 or supply -ISCC' }
    & $Python -B scripts\check_ui_licenses.py --project $projectRoot
    if ($LASTEXITCODE -ne 0) { throw 'UI dependency licenses are incomplete; no binary build started' }
    & $Python -B scripts\build_manifest.py prepare --project $projectRoot --candidate $candidateDirectory --build-id $candidateBuildId
    if ($LASTEXITCODE -ne 0) { throw 'Source snapshot failed' }
    $env:CANVAS_BUILD_INFO = Join-Path $candidateDirectory 'build-info.json'
    $env:CANVAS_VERSION_INFO = Join-Path $candidateDirectory 'version-info.txt'
    & $Python -B -m PyInstaller --noconfirm --clean --distpath "$candidateDirectory\payload" --workpath "$candidateDirectory\pyinstaller" CanvasDeadlineAgent.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
    & $Python -B scripts\collect_licenses.py "$candidateDirectory\payload\CanvasDeadlineAgent\notices\licenses"
    if ($LASTEXITCODE -ne 0) { throw 'License collection failed' }
    & $Python -B scripts\check_ui_licenses.py --project $projectRoot --collect "$candidateDirectory\payload\CanvasDeadlineAgent\notices\licenses"
    if ($LASTEXITCODE -ne 0) { throw 'UI license collection failed' }
    & $ISCC "/DAppVersion=1.2.0" "/DBuildIdentity=$candidateBuildId" "/DPayloadDir=$candidateDirectory\payload\CanvasDeadlineAgent" "/DDeliveryDir=$candidateDirectory" installer\canvas-agent.iss
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup failed' }
    & $Python -B scripts\build_manifest.py finalize --project $projectRoot --candidate $candidateDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Build provenance verification failed' }
    Write-Output "Development candidate only; public release remains blocked: $candidateDirectory"
} finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:CANVAS_BUILD_INFO = $previousBuildInfo
    $env:CANVAS_VERSION_INFO = $previousVersionInfo
    $env:CANVAS_DEPENDENCY_DIR = $previousDependencyDir
    Pop-Location
}
