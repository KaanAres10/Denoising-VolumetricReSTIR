# Still comparison at NATIVE resolution: previous RR (310.7.0 E) | RR2 (310.9.1 F) | |difference| x4.
# Crops are fixed pixel boxes on the 1080p orbit, chosen from the overview: the plume's interior, a
# plume silhouette against lit geometry, and surface detail (cobbles, cafe furniture) away from it.
import os, re, sys

import cv2, numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
# Default: the captures taken with DLSSDGuides' sky fix, i.e. the current pipeline. Any two capture
# folders work, labelled from their names (see video_rr2.describe).
LEFT = sys.argv[1] if len(sys.argv) > 1 else "rr2s_prev_E"
RIGHT = sys.argv[2] if len(sys.argv) > 2 else "rr2s_cur_F"
_default_pair = (LEFT, RIGHT) == ("rr2s_prev_E", "rr2s_cur_F")
OUT = sys.argv[3] if len(sys.argv) > 3 else os.path.join(
    HERE, "_cmp_rr_vs_rr2.png" if _default_pair else "_cmp_%s_vs_%s.png" % (LEFT, RIGHT))


def describe(tag):
    m = re.match(r"rr2s?_(prev|cur)_([A-Za-z]+)", tag)
    if not m:
        return tag
    sdk = "310.7.0" if m.group(1) == "prev" else "310.9.1"
    rr2 = m.group(2) == "F" or (m.group(2) == "Default" and sdk == "310.9.1")
    return "DLSS %s, preset %s%s" % (sdk, m.group(2), " (RR2)" if rr2 else "")
W, H = 560, 420
# (absolute frame index, x0, y0, what)
CROPS = [(105, 930, 260, "plume interior, orbit frame 75"),
         (255, 720, 520, "plume silhouette, orbit frame 225"),
         (180, 380, 440, "surfaces: cobbles and cafe, orbit frame 150")]


def frame(d, idx):
    return cv2.imread(os.path.join(HERE, d, "%s.TAA_LDR.colorOut.%d.png" % (d, idx)))[..., :3]


def strip(text, width):
    s = np.zeros((28, width, 3), np.uint8)
    cv2.putText(s, text, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    return s


rows = [np.hstack([strip(describe(LEFT), W), strip(describe(RIGHT), W), strip("|difference| x4", W)])]
for idx, x0, y0, what in CROPS:
    a = frame(LEFT, idx)[y0:y0 + H, x0:x0 + W]
    b = frame(RIGHT, idx)[y0:y0 + H, x0:x0 + W]
    d = np.clip(np.abs(a.astype(np.int16) - b.astype(np.int16)) * 4, 0, 255).astype(np.uint8)
    rows.append(strip(what, 3 * W))
    rows.append(np.hstack([a, b, d]))
cv2.imwrite(OUT, np.vstack(rows))
print("wrote", OUT)
