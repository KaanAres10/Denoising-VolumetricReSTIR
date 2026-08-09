# Build videos of bistro's authored orbit, matching the published artifact's path exactly:
# centre (-11.0, 6.025879, 0.0), radius 9.37, -180 degrees over 300 frames, 90 consecutive frames
# captured after a 40-frame warm-up so history has settled.
#
# Two things matter for the thing being judged:
#  * Frame filenames are NOT zero-padded, so a glob sorts 100 before 40. Order numerically.
#  * The subject is FLICKER, and video compression is very good at hiding exactly that. crf 14 with
#    a small GOP, so what you see is the renderer's temporal behaviour and not the encoder's.
import os, re, subprocess, sys
import cv2, numpy as np

SP = os.path.dirname(os.path.abspath(__file__))
FPS = 20
CFG = [("vid_relax", "RELAX-SH"), ("vid_reblur", "REBLUR-SH"), ("vid_rr", "DLSS Ray Reconstruction")]

def frames(d):
    fs = [f for f in os.listdir(os.path.join(SP, d)) if f.endswith(".png")]
    fs.sort(key=lambda f: int(re.search(r"\.(\d+)\.png$", f).group(1)))
    return [os.path.join(SP, d, f) for f in fs]

def encode(pattern_dir, out, vf=None):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
           "-i", os.path.join(pattern_dir, "%04d.png"),
           "-c:v", "libx264", "-crf", "14", "-g", "10", "-pix_fmt", "yuv420p"]
    if vf:
        cmd += ["-vf", vf]
    cmd += [out]
    subprocess.run(cmd, check=True)

# Renumber into a temp dir so ffmpeg's sequential reader gets the right order.
for d, label in CFG:
    fs = frames(d)
    tmp = os.path.join(SP, d + "_seq")
    os.makedirs(tmp, exist_ok=True)
    for i, f in enumerate(fs):
        img = cv2.imread(f, cv2.IMREAD_UNCHANGED)
        cv2.imwrite(os.path.join(tmp, "%04d.png" % i), img)
    out = os.path.join(SP, "orbit_%s.mp4" % d.replace("vid_", ""))
    encode(tmp, out)
    print("%-26s %2d frames -> %s" % (label, len(fs), os.path.basename(out)))

# Three-up comparison, same frame index in every panel so the columns stay in sync.
seqs = [frames(d) for d, _ in CFG]
n = min(len(s) for s in seqs)
tmp = os.path.join(SP, "cmp_seq")
os.makedirs(tmp, exist_ok=True)
for i in range(n):
    panels = []
    for (d, label), s in zip(CFG, seqs):
        im = cv2.resize(cv2.imread(s[i], cv2.IMREAD_UNCHANGED)[..., :3], (640, 360))
        cv2.rectangle(im, (0, 0), (640, 26), (0, 0, 0), -1)
        cv2.putText(im, label, (8, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1, cv2.LINE_AA)
        panels.append(im)
    row = np.hstack(panels)
    cv2.rectangle(row, (0, 360 - 22), (row.shape[1], 360), (0, 0, 0), -1)
    cv2.putText(row, "bistro / authored 180 deg orbit r=9.37 / frame %2d of %d" % (i + 1, n),
                (8, 360 - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1, cv2.LINE_AA)
    cv2.imwrite(os.path.join(tmp, "%04d.png" % i), row)
out = os.path.join(SP, "orbit_compare.mp4")
encode(tmp, out)
print("three-up comparison         %2d frames -> %s" % (n, os.path.basename(out)))
