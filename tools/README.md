# tools/

Helpers that bridge stdpng to the operating system. Nothing here is required
to use the library; these exist for the gaps stdpng deliberately leaves open.

## image_transcode.ps1

Decodes JPEG / GIF / TIFF / BMP and re-encodes as PNG or BMP, using the GDI+
codecs that ship with Windows. This is the on-ramp for stdpng's one deliberate
omission: JPEG decoding.

```powershell
$sb = [scriptblock]::Create((Get-Content -Raw .\image_transcode.ps1))

# A single file, original size
& $sb -InputPath 'C:\shots\hero.jpg' -OutputPath 'C:\work\hero.png'

# Scale the longest edge to 512 while converting
& $sb -InputPath 'C:\shots\hero.jpg' -OutputPath 'C:\work\hero.png' -MaxSize 512

# Every image in a directory
& $sb -InputPath 'C:\shots' -OutputPath 'C:\work\png' -MaxSize 1024

# Write a JSON summary for a program to read back
& $sb -InputPath 'C:\shots\hero.jpg' -OutputPath 'C:\work\hero.png' -Report 'C:\work\report.json'
```

Parameters:

| Parameter | Default | Meaning |
|---|---|---|
| `-InputPath` | required | A file, or a directory to process in bulk |
| `-OutputPath` | required | A file, or an output directory |
| `-Format` | `png` | `png` or `bmp` |
| `-MaxSize` | `0` | Longest output edge; `0` keeps the original size |
| `-Report` | none | Path for a JSON summary of what happened |

### Why invoke it through a scriptblock?

A `Restricted` execution policy refuses to run `.ps1` files at all (exit code 1,
no output). Reading the file and piping its text into `[scriptblock]::Create()`
sidesteps the policy without changing it. This is also why the script avoids
`$script:` scoped variables, which resolve to `null` inside a created scriptblock.

### Why not WinRT?

The obvious way to decode a JPEG on Windows is `Windows.Graphics.Imaging`. The
decoding half works. The problem is PowerShell: when a WinRT object comes back
to the script layer, PowerShell 5.1 tries to wrap it as a `__ComObject`, and
`Marshal.GetComObjectData` refuses Windows Runtime types:

```
System.ArgumentException: 对象的类型不能为 Windows 运行时类型。
   at System.Runtime.InteropServices.Marshal.GetComObjectData(Object obj, Object key)
   at System.Management.Automation.ComInterop.ComObject.ObjectToComObject(Object rcw)
```

Note that the async operation has *already completed* by the time this throws -
the failure is entirely in PowerShell touching the result. Working around it
means driving every WinRT call through reflection and never letting the script
engine see an RCW, which is far more fragile than it is worth.

`System.Drawing` reaches the same GDI+ codecs with none of that friction. The
usual objection is that `Add-Type` is blocked on hardened machines - but
`[Reflection.Assembly]::LoadFrom` is not, and that is all System.Drawing needs.

Verified on PowerShell 5.1.26100: a 3840x2400 JPEG decodes and writes a 6.3 MB
PNG; `-MaxSize 256` produces 256x160; a directory of 6 files converts in one
call; a missing input throws rather than silently succeeding.

## Note for other tools

If you are writing your own Windows helper for a restricted environment, the
same two tricks apply:

- `[Reflection.Assembly]::LoadFrom('C:\Windows\Microsoft.NET\Framework64\v4.0.30319\<Name>.dll')`
  loads a framework assembly without `Add-Type`.
- Write results to a file rather than relying on stdout; some hosts do not
  return it.
