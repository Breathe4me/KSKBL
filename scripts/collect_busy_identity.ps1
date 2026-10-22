param(
    [string]$DataRoot = (Join-Path $env:LOCALAPPDATA 'CanvasDeadlineAgent-v1.2-UI-QA'),
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)
# Run manually IN THE SMOKE VM. Read-only process/package/log inspection; creates only a new evidence folder.
$ErrorActionPreference='Stop'
$marker=Get-Content -LiteralPath (Join-Path $DataRoot 'QA_ONLY.json') -Raw | ConvertFrom-Json
if ($marker.mode -ne 'synthetic_only' -or $marker.schema -ne 1) { throw 'Expected existing synthetic QA directory' }
if (Test-Path -LiteralPath $OutputDirectory) { throw 'Refusing to overwrite existing evidence' }
$output=(New-Item -ItemType Directory -Path $OutputDirectory -ErrorAction Stop).FullName
$known=@{
    '4fc22e96764ae015df6e6124276c95333be46fff04dafe0f7baddf50ceaf3835'='p0-assignment-busyfix-20261022-01'
    'c3e1f105b3f5a2bc8c8f47b69eec54c7bc864407fcc6f5ee24e29339719a4e6f'='p0-backend-bootstrapfix-20261022-01'
    'f22442b250c542dea168787e45a6fe7962b9a445dd522e6efc69cfb4f829491c'='v1.2-functional-integration-20261022-01'
}
$expectedFrontend=@{
    'app.css'='4e6be8588eb5e04adef13e53fd11c2f9583421ac8180f781e6abfdfb883a3f1e'
    'app.js'='1aae602a0ecc5679c1e6677d8cfa46742a1e6461617f92c66de6e1a73930dd59'
    'index.html'='478569c3cfa5ac03569ccb61913864fe3be1516772e65abb46f38841d2142427'
    'prototype.css'='3382a2a7fdb79407713573398064b30e0825debdfe5f0f6040fcdfe0e62a6528'
    'startup.js'='e19d7a77783cc12e83d7d4bad87d6cf494f0e2dc4574799e63d3fcd11e42da51'
}
function MatchesBusyFix($Assets) {
    return @($expectedFrontend.Keys | Where-Object { $Assets[$_] -ne $expectedFrontend[$_] }).Count -eq 0
}
function Identity([string]$Executable) {
    if (-not $Executable -or -not (Test-Path -LiteralPath $Executable -PathType Leaf)) { return @{status='path_unavailable'} }
    $hash=(Get-FileHash -LiteralPath $Executable -Algorithm SHA256).Hash.ToLowerInvariant()
    $folder=Split-Path -Path $Executable -Parent
    $assets=@{}
    foreach ($name in @('index.html','prototype.css','app.css','app.js','startup.js')) {
        $file=Join-Path $folder ('_internal\frontend\'+$name)
        $assets[$name]=if (Test-Path -LiteralPath $file -PathType Leaf) { (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() } else { 'missing' }
    }
    return @{status='read';executable=$Executable;executable_sha256=$hash;known_candidate=$known[$hash];frontend_sha256=$assets;frontend_matches_busyfix=(MatchesBusyFix $assets)}
}
$processes=@()
try {
    # Never read or export CommandLine, environment variables, credentials, config.json or the database.
    foreach ($process in @(Get-CimInstance Win32_Process -Filter "Name='CanvasDeadlineAgent-UI-QA.exe'")) {
        $processes+=@{pid=$process.ProcessId;identity=(Identity $process.ExecutablePath)}
    }
} catch { $processes=@(@{status='process_metadata_unavailable'}) }
$runs=@()
foreach ($directory in @(Get-ChildItem -LiteralPath (Join-Path $DataRoot 'diagnostics') -Directory)) {
    if (-not (Test-Path -LiteralPath (Join-Path $directory.FullName 'startup.jsonl'))) { continue }
    $entry=$null;$paths=$null;$identity=$null;$status=$null
    foreach ($line in Get-Content -LiteralPath (Join-Path $directory.FullName 'startup.jsonl')) {
        try { $row=$line | ConvertFrom-Json } catch { continue }
        if ($row.event -eq 'entry') { $entry=$row.at }
        if ($row.event -eq 'paths') { $paths=$row.executable }
    }
    $statusFile=Join-Path $directory.FullName 'startup-status.json'
    if (Test-Path -LiteralPath $statusFile) { $status=Get-Content -LiteralPath $statusFile -Raw | ConvertFrom-Json }
    $resourceHashes=@{}
    $resourceFile=Join-Path $directory.FullName 'resources.json'
    if (Test-Path -LiteralPath $resourceFile) {
        $resources=Get-Content -LiteralPath $resourceFile -Raw | ConvertFrom-Json
        foreach ($name in @('index.html','prototype.css','app.css','app.js','startup.js')) {
            if ($resources.$name.sha256 -match '^[a-fA-F0-9]{64}$') { $resourceHashes[$name]=$resources.$name.sha256.ToLowerInvariant() }
        }
    }
    $runs+=@{run_id=$directory.Name;entry_utc=$entry;logged_executable=$paths;status=$status.status;
             failure=$status.failure;stages=$status.stages;frontend_sha256=$resourceHashes;
             frontend_matches_busyfix=(MatchesBusyFix $resourceHashes);
             operations_present=(Test-Path -LiteralPath (Join-Path $directory.FullName 'operations.jsonl'))}
}
$result=@{collected_utc=[DateTime]::UtcNow.ToString('o');active_processes=$processes;
          runs_by_entry_time=@($runs | Sort-Object entry_utc -Descending);
          note='A navigation_failed run cannot establish which successful UI later showed Busy. Hashes identify the candidate; timestamps alone do not link a click.'}
$result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $output 'busy-identity-summary.json') -Encoding UTF8
Write-Output (Join-Path $output 'busy-identity-summary.json')
