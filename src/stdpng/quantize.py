"""Palette quantisation and interchange.

Two directions matter for pixel art:

* **Reduce** an arbitrary image to N colours, which median cut does well.
* **Snap** an image onto a palette you already own (PICO-8, DB16, a project
  sheet), which needs nearest-neighbour lookup instead.

Palettes are read from and written to the formats artists actually pass around:
GIMP ``.gpl``, JASC ``.pal``, plain ``.hex``, and Adobe ``.act``.
"""

from .codec import Image, PNGError

# ----------------------------------------------------------------------
# distance
# ----------------------------------------------------------------------


def _rgb_to_lab(r, g, b):
    """sRGB to CIE L*a*b* (D65).  Used when perceptual matching is requested."""
    def to_linear(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    rl, gl, bl = to_linear(r), to_linear(g), to_linear(b)

    # Linear RGB -> XYZ, D65.
    x = (rl * 0.4124 + gl * 0.3576 + bl * 0.1805) / 0.95047
    y = rl * 0.2126 + gl * 0.7152 + bl * 0.0722
    z = (rl * 0.0193 + gl * 0.1192 + bl * 0.9505) / 1.08883

    def f(t):
        return t ** (1.0 / 3.0) if t > 0.008856 else (7.787 * t + 16.0 / 116.0)

    fx, fy, fz = f(x), f(y), f(z)
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


def _prepare(palette, perceptual):
    if perceptual:
        return [_rgb_to_lab(c[0], c[1], c[2]) for c in palette], True
    return [(c[0], c[1], c[2]) for c in palette], False


def nearest_index(colour, palette, perceptual=False):
    """Index of the closest palette entry to ``colour``.

    Euclidean distance in RGB is fast and, for artist-authored palettes that
    were chosen to be far apart, entirely adequate.  ``perceptual=True``
    switches to L*a*b*, which matters when a photo is being forced onto a small
    palette and eye-pleasing results beat raw proximity.
    """
    prepared, is_lab = _prepare(palette, perceptual)
    return nearest_index_prepared(colour, prepared, is_lab)


def nearest_index_prepared(colour, prepared, is_lab):
    r, g, b = colour[0], colour[1], colour[2]
    if is_lab:
        r, g, b = _rgb_to_lab(r, g, b)
    best, best_distance = 0, 1 << 30
    for i, (pr, pg, pb) in enumerate(prepared):
        dr = r - pr
        dg = g - pg
        db = b - pb
        d = dr * dr + dg * dg + db * db
        if d < best_distance:
            best_distance = d
            best = i
            if d == 0:
                break
    return best


# ----------------------------------------------------------------------
# median cut
# ----------------------------------------------------------------------


def _histogram(image):
    counts = {}
    src = image.pixels
    for i in range(0, len(src), 4):
        if src[i + 3] == 0:
            continue  # fully transparent pixels must not pull the palette
        key = (src[i], src[i + 1], src[i + 2])
        counts[key] = counts.get(key, 0) + 1
    return counts


def _bounds(entries):
    lo = [255, 255, 255]
    hi = [0, 0, 0]
    for colour, _weight in entries:
        for c in range(3):
            v = colour[c]
            if v < lo[c]:
                lo[c] = v
            if v > hi[c]:
                hi[c] = v
    return lo, hi


def median_cut(colours, weights, ncolours, perceptual=False):
    """Split the colour cloud until ``ncolours`` boxes remain.

    ``perceptual=True`` splits along the widest L*a*b* axis, which stops the
    algorithm from spending its budget on luminance and starving chroma - the
    failure mode that makes naive median cut look washed out on gradients.
    """
    if ncolours < 1:
        raise PNGError("colour count must be at least 1")
    if not colours:
        return [(0, 0, 0)]

    work = list(zip(colours, weights))
    if perceptual:
        work = [(_rgb_to_lab(c[0], c[1], c[2]), w) for c, w in work]

    boxes = [work]
    bounds = [_bounds(work)]

    while len(boxes) < ncolours:
        best_index, best_range, best_channel = -1, 0, 0
        for i, (lo, hi) in enumerate(bounds):
            if len(boxes[i]) < 2:
                continue
            for c in range(3):
                span = hi[c] - lo[c]
                if span > best_range:
                    best_range, best_index, best_channel = span, i, c
        if best_index < 0 or best_range == 0:
            break

        box = boxes.pop(best_index)
        bounds.pop(best_index)
        box.sort(key=lambda item: item[0][best_channel])

        total = sum(w for _c, w in box)
        running, split = 0, 1
        for i, (_c, w) in enumerate(box):
            running += w
            if running * 2 >= total:
                split = max(1, i + 1)
                break

        left = box[:split]
        right = box[split:]
        if not right:
            break
        boxes.append(left)
        boxes.append(right)
        bounds.append(_bounds(left))
        bounds.append(_bounds(right))

    palette = []
    for box in boxes:
        total = sum(w for _c, w in box)
        if total == 0:
            palette.append((0, 0, 0))
            continue
        if perceptual:
            # Average in Lab, then convert back so the entry is a real sRGB triple.
            l = sum(c[0] * w for c, w in box) / total
            a = sum(c[1] * w for c, w in box) / total
            b = sum(c[2] * w for c, w in box) / total
            palette.append(_lab_to_rgb(l, a, b))
        else:
            palette.append(
                tuple(int(sum(c[i] * w for c, w in box) / total) for i in range(3))
            )
    return _dedupe(palette)


def _lab_to_rgb(l, a, b):
    fy = (l + 16.0) / 116.0
    fx = fy + a / 500.0
    fz = fy - b / 200.0

    def finv(t):
        return t ** 3 if t ** 3 > 0.008856 else (t - 16.0 / 116.0) / 7.787

    x = finv(fx) * 0.95047
    y = finv(fy)
    z = finv(fz) * 1.08883

    rl = x * 3.2406 + y * -1.5372 + z * -0.4986
    gl = x * -0.9689 + y * 1.8758 + z * 0.0415
    bl = x * 0.0557 + y * -0.2040 + z * 1.0570

    def gamma(v):
        v = max(0.0, min(1.0, v))
        return v * 12.92 if v <= 0.0031308 else 1.055 * (v ** (1 / 2.4)) - 0.055

    return tuple(int(round(gamma(v) * 255)) for v in (rl, gl, bl))


def _dedupe(palette):
    seen = set()
    out = []
    for entry in palette:
        key = (entry[0], entry[1], entry[2])
        if key not in seen:
            seen.add(key)
            out.append(entry)
    return out


# ----------------------------------------------------------------------
# quantise / snap
# ----------------------------------------------------------------------


def quantize(image, ncolours, perceptual=False, dither=False, alpha_threshold=128):
    """Reduce ``image`` to at most ``ncolours`` palette entries.

    Returns ``(palette, indices)`` where ``indices`` is one byte per pixel.

    **``ncolours`` is the total budget, transparency included.**  When the image
    contains genuinely transparent pixels and ``ncolours >= 2``, one entry is
    reserved for transparency and the colour budget becomes ``ncolours - 1``.
    So ``--colors 16`` always yields at most 16 entries, whether or not the
    image has an alpha channel - which is what "reduce to 16 colours" should
    mean.

    ``alpha_threshold`` decides what counts as transparent.  It matters more
    than it looks: PNGs that came from a JPEG routinely carry a few thousand
    pixels with alpha in the 220-250 range, left behind by resampling.  Treating
    those as transparency spends a palette entry on nothing, so the default only
    reserves a slot for pixels that are genuinely see-through.
    """
    if ncolours < 1:
        raise PNGError("colour count must be at least 1")

    histogram = _histogram(image)
    if not histogram:
        return [(0, 0, 0, 0)], bytearray(image.width * image.height)

    # A single-colour request cannot share its budget with transparency, so the
    # reserved slot only applies from two entries upwards.
    reserve_transparency = ncolours >= 2 and any(
        image.pixels[i] < alpha_threshold for i in range(3, len(image.pixels), 4)
    )
    colour_budget = ncolours - 1 if reserve_transparency else ncolours

    palette = median_cut(
        list(histogram.keys()), list(histogram.values()), colour_budget, perceptual=perceptual
    )

    if reserve_transparency:
        palette = [(r, g, b, 255) for (r, g, b) in palette]
        palette = [(0, 0, 0, 0)] + palette

    if dither:
        return palette, _dither(image, palette, perceptual, alpha_threshold)
    return palette, _map_direct(image, palette, perceptual, alpha_threshold)


def snap(image, palette, perceptual=False, dither=False, alpha_threshold=128):
    """Force ``image`` onto an existing ``palette``.

    This is the "keep my sprite on the DB16 sheet" operation.  Palette entries
    are returned untouched so the output is guaranteed to use exactly your
    colours.  A transparent slot is honoured only if the palette you supplied
    actually has one (entry 0 with alpha 0).
    """
    entries = [(c[0], c[1], c[2], c[3] if len(c) > 3 else 255) for c in palette]
    if dither:
        return entries, _dither(image, entries, perceptual, alpha_threshold)
    return entries, _map_direct(image, entries, perceptual, alpha_threshold)


def _map_direct(image, palette, perceptual, alpha_threshold=128):
    prepared, is_lab = _prepare(palette, perceptual)
    cache = {}
    indices = bytearray(image.width * image.height)
    src = image.pixels
    transparent_slot = len(palette[0]) == 4 and palette[0][3] == 0
    for pixel in range(image.width * image.height):
        o = pixel * 4
        if transparent_slot and src[o + 3] < alpha_threshold:
            indices[pixel] = 0
            continue
        key = (src[o], src[o + 1], src[o + 2])
        found = cache.get(key)
        if found is None:
            found = nearest_index_prepared(key, prepared, is_lab)
            cache[key] = found
        indices[pixel] = found
    return indices


def _dither(image, palette, perceptual, alpha_threshold=128):
    """Floyd-Steinberg error diffusion on a float working buffer."""
    prepared, is_lab = _prepare(palette, perceptual)
    w, h = image.width, image.height
    src = image.pixels
    transparent_slot = len(palette[0]) == 4 and palette[0][3] == 0

    # Work on a copy so the caller's image is never mutated.
    buffer = [float(src[i]) for i in range(w * h * 3)]
    indices = bytearray(w * h)

    for y in range(h):
        for x in range(w):
            i = (y * w + x) * 3
            pixel = y * w + x

            # Transparent pixels are not part of the gradient, so they neither
            # receive nor emit diffused error.
            if transparent_slot and src[pixel * 4 + 3] < alpha_threshold:
                indices[pixel] = 0
                continue

            r = max(0.0, min(255.0, buffer[i]))
            g = max(0.0, min(255.0, buffer[i + 1]))
            b = max(0.0, min(255.0, buffer[i + 2]))

            index = nearest_index_prepared((r, g, b), prepared, is_lab)
            indices[pixel] = index
            entry = palette[index]
            er = r - entry[0]
            eg = g - entry[1]
            eb = b - entry[2]

            # Distribute 7/16, 3/16, 5/16, 1/16 to the four neighbours.
            for dx, dy, weight in ((1, 0, 7 / 16), (-1, 1, 3 / 16), (0, 1, 5 / 16), (1, 1, 1 / 16)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h:
                    j = (ny * w + nx) * 3
                    buffer[j] += er * weight
                    buffer[j + 1] += eg * weight
                    buffer[j + 2] += eb * weight
    return indices


# ----------------------------------------------------------------------
# palette interchange
# ----------------------------------------------------------------------


def read_palette(path):
    """Load a palette from ``.gpl``, ``.pal``, ``.hex`` or ``.act``."""
    lower = path.lower()
    if lower.endswith(".gpl"):
        return _read_gpl(path)
    if lower.endswith(".pal"):
        return _read_jasc_pal(path)
    if lower.endswith(".act"):
        return _read_act(path)
    if lower.endswith((".hex", ".txt")):
        return _read_hex(path)
    raise PNGError("unrecognised palette extension: %s" % path)


def write_palette(path, palette, name="stdpng palette"):
    """Save a palette, choosing the format from the file extension."""
    lower = path.lower()
    if lower.endswith(".gpl"):
        return _write_gpl(path, palette, name)
    if lower.endswith(".pal"):
        return _write_jasc_pal(path, palette)
    if lower.endswith(".act"):
        return _write_act(path, palette)
    if lower.endswith((".hex", ".txt")):
        return _write_hex(path, palette)
    raise PNGError("unrecognised palette extension: %s" % path)


def _read_gpl(path):
    palette = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith(("gimp palette", "name:", "columns:")):
                continue
            parts = line.split()
            if len(parts) >= 3:
                try:
                    palette.append((int(parts[0]), int(parts[1]), int(parts[2])))
                except ValueError:
                    continue
    if not palette:
        raise PNGError("no colours found in %s" % path)
    return palette


def _write_gpl(path, palette, name):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("GIMP Palette\n")
        fh.write("Name: %s\n" % name)
        fh.write("Columns: 16\n")
        fh.write("#\n")
        for entry in palette:
            r, g, b = entry[0], entry[1], entry[2]
            fh.write("%3d %3d %3d\t#%02X%02X%02X\n" % (r, g, b, r, g, b))


def _read_jasc_pal(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = [line.strip() for line in fh if line.strip()]
    if not lines or not lines[0].upper().startswith("JASC"):
        raise PNGError("not a JASC-PAL file: %s" % path)
    palette = []
    for line in lines[3:]:
        parts = line.split()
        if len(parts) >= 3:
            try:
                palette.append((int(parts[0]), int(parts[1]), int(parts[2])))
            except ValueError:
                continue
    if not palette:
        raise PNGError("no colours found in %s" % path)
    return palette


def _write_jasc_pal(path, palette):
    with open(path, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write("JASC-PAL\n0100\n%d\n" % len(palette))
        for entry in palette:
            fh.write("%d %d %d\n" % (entry[0], entry[1], entry[2]))


def _read_hex(path):
    palette = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip().lstrip("#")
            if len(line) >= 6:
                try:
                    palette.append((int(line[0:2], 16), int(line[2:4], 16), int(line[4:6], 16)))
                except ValueError:
                    continue
    if not palette:
        raise PNGError("no colours found in %s" % path)
    return palette


def _write_hex(path, palette):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for entry in palette:
            fh.write("#%02X%02X%02X\n" % (entry[0], entry[1], entry[2]))


def _read_act(path):
    with open(path, "rb") as fh:
        data = fh.read()
    if len(data) not in (768, 772):
        raise PNGError("ACT file must be 768 or 772 bytes, got %d" % len(data))
    count = 256
    if len(data) == 772:
        count = (data[768] << 8) | data[769]
    palette = []
    for i in range(count):
        o = i * 3
        palette.append((data[o], data[o + 1], data[o + 2]))
    return palette


def _write_act(path, palette):
    if len(palette) > 256:
        raise PNGError("ACT supports at most 256 colours")
    data = bytearray(768)
    for i, entry in enumerate(palette):
        o = i * 3
        data[o] = entry[0]
        data[o + 1] = entry[1]
        data[o + 2] = entry[2]
    with open(path, "wb") as fh:
        fh.write(bytes(data))


# ----------------------------------------------------------------------
# built-in palettes
# ----------------------------------------------------------------------

PALETTES = {
    "db16": [
        (20, 12, 28), (68, 36, 52), (48, 52, 109), (78, 74, 78),
        (133, 76, 48), (52, 101, 36), (208, 70, 72), (117, 113, 97),
        (89, 125, 206), (210, 125, 44), (133, 149, 161), (109, 170, 44),
        (210, 170, 153), (109, 194, 202), (218, 212, 94), (222, 238, 214),
    ],
    "db32": [
        (0, 0, 0), (34, 32, 52), (69, 40, 60), (102, 57, 49),
        (143, 86, 59), (223, 113, 38), (217, 160, 102), (238, 195, 154),
        (251, 242, 54), (153, 229, 80), (106, 190, 48), (55, 148, 110),
        (75, 105, 47), (82, 75, 36), (50, 60, 57), (63, 38, 49),
        (48, 52, 109), (60, 66, 137), (44, 44, 66), (70, 130, 180),
        (38, 126, 168), (97, 155, 163), (74, 105, 116), (42, 61, 79),
        (65, 50, 72), (97, 75, 86), (124, 79, 106), (173, 103, 115),
        (214, 137, 128), (223, 170, 148), (248, 216, 178), (255, 255, 255),
    ],
    "pico8": [
        (0, 0, 0), (29, 43, 83), (126, 37, 83), (0, 135, 81),
        (171, 82, 54), (95, 87, 79), (194, 195, 199), (255, 241, 232),
        (255, 0, 77), (255, 163, 0), (255, 236, 39), (0, 228, 54),
        (41, 173, 255), (131, 118, 156), (255, 119, 168), (255, 204, 170),
    ],
    "gameboy": [
        (15, 56, 15), (48, 98, 48), (139, 172, 15), (155, 188, 15),
    ],
    "nes": [
        (124, 124, 124), (0, 0, 252), (0, 0, 188), (68, 40, 188),
        (148, 0, 132), (168, 0, 32), (168, 16, 0), (136, 20, 0),
        (80, 48, 0), (0, 120, 0), (0, 104, 0), (0, 88, 0),
        (0, 64, 88), (0, 0, 0), (188, 188, 188), (0, 120, 248),
        (0, 88, 248), (104, 68, 252), (216, 0, 204), (228, 0, 88),
        (248, 56, 0), (228, 92, 16), (172, 124, 0), (0, 184, 0),
        (0, 168, 0), (0, 168, 68), (0, 136, 136), (248, 248, 248),
        (60, 188, 252), (104, 136, 252), (152, 120, 248), (248, 120, 248),
        (248, 88, 152), (248, 120, 88), (252, 160, 68), (248, 184, 0),
    ],
    "cga": [
        (0, 0, 0), (0, 0, 170), (0, 170, 0), (0, 170, 170),
        (170, 0, 0), (170, 0, 170), (170, 85, 0), (170, 170, 170),
        (85, 85, 85), (85, 85, 255), (85, 255, 85), (85, 255, 255),
        (255, 85, 85), (255, 85, 255), (255, 255, 85), (255, 255, 255),
    ],
}


def builtin(name):
    """Return a bundled palette by name (see :data:`PALETTES`)."""
    key = name.lower()
    if key not in PALETTES:
        raise PNGError(
            "unknown palette %r; available: %s" % (name, ", ".join(sorted(PALETTES)))
        )
    return list(PALETTES[key])
