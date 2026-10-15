"""Additional container formats, read and written in pure Python.

PNG is the primary format, but pipeline work constantly runs into BMP, PPM and
PGM dumps from other tools.  All three have simple enough headers to parse
without a dependency, so they are supported here.  JPEG is deliberately *not*
implemented - a correct baseline JPEG decoder is a large amount of code, and
shipping a half-broken one would be worse than refusing; see ``tools/`` for the
Windows-only transcode helper.
"""

from .codec import Image, PNGError

# ----------------------------------------------------------------------
# BMP
# ----------------------------------------------------------------------


def read_bmp(path):
    """Read an uncompressed 24- or 32-bit BMP."""
    with open(path, "rb") as fh:
        data = fh.read()
    if len(data) < 54 or data[:2] != b"BM":
        raise PNGError("not a BMP file")

    pixel_offset = int.from_bytes(data[10:14], "little")
    header_size = int.from_bytes(data[14:18], "little")
    if header_size < 40:
        raise PNGError("unsupported BMP header size %d" % header_size)

    width = int.from_bytes(data[18:22], "little", signed=True)
    height = int.from_bytes(data[22:26], "little", signed=True)
    planes = int.from_bytes(data[26:28], "little")
    bit_count = int.from_bytes(data[28:30], "little")
    compression = int.from_bytes(data[30:34], "little")

    if planes != 1:
        raise PNGError("unsupported BMP plane count %d" % planes)
    if compression != 0:
        raise PNGError("compressed BMP is not supported (compression=%d)" % compression)
    if bit_count not in (24, 32):
        raise PNGError("only 24- and 32-bit BMP is supported (got %d)" % bit_count)

    bottom_up = height > 0
    height = abs(height)
    bytes_per_pixel = bit_count // 8
    row_stride = ((width * bit_count + 31) // 32) * 4

    out = bytearray(width * height * 4)
    for y in range(height):
        src_y = (height - 1 - y) if bottom_up else y
        row = pixel_offset + src_y * row_stride
        for x in range(width):
            o = row + x * bytes_per_pixel
            if o + bytes_per_pixel > len(data):
                raise PNGError("truncated BMP pixel data")
            d = (y * width + x) * 4
            out[d] = data[o + 2]
            out[d + 1] = data[o + 1]
            out[d + 2] = data[o]
            out[d + 3] = data[o + 3] if bytes_per_pixel == 4 else 255
    return Image(width, height, out)


def write_bmp(path, image):
    """Write a 32-bit BMP with alpha."""
    width, height = image.width, image.height
    row_stride = width * 4
    pixel_size = row_stride * height

    header = bytearray()
    header += b"BM"
    header += (14 + 40 + pixel_size).to_bytes(4, "little")
    header += b"\x00\x00\x00\x00"
    header += (14 + 40).to_bytes(4, "little")
    header += (40).to_bytes(4, "little")
    header += width.to_bytes(4, "little", signed=True)
    header += height.to_bytes(4, "little", signed=True)
    header += (1).to_bytes(2, "little")
    header += (32).to_bytes(2, "little")
    header += (0).to_bytes(4, "little")
    header += pixel_size.to_bytes(4, "little")
    header += (2835).to_bytes(4, "little")
    header += (2835).to_bytes(4, "little")
    header += (0).to_bytes(4, "little")
    header += (0).to_bytes(4, "little")

    src = image.pixels
    body = bytearray(pixel_size)
    for y in range(height):
        src_y = height - 1 - y  # BMP stores rows bottom-up
        for x in range(width):
            s = (src_y * width + x) * 4
            d = (y * width + x) * 4
            body[d] = src[s + 2]
            body[d + 1] = src[s + 1]
            body[d + 2] = src[s]
            body[d + 3] = src[s + 3]

    with open(path, "wb") as fh:
        fh.write(bytes(header))
        fh.write(bytes(body))


# ----------------------------------------------------------------------
# Netpbm: PPM (colour) and PGM (greyscale)
# ----------------------------------------------------------------------


def _read_netpbm_tokens(data, start, count):
    """Read ``count`` whitespace-separated tokens starting at ``start``.

    Returns ``(tokens, offset)`` where ``offset`` points at the whitespace
    character that terminated the last token.  Comment lines introduced by
    ``#`` are skipped, as the format requires.
    """
    tokens = []
    i = start
    length = len(data)
    while len(tokens) < count:
        while i < length and data[i : i + 1].isspace():
            i += 1
        if i >= length:
            break
        if data[i : i + 1] == b"#":
            while i < length and data[i : i + 1] != b"\n":
                i += 1
            continue
        j = i
        while j < length and not data[j : j + 1].isspace():
            j += 1
        tokens.append(data[i:j])
        i = j
    return tokens, i


_NETPBM_ASCII = (b"P1", b"P2", b"P3")
_NETPBM_BINARY = (b"P5", b"P6")
_NETPBM_CHANNELS = {b"P2": 1, b"P3": 3, b"P5": 1, b"P6": 3}


def read_ppm(path):
    """Read a Netpbm file: binary P6/P5 or ASCII P3/P2."""
    with open(path, "rb") as fh:
        data = fh.read()
    if len(data) < 2:
        raise PNGError("empty Netpbm file")

    magic = data[:2]
    if magic not in _NETPBM_CHANNELS:
        raise PNGError(
            "unsupported Netpbm magic %r; supported: P2, P3, P5, P6"
            % magic.decode("ascii", "replace")
        )

    tokens, offset = _read_netpbm_tokens(data, 2, 3)
    if len(tokens) != 3:
        raise PNGError("truncated Netpbm header")
    try:
        width = int(tokens[0])
        height = int(tokens[1])
        maxval = int(tokens[2])
    except ValueError:
        raise PNGError("malformed Netpbm header")
    if width <= 0 or height <= 0:
        raise PNGError("Netpbm dimensions must be positive")
    if maxval <= 0 or maxval > 255:
        raise PNGError("only 8-bit Netpbm files are supported (maxval=%d)" % maxval)

    channels = _NETPBM_CHANNELS[magic]
    expected = width * height * channels
    out = bytearray(width * height * 4)

    if magic in _NETPBM_BINARY:
        # A single whitespace byte separates the header from the sample data.
        payload = data[offset + 1 : offset + 1 + expected]
        if len(payload) != expected:
            raise PNGError("truncated Netpbm pixel data")
        values = payload
    else:
        # ASCII variants: the remaining text is just whitespace-separated numbers.
        values = []
        for token in data[offset:].split():
            if token.startswith(b"#"):
                continue
            try:
                values.append(int(token))
            except ValueError:
                continue
            if len(values) == expected:
                break
        if len(values) != expected:
            raise PNGError("truncated Netpbm pixel data")

    for pixel in range(width * height):
        d = pixel * 4
        if channels == 3:
            o = pixel * 3
            out[d] = values[o]
            out[d + 1] = values[o + 1]
            out[d + 2] = values[o + 2]
        else:
            out[d] = out[d + 1] = out[d + 2] = values[pixel]
        out[d + 3] = 255
    return Image(width, height, out)


def write_ppm(path, image, binary=True):
    """Write a P6 PPM.  ``binary=False`` produces the ASCII P3 variant."""
    src = image.pixels
    width, height = image.width, image.height
    if binary:
        body = bytearray(width * height * 3)
        for pixel in range(width * height):
            o = pixel * 4
            d = pixel * 3
            body[d] = src[o]
            body[d + 1] = src[o + 1]
            body[d + 2] = src[o + 2]
        with open(path, "wb") as fh:
            fh.write(b"P6\n%d %d\n255\n" % (width, height))
            fh.write(bytes(body))
    else:
        with open(path, "w", encoding="ascii", newline="\n") as fh:
            fh.write("P3\n%d %d\n255\n" % (width, height))
            for y in range(height):
                row = []
                for x in range(width):
                    o = (y * width + x) * 4
                    row.append("%d %d %d" % (src[o], src[o + 1], src[o + 2]))
                fh.write(" ".join(row) + "\n")


def write_pgm(path, image):
    """Write the greyscale reduce of an image as a P5 PGM."""
    src = image.pixels
    width, height = image.width, image.height
    body = bytearray(width * height)
    for pixel in range(width * height):
        o = pixel * 4
        body[pixel] = (src[o] * 299 + src[o + 1] * 587 + src[o + 2] * 114) // 1000
    with open(path, "wb") as fh:
        fh.write(b"P5\n%d %d\n255\n" % (width, height))
        fh.write(bytes(body))


# ----------------------------------------------------------------------
# dispatch
# ----------------------------------------------------------------------

READERS = {
    ".png": None,  # handled by codec directly
    ".bmp": read_bmp,
    ".ppm": read_ppm,
    ".pgm": read_ppm,
    ".pnm": read_ppm,
}

WRITERS = {
    ".bmp": write_bmp,
    ".ppm": write_ppm,
    ".pgm": write_pgm,
}


def extension_of(path):
    dot = path.rfind(".")
    return path[dot:].lower() if dot >= 0 else ""


def load(path):
    """Read any supported format, dispatching on the file extension."""
    import os

    from . import codec

    ext = extension_of(path)
    if ext == ".png":
        return codec.read(path)
    if ext == ".jpg" or ext == ".jpeg":
        raise PNGError(
            "JPEG decoding is not implemented in stdpng; run "
            "tools/winrt_transcode.ps1 on Windows, or convert to PNG first"
        )
    reader = READERS.get(ext)
    if reader is None:
        raise PNGError("unsupported input format: %s" % (ext or os.path.basename(path)))
    return reader(path)


def save(path, image, **kwargs):
    """Write any supported format, dispatching on the file extension."""
    from . import codec

    ext = extension_of(path)
    if ext == ".png":
        return codec.write(path, image, **kwargs)
    writer = WRITERS.get(ext)
    if writer is None:
        raise PNGError("unsupported output format: %s" % (ext or path))
    return writer(path, image)
