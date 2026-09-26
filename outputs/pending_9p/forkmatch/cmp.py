"""9.0 verify frames against the 4.x fork's (time_raw.py / _time_raw_legacy.py VR_VERIFY=1: bistro, orbit pose
150, raw estimator, fixed +8 EV linear tone map). Per frame: share of lit pixels, mean level, and the
correlation / mean abs difference with the fork's frame. cmp.py <fork.png> <label=png> ..."""
import sys, cv2, numpy as np
lum = lambda p: (cv2.imread(p, cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float64)[..., ::-1] * [0.2126, 0.7152, 0.0722]).sum(-1)
F = lum(sys.argv[1])
def row(label, I):
    c = np.corrcoef(I.ravel(), F.ravel())[0, 1]
    b = lambda X: cv2.GaussianBlur(X, (0, 0), 6)
    cb = np.corrcoef(b(I).ravel(), b(F).ravel())[0, 1]
    print("%-22s lit %5.1f%%  mean %6.2f  | vs fork: corr %.4f (blurred %.4f)  mean abs diff %5.2f (blurred %5.2f)"
          % (label, 100 * (I > 0).mean(), I.mean(), c, cb, np.abs(I - F).mean(), np.abs(b(I) - b(F)).mean()))
row("fork", F)
for a in sys.argv[2:]:
    label, p = a.split("=", 1); row(label, lum(p))
