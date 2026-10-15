"""ASCII preview - look at an image through a text-only channel.

This exists for a very specific reason: when you are driving this library from a
tool or model that cannot render images, an ASCII rendering is the only way to
eyeball whether an operation produced something sane.  It is also genuinely
handy over SSH.
"""

from .codec import Image

RAMP = " .:-=+*#%@"


def render(image, columns=120, mode="mean", invert=False, ramp=RAMP):
    """Render ``image`` as ASCII art of roughly ``columns`` characters wide.

    ``mode`` selects what each character cell represents:

    * ``"mean"`` - average luminance, good for spotting blocks and colour bands
    * ``"min"`` - darkest pixel in the cell, good for reading thin strokes
    * ``"max"`` - lightest pixel, useful against dark backgrounds

    Terminal characters are about twice as tall as they are wide, so the row
    count is halved to keep the aspect ratio honest.
    """
    if mode not in ("mean", "min", "max"):
        raise ValueError("mode must be 'mean', 'min' or 'max'")
    if columns < 1:
        raise ValueError("columns must be positive")

    w, h = image.width, image.height
    rows = max(1, int(columns * h / w / 2.05))
    cell_w = w / columns
    cell_h = h / rows
    src = image.pixels
    lines = []

    for row in range(rows):
        y0 = int(row * cell_h)
        y1 = max(y0 + 1, int((row + 1) * cell_h))
        chars = []
        for col in range(columns):
            x0 = int(col * cell_w)
            x1 = max(x0 + 1, int((col + 1) * cell_w))

            total = 0
            count = 0
            darkest = 255
            lightest = 0
            for y in range(y0, min(y1, h)):
                base = y * w * 4
                for x in range(x0, min(x1, w)):
                    o = base + x * 4
                    lum = (src[o] * 299 + src[o + 1] * 587 + src[o + 2] * 114) // 1000
                    total += lum
                    count += 1
                    if lum < darkest:
                        darkest = lum
                    if lum > lightest:
                        lightest = lum

            if count == 0:
                chars.append(" ")
                continue
            if mode == "mean":
                value = total // count
            elif mode == "min":
                value = darkest
            else:
                value = lightest
            if invert:
                value = 255 - value
            chars.append(ramp[int((255 - value) / 255 * (len(ramp) - 1))])
        lines.append("".join(chars))

    return "\n".join(lines)


def print_preview(image, columns=120, mode="mean", invert=False, stream=None):
    """Print :func:`render` output, returning it as a string as well."""
    text = render(image, columns=columns, mode=mode, invert=invert)
    if stream is None:
        import sys

        stream = sys.stdout
    stream.write(text + "\n")
    return text


def describe(image):
    """A one-line human summary: size, alpha usage and colour count."""
    src = image.pixels
    colours = set()
    transparent = 0
    for i in range(0, len(src), 4):
        colours.add((src[i], src[i + 1], src[i + 2]))
        if src[i + 3] == 0:
            transparent += 1
    total = image.width * image.height
    parts = ["%dx%d" % (image.width, image.height)]
    parts.append("%d colours" % len(colours))
    if transparent:
        parts.append("%.1f%% transparent" % (transparent * 100.0 / total))
    return ", ".join(parts)
