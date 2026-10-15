"""Command line interface.

Design notes:

* Every command is a noun-verb pair expressed as a flat subcommand, so the tool
  composes cleanly in shell pipelines without nested argument soup.
* Inputs and outputs are positional, options are always flags.  ``-`` is not
  special-cased; stdpng never wants to own a stream.
* Exit codes: 0 success, 1 bad input, 2 usage error (argparse default).
"""

import argparse
import os
import sys

from . import ascii as ascii_mod
from . import codec, formats, ops, quantize


def _load(path):
    return formats.load(path)


def _save(path, image, compress_level=9):
    ext = formats.extension_of(path)
    if ext == ".png":
        codec.write(path, image, compress_level=compress_level)
    else:
        formats.save(path, image)


def _report(path, image):
    print("%s: %s" % (path, ascii_mod.describe(image)))


def _parse_box(text):
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("box must be x,y,width,height")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        raise argparse.ArgumentTypeError("box values must be integers")


def _resolve_palette(spec):
    """A palette spec is either a bundled name or a path to a palette file."""
    if os.path.exists(spec):
        return quantize.read_palette(spec)
    return quantize.builtin(spec)


# ----------------------------------------------------------------------
# commands
# ----------------------------------------------------------------------


def cmd_info(args):
    image = _load(args.image)
    print("file:      %s" % args.image)
    print("size:      %dx%d" % (image.width, image.height))
    print("pixels:    %d" % (image.width * image.height))
    print("bytes:     %d" % os.path.getsize(args.image))
    print("summary:   %s" % ascii_mod.describe(image))
    return 0


def cmd_resize(args):
    image = _load(args.input)
    if args.width is None and args.height is None:
        print("error: give --width and/or --height", file=sys.stderr)
        return 1
    width = args.width or image.width
    height = args.height or image.height
    if args.mode == "box":
        result = ops.box_resize(image, width, height)
    else:
        result = ops.resize_nearest(image, width, height)
    _save(args.output, result)
    print("%s -> %s (%dx%d)" % (args.input, args.output, result.width, result.height))
    return 0


def cmd_scale(args):
    image = _load(args.input)
    result = ops.scale(image, args.factor)
    _save(args.output, result)
    print("%s -> %s (%dx%d)" % (args.input, args.output, result.width, result.height))
    return 0


def cmd_crop(args):
    image = _load(args.input)
    x, y, w, h = args.box
    result = ops.crop(image, x, y, w, h)
    _save(args.output, result)
    print("%s -> %s (%dx%d)" % (args.input, args.output, result.width, result.height))
    return 0


def cmd_rotate(args):
    image = _load(args.input)
    result = ops.rotate(image, args.degrees)
    _save(args.output, result)
    print("%s -> %s (%dx%d)" % (args.input, args.output, result.width, result.height))
    return 0


def cmd_flip(args):
    image = _load(args.input)
    result = ops.flip_horizontal(image) if args.axis == "h" else ops.flip_vertical(image)
    _save(args.output, result)
    print("%s -> %s (axis %s)" % (args.input, args.output, args.axis))
    return 0


def cmd_pad(args):
    image = _load(args.input)
    colour = (0, 0, 0, 0) if args.transparent else (255, 255, 255, 255)
    result = ops.pad(image, args.left, args.top, args.right, args.bottom, colour)
    _save(args.output, result)
    print("%s -> %s (%dx%d)" % (args.input, args.output, result.width, result.height))
    return 0


def cmd_trim(args):
    image = _load(args.input)
    result = ops.trim(image, tolerance=args.tolerance)
    _save(args.output, result)
    print("%s -> %s (%dx%d)" % (args.input, args.output, result.width, result.height))
    return 0


def cmd_quantize(args):
    image = _load(args.input)
    palette, indices = quantize.quantize(
        image,
        args.colors,
        perceptual=args.perceptual,
        dither=args.dither,
        alpha_threshold=args.alpha_threshold,
    )
    codec.write_indexed(args.output, image, indices, palette)
    print(
        "%s -> %s (%d colours, %d bytes)"
        % (args.input, args.output, len(palette), os.path.getsize(args.output))
    )
    return 0


def cmd_snap(args):
    image = _load(args.input)
    palette = _resolve_palette(args.palette)
    entries, indices = quantize.snap(
        image,
        palette,
        perceptual=args.perceptual,
        dither=args.dither,
        alpha_threshold=args.alpha_threshold,
    )
    codec.write_indexed(args.output, image, indices, entries)
    print(
        "%s -> %s (snapped to %d colours, %d bytes)"
        % (args.input, args.output, len(entries), os.path.getsize(args.output))
    )
    return 0


def cmd_extract_palette(args):
    image = _load(args.input)
    histogram = quantize._histogram(image)
    palette = quantize.median_cut(
        list(histogram.keys()), list(histogram.values()), args.colors, perceptual=args.perceptual
    )
    quantize.write_palette(args.output, palette, name=os.path.basename(args.input))
    print("wrote %s (%d colours)" % (args.output, len(palette)))
    return 0


def cmd_show_palette(args):
    palette = _resolve_palette(args.palette)
    for i, entry in enumerate(palette):
        r, g, b = entry[0], entry[1], entry[2]
        print("%3d  #%02X%02X%02X  rgb(%3d, %3d, %3d)" % (i, r, g, b, r, g, b))
    print("%d colours" % len(palette))
    return 0


def cmd_list_palettes(args):
    for name in sorted(quantize.PALETTES):
        print("%-10s %d colours" % (name, len(quantize.PALETTES[name])))
    return 0


def cmd_ascii(args):
    image = _load(args.image)
    ascii_mod.print_preview(image, columns=args.cols, mode=args.mode, invert=args.invert)
    return 0


def cmd_convert(args):
    image = _load(args.input)
    if args.colors:
        palette, indices = quantize.quantize(image, args.colors, dither=args.dither)
        codec.write_indexed(args.output, image, indices, palette)
        print("%s -> %s (%d colours)" % (args.input, args.output, len(palette)))
    else:
        _save(args.output, image)
        print("%s -> %s" % (args.input, args.output))
    return 0


# ----------------------------------------------------------------------
# parser
# ----------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(
        prog="stdpng",
        description="PNG and pixel-art toolkit with zero third-party dependencies.",
    )
    parser.add_argument("--version", action="version", version="stdpng 0.1.0")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p = sub.add_parser("info", help="print image metadata")
    p.add_argument("image")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("resize", help="resize to exact dimensions")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    p.add_argument("--mode", choices=("nearest", "box"), default="nearest")
    p.set_defaults(func=cmd_resize)

    p = sub.add_parser("scale", help="scale by a factor")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("factor", type=float)
    p.set_defaults(func=cmd_scale)

    p = sub.add_parser("crop", help="cut out a rectangle")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--box", type=_parse_box, required=True, metavar="X,Y,W,H")
    p.set_defaults(func=cmd_crop)

    p = sub.add_parser("rotate", help="rotate by 90/180/270 degrees")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--degrees", type=int, required=True)
    p.set_defaults(func=cmd_rotate)

    p = sub.add_parser("flip", help="mirror horizontally or vertically")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--axis", choices=("h", "v"), required=True)
    p.set_defaults(func=cmd_flip)

    p = sub.add_parser("pad", help="add a border around the image")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--left", type=int, default=0)
    p.add_argument("--top", type=int, default=0)
    p.add_argument("--right", type=int, default=0)
    p.add_argument("--bottom", type=int, default=0)
    p.add_argument("--transparent", action="store_true", help="pad with transparency")
    p.set_defaults(func=cmd_pad)

    p = sub.add_parser("trim", help="drop uniform borders")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--tolerance", type=int, default=0)
    p.set_defaults(func=cmd_trim)

    p = sub.add_parser("quantize", help="reduce to N colours")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument(
        "--colors",
        type=int,
        default=16,
        metavar="N",
        help="total palette entries, transparency included (default 16)",
    )
    p.add_argument("--dither", action="store_true")
    p.add_argument("--perceptual", action="store_true", help="match in L*a*b* space")
    p.add_argument(
        "--alpha-threshold",
        type=int,
        default=128,
        metavar="N",
        help="alpha below N counts as transparent (default 128)",
    )
    p.set_defaults(func=cmd_quantize)

    p = sub.add_parser("snap", help="force onto an existing palette")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--palette", required=True, help="bundled name or .gpl/.pal/.hex/.act path")
    p.add_argument("--dither", action="store_true")
    p.add_argument("--perceptual", action="store_true")
    p.add_argument("--alpha-threshold", type=int, default=128, metavar="N")
    p.set_defaults(func=cmd_snap)

    p = sub.add_parser("extract-palette", help="write an image's palette to a file")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--colors", type=int, default=16)
    p.add_argument("--perceptual", action="store_true")
    p.set_defaults(func=cmd_extract_palette)

    p = sub.add_parser("show-palette", help="print a palette")
    p.add_argument("palette")
    p.set_defaults(func=cmd_show_palette)

    p = sub.add_parser("list-palettes", help="list bundled palettes")
    p.set_defaults(func=cmd_list_palettes)

    p = sub.add_parser("ascii", help="render as ASCII art")
    p.add_argument("image")
    p.add_argument("--cols", type=int, default=120)
    p.add_argument("--mode", choices=("mean", "min", "max"), default="mean")
    p.add_argument("--invert", action="store_true")
    p.set_defaults(func=cmd_ascii)

    p = sub.add_parser("convert", help="convert between formats")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--colors", type=int, help="also quantise to N colours")
    p.add_argument("--dither", action="store_true")
    p.set_defaults(func=cmd_convert)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    try:
        return args.func(args)
    except (codec.PNGError, OSError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
