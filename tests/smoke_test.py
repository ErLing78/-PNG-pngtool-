"""End-to-end smoke test: drive the CLI the way a user would."""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

from stdpng import codec  # noqa: E402


def make_fixture(path):
    """A 32x32 image with a gradient plus a transparent corner."""
    image = codec.Image(32, 32)
    for y in range(32):
        for x in range(32):
            if x < 8 and y < 8:
                image.set(x, y, (0, 0, 0, 0))
            else:
                image.set(x, y, (x * 8 % 256, y * 8 % 256, 128, 255))
    codec.write(path, image)


def run(args, cwd):
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "stdpng.cli"] + args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    return proc


def main():
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        fixture = os.path.join(tmp, "in.png")
        make_fixture(fixture)

        steps = [
            (["info", fixture], 0),
            (["scale", fixture, os.path.join(tmp, "x2.png"), "2"], 0),
            (["resize", fixture, os.path.join(tmp, "r16.png"), "--width", "16", "--height", "16"], 0),
            (["resize", fixture, os.path.join(tmp, "box.png"), "--width", "7", "--mode", "box"], 0),
            (["crop", fixture, os.path.join(tmp, "c.png"), "--box", "4,4,16,16"], 0),
            (["rotate", fixture, os.path.join(tmp, "rot.png"), "--degrees", "90"], 0),
            (["flip", fixture, os.path.join(tmp, "flip.png"), "--axis", "h"], 0),
            (["pad", fixture, os.path.join(tmp, "p.png"), "--left", "2", "--transparent"], 0),
            (["quantize", fixture, os.path.join(tmp, "q16.png"), "--colors", "16"], 0),
            (["snap", fixture, os.path.join(tmp, "snap.png"), "--palette", "pico8"], 0),
            (["convert", fixture, os.path.join(tmp, "out.bmp")], 0),
            (["convert", fixture, os.path.join(tmp, "out.ppm")], 0),
            (["extract-palette", fixture, os.path.join(tmp, "p.gpl"), "--colors", "8"], 0),
            (["show-palette", "db16"], 0),
            (["list-palettes"], 0),
            (["ascii", fixture, "--cols", "40"], 0),
            (["snap", fixture, os.path.join(tmp, "db16.png"), "--palette", os.path.join(tmp, "p.gpl")], 0),
            # Failure paths must exit non-zero, not traceback.
            (["info", os.path.join(tmp, "missing.png")], 1),
            (["convert", fixture, os.path.join(tmp, "bad.tiff")], 1),
        ]

        for args, expected in steps:
            proc = run(args, ROOT)
            ok = proc.returncode == expected
            label = " ".join(args[:2])
            if not ok:
                failures.append(
                    "%s -> exit %d (expected %d)\nstdout: %s\nstderr: %s"
                    % (label, proc.returncode, expected, proc.stdout.strip(), proc.stderr.strip())
                )
            print("%s %-40s exit=%d" % ("PASS" if ok else "FAIL", label, proc.returncode))

        # Verify a couple of outputs are readable and correctly sized.
        checks = [
            ("x2.png", 64, 64),
            ("r16.png", 16, 16),
            ("box.png", 7, 32),
            ("c.png", 16, 16),
            ("q16.png", 32, 32),
            ("snap.png", 32, 32),
        ]
        for name, want_w, want_h in checks:
            path = os.path.join(tmp, name)
            try:
                image = codec.read(path)
                ok = (image.width, image.height) == (want_w, want_h)
                if not ok:
                    failures.append(
                        "%s is %dx%d, expected %dx%d"
                        % (name, image.width, image.height, want_w, want_h)
                    )
                print("%s %-40s %dx%d" % ("PASS" if ok else "FAIL", name, image.width, image.height))
            except Exception as exc:  # noqa: BLE001
                failures.append("%s unreadable: %s" % (name, exc))
                print("FAIL %-40s %s" % (name, exc))

    print()
    if failures:
        print("SMOKE TEST FAILED (%d issues)" % len(failures))
        for item in failures:
            print(" - " + item)
        return 1
    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
