"""Geometric and per-pixel operations on :class:`~stdpng.codec.Image`.

Everything here is pure Python and allocation-conscious: operations that can be
expressed as a straight buffer walk are, and nothing creates an intermediate
``Image`` unless the operation genuinely needs one.
"""

from .codec import Image, PNGError

# ----------------------------------------------------------------------
# geometry
# ----------------------------------------------------------------------


def crop(image, x, y, width, height):
    """Return the rectangle ``(x, y, width, height)`` clipped to the source."""
    if width <= 0 or height <= 0:
        raise PNGError("crop width and height must be positive")

    x0 = max(0, min(x, image.width))
    y0 = max(0, min(y, image.height))
    x1 = max(x0, min(x + width, image.width))
    y1 = max(y0, min(y + height, image.height))
    if x1 <= x0 or y1 <= y0:
        raise PNGError("crop rectangle lies entirely outside the image")

    w = x1 - x0
    h = y1 - y0
    out = bytearray(w * h * 4)
    src = image.pixels
    src_stride = image.width * 4
    for row in range(h):
        s = (y0 + row) * src_stride + x0 * 4
        out[row * w * 4 : (row + 1) * w * 4] = src[s : s + w * 4]
    return Image(w, h, out)


def flip_horizontal(image):
    out = bytearray(len(image.pixels))
    src = image.pixels
    w4 = image.width * 4
    for y in range(image.height):
        base = y * w4
        for x in range(image.width):
            s = base + x * 4
            d = base + (image.width - 1 - x) * 4
            out[d : d + 4] = src[s : s + 4]
    return Image(image.width, image.height, out)


def flip_vertical(image):
    out = bytearray(len(image.pixels))
    w4 = image.width * 4
    for y in range(image.height):
        out[y * w4 : (y + 1) * w4] = image.pixels[(image.height - 1 - y) * w4 : (image.height - y) * w4]
    return Image(image.width, image.height, out)


def rotate(image, degrees):
    """Rotate by a multiple of 90 degrees, clockwise for positive values."""
    degrees %= 360
    if degrees == 0:
        return image.copy()
    if degrees == 180:
        out = bytearray(len(image.pixels))
        src = image.pixels
        n = image.width * image.height
        for i in range(n):
            s = i * 4
            d = (n - 1 - i) * 4
            out[d : d + 4] = src[s : s + 4]
        return Image(image.width, image.height, out)

    # 90 and 270 swap the dimensions.  With w and h the source width/height,
    # the destination has size (h, w) and index dst(X, Y) = Y * h + X.
    w, h = image.width, image.height
    out = bytearray(w * h * 4)
    src = image.pixels
    if degrees == 90:  # clockwise: dst(X, Y) = src(Y, H - 1 - X)
        for y in range(h):
            for x in range(w):
                sx = x
                sy = h - 1 - y
                s = (sy * w + sx) * 4
                d = (x * h + y) * 4
                out[d : d + 4] = src[s : s + 4]
        return Image(h, w, out)
    if degrees == 270:  # counter-clockwise: dst(X, Y) = src(W - 1 - Y, X)
        for y in range(h):
            for x in range(w):
                sx = w - 1 - x
                sy = y
                s = (sy * w + sx) * 4
                d = (x * h + y) * 4
                out[d : d + 4] = src[s : s + 4]
        return Image(h, w, out)
    raise PNGError("rotation must be a multiple of 90 degrees")


def scale(image, factor):
    """Nearest-neighbour scale by ``factor``.

    Nearest neighbour is the point: this library exists for pixel art and UI
    assets, where any interpolation destroys the look.  ``factor`` may be
    fractional, but whole numbers are what you want.
    """
    if factor <= 0:
        raise PNGError("scale factor must be positive")
    if factor == 1:
        return image.copy()

    nw = max(1, int(image.width * factor))
    nh = max(1, int(image.height * factor))
    out = bytearray(nw * nh * 4)
    src = image.pixels
    sw = image.width
    sh = image.height

    # Precompute column mappings once instead of dividing per pixel.
    xmap = [min(sw - 1, int(x / factor)) * 4 for x in range(nw)]
    for y in range(nh):
        sy = min(sh - 1, int(y / factor))
        srow = sy * sw * 4
        drow = y * nw * 4
        for x in range(nw):
            s = srow + xmap[x]
            d = drow + x * 4
            out[d : d + 4] = src[s : s + 4]
    return Image(nw, nh, out)


def resize_nearest(image, width, height):
    """Nearest-neighbour resize to an exact size (aspect ratio not preserved)."""
    if width <= 0 or height <= 0:
        raise PNGError("target dimensions must be positive")
    out = bytearray(width * height * 4)
    src = image.pixels
    sw = image.width
    sh = image.height
    xmap = [(min(sw - 1, x * sw // width)) * 4 for x in range(width)]
    for y in range(height):
        sy = min(sh - 1, y * sh // height)
        srow = sy * sw * 4
        drow = y * width * 4
        for x in range(width):
            s = srow + xmap[x]
            d = drow + x * 4
            out[d : d + 4] = src[s : s + 4]
    return Image(width, height, out)


def box_resize(image, width, height):
    """Area-average resize to an exact size, for photos and smooth sources.

    The source is partitioned into ``width`` x ``height`` cells whose sizes need
    not divide evenly, so this accepts arbitrary ratios (1000 -> 512 works).
    """
    if width <= 0 or height <= 0:
        raise PNGError("target dimensions must be positive")
    out = bytearray(width * height * 4)
    src = image.pixels
    sw = image.width
    sh = image.height
    for y in range(height):
        y0 = y * sh // height
        y1 = max(y0 + 1, (y + 1) * sh // height)
        for x in range(width):
            x0 = x * sw // width
            x1 = max(x0 + 1, (x + 1) * sw // width)
            count = (x1 - x0) * (y1 - y0)
            r = g = b = a = 0
            for sy in range(y0, y1):
                row = sy * sw * 4
                for sx in range(x0, x1):
                    o = row + sx * 4
                    r += src[o]
                    g += src[o + 1]
                    b += src[o + 2]
                    a += src[o + 3]
            d = (y * width + x) * 4
            out[d] = r // count
            out[d + 1] = g // count
            out[d + 2] = b // count
            out[d + 3] = a // count
    return Image(width, height, out)


def pad(image, left, top, right, bottom, colour=(0, 0, 0, 0)):
    """Place the image on a larger canvas filled with ``colour``."""
    if min(left, top, right, bottom) < 0:
        raise PNGError("padding values must not be negative")
    nw = image.width + left + right
    nh = image.height + top + bottom
    out = bytearray(nw * nh * 4)
    fill = bytes(colour)
    if fill != b"\x00\x00\x00\x00":
        for i in range(0, len(out), 4):
            out[i : i + 4] = fill
    src = image.pixels
    for y in range(image.height):
        s = y * image.width * 4
        d = ((y + top) * nw + left) * 4
        out[d : d + image.width * 4] = src[s : s + image.width * 4]
    return Image(nw, nh, out)


def composite_over_white(image):
    """Flatten transparency onto a white background, returning opaque RGB."""
    out = bytearray(len(image.pixels))
    src = image.pixels
    for i in range(0, len(src), 4):
        a = src[i + 3]
        if a == 255:
            out[i : i + 4] = src[i : i + 4]
        else:
            inv = 255 - a
            out[i] = (src[i] * a + 255 * inv) // 255
            out[i + 1] = (src[i + 1] * a + 255 * inv) // 255
            out[i + 2] = (src[i + 2] * a + 255 * inv) // 255
            out[i + 3] = 255
    return Image(image.width, image.height, out)


def trim(image, tolerance=0):
    """Drop uniform borders, keeping a transparent or single-colour margin out.

    The reference colour is taken from pixel ``(0, 0)``.  Useful for sprite
    sheets where the generator added a wide empty frame.
    """
    w, h = image.width, image.height
    ref = image.get(0, 0)

    def matches(x, y):
        c = image.get(x, y)
        return all(abs(c[i] - ref[i]) <= tolerance for i in range(4))

    left, right, top, bottom = 0, w - 1, 0, h - 1
    while left < right and all(matches(left, y) for y in range(top, bottom + 1)):
        left += 1
    while right > left and all(matches(right, y) for y in range(top, bottom + 1)):
        right -= 1
    while top < bottom and all(matches(x, top) for x in range(left, right + 1)):
        top += 1
    while bottom > top and all(matches(x, bottom) for x in range(left, right + 1)):
        bottom -= 1
    return crop(image, left, top, right - left + 1, bottom - top + 1)


# ----------------------------------------------------------------------
# pixels
# ----------------------------------------------------------------------


def invert(image):
    out = bytearray(image.pixels)
    for i in range(0, len(out), 4):
        out[i] = 255 - out[i]
        out[i + 1] = 255 - out[i + 1]
        out[i + 2] = 255 - out[i + 2]
    return Image(image.width, image.height, out)


def greyscale(image):
    out = bytearray(image.pixels)
    src = image.pixels
    for i in range(0, len(src), 4):
        v = (src[i] * 299 + src[i + 1] * 587 + src[i + 2] * 114) // 1000
        out[i] = out[i + 1] = out[i + 2] = v
    return Image(image.width, image.height, out)


def tint(image, colour, strength=0.5):
    """Blend every pixel toward ``colour`` (3- or 4-tuple) by ``strength``."""
    if not 0.0 <= strength <= 1.0:
        raise PNGError("strength must be between 0 and 1")
    t = bytes(colour)
    out = bytearray(image.pixels)
    src = image.pixels
    keep = 1.0 - strength
    for i in range(0, len(src), 4):
        for c in range(3):
            out[i + c] = int(src[i + c] * keep + t[c] * strength)
    return Image(image.width, image.height, out)


def outline(image, colour=(0, 0, 0, 255), diagonal=False):
    """Add a 1px outline around every opaque region.

    Offsets are the four orthogonal neighbours, plus the diagonals when
    ``diagonal`` is true.  The original pixels are never overwritten, so the
    outline stays behind the sprite rather than eating into it.
    """
    w, h = image.width, image.height
    out = bytearray(image.pixels)
    fill = bytes(colour)
    offsets = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    if diagonal:
        offsets += [(-1, -1), (1, -1), (-1, 1), (1, 1)]

    src = image.pixels
    for y in range(h):
        for x in range(w):
            i = (y * w + x) * 4
            if src[i + 3] != 0:
                continue
            for dx, dy in offsets:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h:
                    n = (ny * w + nx) * 4
                    if src[n + 3] != 0:
                        out[i : i + 4] = fill
                        break
    return Image(w, h, out)


def replace_colour(image, source, target, tolerance=0):
    """Swap every pixel close to ``source`` for ``target``."""
    s = bytes(source)
    t = bytes(target)
    out = bytearray(image.pixels)
    src = image.pixels
    for i in range(0, len(src), 4):
        if all(abs(src[i + c] - s[c]) <= tolerance for c in range(4)):
            out[i : i + 4] = t
    return Image(image.width, image.height, out)


def extract_alpha(image):
    """Return a greyscale image of the alpha channel, for use as a mask."""
    out = bytearray(len(image.pixels))
    src = image.pixels
    for i in range(0, len(src), 4):
        a = src[i + 3]
        out[i] = out[i + 1] = out[i + 2] = a
        out[i + 3] = 255
    return Image(image.width, image.height, out)


def apply_mask(image, mask):
    """Multiply ``image``'s alpha by the luminance of ``mask``."""
    if mask.width != image.width or mask.height != image.height:
        raise PNGError("mask dimensions must match the image")
    out = bytearray(image.pixels)
    src = image.pixels
    m = mask.pixels
    for i in range(0, len(src), 4):
        out[i + 3] = src[i + 3] * m[i] // 255
    return Image(image.width, image.height, out)
