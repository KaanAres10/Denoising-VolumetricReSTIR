# The halo beside the smoke in motion, measured where it lives: the band just OUTSIDE the silhouette.
#
# Stop-and-go recordings (Scripts/record_look.py, VR_RECORD_STOPS=3, 960x540): the frame that ARRIVES at
# a stop and the last frame of that stop show the identical pose, so a difference in the band is what
# motion left behind. Masks are the estimator's mediumAlpha at each stop pose (halo_masks/, written by
# halo_masks.py -- geometry only, the same for every configuration). Band = 1..12 px outside
# alpha > 0.3, background only (alpha < 0.05); rim = 1..6 px INSIDE, so a fix cannot quietly move the
# problem onto the smoke's own edge.
#
# The stops occupy schedule (= file) indices 74..224, 299..449, 524..674; arrival is the FIRST frame at
# the pose. A first version of this measurement took 75..225: its "settled" frame was the first one
# after the camera moved on, the mask no longer fit, and it reported a dark band in the raw input with
# or without temporal reuse. Without temporal reuse there is none.
#
# Usage: python m_halo_band.py <capture dir> [...]     (values are 8-bit LDR, /255)
import glob, os, re, sys
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import cv2, numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FRAMES, STOPS, STOP_FRAMES = 300, 3, 150
bounds = {int(round(j * FRAMES / (STOPS + 1))) for j in range(1, STOPS + 1)}
schedule = []
for i in range(FRAMES):
    schedule.append(i)
    if i + 1 in bounds:
        schedule += [i] * STOP_FRAMES
ARRIVALS = [k for k in range(1, len(schedule))
            if schedule[k] != schedule[k - 1] and k + 1 < len(schedule) and schedule[k + 1] == schedule[k]]
assert ARRIVALS == [74, 299, 524], ARRIVALS


def ring(core, lo, hi):
    d = lambda r: cv2.dilate(core, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))) > 0
    return d(hi) & ~d(lo)


def masks():
    out = []
    for f in (19, 39, 59):
        a = cv2.imread(os.path.join(HERE, os.environ.get("HALO_MASKS", "halo_masks"), "alpha.VolumetricReSTIR.mediumAlpha.%d.exr" % f), cv2.IMREAD_UNCHANGED)
        a = a[..., 2] if a.ndim == 3 else a
        core = (a > 0.3).astype(np.uint8)
        band = ring(core, 1, 12) & (a < 0.05)
        rim = ring(1 - core, 1, 6) & (a > 0.3)
        out.append((band, rim))
    return out


def frame_paths(d):
    fs = glob.glob(os.path.join(HERE, d, "*.png"))
    return sorted(fs, key=lambda f: int(re.search(r"\.(\d+)\.png$", f).group(1)))


LUM = np.array([0.0722, 0.7152, 0.2126], np.float32)   # BGR


def main(dirs):
    M = masks()
    print("band = background 1-12 px outside the smoke, rim = smoke 1-6 px inside its edge; LDR /255")
    print("%-18s %-44s %-24s %-22s %s" % ("capture", "band arrival-settled per stop (mean)", "band B/G/R shift (mean)",
                                        "rim arrival-settled", "band dark px*   floor"))
    for d in dirs:
        fs = frame_paths(d)
        assert len(fs) == len(schedule), (d, len(fs), len(schedule))
        dl, bgr, rim, dark, floor = [], [], [], [], []
        for (band, rimm), a in zip(M, ARRIVALS):
            A, S, S1 = (cv2.imread(fs[k]).astype(np.float32) for k in (a, a + STOP_FRAMES, a + STOP_FRAMES - 1))
            dl.append((A @ LUM)[band].mean() - (S @ LUM)[band].mean())
            bgr.append(A[band].mean(0) - S[band].mean(0))
            rim.append((A @ LUM)[rimm].mean() - (S @ LUM)[rimm].mean())
            # Per-pixel darkening, after a small blur so raw-input noise does not count as halo.
            Ab, Sb = (cv2.GaussianBlur(x @ LUM, (0, 0), 1.5) for x in (A, S))
            dark.append(100.0 * ((Ab < 0.7 * Sb) & (Sb > 8))[band].mean())
            floor.append(abs((S @ LUM)[band].mean() - (S1 @ LUM)[band].mean()))
        b = np.mean(bgr, 0)
        print("%-18s %+.2f  (%s)%s %+.2f/%+.2f/%+.2f%s %+.2f%s %4.1f%%   %.2f"
              % (d, np.mean(dl), " ".join("%+.2f" % v for v in dl), " " * max(1, 22 - 7 * len(dl) + 11), b[0], b[1], b[2],
                 " " * 5, np.mean(rim), " " * 15, np.mean(dark), np.mean(floor)))
    print("* % of band pixels whose blurred luminance on arrival is < 70% of settled")


if __name__ == "__main__":
    main(sys.argv[1:])
