"""Test suite.  Runs on stock CPython with ``python -m unittest`` - no pytest.

The tests deliberately build tiny synthetic images by hand rather than shipping
fixture files: a 4x4 checkerboard is easier to reason about than a PNG nobody
can inspect in a diff.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from stdpng import ascii as ascii_mod  # noqa: E402
from stdpng import codec, formats, ops, quantize  # noqa: E402


def solid(width, height, rgba):
    """An image filled with a single colour."""
    return codec.Image(width, height, bytearray(bytes(rgba) * (width * height)))


def checkerboard(width, height, a=(255, 0, 0, 255), b=(0, 0, 255, 255)):
    image = codec.Image(width, height)
    for y in range(height):
        for x in range(width):
            image.set(x, y, a if (x + y) % 2 == 0 else b)
    return image


class TestCodec(unittest.TestCase):
    def test_rgba_round_trip(self):
        original = checkerboard(8, 6)
        decoded = codec.decode(codec.encode(original))
        self.assertEqual((decoded.width, decoded.height), (8, 6))
        self.assertEqual(bytes(decoded.pixels), bytes(original.pixels))

    def test_round_trip_through_file(self):
        original = checkerboard(5, 3)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.png")
            codec.write(path, original)
            decoded = codec.read(path)
        self.assertEqual(bytes(decoded.pixels), bytes(original.pixels))

    def test_indexed_round_trip_preserves_alpha(self):
        image = codec.Image(4, 1)
        palette = [(255, 0, 0, 255), (0, 255, 0, 128), (0, 0, 255, 0)]
        indices = bytearray([0, 1, 2, 0])
        for x, index in enumerate(indices):
            entry = palette[index]
            image.set(x, 0, entry)
        data = codec.encode_indexed(image, indices, palette)
        decoded = codec.decode(data)
        self.assertEqual(decoded.get(0, 0), (255, 0, 0, 255))
        self.assertEqual(decoded.get(1, 0), (0, 255, 0, 128))
        self.assertEqual(decoded.get(2, 0), (0, 0, 255, 0))

    def test_rejects_bad_signature(self):
        with self.assertRaises(codec.PNGError):
            codec.decode(b"not a png at all")

    def test_rejects_truncated_ihdr(self):
        with self.assertRaises(codec.PNGError):
            codec.decode(codec.PNG_SIGNATURE + b"\x00\x00\x00\x0dIHDR")

    def test_grayscale_decodes_to_grey(self):
        # Build a colour type 0 image by hand: 2x1 greyscale, filter 0.
        import struct
        import zlib

        raw = bytes([0, 0, 255])  # filter byte, then two 8-bit samples
        def chunk(ctype, payload):
            return (
                struct.pack(">I", len(payload))
                + ctype
                + payload
                + struct.pack(">I", zlib.crc32(ctype + payload) & 0xFFFFFFFF)
            )

        data = bytearray(codec.PNG_SIGNATURE)
        data += chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 0, 0, 0, 0))
        data += chunk(b"IDAT", zlib.compress(raw))
        data += chunk(b"IEND", b"")
        image = codec.decode(bytes(data))
        self.assertEqual(image.get(0, 0), (0, 0, 0, 255))
        self.assertEqual(image.get(1, 0), (255, 255, 255, 255))


class TestGeometry(unittest.TestCase):
    def test_crop_extracts_the_right_region(self):
        image = solid(8, 8, (10, 20, 30, 255))
        image.set(4, 4, (200, 100, 50, 255))
        cropped = ops.crop(image, 3, 3, 3, 3)
        self.assertEqual((cropped.width, cropped.height), (3, 3))
        self.assertEqual(cropped.get(1, 1), (200, 100, 50, 255))
        self.assertEqual(cropped.get(0, 0), (10, 20, 30, 255))

    def test_crop_clips_to_image_bounds(self):
        image = solid(4, 4, (1, 2, 3, 255))
        cropped = ops.crop(image, 2, 2, 100, 100)
        self.assertEqual((cropped.width, cropped.height), (2, 2))

    def test_crop_entirely_outside_raises(self):
        image = solid(4, 4, (1, 2, 3, 255))
        with self.assertRaises(codec.PNGError):
            ops.crop(image, 50, 50, 4, 4)

    def test_flip_horizontal(self):
        image = codec.Image(3, 1)
        image.set(0, 0, (1, 0, 0, 255))
        image.set(1, 0, (2, 0, 0, 255))
        image.set(2, 0, (3, 0, 0, 255))
        flipped = ops.flip_horizontal(image)
        self.assertEqual([flipped.get(x, 0)[0] for x in range(3)], [3, 2, 1])

    def test_flip_vertical(self):
        image = codec.Image(1, 3)
        for y in range(3):
            image.set(0, y, (y + 1, 0, 0, 255))
        flipped = ops.flip_vertical(image)
        self.assertEqual([flipped.get(0, y)[0] for y in range(3)], [3, 2, 1])

    def test_rotate_90_swaps_dimensions(self):
        image = codec.Image(3, 2)
        image.set(0, 0, (9, 0, 0, 255))
        rotated = ops.rotate(image, 90)
        self.assertEqual((rotated.width, rotated.height), (2, 3))

    def test_rotate_360_is_identity(self):
        image = checkerboard(5, 4)
        rotated = ops.rotate(image, 360)
        self.assertEqual(bytes(rotated.pixels), bytes(image.pixels))

    def test_rotate_four_quarters_returns_to_start(self):
        image = checkerboard(3, 3)
        result = image
        for _ in range(4):
            result = ops.rotate(result, 90)
        self.assertEqual((result.width, result.height), (3, 3))
        self.assertEqual(bytes(result.pixels), bytes(image.pixels))

    def test_rotate_90_moves_top_left_to_top_right(self):
        image = codec.Image(2, 3)
        image.set(0, 0, (255, 0, 0, 255))  # top-left
        rotated = ops.rotate(image, 90)  # clockwise: 2x3 -> 3x2
        self.assertEqual(rotated.width, 3)
        self.assertEqual(rotated.height, 2)
        # Clockwise rotation sends the top-left pixel to the top-right corner.
        self.assertEqual(rotated.get(rotated.width - 1, 0), (255, 0, 0, 255))

    def test_scale_nearest_doubles_pixels(self):
        image = codec.Image(2, 2)
        image.set(0, 0, (255, 0, 0, 255))
        scaled = ops.scale(image, 2)
        self.assertEqual((scaled.width, scaled.height), (4, 4))
        self.assertEqual(scaled.get(0, 0), (255, 0, 0, 255))
        self.assertEqual(scaled.get(1, 1), (255, 0, 0, 255))
        self.assertEqual(scaled.get(3, 3), (0, 0, 0, 0))

    def test_resize_nearest_exact_dimensions(self):
        image = checkerboard(10, 10)
        resized = ops.resize_nearest(image, 4, 4)
        self.assertEqual((resized.width, resized.height), (4, 4))

    def test_box_resize_averages(self):
        image = solid(4, 4, (100, 100, 100, 255))
        image.set(0, 0, (200, 100, 100, 255))
        resized = ops.box_resize(image, 2, 2)
        self.assertEqual((resized.width, resized.height), (2, 2))
        # The top-left cell averages one bright pixel with three medium ones.
        self.assertGreater(resized.get(0, 0)[0], 100)
        self.assertLess(resized.get(0, 0)[0], 200)
        self.assertEqual(resized.get(1, 1), (100, 100, 100, 255))

    def test_box_resize_handles_non_integer_ratio(self):
        image = checkerboard(1000, 3)
        resized = ops.box_resize(image, 512, 3)
        self.assertEqual((resized.width, resized.height), (512, 3))

    def test_pad_adds_transparent_border(self):
        image = solid(2, 2, (5, 5, 5, 255))
        padded = ops.pad(image, 1, 1, 1, 1)
        self.assertEqual((padded.width, padded.height), (4, 4))
        self.assertEqual(padded.get(0, 0), (0, 0, 0, 0))
        self.assertEqual(padded.get(1, 1), (5, 5, 5, 255))

    def test_pad_with_opaque_colour(self):
        image = solid(1, 1, (5, 5, 5, 255))
        padded = ops.pad(image, 1, 0, 0, 0, (255, 255, 255, 255))
        self.assertEqual(padded.get(0, 0), (255, 255, 255, 255))

    def test_trim_removes_uniform_border(self):
        image = codec.Image(5, 5)
        image.set(2, 2, (255, 0, 0, 255))
        trimmed = ops.trim(image)
        self.assertEqual((trimmed.width, trimmed.height), (1, 1))
        self.assertEqual(trimmed.get(0, 0), (255, 0, 0, 255))

    def test_trim_on_uniform_image_keeps_one_pixel(self):
        trimmed = ops.trim(solid(4, 4, (7, 7, 7, 255)))
        self.assertEqual((trimmed.width, trimmed.height), (1, 1))


class TestPixels(unittest.TestCase):
    def test_invert(self):
        image = solid(2, 2, (0, 128, 255, 255))
        inverted = ops.invert(image)
        self.assertEqual(inverted.get(0, 0)[:3], (255, 127, 0))

    def test_greyscale_weights_green_highest(self):
        image = codec.Image(2, 1)
        image.set(0, 0, (255, 0, 0, 255))
        image.set(1, 0, (0, 255, 0, 255))
        grey = ops.greyscale(image)
        self.assertGreater(grey.get(1, 0)[0], grey.get(0, 0)[0])

    def test_replace_colour_with_tolerance(self):
        image = solid(2, 2, (100, 100, 100, 255))
        image.set(1, 1, (105, 100, 100, 255))
        replaced = ops.replace_colour(image, (100, 100, 100, 255), (0, 0, 0, 255), tolerance=5)
        self.assertEqual(replaced.get(0, 0), (0, 0, 0, 255))
        self.assertEqual(replaced.get(1, 1), (0, 0, 0, 255))

    def test_outline_wraps_orthogonal_neighbours_only(self):
        image = codec.Image(3, 3)
        image.set(1, 1, (255, 0, 0, 255))
        outlined = ops.outline(image, (0, 0, 0, 255))
        for x, y in ((1, 0), (1, 2), (0, 1), (2, 1)):
            self.assertEqual(outlined.get(x, y), (0, 0, 0, 255), "orthogonal (%d,%d)" % (x, y))
        # Corners are diagonal neighbours, so the default leaves them alone.
        for x, y in ((0, 0), (2, 0), (0, 2), (2, 2)):
            self.assertEqual(outlined.get(x, y), (0, 0, 0, 0), "corner (%d,%d)" % (x, y))
        # The original pixel survives untouched.
        self.assertEqual(outlined.get(1, 1), (255, 0, 0, 255))

    def test_outline_with_diagonal_covers_corners(self):
        image = codec.Image(3, 3)
        image.set(1, 1, (255, 0, 0, 255))
        outlined = ops.outline(image, (0, 0, 0, 255), diagonal=True)
        for x, y in ((0, 0), (2, 0), (0, 2), (2, 2)):
            self.assertEqual(outlined.get(x, y), (0, 0, 0, 255), "corner (%d,%d)" % (x, y))
        self.assertEqual(outlined.get(1, 1), (255, 0, 0, 255))

    def test_composite_over_white(self):
        image = codec.Image(1, 1)
        image.set(0, 0, (0, 0, 0, 0))
        flat = ops.composite_over_white(image)
        self.assertEqual(flat.get(0, 0), (255, 255, 255, 255))

    def test_extract_alpha_and_apply_mask(self):
        image = solid(2, 2, (10, 20, 30, 200))
        alpha = ops.extract_alpha(image)
        self.assertEqual(alpha.get(0, 0), (200, 200, 200, 255))
        masked = ops.apply_mask(image, alpha)
        self.assertEqual(masked.get(0, 0)[3], 200 * 200 // 255)


class TestQuantize(unittest.TestCase):
    def test_median_cut_returns_requested_count(self):
        colours = [(i * 16, 255 - i * 16, i * 8) for i in range(16)]
        palette = quantize.median_cut(colours, [1] * 16, 8)
        self.assertLessEqual(len(palette), 8)
        self.assertTrue(all(len(c) == 3 for c in palette))

    def test_median_cut_never_exceeds_available_colours(self):
        palette = quantize.median_cut([(0, 0, 0), (255, 255, 255)], [1, 1], 16)
        self.assertEqual(len(palette), 2)

    def test_quantize_reduces_colour_count(self):
        image = codec.Image(16, 16)
        for y in range(16):
            for x in range(16):
                image.set(x, y, (x * 16, y * 16, 128, 255))
        palette, indices = quantize.quantize(image, 8)
        self.assertLessEqual(len(palette), 8)
        self.assertEqual(len(indices), 256)
        self.assertTrue(all(i < len(palette) for i in indices))

    def test_quantize_preserves_shape(self):
        image = checkerboard(12, 7)
        palette, indices = quantize.quantize(image, 4)
        self.assertEqual(len(indices), 12 * 7)

    def test_quantize_with_dither_returns_valid_indices(self):
        image = checkerboard(8, 8)
        palette, indices = quantize.quantize(image, 4, dither=True)
        self.assertEqual(len(indices), 64)
        self.assertTrue(all(i < len(palette) for i in indices))

    def test_snap_uses_the_given_palette_exactly(self):
        image = solid(4, 4, (250, 2, 2, 255))
        pico8 = quantize.builtin("pico8")
        entries, indices = quantize.snap(image, pico8)
        self.assertEqual(len(entries), 16)
        # Pure red must land on PICO-8's red, index 8.
        self.assertEqual(indices[0], 8)

    def test_snap_keeps_palette_entries_untouched(self):
        image = solid(2, 2, (1, 1, 1, 255))
        db16 = quantize.builtin("db16")
        entries, _indices = quantize.snap(image, db16)
        self.assertEqual([tuple(e[:3]) for e in entries], [tuple(c) for c in db16])

    def test_nearest_index_finds_exact_match(self):
        palette = [(0, 0, 0), (255, 0, 0), (0, 255, 0)]
        self.assertEqual(quantize.nearest_index((255, 0, 0), palette), 1)

    def test_perceptual_matching_runs(self):
        palette = quantize.builtin("db32")
        image = solid(4, 4, (200, 150, 100, 255))
        _entries, indices = quantize.snap(image, palette, perceptual=True)
        self.assertEqual(len(indices), 16)

    def test_quantize_ignores_faint_alpha_noise(self):
        """Faint alpha from JPEG resampling must not consume a palette slot.

        This is a real regression: a 256x160 PNG produced by GDI+ carried 828
        pixels with alpha between 222 and 244, which was pushing the reported
        palette size from 16 to 17 on a 16-colour request.
        """
        image = codec.Image(8, 8)
        for y in range(8):
            for x in range(8):
                image.set(x, y, (x * 30, y * 30, 128, 240))
        palette, indices = quantize.quantize(image, 4)
        self.assertEqual(len(palette), 4)
        self.assertTrue(all(len(entry) == 3 for entry in palette))
        self.assertTrue(all(i < len(palette) for i in indices))

    def test_quantize_reserves_slot_for_real_transparency(self):
        image = codec.Image(4, 4)
        for y in range(4):
            for x in range(4):
                image.set(x, y, (200, 100, 50, 0) if x == 0 else (200, 100, 50, 255))
        palette, indices = quantize.quantize(image, 4)
        self.assertEqual(palette[0][3], 0)
        self.assertEqual(indices[0], 0)

    def test_colour_budget_is_the_total_not_the_colour_count(self):
        """``--colors N`` must yield at most N entries, transparency included.

        Regression: a 16-colour request on an image with a transparent region
        used to return 17 entries, because the transparency slot was added on
        top of the colour budget rather than inside it.
        """
        image = codec.Image(16, 16)
        for y in range(16):
            for x in range(16):
                if x < 4 and y < 4:
                    image.set(x, y, (0, 0, 0, 0))
                else:
                    image.set(x, y, (x * 16, y * 16, 128, 255))
        for requested in (2, 4, 8, 16, 32):
            palette, indices = quantize.quantize(image, requested)
            self.assertLessEqual(
                len(palette), requested, "requested %d, got %d" % (requested, len(palette))
            )
            self.assertTrue(all(i < len(palette) for i in indices))
        # Transparency still gets its slot: 15 colours plus the transparent entry.
        palette, _indices = quantize.quantize(image, 16)
        self.assertEqual(len(palette), 16)
        self.assertEqual(palette[0][3], 0)

    def test_single_colour_request_does_not_reserve_transparency(self):
        """With a budget of one there is nothing to share, so it stays a colour."""
        image = codec.Image(4, 4)
        for y in range(4):
            for x in range(4):
                image.set(x, y, (200, 100, 50, 0) if x == 0 else (200, 100, 50, 255))
        palette, indices = quantize.quantize(image, 1)
        self.assertEqual(len(palette), 1)
        self.assertEqual(len(palette[0]), 3)
        self.assertEqual(len(indices), 16)

    def test_quantize_alpha_threshold_is_configurable(self):
        image = solid(4, 4, (10, 20, 30, 200))
        # At the default threshold, alpha 200 is opaque, so entries stay 3-tuples
        # and no transparent slot is reserved.
        palette_strict, _ = quantize.quantize(image, 4)
        self.assertEqual(len(palette_strict[0]), 3)
        # Raise the threshold past 200 and the same image becomes transparent.
        palette_loose, _ = quantize.quantize(image, 4, alpha_threshold=220)
        self.assertEqual(len(palette_loose[0]), 4)
        self.assertEqual(palette_loose[0][3], 0)

    def test_dither_leaves_transparent_pixels_alone(self):
        image = codec.Image(4, 4)
        for y in range(4):
            for x in range(4):
                alpha = 0 if (x + y) % 2 == 0 else 255
                image.set(x, y, (100, 150, 200, alpha))
        palette, indices = quantize.quantize(image, 4, dither=True)
        self.assertEqual(palette[0][3], 0)
        self.assertEqual(indices[0], 0)
        # Error diffusion must not bleed into the transparent checkerboard.
        self.assertEqual(indices[2], 0)

    def test_unknown_palette_raises(self):
        with self.assertRaises(codec.PNGError):
            quantize.builtin("does-not-exist")


class TestPaletteIO(unittest.TestCase):
    def test_gpl_round_trip(self):
        palette = [(0, 0, 0), (255, 255, 255), (18, 52, 86)]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.gpl")
            quantize.write_palette(path, palette)
            loaded = quantize.read_palette(path)
        self.assertEqual(loaded, palette)

    def test_jasc_pal_round_trip(self):
        palette = [(1, 2, 3), (4, 5, 6)]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.pal")
            quantize.write_palette(path, palette)
            loaded = quantize.read_palette(path)
        self.assertEqual(loaded, palette)

    def test_hex_round_trip(self):
        palette = [(0, 0, 0), (16, 32, 48)]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.hex")
            quantize.write_palette(path, palette)
            loaded = quantize.read_palette(path)
        self.assertEqual(loaded, palette)

    def test_act_round_trip(self):
        palette = [(10, 20, 30), (40, 50, 60)]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.act")
            quantize.write_palette(path, palette)
            loaded = quantize.read_palette(path)
        self.assertEqual(loaded[:2], palette)

    def test_gpl_ignores_comments_and_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.gpl")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("GIMP Palette\nName: test\nColumns: 4\n#\n")
                fh.write("# a comment\n255   0   0\t#FF0000\n")
            loaded = quantize.read_palette(path)
        self.assertEqual(loaded, [(255, 0, 0)])

    def test_bundled_palettes_are_well_formed(self):
        for name in ("db16", "db32", "pico8", "gameboy", "nes", "cga"):
            palette = quantize.builtin(name)
            self.assertTrue(palette, name)
            for entry in palette:
                self.assertEqual(len(entry), 3)
                self.assertTrue(all(0 <= v <= 255 for v in entry))


class TestFormats(unittest.TestCase):
    def test_bmp_round_trip(self):
        original = checkerboard(6, 4)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.bmp")
            formats.write_bmp(path, original)
            loaded = formats.read_bmp(path)
        self.assertEqual((loaded.width, loaded.height), (6, 4))
        self.assertEqual(bytes(loaded.pixels), bytes(original.pixels))

    def test_ppm_binary_round_trip(self):
        original = checkerboard(5, 5)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.ppm")
            formats.write_ppm(path, original)
            loaded = formats.read_ppm(path)
        self.assertEqual((loaded.width, loaded.height), (5, 5))
        # PPM has no alpha, so compare RGB only.
        for i in range(0, len(original.pixels), 4):
            self.assertEqual(loaded.pixels[i : i + 3], original.pixels[i : i + 3])

    def test_ppm_ascii_round_trip(self):
        original = checkerboard(3, 3)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.ppm")
            formats.write_ppm(path, original, binary=False)
            loaded = formats.read_ppm(path)
        self.assertEqual((loaded.width, loaded.height), (3, 3))

    def test_pgm_writes_greyscale(self):
        original = solid(3, 3, (100, 100, 100, 255))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.pgm")
            formats.write_pgm(path, original)
            loaded = formats.read_ppm(path)
        self.assertEqual(loaded.get(1, 1), (100, 100, 100, 255))

    def test_load_dispatches_on_extension(self):
        original = checkerboard(4, 4)
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("x.png", "x.bmp", "x.ppm"):
                path = os.path.join(tmp, name)
                formats.save(path, original)
                loaded = formats.load(path)
                self.assertEqual((loaded.width, loaded.height), (4, 4), name)

    def test_jpeg_is_refused_with_a_helpful_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.jpg")
            with open(path, "wb") as fh:
                fh.write(b"\xff\xd8\xff\xe0")
            with self.assertRaises(codec.PNGError) as ctx:
                formats.load(path)
        self.assertIn("JPEG", str(ctx.exception))

    def test_unsupported_extension_raises(self):
        with self.assertRaises(codec.PNGError):
            formats.load("mystery.tiff")


class TestAscii(unittest.TestCase):
    def test_render_produces_requested_width(self):
        image = checkerboard(40, 20)
        text = ascii_mod.render(image, columns=20)
        lines = text.split("\n")
        self.assertTrue(lines)
        self.assertEqual(len(lines[0]), 20)

    def test_render_marks_dark_and_light_differently(self):
        dark = ascii_mod.render(solid(4, 4, (0, 0, 0, 255)), columns=4)
        light = ascii_mod.render(solid(4, 4, (255, 255, 255, 255)), columns=4)
        self.assertNotEqual(dark[0], light[0])

    def test_describe_reports_size_and_colours(self):
        text = ascii_mod.describe(checkerboard(4, 4))
        self.assertIn("4x4", text)
        self.assertIn("2 colours", text)

    def test_describe_reports_transparency(self):
        image = codec.Image(2, 2)
        text = ascii_mod.describe(image)
        self.assertIn("100.0% transparent", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
