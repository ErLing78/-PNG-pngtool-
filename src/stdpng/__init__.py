"""stdpng - a PNG and pixel-art toolkit built on the Python standard library.

Why this exists
---------------
Every other image library assumes something: Pillow needs a wheel, OpenCV needs
a native build, ImageMagick needs a binary on PATH.  On a locked-down machine
none of that is available, and ``pip install`` has no network.  stdpng assumes
only stock CPython.

What it is good at
------------------
* Pixel art and sprite sheets: nearest-neighbour scaling, palette snapping,
  trimming, outlining.
* Shrinking assets under a byte budget with median-cut quantisation.
* Reading an image when you have no way to display one, via ASCII preview.

What it is not
--------------
* A photo editor.  JPEG decoding is out of scope on purpose.
* Fast on megapixel photographs.  Pure Python means honest, modest throughput -
  a 1024x1024 resize takes a second or so, not a millisecond.

Quick start
-----------
>>> from stdpng import codec, ops
>>> image = codec.read("sprite.png")
>>> small = ops.scale(image, 0.5)
>>> codec.write("sprite_half.png", small)

Or from the shell::

    stdpng scale sprite.png sprite_2x.png 2
    stdpng quantize sprite.png sprite_16c.png --colors 16
    stdpng ascii sprite.png --cols 80
"""

from . import ascii, codec, formats, ops, quantize
from .codec import Image, PNGError

__version__ = "0.1.0"

__all__ = [
    "Image",
    "PNGError",
    "ascii",
    "codec",
    "formats",
    "ops",
    "quantize",
    "__version__",
]
