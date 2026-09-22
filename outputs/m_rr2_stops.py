# Stop-and-go recording (Scripts/record_look.py, VR_RECORD_STOPS=3, 5 s stops): what each denoiser does
# when the camera STOPS -- how much it still flickers right after stopping, and once settled -- versus
# while it moves. Flicker = mean |frame - previous frame| (8-bit), which on a still camera is pure
# temporal noise; the moving segments use the same instability metric as m_rr2.py.
#
# The frame -> orbit-position schedule is rebuilt here with record_look.py's own rule, so the segments
# are exact rather than detected from the images.
#
# Usage: python m_rr2_stops.py [left dir] [right dir]   (default lookstop_prev_E lookstop_cur_F)
import os, re, sys
import cv2, numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
LEFT = sys.argv[1] if len(sys.argv) > 1 else "lookstop_prev_E"
RIGHT = sys.argv[2] if len(sys.argv) > 2 else "lookstop_cur_F"
FRAMES, STOPS, STOP_FRAMES, FPS = 300, 3, 150, 30   # record_look.py defaults with VR_RECORD_STOPS=3

bounds = {int(round(j * FRAMES / (STOPS + 1))) for j in range(1, STOPS + 1)}
schedule = []
for i in range(FRAMES):
    schedule.append(i)
    if i + 1 in bounds:
        schedule += [i] * STOP_FRAMES
moving = [k == 0 or schedule[k] != schedule[k - 1] for k in range(len(schedule))]


def load(d):
    fs = sorted([f for f in os.listdir(os.path.join(HERE, d)) if f.endswith(".png")],
                key=lambda f: int(re.search(r"\.(\d+)\.png$", f).group(1)))
    return [cv2.imread(os.path.join(HERE, d, f)).astype(np.float32) for f in fs]


def segments():
    out, start = [], 0
    for k in range(1, len(moving) + 1):
        if k == len(moving) or moving[k] != moving[start]:
            out.append((moving[start], start, k))
            start = k
    return out


data = {LEFT: load(LEFT), RIGHT: load(RIGHT)}
assert all(len(v) == len(schedule) for v in data.values()), {k: len(v) for k, v in data.items()}
flick = lambda g, a, b: float(np.mean([np.abs(g[k] - g[k - 1]).mean() for k in range(max(a, 1), b)]))

print("%-26s %s" % ("flicker (/255 per frame)", "   ".join("%-24s" % d for d in (LEFT, RIGHT))))
stop_no = 0
for mov, a, b in segments():
    if mov:
        continue
    stop_no += 1
    first, settled = (a, a + FPS), (b - 2 * FPS, b)
    cells = ["first 1 s %.3f, settled %.3f" % (flick(data[d], *first), flick(data[d], *settled)) for d in (LEFT, RIGHT)]
    print("stop %d (%4.1f-%4.1f s)        %s" % (stop_no, a / FPS, b / FPS, "   ".join(cells)))


# Instability while moving, same definition as m_rr2.py (grey, blurred, 2nd temporal difference / mean).
def instability(g, idx, s):
    x = [cv2.GaussianBlur(g[k].mean(axis=2) / 255.0, (0, 0), s) for k in idx]
    mu = float(np.mean([g[k].mean() / 255.0 for k in idx]))
    return 1e3 * float(np.mean([np.abs(x[i] - 2 * x[i - 1] + x[i - 2]).mean() for i in range(2, len(x))])) / mu


w = data[LEFT][0].shape[1]
for d in (LEFT, RIGHT):
    runs = [list(range(a, b)) for mov, a, b in segments() if mov]
    print("%-24s moving: instability s=32 %.2f (mean over %d moving segments)"
          % (d, float(np.mean([instability(data[d], r, 32 * w / 1280.0) for r in runs if len(r) > 3])), len(runs)))
