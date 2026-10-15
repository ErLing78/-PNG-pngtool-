# stdpng

**A PNG and pixel-art toolkit that runs on stock Python.** No Pillow, no numpy, no OpenCV, no ImageMagick, no wheels.

```bash
stdpng scale sprite.png sprite_2x.png 2
stdpng quantize sprite.png sprite_16c.png --colors 16
stdpng snap sprite.png sprite_pico8.png --palette pico8
stdpng ascii sprite.png --cols 80
```

---

## 中文说明

**解决什么问题**：所有图像库都有前提——Pillow 要编译好的 wheel、OpenCV 要原生构建、ImageMagick 要 PATH 里有可执行文件。在被安全策略锁死的机器、精简容器或离线环境里，这三个都不存在，而 `pip install` 也连不上网。

**stdpng 只假设一件事：有一份 CPython。** 这就是全部依赖。

**主要功能**：PNG 读写（索引色 / 真彩 / 灰度 / Alpha）、最近邻与面积平均缩放、裁剪旋转翻转、边框裁切、描边、调色板量化（中位切分 + Lab 感知匹配 + 抖动）、调色板互转（`.gpl`/`.pal`/`.hex`/`.act`）、6 套内置像素调色板、ASCII 预览、15 条命令行子命令、BMP/PPM/PGM 互通。

**安装**：把 `src/stdpng/` 拷到脚本旁边即可用，或 `pip install .`。

**使用**：命令行 `stdpng <命令> <输入> <输出> [选项]`；Python 侧 `from stdpng import codec, ops, quantize`。

**示例**见下方 [Examples](#examples) 一节。

---

## What problem does it solve

Every image library assumes something about your machine:

| Library | What it needs | What happens when it's missing |
|---|---|---|
| Pillow | a compiled wheel from PyPI | `pip install pillow` → `No matching distribution found` |
| OpenCV | a native build | same |
| ImageMagick | `magick` / `convert` on `PATH` | nothing to call |
| ffmpeg | a binary on `PATH` | nothing to call |

On a locked-down corporate machine, a distroless container, or an air-gapped box, **all four are unavailable and `pip` cannot reach the network to fix it.**

stdpng assumes exactly one thing: Python 3.8 or newer. That is the whole dependency list.

It is not a Pillow replacement — it is the thing you reach for when Pillow is not an option.

> **One trap worth knowing:** on Windows, `C:\Windows\System32\convert.exe` is the FAT-to-NTFS converter, **not** ImageMagick. Scripts that probe for `convert` find it and then wonder why image conversion does nothing.

---

## Features

### Image I/O
- **PNG**: read and write. 8-bit, colour types 0 (grey) / 2 (RGB) / 3 (indexed) / 4 (grey+alpha) / 6 (RGBA), including `tRNS` transparency. Non-interlaced.
- **BMP**: read and write uncompressed 24- and 32-bit.
- **PPM / PGM**: read and write binary (P5/P6) and ASCII (P2/P3) Netpbm.
- **JPEG**: deliberately not implemented — see [Limitations](#limitations). A Windows helper ships in [`tools/`](tools/README.md).

### Geometry
`crop` · `rotate` (90/180/270) · `flip` (horizontal/vertical) · `scale` (nearest neighbour) · `resize_nearest` (exact size) · `box_resize` (area average, any ratio) · `pad` · `trim` (strip uniform borders)

### Pixel operations
`invert` · `greyscale` · `tint` · `outline` (orthogonal or diagonal) · `replace_colour` (with tolerance) · `extract_alpha` · `apply_mask` · `composite_over_white`

### Palette work
- **Quantise** to N colours with median cut. **N is the total entry budget, transparency included** — `--colors 16` always yields at most 16 entries
- **Perceptual matching** in L\*a\*b\*, so gradients don't come out muddy
- **Floyd–Steinberg dithering**
- **Snap** an image onto a palette you already own — entries are preserved exactly, so output is guaranteed to use your colours
- **Read/write** `.gpl` (GIMP/Aseprite/Krita), `.pal` (JASC), `.hex`, `.act` (Adobe)
- **6 bundled palettes**: `db16`, `db32`, `pico8`, `gameboy`, `nes`, `cga`

### Text-only preview
Render any image as ASCII art — for checking output over SSH, in CI logs, or from a tool that cannot display images.

### Command line
15 subcommands, scriptable, positional in/out, exit code 1 on failure. See [Commands](#commands).

---

## Installation

**Requires Python 3.8 or newer. No third-party packages, ever.**

### Option 1 — vendor it (no install, no network)

Copy the `src/stdpng/` directory next to your script and import it. That's the whole procedure, and it works completely offline.

```bash
git clone https://github.com/ErLing78/-PNG-pngtool-.git
cp -r stdpng/src/stdpng your-project/
```

### Option 2 — pip

```bash
git clone https://github.com/ErLing78/-PNG-pngtool-.git
cd stdpng
pip install .
```

This installs a `stdpng` console command. Verified working — the package installs and runs with zero downloads beyond setuptools.

For a development checkout use `pip install -e .` instead.

### Option 3 — run without installing at all

```bash
cd stdpng
PYTHONPATH=src python -m stdpng.cli info sprite.png
```

> **Note:** `python src/stdpng/cli.py` does **not** work — the package uses relative imports. Use `-m stdpng.cli` with `PYTHONPATH=src`, as shown above.

### Verified versions

Tested end to end on **Python 3.9.0** and **Python 3.13.12**. CI runs the suite on Python 3.8 / 3.10 / 3.12 / 3.13 across Linux, Windows and macOS.

---

## Usage

### Command line

```
stdpng <command> [arguments] [options]
```

Inputs and outputs are positional; every option is a flag. That keeps the tool composable in shell pipelines and makes batch scripts easy to read.

```bash
stdpng --help              # list all commands
stdpng <command> --help    # options for one command
```

### Python

```python
from stdpng import codec, ops, quantize, ascii

image = codec.read("sprite.png")   # -> Image (flat RGBA buffer)
image.width, image.height          # -> ints
image.get(x, y)                    # -> (r, g, b, a)

# every function returns a new Image; nothing is mutated in place
result = ops.scale(image, 2)
codec.write("sprite_2x.png", result)
```

---

## Examples

### Command line

```bash
# Inspect: size, pixel count, byte size, colour count, transparency ratio
stdpng info hero.png

# Pixel-perfect 2x upscale. Nearest neighbour, so it never blurs.
stdpng scale hero.png hero_2x.png 2

# Downsize to exact dimensions
stdpng resize hero.png hero_512.png --width 512 --height 512

# Downsize a photo instead: area averaging, accepts any ratio
stdpng resize photo.png photo_small.png --width 300 --mode box

# Squeeze under a byte budget
stdpng quantize hero.png hero_16c.png --colors 16
stdpng quantize hero.png hero_8c.png  --colors 8 --dither

# Lock a sprite onto a palette. Bundled name, or your own .gpl file.
stdpng snap hero.png hero_pico8.png --palette pico8
stdpng snap hero.png hero_mine.png  --palette ./project-palette.gpl

# Pull a palette out of an image and save it for Aseprite
stdpng extract-palette hero.png hero.gpl --colors 16

# Sprite-sheet hygiene
stdpng crop sheet.png frame1.png --box 0,0,32,32
stdpng trim sheet.png sheet_tight.png
stdpng rotate hero.png hero_cw.png --degrees 90
stdpng flip hero.png hero_mirror.png --axis h

# Look at an image through a text-only channel
stdpng ascii hero.png --cols 100 --mode min

# Convert between formats
stdpng convert photo.bmp photo.png
stdpng convert photo.bmp photo_64c.png --colors 64
```

### Python — geometry

```python
from stdpng import codec, ops

image = codec.read("hero.png")

bigger  = ops.scale(image, 3)                 # nearest neighbour
thumb   = ops.box_resize(image, 64, 64)       # area average, any ratio
frame   = ops.crop(image, 0, 0, 32, 32)       # x, y, width, height
upright = ops.rotate(frame, 90)               # clockwise, multiple of 90
tight   = ops.trim(frame)                     # drop uniform borders
padded  = ops.pad(frame, 2, 2, 2, 2)          # transparent margin

codec.write("frame1.png", upright)
```

### Python — pixel work

```python
from stdpng import codec, ops

image = codec.read("hero.png")

masked   = ops.apply_mask(image, ops.extract_alpha(image))
outlined = ops.outline(image, (0, 0, 0, 255), diagonal=True)
recoloured = ops.replace_colour(image, (255, 0, 255, 255), (0, 0, 0, 0), tolerance=8)

codec.write("hero_outlined.png", outlined)
```

### Python — palettes

```python
from stdpng import codec, quantize

image = codec.read("hero.png")

# Reduce to 16 colours and write an 8-bit indexed PNG
palette, indices = quantize.quantize(image, 16)
codec.write_indexed("hero_16c.png", image, indices, palette)

# Force onto a palette you already own — entries stay exactly as given
palette, indices = quantize.snap(image, quantize.builtin("db16"))
codec.write_indexed("hero_db16.png", image, indices, palette)

# Load a palette from disk
myth = quantize.read_palette("project-palette.gpl")
palette, indices = quantize.snap(image, myth, perceptual=True)
codec.write_indexed("hero_myth.png", image, indices, palette)
```

### Python — transparent handling

```python
from stdpng import codec, quantize

image = codec.read("hero.png")

# `16` is the total entry budget. If the image has genuinely transparent
# pixels, one entry is reserved for them and the colour budget becomes 15.
palette, indices = quantize.quantize(image, 16)
codec.write_indexed("hero_16c.png", image, indices, palette)

# alpha_threshold decides what counts as transparent. This matters more than it
# looks: PNGs that came from a JPEG routinely carry a few thousand pixels with
# alpha in the 220-250 range, left behind by resampling. Treating those as
# transparency would spend a palette entry on nothing, so the default (128)
# only reserves a slot for pixels that are genuinely see-through.
palette, indices = quantize.quantize(image, 16, alpha_threshold=128)
```

### Python — text preview

```python
from stdpng import ascii, codec

image = codec.read("hero.png")
print(ascii.describe(image))                  # "256x160, 16592 colours"
print(ascii.render(image, columns=100, mode="mean"))
```

---

## Commands

| Command | What it does | Key options |
|---|---|---|
| `info` | Size, pixel count, byte size, colour count, transparency ratio | — |
| `resize` | Resize to exact dimensions | `--width`, `--height`, `--mode nearest\|box` |
| `scale` | Multiply dimensions by a factor | `<factor>` |
| `crop` | Extract a rectangle | `--box X,Y,W,H` |
| `rotate` | Rotate by 90 / 180 / 270 | `--degrees` |
| `flip` | Mirror horizontally or vertically | `--axis h\|v` |
| `pad` | Add a border | `--left/--top/--right/--bottom`, `--transparent` |
| `trim` | Remove uniform borders | `--tolerance` |
| `quantize` | Reduce to N colours via median cut | `--colors`, `--dither`, `--perceptual`, `--alpha-threshold` |
| `snap` | Force onto an existing palette | `--palette`, `--dither`, `--perceptual`, `--alpha-threshold` |
| `extract-palette` | Write an image's own palette to a file | `--colors`, `--perceptual` |
| `show-palette` | Print a palette as hex + RGB | `<palette>` |
| `list-palettes` | List bundled palettes | — |
| `ascii` | Render as ASCII art | `--cols`, `--mode mean\|min\|max`, `--invert` |
| `convert` | Convert between PNG / BMP / PPM / PGM | `--colors`, `--dither` |

---

## Formats

| Format | Read | Write | Notes |
|---|---|---|---|
| PNG | yes | yes | 8-bit, colour types 0/2/3/4/6, `tRNS`, non-interlaced. Writes truecolour+alpha or 8-bit indexed. |
| BMP | yes | yes | Uncompressed 24- and 32-bit |
| PPM / PGM | yes | yes | Binary P5/P6 and ASCII P2/P3 |
| JPEG | no | no | Deliberate — see below |

### Why there is no JPEG support

A correct baseline JPEG decoder needs Huffman decoding, dequantisation, inverse DCT, chroma upsampling and colour-space conversion — several hundred lines of subtle code.

The problem is that **a wrong JPEG decoder does not crash.** It produces photographs with slightly incorrect colour, and you find out after processing a few hundred images.

Shipping neither is more honest than shipping a broken one.

**On Windows**, [`tools/image_transcode.ps1`](tools/README.md) converts JPEG/GIF/TIFF to PNG using the GDI+ codecs that ship with the OS — no dependencies, with bulk conversion and optional downscaling:

```powershell
$sb = [scriptblock]::Create((Get-Content -Raw .\tools\image_transcode.ps1))
& $sb -InputPath 'C:\shots' -OutputPath 'C:\work\png' -MaxSize 1024
```

---

## Bundled palettes

| Name | Colours |
|---|---|
| `db16` | 16 |
| `db32` | 32 |
| `pico8` | 16 |
| `gameboy` | 4 |
| `nes` | 36 |
| `cga` | 16 |

```bash
stdpng list-palettes
stdpng show-palette pico8
```

Palette files are read and written as `.gpl`, `.pal`, `.hex` and `.act`.

---

## Performance

Measured on Windows 11, Python 3.13.12, single-threaded. The test image is a synthetic RGB gradient — a **worst case** for both compression and colour counting, since it has maximum entropy. Real sprites and UI art are far faster and far smaller.

### 1024×1024

| Operation | Time |
|---|---|
| Decode | 0.012 s |
| Encode | 0.034 s |
| Nearest resize → 512×512 | 0.031 s |
| Area-average resize → 512×512 | 0.274 s |
| Quantise → 16 colours | 0.603 s |
| Quantise → 256 colours | 2.326 s |
| Quantise → 16 colours + dither | 4.169 s |
| Trim | 0.003 s |
| Outline | 0.064 s |

### 64×64 sprite

| Operation | Time |
|---|---|
| Decode | < 0.001 s |
| Encode | < 0.001 s |
| Scale ×4 | 0.007 s |
| Quantise → 16 colours | 0.015 s |
| Snap to PICO-8 | 0.008 s |

This is pure Python, so it is roughly one to two orders of magnitude slower than Pillow on large images. **The sweet spot is genuinely small images** — sprites, icons, tile sheets, avatars. If you are batch-processing photographs, use Pillow. If you are cleaning up a sprite sheet on a machine where Pillow will not install, this is what you want.

### File sizes

Same worst-case gradient:

| Output | Size |
|---|---|
| 1024×1024 truecolour | 843 KB |
| 1024×1024 / 256 colours | 75 KB |
| 1024×1024 / 128 colours | 59 KB |
| 1024×1024 / 16 colours | 29 KB |
| 512×512 truecolour | 198 KB |
| 512×512 / 256 colours | 31 KB |

Indexed PNG with a median-cut palette typically lands 10–30× smaller than truecolour, which is how you get an avatar under a 500 KB limit.

---

## Limitations

- **Never interpolates.** Every resampling path is nearest neighbour or area average; there is no Lanczos or bicubic. This is a feature for pixel art and a limitation for photographs.
- **8-bit only.** 16-bit PNGs and Adam7 interlacing raise a clear error rather than producing garbage.
- **No animation.** APNG and animated formats are out of scope.
- **No text rendering**, and no drawing primitives beyond `outline` and `pad`.
- **Slow on megapixel photographs.** See the performance section — this is the honest trade-off of zero dependencies.

---

## Testing

```bash
python -m unittest discover -s tests    # 63 unit tests
python tests/smoke_test.py              # 19 CLI invocations + 6 output checks
python tests/readme_examples_test.py    # runs every example in this README
```

All three run on stock CPython with no test dependencies.

The third one exists to keep this document honest: it executes each command and
Python snippet printed above and checks the results, so a claim here cannot
quietly drift away from the code. It also asserts the bundled palette sizes
listed in the table above and the `--colors N` entry-count contract.

CI runs all three on Linux, Windows and macOS against Python 3.8 / 3.10 / 3.12 /
3.13, and asserts that `pyproject.toml` still declares zero dependencies — if
that assertion ever fails, the project has lost the plot.

---

## License

[MIT](LICENSE)
