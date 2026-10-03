"""The port's 2-bounce explosion against the legacy build's: sky (top-left patch) and in-medium mean, per channel.

    python compare_legacy.py <legacy exr> <port exr>
Prints relative differences; exits 1 if the sky differs by more than 0.5% or the medium mean by more than 2%.
"""
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m_corr as mc


def main(argv):
    leg = mc.read_exr(argv[0])[..., :3][..., ::-1].astype(np.float64)
    port = mc.read_exr(argv[1])[..., :3][..., ::-1].astype(np.float64)
    h, w = leg.shape[:2]
    sky = lambda im: im[10:40, 20:120].reshape(-1, 3).mean(0)
    # The explosion's box at this camera (the fireball and its column), as fractions of the frame: the dusk sky's own
    # gradient exceeds any luminance threshold, so the box is fixed rather than thresholded.
    box = np.s_[int(0.11 * h):h, int(0.29 * w):int(0.73 * w)]
    ds = sky(port) / sky(leg) - 1
    dm = port[box].reshape(-1, 3).mean(0) / leg[box].reshape(-1, 3).mean(0) - 1
    dw = port.reshape(-1, 3).mean(0) / leg.reshape(-1, 3).mean(0) - 1
    print("sky rel diff %s; explosion box rel diff %s; whole frame %s" % (np.round(ds, 4), np.round(dm, 4), np.round(dw, 4)))
    return 0 if np.all(np.abs(ds) < 0.005) and np.all(np.abs(dm) < 0.02) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
