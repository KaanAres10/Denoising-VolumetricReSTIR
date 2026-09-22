# Side-by-side orbit videos: previous Ray Reconstruction (310.7.0, preset E) | RR2 (310.9.1, preset F),
# or any two captures given as arguments (then named video/<left>_vs_<right>*.mp4). Captures of the
# live windows (record_look.py, 960x540) are put side by side 1:1, with no crop video.
#
#   video/rr_vs_rr2.mp4        1920x540, both frames at half resolution -- same shape as compare.mp4
#   video/rr_vs_rr2_plume.mp4  1920x1080, the centre 960x1080 of each frame at NATIVE resolution. The
#                              orbit's centre is the camera target, so this is the plume and the wall
#                              behind it. Half resolution averages away the per-pixel crawl that
#                              separates two strong denoisers, which is the thing being judged here.
#
# Frames are read in numeric order (.30.png ... .329.png) -- a glob order runs 100..329 first. crf 16
# for the reason encode.py gives: a thriftier encode smooths the temporal artifacts under comparison.
import os, re, subprocess, sys

import cv2, numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FPS = 30
# Default: the captures taken with DLSSDGuides' sky fix, i.e. the current pipeline. Any two capture
# folders work -- e.g. `python video_rr2.py rr2s_prev_D rr2s_prev_E` -- and are labelled from their
# names (capture_orbit.py tags: rr2s_<prev|cur>_<preset>).
LEFT = sys.argv[1] if len(sys.argv) > 1 else "rr2s_prev_E"
RIGHT = sys.argv[2] if len(sys.argv) > 2 else "rr2s_cur_F"


def describe(tag):
    # Any tag ending in <prev|cur>_<preset>: rr2s_prev_E (orbit), look_cur_F (record_look.py), ...
    m = re.search(r"(prev|cur)_([A-Za-z]+)$", tag)
    if not m:
        return tag
    sdk = "310.7.0" if m.group(1) == "prev" else "310.9.1"
    rr2 = m.group(2) == "F" or (m.group(2) == "Default" and sdk == "310.9.1")
    return "DLSS %s, preset %s%s" % (sdk, m.group(2), "  (RR2)" if rr2 else "")


# VIDEO_LABELS="left|right" overrides the names, e.g. for a before/after of one configuration.
LABELS = tuple(os.environ["VIDEO_LABELS"].split("|", 1)) if "|" in os.environ.get("VIDEO_LABELS", "") \
    else (describe(LEFT), describe(RIGHT))
DEFAULT_PAIR = (LEFT, RIGHT) == ("rr2s_prev_E", "rr2s_cur_F")


def frames(d):
    fs = [f for f in os.listdir(os.path.join(HERE, d)) if f.endswith(".png")]
    fs.sort(key=lambda f: int(re.search(r"\.(\d+)\.png$", f).group(1)))
    return [os.path.join(HERE, d, f) for f in fs]


def label(im, text):
    cv2.rectangle(im, (0, 0), (min(im.shape[1], 12 + 11 * len(text)), 30), (0, 0, 0), -1)
    cv2.putText(im, text, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    return im


def encode(name, make):
    a, b = frames(LEFT), frames(RIGHT)
    n = min(len(a), len(b))
    first = make(cv2.imread(a[0])[..., :3], cv2.imread(b[0])[..., :3])
    h, w = first.shape[:2]
    out = os.path.join(HERE, "video", name)
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                          "-s", "%dx%d" % (w, h), "-r", str(FPS), "-i", "-",
                          "-c:v", "libx264", "-crf", "16", "-preset", "slow", "-pix_fmt", "yuv420p", out],
                         stdin=subprocess.PIPE)
    for i in range(n):
        p.stdin.write(make(cv2.imread(a[i])[..., :3], cv2.imread(b[i])[..., :3]).tobytes())
    p.stdin.close()
    p.wait()
    print("%s  %d frames %dx%d  %.1f MB" % (out, n, w, h, os.path.getsize(out) / 1e6))


def half(x, y):
    s = [cv2.resize(im, (960, 540), interpolation=cv2.INTER_AREA) for im in (x, y)]
    return np.hstack([label(s[0], LABELS[0]), label(s[1], LABELS[1])])


def plume(x, y):
    c = [np.ascontiguousarray(im[:, 480:1440]) for im in (x, y)]
    return np.hstack([label(c[0], LABELS[0]), label(c[1], LABELS[1])])


stem = "rr_vs_rr2" if DEFAULT_PAIR else "%s_vs_%s" % (LEFT, RIGHT)
_w = cv2.imread(frames(LEFT)[0]).shape[1]
if _w <= 960:
    # Already window-sized (record_look.py at 960x540): side by side 1:1 -- half() leaves a 960x540
    # frame untouched -- and no crop, which is only meaningful on a 1080p frame.
    encode(stem + ".mp4", half)
else:
    encode(stem + ".mp4", half)
    encode(stem + "_plume.mp4", plume)
