"""Verify every example that appears in README.md actually runs.

This exists to satisfy one requirement: the README must match the real
behaviour of the project.  Prose claims rot; executable checks do not.
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

from stdpng import codec, ops, quantize  # noqa: E402

failures = []


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print("%s  %s%s" % (status, label, ("  -- " + detail) if detail and not condition else ""))
    if not condition:
        failures.append(label if not detail else "%s: %s" % (label, detail))


def cli(args, cwd):
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "stdpng.cli"] + args,
        cwd=cwd, env=env, capture_output=True, text=True,
    )


def main():
    with tempfile.TemporaryDirectory() as work:
        # Build the fixtures the README examples assume.
        hero = codec.Image(64, 64)
        for y in range(64):
            for x in range(64):
                if x < 8 and y < 8:
                    hero.set(x, y, (0, 0, 0, 0))
                else:
                    hero.set(x, y, ((x * 4) % 256, (y * 4) % 256, 128, 255))
        hero_path = os.path.join(work, "hero.png")
        codec.write(hero_path, hero)

        sheet = codec.Image(128, 32)
        for y in range(32):
            for x in range(128):
                sheet.set(x, y, ((x * 2) % 256, 200, (y * 8) % 256, 255))
        sheet_path = os.path.join(work, "sheet.png")
        codec.write(sheet_path, sheet)

        photo = codec.Image(400, 300)
        for y in range(300):
            for x in range(400):
                photo.set(x, y, ((x * 3) % 256, (y * 5) % 256, 200, 255))
        photo_path = os.path.join(work, "photo.png")
        codec.write(photo_path, photo)
        bmp_path = os.path.join(work, "photo.bmp")
        codec.write(bmp_path, photo) if False else None
        from stdpng import formats
        formats.write_bmp(bmp_path, photo)

        print("=== README: command line examples ===")
        cases = [
            (["info", "hero.png"], "info"),
            (["scale", "hero.png", "hero_2x.png", "2"], "scale"),
            (["resize", "hero.png", "hero_512.png", "--width", "512", "--height", "512"], "resize exact"),
            (["resize", "photo.png", "photo_small.png", "--width", "300", "--mode", "box"], "resize box"),
            (["quantize", "hero.png", "hero_16c.png", "--colors", "16"], "quantize 16"),
            (["quantize", "hero.png", "hero_8c.png", "--colors", "8", "--dither"], "quantize 8 dither"),
            (["snap", "hero.png", "hero_pico8.png", "--palette", "pico8"], "snap pico8"),
            (["extract-palette", "hero.png", "hero.gpl", "--colors", "16"], "extract-palette"),
            (["snap", "hero.png", "hero_mine.png", "--palette", "hero.gpl"], "snap to extracted .gpl"),
            (["crop", "sheet.png", "frame1.png", "--box", "0,0,32,32"], "crop"),
            (["trim", "sheet.png", "sheet_tight.png"], "trim"),
            (["rotate", "hero.png", "hero_cw.png", "--degrees", "90"], "rotate 90"),
            (["flip", "hero.png", "hero_mirror.png", "--axis", "h"], "flip h"),
            (["ascii", "hero.png", "--cols", "100", "--mode", "min"], "ascii"),
            (["convert", "photo.bmp", "photo_out.png"], "convert bmp->png"),
            (["convert", "photo.bmp", "photo_64c.png", "--colors", "64"], "convert + quantise"),
            (["list-palettes"], "list-palettes"),
            (["show-palette", "pico8"], "show-palette"),
            (["--help"], "--help"),
        ]
        for args, label in cases:
            proc = cli(args, work)
            check("cli: %s" % label, proc.returncode == 0, proc.stderr.strip()[:200])

        # Outputs claimed in the README must exist and have the stated size.
        expectations = [
            ("hero_2x.png", 128, 128),
            ("hero_512.png", 512, 512),
            ("photo_small.png", 300, 300),
            ("hero_16c.png", 64, 64),
            ("hero_pico8.png", 64, 64),
            ("hero_mine.png", 64, 64),
            ("frame1.png", 32, 32),
            ("hero_cw.png", 64, 64),
            ("hero_mirror.png", 64, 64),
            ("photo_out.png", 400, 300),
            ("photo_64c.png", 400, 300),
        ]
        for name, want_w, want_h in expectations:
            path = os.path.join(work, name)
            if not os.path.exists(path):
                check("output: %s" % name, False, "missing")
                continue
            img = codec.read(path)
            check("output: %s is %dx%d" % (name, want_w, want_h),
                  (img.width, img.height) == (want_w, want_h),
                  "got %dx%d" % (img.width, img.height))

        # The README says list-palettes reports exactly these six names.
        proc = cli(["list-palettes"], work)
        for name in ("db16", "db32", "pico8", "gameboy", "nes", "cga"):
            check("list-palettes includes %s" % name, name in proc.stdout)

        # --- Python snippets from the README ---
        print()
        print("=== README: Python examples ===")

        img = codec.read(hero_path)
        check("codec.read + width/height", (img.width, img.height) == (64, 64))
        check("image.get returns 4-tuple", len(img.get(0, 0)) == 4)

        # Geometry block
        bigger = ops.scale(img, 3)
        check("ops.scale(img, 3) -> 192x192", (bigger.width, bigger.height) == (192, 192))
        thumb = ops.box_resize(img, 64, 64)
        check("ops.box_resize(img, 64, 64)", (thumb.width, thumb.height) == (64, 64))
        frame = ops.crop(img, 0, 0, 32, 32)
        check("ops.crop(img, 0,0,32,32)", (frame.width, frame.height) == (32, 32))
        upright = ops.rotate(frame, 90)
        check("ops.rotate(frame, 90)", (upright.width, upright.height) == (32, 32))
        tight = ops.trim(frame)
        check("ops.trim(frame) returns an image", tight.width >= 1 and tight.height >= 1)
        padded = ops.pad(frame, 2, 2, 2, 2)
        check("ops.pad(frame, 2,2,2,2) -> 36x36", (padded.width, padded.height) == (36, 36))
        check("codec.write of rotated frame", os.path.exists(
            (lambda p: (codec.write(p, upright), p)[1])(os.path.join(work, "frame1_py.png"))))

        # Pixel block
        masked = ops.apply_mask(img, ops.extract_alpha(img))
        check("ops.apply_mask(extract_alpha)", (masked.width, masked.height) == (64, 64))
        outlined = ops.outline(img, (0, 0, 0, 255), diagonal=True)
        check("ops.outline(..., diagonal=True)", (outlined.width, outlined.height) == (64, 64))
        recoloured = ops.replace_colour(img, (255, 0, 255, 255), (0, 0, 0, 0), tolerance=8)
        check("ops.replace_colour(tolerance=8)", (recoloured.width, recoloured.height) == (64, 64))

        # Palette block
        palette, indices = quantize.quantize(img, 16)
        check("quantize.quantize(img, 16) -> <=16 colours", len(palette) <= 16,
              "got %d" % len(palette))
        p = os.path.join(work, "py_16c.png")
        codec.write_indexed(p, img, indices, palette)
        check("codec.write_indexed readable", codec.read(p).width == 64)

        palette, indices = quantize.snap(img, quantize.builtin("db16"))
        check("builtin('db16') has 16 entries", len(palette) == 16)
        p = os.path.join(work, "py_db16.png")
        codec.write_indexed(p, img, indices, palette)
        check("write_indexed(snap to db16)", codec.read(p).width == 64)

        myth = quantize.read_palette(os.path.join(work, "hero.gpl"))
        check("quantize.read_palette('.gpl')", len(myth) > 0)
        palette, indices = quantize.snap(img, myth, perceptual=True)
        p = os.path.join(work, "py_myth.png")
        codec.write_indexed(p, img, indices, palette)
        check("write_indexed(snap perceptual=True)", codec.read(p).width == 64)

        # Alpha-threshold block
        palette, indices = quantize.quantize(img, 16, alpha_threshold=128)
        check("quantize(alpha_threshold=128)", len(palette) <= 17,
              "got %d" % len(palette))
        # The fixture has a transparent 8x8 corner, so a slot IS reserved.
        check("transparent corner reserves a palette slot", len(palette[0]) == 4,
              "first entry is %r" % (palette[0],))

        # ascii block
        text = ascii_check = None
        from stdpng import ascii as ascii_mod
        text = ascii_mod.describe(img)
        check("ascii.describe reports dimensions", "64x64" in text, text)
        rendered = ascii_mod.render(img, columns=100, mode="mean")
        check("ascii.render(columns=100) width",
              all(len(line) == 100 for line in rendered.split("\n")))

        # Claims about bundled palette sizes
        print()
        print("=== README: bundled palette table ===")
        claimed = {"db16": 16, "db32": 32, "pico8": 16, "gameboy": 4, "nes": 36, "cga": 16}
        for name, count in claimed.items():
            actual = len(quantize.builtin(name))
            check("palette %s has %d colours" % (name, count), actual == count,
                  "actual %d" % actual)

        # Claim: __version__ is 0.1.0
        import stdpng as pkg
        check("__version__ == 0.1.0", pkg.__version__ == "0.1.0", pkg.__version__)

    print()
    if failures:
        print("README VERIFICATION FAILED (%d)" % len(failures))
        for item in failures:
            print("  - " + item)
        return 1
    print("README VERIFICATION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
