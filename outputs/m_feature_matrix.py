# Feature coverage, Falcor 8.0 vs 9.0: every scene/switch the VS Code tasks use beyond the bistro table.
# Reads outputs/fm_<v8|v9>_<case> (written by the feature-matrix batch: 20 frames after 10 warm-up).
#
# Per case: frames written, error lines, mean level of the last 5 frames (9.0 vs 8.0), and log
# warnings that appear on 9.0 but not 8.0 (normalised: numbers and paths stripped, so a warning that
# merely moved is not "new"). Writes fm_sheet.png: last frame of each case, 8.0 left, 9.0 right.
import glob
import os
import re

import cv2
import numpy as np

CASES = ["b_oidncpu", "b_sr", "b_sr_legacycnn", "b_rr_layers", "b_rr_prev310", "b_rr_presetF",
         "p_none", "p_optix", "p_oidn", "p_relax", "p_reblur", "p_rr", "pa_none", "pa_rr", "e_none", "e_optix"]


def frames(d):
    got = []
    for f in glob.glob(d + "/*.png"):
        m = re.search(r"\.(\d+)\.png$", os.path.basename(f))
        if m:
            got.append((int(m.group(1)), f))
    return [f for _, f in sorted(got)]


def level(fs):
    return float(np.mean([cv2.imread(f)[..., :3].astype(np.float32).mean() for f in fs[-5:]])) if fs else float("nan")


def log_lines(d, kind):
    p = os.path.join(d, "run.log")
    if not os.path.exists(p):
        return set()
    out = set()
    for l in open(p, encoding="utf-8", errors="replace"):
        if kind in l:
            n = re.sub(r"[A-Za-z]:[\\/][^\s:]*", "<path>", l.strip())   # paths differ between the two bins
            n = re.sub(r"\d+(\.\d+)?", "#", n)
            out.add(n[:150])
    return out


tiles = []
print("%-16s %8s %8s %8s %9s %9s %9s  %s" % ("case", "frames8", "frames9", "err8/9", "level8", "level9", "change", "warnings new in 9.0"))
for c in CASES:
    a, b = "fm_v8_" + c, "fm_v9_" + c
    fa, fb = frames(a), frames(b)
    e8, e9 = len(log_lines(a, "(Error)")), len(log_lines(b, "(Error)"))
    la, lb = level(fa), level(fb)
    neww = sorted(log_lines(b, "(Warning)") - log_lines(a, "(Warning)"))
    print("%-16s %8d %8d %5d/%-3d %9.2f %9.2f %+8.2f%%  %d" % (c, len(fa), len(fb), e8, e9, la, lb,
          100 * (lb / la - 1) if la == la and la > 0 else float("nan"), len(neww)))
    for w in neww[:3]:
        print("%18s- %s" % ("", w))
    row = []
    for fs, tag in ((fa, "8.0"), (fb, "9.0")):
        im = cv2.resize(cv2.imread(fs[-1]), (384, 216)) if fs else np.zeros((216, 384, 3), np.uint8)
        cv2.putText(im, "%s %s" % (c, tag), (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
        row.append(im)
    tiles.append(np.hstack(row))
pairs = [np.hstack(tiles[i:i + 2]) if i + 1 < len(tiles) else np.hstack([tiles[i], np.zeros_like(tiles[i])])
         for i in range(0, len(tiles), 2)]
cv2.imwrite("fm_sheet.png", np.vstack(pairs))
print("\ncontact sheet -> outputs/fm_sheet.png (each pair: 8.0 left, 9.0 right)")
