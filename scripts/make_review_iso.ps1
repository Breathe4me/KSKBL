param([Parameter(Mandatory=$true)][string]$Payload, [Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference='Stop'
$resolvedPayload=(Resolve-Path -LiteralPath $Payload).Path
$resolvedOutput=[System.IO.Path]::GetFullPath($Output)
if (-not $resolvedPayload.StartsWith('G:\CanvasDeadlineAgent\development\v1.2\ui-redesign\review-builds\', [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Only the isolated review payload is allowed' }
if (-not $resolvedOutput.StartsWith('G:\CanvasDeadlineAgent\development\v1.2\ui-redesign\review-builds\', [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Output must remain in isolated review builds' }
if (Test-Path -LiteralPath $resolvedOutput) { throw 'Refusing to overwrite an existing review ISO' }
Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
public static class CDAReviewIsoStream {
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
$image.VolumeName='CDA_UI_REVIEW'
$image.Root.AddTree($resolvedPayload,$false)
$result=$image.CreateResultImage()
[CDAReviewIsoStream]::Write($result.ImageStream,$resolvedOutput)
Get-FileHash -LiteralPath $resolvedOutput -Algorithm SHA256
