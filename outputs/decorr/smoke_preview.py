"""A smoke run's first frame as preview.png (tone-mapped to its 99.5th percentile), and the share of pixels that are
lit (above 5% of that level), so a new scene's framing and lighting can be checked before its long runs.

    python smoke_preview.py <dir>      prints "lit fraction 0.xxx: <dir>/preview.png"
"""
import glob
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2  # noqa: E402
import numpy as np  # noqa: E402


def preview(d):
    img = cv2.imread(sorted(glob.glob(os.path.join(d, "*accumulated_color*.exr")))[0], cv2.IMREAD_UNCHANGED)[..., :3]
    img = np.nan_to_num(img, posinf=0.0)
    k = np.percentile(img, 99.5) + 1e-9
    out = os.path.join(d, "preview.png")
    cv2.imwrite(out, (255 * np.clip(img / k, 0, 1) ** (1 / 2.2)).astype(np.uint8))
    lum = img @ np.array([0.0722, 0.7152, 0.2126])  # BGR
    return float((lum > 0.05 * np.percentile(lum, 99.5)).mean()), out


if __name__ == "__main__":
    lit, out = preview(sys.argv[1])
    print("lit fraction %.3f: %s" % (lit, out))
