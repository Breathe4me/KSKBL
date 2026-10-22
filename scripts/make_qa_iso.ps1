param([string]$ExportDirectory='')
$ErrorActionPreference='Stop'
$project=Split-Path $PSScriptRoot -Parent
$expected=Join-Path $project 'qa-export'
if ($ExportDirectory) {
    $selected=[System.IO.Path]::GetFullPath($ExportDirectory)
    if (-not $selected.StartsWith($expected+'\', [System.StringComparison]::OrdinalIgnoreCase)) { throw 'QA export must remain in qa-export' }
    $expected=$selected
}
$resolvedPayload=(Resolve-Path -LiteralPath (Join-Path $expected 'iso-content')).Path
$resolvedOutput=[System.IO.Path]::GetFullPath((Join-Path $expected 'CDA-V12-UI-QA.iso'))
if (-not $resolvedPayload.Equals((Join-Path $expected 'iso-content'), [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected ISO source path' }
if (-not $resolvedOutput.StartsWith($expected+'\', [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected output path' }
if (Test-Path -LiteralPath $resolvedOutput) { throw 'Refusing to overwrite an existing ISO' }
$verification = Get-Content -LiteralPath (Join-Path $expected 'QA_STATIC_VERIFICATION.json') -Raw | ConvertFrom-Json
if ($verification.full_application_cli) {
    $backendProof = Get-Content -LiteralPath (Join-Path $expected 'FROZEN_BACKEND_CHECK.json') -Raw | ConvertFrom-Json
    $checkedExe = Join-Path $expected 'portable\CanvasDeadlineAgent-UI-QA\CanvasDeadlineAgent-UI-QA.exe'
    $actualHash = (Get-FileHash -LiteralPath $checkedExe -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($backendProof.status -ne 'passed' -or $backendProof.exe_sha256 -ne $actualHash -or @($backendProof.cases).Count -eq 0 -or @($backendProof.cases | Where-Object { -not $_.passed }).Count -gt 0) {
        throw 'Frozen backend initialization gate failed; ISO creation blocked'
    }
    $assignmentProof = Get-Content -LiteralPath (Join-Path $expected 'FROZEN_ASSIGNMENT_CHECK.json') -Raw | ConvertFrom-Json
    if ($assignmentProof.status -ne 'passed' -or $assignmentProof.exe_sha256 -ne $actualHash) {
        throw 'Frozen actual assignment write gate failed; ISO creation blocked'
    }
    $credentialProof = Get-Content -LiteralPath (Join-Path $expected 'FROZEN_CREDENTIAL_CHECK.json') -Raw | ConvertFrom-Json
    if ($credentialProof.status -ne 'passed' -or $credentialProof.exe_sha256 -ne $actualHash) {
        throw 'Frozen actual DPAPI gate failed; ISO creation blocked'
    }
    $tlsProof = Get-Content -LiteralPath (Join-Path $expected 'FROZEN_TLS_CHECK.json') -Raw | ConvertFrom-Json
    if ($tlsProof.status -ne 'passed' -or $tlsProof.exe_sha256 -ne $actualHash) {
        throw 'Frozen real local HTTPS gate failed; ISO creation blocked'
    }
}
Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
public static class CDAQaIsoStream {
  public static void Write(object image, string destination) {
    IStream stream=(IStream)image;
    IntPtr read=Marshal.AllocHGlobal(4);
    try {
      byte[] buffer=new byte[1024*1024];
      using(FileStream output=new FileStream(destination,FileMode.CreateNew,FileAccess.Write)) {
        while(true) { stream.Read(buffer,buffer.Length,read);int count=Marshal.ReadInt32(read);if(count==0)break;output.Write(buffer,0,count); }
      }
    } finally { Marshal.FreeHGlobal(read); }
  }
}
'@
$image=New-Object -ComObject IMAPI2FS.MsftFileSystemImage
$image.FileSystemsToCreate=7
$image.VolumeName='CDA_V12_UI_QA'
$image.Root.AddTree($resolvedPayload,$false)
$result=$image.CreateResultImage()
[CDAQaIsoStream]::Write($result.ImageStream,$resolvedOutput)
Get-FileHash -LiteralPath $resolvedOutput -Algorithm SHA256
