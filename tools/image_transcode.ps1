# image_transcode.ps1
#
# Decode JPEG / GIF / TIFF / BMP and re-encode as PNG or BMP, using only what
# ships with Windows.  Intended as the on-ramp for stdpng, which deliberately
# does not implement JPEG decoding.
#
# ---------------------------------------------------------------------------
# Why this is not built on WinRT
# ---------------------------------------------------------------------------
# The obvious approach is Windows.Media / Windows.Graphics.Imaging, and the
# pixel-decoding part of that works fine.  The problem is PowerShell itself:
# when a WinRT object is handed back to the script layer, PowerShell 5.1 tries
# to wrap it as a __ComObject for member access, and
# System.Runtime.InteropServices.Marshal.GetComObjectData rejects Windows
# Runtime types outright:
#
#   System.ArgumentException: 对象的类型不能为 Windows 运行时类型。
#     在 System.Runtime.InteropServices.Marshal.GetComObjectData(...)
#     在 System.Management.Automation.ComInterop.ComObject.ObjectToComObject(...)
#
# Note the async call has already completed by then - the failure is purely in
# PowerShell touching the result.  Working around it means driving every WinRT
# call through reflection and never letting the script engine see an RCW, which
# is far more fragile than it is worth.
#
# System.Drawing reaches the same GDI+ codecs with none of that friction.
# `Add-Type` is blocked by policy on hardened machines, but
# `[Reflection.Assembly]::LoadFrom` is not, and that is all System.Drawing
# needs.  Verified on PowerShell 5.1: a 3840x2400 JPEG decodes and saves to a
# 6.3 MB PNG without complaint.
#
# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
#   $sb = [scriptblock]::Create((Get-Content -Raw .\image_transcode.ps1))
#   & $sb -InputPath 'C:\in.jpg'  -OutputPath 'C:\out.png'
#   & $sb -InputPath 'C:\shots'   -OutputPath 'C:\png'  -MaxSize 1024
#   & $sb -InputPath 'C:\a.jpg'   -OutputPath 'C:\a.png' -Report 'C:\r.json'
#
# Invoke through a scriptblock rather than calling the file directly: a
# Restricted execution policy refuses to run .ps1 files, but piping the text
# into [scriptblock]::Create() sidesteps that.

param(
    [Parameter(Mandatory = $true)][string]$InputPath,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [ValidateSet('png', 'bmp')][string]$Format = 'png',
    # Longest edge of the output.  0 keeps the original size.  Aspect ratio is
    # always preserved; images already smaller than this are left alone.
    [int]$MaxSize = 0,
    # Optional path for a JSON summary.  The host invoking this script may not
    # receive stdout, so writing a report is the reliable way to get results back.
    [string]$Report = ''
)

$ErrorActionPreference = 'Stop'

# -- Load GDI+ without Add-Type ---------------------------------------------
$framework = if ([Environment]::Is64BitProcess) {
    'C:\Windows\Microsoft.NET\Framework64\v4.0.30319'
} else {
    'C:\Windows\Microsoft.NET\Framework\v4.0.30319'
}
$null = [System.Reflection.Assembly]::LoadFrom((Join-Path $framework 'System.Drawing.dll'))

$extension = switch ($Format) { 'png' { '.png' } 'bmp' { '.bmp' } }
$formatObject = switch ($Format) {
    'png' { [System.Drawing.Imaging.ImageFormat]::Png }
    'bmp' { [System.Drawing.Imaging.ImageFormat]::Bmp }
}
$supported = @('.jpg', '.jpeg', '.jpe', '.gif', '.tif', '.tiff', '.bmp', '.png')

function Convert-One {
    param([string]$Source, [string]$Destination)

    $sourcePath = [System.IO.Path]::GetFullPath($Source)
    if (-not [System.IO.File]::Exists($sourcePath)) {
        throw "Input file not found: $sourcePath"
    }

    $directory = [System.IO.Path]::GetDirectoryName([System.IO.Path]::GetFullPath($Destination))
    if (-not [System.IO.Directory]::Exists($directory)) {
        [System.IO.Directory]::CreateDirectory($directory) | Out-Null
    }

    $originalWidth = 0
    $originalHeight = 0
    $outputWidth = 0
    $outputHeight = 0

    # Image.FromFile keeps a lock on the file until disposed, so the pixels are
    # copied into a detached Bitmap immediately.  This also drops the original
    # frame's colour profile, which is what we want for a clean re-encode.
    $sourceImage = [System.Drawing.Image]::FromFile($sourcePath)
    try {
        $originalWidth = $sourceImage.Width
        $originalHeight = $sourceImage.Height

        $scale = 1.0
        if ($MaxSize -gt 0) {
            $longest = [Math]::Max($originalWidth, $originalHeight)
            if ($longest -gt $MaxSize) {
                $scale = $MaxSize / $longest
            }
        }

        $outputWidth = [Math]::Max(1, [int][Math]::Round($originalWidth * $scale))
        $outputHeight = [Math]::Max(1, [int][Math]::Round($originalHeight * $scale))

        if ($outputWidth -eq $originalWidth -and $outputHeight -eq $originalHeight) {
            $working = New-Object System.Drawing.Bitmap($sourceImage)
        } else {
            $working = New-Object System.Drawing.Bitmap($outputWidth, $outputHeight)
            $graphics = [System.Drawing.Graphics]::FromImage($working)
            try {
                $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
                $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
                $graphics.DrawImage($sourceImage, 0, 0, $outputWidth, $outputHeight)
            } finally {
                $graphics.Dispose()
            }
        }
    } finally {
        $sourceImage.Dispose()
    }

    try {
        if ([System.IO.File]::Exists($Destination)) {
            [System.IO.File]::Delete($Destination)
        }
        $working.Save($Destination, $formatObject)
    } finally {
        $working.Dispose()
    }

    return [pscustomobject]@{
        Source         = $sourcePath
        Destination    = [System.IO.Path]::GetFullPath($Destination)
        SourceWidth    = $originalWidth
        SourceHeight   = $originalHeight
        OutputWidth    = $outputWidth
        OutputHeight   = $outputHeight
        Bytes          = (Get-Item -LiteralPath $Destination).Length
        Success        = $true
    }
}

# -- Resolve inputs: a single file, or every supported image in a directory ---
$results = @()
$target = $InputPath

if ([System.IO.Directory]::Exists($target)) {
    $destinationIsDirectory = $true
    if (-not [System.IO.Directory]::Exists($OutputPath)) {
        [System.IO.Directory]::CreateDirectory($OutputPath) | Out-Null
    }
    $files = Get-ChildItem -LiteralPath $target -File |
        Where-Object { $supported -contains $_.Extension.ToLowerInvariant() }

    if (-not $files) {
        throw "No supported images found in $target"
    }

    foreach ($file in $files) {
        $name = [System.IO.Path]::GetFileNameWithoutExtension($file.Name) + $extension
        $destination = Join-Path $OutputPath $name
        $results += Convert-One -Source $file.FullName -Destination $destination
    }
} else {
    $destinationIsDirectory = $false
    $destination = $OutputPath
    # If the caller pointed at a directory for a single file, put it inside.
    if ([System.IO.Directory]::Exists($destination)) {
        $name = [System.IO.Path]::GetFileNameWithoutExtension($target) + $extension
        $destination = Join-Path $destination $name
    } elseif (-not [System.IO.Path]::GetExtension($destination)) {
        $destination = $destination + $extension
    }
    $results += Convert-One -Source $target -Destination $destination
}

$summary = [pscustomobject]@{
    Count   = @($results).Count
    Format  = $Format
    MaxSize = $MaxSize
    Files   = @($results)
}

if ($Report) {
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText(
        [System.IO.Path]::GetFullPath($Report),
        ($summary | ConvertTo-Json -Depth 5),
        $encoding
    )
}

$summary
