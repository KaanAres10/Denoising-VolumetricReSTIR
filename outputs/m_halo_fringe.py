# The veil around the smoke in motion, measured on the pixels it lies on.
#
# The veil is RR (and TAA) reprojecting the smoke's FRINGE -- pixels whose ray meets some medium but
# which mostly show the ground behind it -- with the smoke's motion, dragging smoke-coloured history
# over that ground while the camera moves. So the region is 0 < mediumAlpha < 0.3 at the stop pose
# (halo_masks/, from halo_masks.py), the comparison is the frame ARRIVING at a stop against the last
# frame of that stop (identical pose, record_look.py VR_RECORD_STOPS=3), and the control is the
# smoke-free ground just beyond the fringe (alpha == 0, within 24 px of it). Floor: the same numbers for
# the last two frames of the stop, i.e. what a settled image changes by on its own.
#
# Luminance on a 1.5 px blur so raw-input noise is not counted as veil; 8-bit LDR (/255).
# Usage: python m_halo_fringe.py <capture dir> [...]
import glob, os, re, sys
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import cv2, numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ARRIVALS, STOP_FRAMES = (74, 299, 524), 150     # record_look.py, VR_RECORD_STOPS=3 (see m_halo_band.py)
LUM = np.array([0.0722, 0.7152, 0.2126], np.float32)   # BGR


def regions():
    out = []
    for f in (19, 39, 59):
        a = cv2.imread(os.path.join(HERE, os.environ.get("HALO_MASKS", "halo_masks"), "alpha.VolumetricReSTIR.mediumAlpha.%d.exr" % f), cv2.IMREAD_UNCHANGED)
        a = a[..., 2] if a.ndim == 3 else a
        fringe = (a > 0) & (a < 0.3)
        near = (a == 0) & (cv2.dilate(fringe.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (49, 49))) > 0)
        out.append((fringe, near))
    return out


def frames(d):
    fs = glob.glob(os.path.join(HERE, d, "*.png"))
    return sorted(fs, key=lambda f: int(re.search(r"\.(\d+)\.png$", f).group(1)))


def lum(f):
    return cv2.GaussianBlur(cv2.imread(f).astype(np.float32) @ LUM, (0, 0), 1.5)


R = regions()
print("mean |arrival - settled| (/255), blurred luminance; signed = arrival - settled")
print("%-18s %22s %14s %20s %14s" % ("capture", "fringe |d| (floor)", "fringe signed", "near-ground |d|", "whole |d|"))
for d in sys.argv[1:]:
    fs = frames(d)
    assert len(fs) == 750, (d, len(fs))
    fa, ff, fsg, na, wh = [], [], [], [], []
    for (fringe, near), a in zip(R, ARRIVALS):
        A, S, S1 = lum(fs[a]), lum(fs[a + STOP_FRAMES]), lum(fs[a + STOP_FRAMES - 1])
        fa.append(np.abs(A - S)[fringe].mean()); ff.append(np.abs(S - S1)[fringe].mean())
        fsg.append((A - S)[fringe].mean()); na.append(np.abs(A - S)[near].mean()); wh.append(np.abs(A - S).mean())
    print("%-18s %13.2f (%.2f) %+14.2f %20.2f %14.2f" % (d, np.mean(fa), np.mean(ff), np.mean(fsg), np.mean(na), np.mean(wh)))
