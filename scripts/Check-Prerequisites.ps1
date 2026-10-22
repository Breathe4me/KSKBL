param([switch]$JsonOutput)
$ErrorActionPreference = 'Stop'
# Read-only. No download, installer launch, elevation, registry mutation or credential access.
$systemDirectory = [Environment]::GetFolderPath('System')
if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
    $systemDirectory = Join-Path $env:WINDIR 'Sysnative'
}
$minimum = [version]'14.44.35211.0'
$files = @('vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll', 'mfc140u.dll')
$checks = @($files | ForEach-Object {
    $path = Join-Path $systemDirectory $_
    $version = $null
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        $info = [Diagnostics.FileVersionInfo]::GetVersionInfo($path)
        $version = [version]::new($info.FileMajorPart, $info.FileMinorPart, $info.FileBuildPart, $info.FilePrivatePart)
    }
    [pscustomobject]@{ file = $_; path = $path; version = [string]$version; passed = ($null -ne $version -and $version -ge $minimum) }
})
$passed = [Environment]::Is64BitOperatingSystem -and @($checks | Where-Object { -not $_.passed }).Count -eq 0
$result = [pscustomobject]@{
    passed = $passed
    minimumVersion = [string]$minimum
    checks = $checks
    instruction = 'Install the current supported Microsoft x64 Visual C++ v14 Runtime directly from Microsoft. This application does not bundle it or install it automatically.'
    officialSource = 'https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist'
}
if ($JsonOutput) { $result | ConvertTo-Json -Depth 4 } else { $checks | Format-Table; Write-Output $result.instruction; Write-Output $result.officialSource }
if (-not $passed) { exit 2 }
exit 0
