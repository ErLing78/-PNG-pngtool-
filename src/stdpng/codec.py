"""PNG decode / encode using only the Python standard library.

This module is the foundation of stdpng.  It reads 8-bit non-interlaced PNGs
(colour types 0, 2, 3, 4 and 6, including ``tRNS`` transparency) into a flat
RGBA byte buffer and writes PNGs back out, either as truecolour+alpha or as
8-bit indexed with a custom palette.

Pixels are always stored internally as ``bytearray(width * height * 4)`` in
R, G, B, A order.  A flat buffer keeps memory low and makes pixel loops roughly
an order of magnitude faster than a list-of-lists-of-tuples.
"""

import struct
import zlib

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}

# Filters that apply a "left" predictor need at least one full pixel of history.
# For bit depth 8 that is simply the channel count, but the formula is kept
# general so sub-byte reading can be added later without surprises.
_SIGNATURE_IHDR = b"IHDR"
_SIGNATURE_IDAT = b"IDAT"
_SIGNATURE_PLTE = b"PLTE"
_SIGNATURE_TRNS = b"tRNS"
_SIGNATURE_IEND = b"IEND"


class PNGError(ValueError):
    """Raised when a file is not a PNG we know how to read."""


class Image:
    """An 8-bit RGBA raster held in a flat ``bytearray``.

    ``pixels`` is laid out row major: pixel ``(x, y)`` starts at
    ``(y * width + x) * 4``.
    """

    __slots__ = ("width", "height", "pixels")

    def __init__(self, width, height, pixels=None):
        if width <= 0 or height <= 0:
            raise PNGError("image dimensions must be positive")
        self.width = int(width)
        self.height = int(height)
        if pixels is None:
            self.pixels = bytearray(self.width * self.height * 4)
        else:
            expected = self.width * self.height * 4
            if len(pixels) != expected:
                raise PNGError(
                    "pixel buffer is %d bytes, expected %d" % (len(pixels), expected)
                )
            self.pixels = bytearray(pixels)

    # -- basic access ---------------------------------------------------
    def get(self, x, y):
        """Return ``(r, g, b, a)`` for one pixel."""
        offset = (y * self.width + x) * 4
        p = self.pixels
        return p[offset], p[offset + 1], p[offset + 2], p[offset + 3]

    def set(self, x, y, rgba):
        """Write one pixel.  ``rgba`` is any 4-item sequence."""
        offset = (y * self.width + x) * 4
        p = self.pixels
        p[offset] = rgba[0]
        p[offset + 1] = rgba[1]
        p[offset + 2] = rgba[2]
        p[offset + 3] = rgba[3]

    def copy(self):
        return Image(self.width, self.height, self.pixels)

    def __repr__(self):
        return "Image(%dx%d)" % (self.width, self.height)


# ----------------------------------------------------------------------
# decoding
# ----------------------------------------------------------------------
def _iter_chunks(data):
    pos = 8
    end = len(data)
    while pos + 8 <= end:
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        ctype = data[pos + 4 : pos + 8]
        if pos + 12 + length > end:
            raise PNGError("truncated %s chunk" % ctype.decode("ascii", "replace"))
        payload = data[pos + 8 : pos + 8 + length]
        yield ctype, payload
        pos += 12 + length
        if ctype == _SIGNATURE_IEND:
            return


def _unfilter(raw, width, height, bit_depth, colour_type):
    """Undo PNG row filters, returning one ``bytearray`` per scanline."""
    channels = _CHANNELS[colour_type]
    bpp = max(1, channels * bit_depth // 8)
    stride = (width * channels * bit_depth + 7) // 8
    rows = []
    prev = bytearray(stride)
    pos = 0
    for _ in range(height):
        if pos >= len(raw):
            raise PNGError("truncated image data")
        filter_type = raw[pos]
        pos += 1
        line = bytearray(raw[pos : pos + stride])
        if len(line) != stride:
            raise PNGError("truncated image data")
        pos += stride

        if filter_type == 0:
            pass
        elif filter_type == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif filter_type == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif filter_type == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif filter_type == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                pa = abs(b - c)
                pb = abs(a - c)
                pc = abs(a + b - 2 * c)
                if pa <= pb and pa <= pc:
                    predictor = a
                elif pb <= pc:
                    predictor = b
                else:
                    predictor = c
                line[i] = (line[i] + predictor) & 0xFF
        else:
            raise PNGError("unknown filter type %d" % filter_type)

        rows.append(line)
        prev = line
    return rows


def decode(data):
    """Decode PNG bytes into an :class:`Image`.

    Supports 8-bit, non-interlaced images of every standard colour type.
    16-bit and interlaced files raise :class:`PNGError` with a clear message
    rather than producing garbage.
    """
    if data[:8] != PNG_SIGNATURE:
        raise PNGError("not a PNG file (bad signature)")

    width = height = bit_depth = colour_type = interlace = None
    palette = None
    transparency = None
    idat = bytearray()

    for ctype, payload in _iter_chunks(data):
        if ctype == _SIGNATURE_IHDR:
            (width, height, bit_depth, colour_type, _comp, _filt, interlace) = struct.unpack(
                ">IIBBBBB", payload
            )
        elif ctype == _SIGNATURE_PLTE:
            palette = bytes(payload)
        elif ctype == _SIGNATURE_TRNS:
            transparency = bytes(payload)
        elif ctype == _SIGNATURE_IDAT:
            idat += payload

    if width is None:
        raise PNGError("missing IHDR chunk")
    if bit_depth != 8:
        raise PNGError("only 8-bit PNGs are supported (got bit depth %s)" % bit_depth)
    if interlace != 0:
        raise PNGError("interlaced (Adam7) PNGs are not supported")
    if colour_type not in _CHANNELS:
        raise PNGError("unsupported colour type %s" % colour_type)
    if not idat:
        raise PNGError("missing IDAT chunk")

    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise PNGError("corrupt image data: %s" % exc)

    rows = _unfilter(raw, width, height, bit_depth, colour_type)
    channels = _CHANNELS[colour_type]
    out = bytearray(width * height * 4)

    # An indexed image may carry alpha per palette entry rather than per pixel.
    palette_alpha = None
    if colour_type == 3 and transparency:
        palette_alpha = bytearray(transparency)

    for y in range(height):
        row = rows[y]
        base = y * width * 4
        if colour_type == 2:  # RGB
            for x in range(width):
                o = x * 3
                d = base + x * 4
                out[d] = row[o]
                out[d + 1] = row[o + 1]
                out[d + 2] = row[o + 2]
                out[d + 3] = 255
        elif colour_type == 6:  # RGBA
            out[base : base + width * 4] = row
        elif colour_type == 0:  # greyscale
            for x in range(width):
                v = row[x]
                d = base + x * 4
                out[d] = out[d + 1] = out[d + 2] = v
                out[d + 3] = 255
        elif colour_type == 4:  # greyscale + alpha
            for x in range(width):
                o = x * 2
                v = row[o]
                d = base + x * 4
                out[d] = out[d + 1] = out[d + 2] = v
                out[d + 3] = row[o + 1]
        else:  # colour_type == 3, indexed
            if palette is None:
                raise PNGError("indexed PNG without a PLTE chunk")
            for x in range(width):
                index = row[x]
                o = index * 3
                d = base + x * 4
                out[d] = palette[o]
                out[d + 1] = palette[o + 1]
                out[d + 2] = palette[o + 2]
                if palette_alpha is not None and index < len(palette_alpha):
                    out[d + 3] = palette_alpha[index]
                else:
                    out[d + 3] = 255

    return Image(width, height, out)


def read(path):
    """Read and decode a PNG file from ``path``."""
    with open(path, "rb") as fh:
        return decode(fh.read())


# ----------------------------------------------------------------------
# encoding
# ----------------------------------------------------------------------
def _chunk(ctype, payload):
    return (
        struct.pack(">I", len(payload))
        + ctype
        + payload
        + struct.pack(">I", zlib.crc32(ctype + payload) & 0xFFFFFFFF)
    )


def _pack_rows(image, bpp=4, compress_level=9):
    """Serialise scanlines with filter type 0 (None).

    Filter 0 is deliberate: the main use case is palette-quantised sprites and
    flat artwork, where adaptive filtering costs CPU and often inflates the
    output.  It also keeps the encoder small enough to audit by eye.
    """
    stride = image.width * bpp
    raw = bytearray((stride + 1) * image.height)
    src = image.pixels
    for y in range(image.height):
        dst = y * (stride + 1)
        raw[dst] = 0
        if bpp == 4:
            raw[dst + 1 : dst + 1 + stride] = src[y * stride : (y + 1) * stride]
        else:
            for x in range(image.width):
                o = (y * image.width + x) * 4
                raw[dst + 1 + x] = src[o]
    return zlib.compress(bytes(raw), compress_level)


def encode(image, compress_level=9):
    """Encode an :class:`Image` as a truecolour+alpha PNG."""
    out = bytearray(PNG_SIGNATURE)
    out += _chunk(b"IHDR", struct.pack(">IIBBBBB", image.width, image.height, 8, 6, 0, 0, 0))
    out += _chunk(b"IDAT", _pack_rows(image, bpp=4, compress_level=compress_level))
    out += _chunk(b"IEND", b"")
    return bytes(out)


def encode_indexed(image, indices, palette, compress_level=9):
    """Encode an indexed PNG from a palette and one index byte per pixel.

    ``indices`` must be a ``bytearray`` of ``width * height`` entries and
    ``palette`` a sequence of ``(r, g, b)`` tuples of at most 256 entries.
    """
    if len(palette) > 256:
        raise PNGError("palette may hold at most 256 colours")
    if len(indices) != image.width * image.height:
        raise PNGError("index buffer does not match image dimensions")

    plte = bytearray()
    for entry in palette:
        plte += bytes((entry[0], entry[1], entry[2]))

    # Preserve alpha when the source actually uses it, via a tRNS chunk.
    alpha = bytearray()
    used_alpha = False
    for entry in palette:
        a = entry[3] if len(entry) > 3 else 255
        alpha.append(a)
        if a != 255:
            used_alpha = True

    stride = image.width
    raw = bytearray((stride + 1) * image.height)
    for y in range(image.height):
        dst = y * (stride + 1)
        raw[dst] = 0
        raw[dst + 1 : dst + 1 + stride] = indices[y * stride : (y + 1) * stride]

    out = bytearray(PNG_SIGNATURE)
    out += _chunk(b"IHDR", struct.pack(">IIBBBBB", image.width, image.height, 8, 3, 0, 0, 0))
    out += _chunk(b"PLTE", bytes(plte))
    if used_alpha:
        out += _chunk(b"tRNS", bytes(alpha))
    out += _chunk(b"IDAT", zlib.compress(bytes(raw), compress_level))
    out += _chunk(b"IEND", b"")
    return bytes(out)


def write(path, image, compress_level=9):
    """Encode ``image`` and write it to ``path``."""
    with open(path, "wb") as fh:
        fh.write(encode(image, compress_level=compress_level))


def write_indexed(path, image, indices, palette, compress_level=9):
    with open(path, "wb") as fh:
        fh.write(encode_indexed(image, indices, palette, compress_level=compress_level))
