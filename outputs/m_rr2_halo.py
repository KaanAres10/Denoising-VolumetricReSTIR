# The halo around the smoke in motion, measured without a path-traced reference.
#
# In a stop-and-go recording (Scripts/record_look.py, VR_RECORD_STOPS=3) the frame where the camera
# ARRIVES at a stop and the frame 5 s later are rendered from the identical camera pose; the only
# difference is the temporal history that motion left behind -- which is exactly the halo (smoke
# history dragged over the background, smeared edges). Settled is the same image with that history
# gone, so |arrival - settled| isolates the artifact. The noise floor is two consecutive settled frames.
#
# Usage: python m_rr2_halo.py <capture dir> [...]
import glob, os, re, sys
import cv2, numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FRAMES, STOPS, STOP_FRAMES = 300, 3, 150   # record_look.py defaults with VR_RECORD_STOPS=3
bounds = {int(round(j * FRAMES / (STOPS + 1))) for j in range(1, STOPS + 1)}
schedule = []
for i in range(FRAMES):
    schedule.append(i)
    if i + 1 in bounds:
        schedule += [i] * STOP_FRAMES
# Arrival = the moving frame that first reaches the stop's pose; settled = the last frame of the stop.
arrivals = [k for k in range(1, len(schedule)) if schedule[k] != schedule[k - 1] and k + 1 < len(schedule) and schedule[k + 1] == schedule[k]]


def frame_paths(d):
    fs = glob.glob(os.path.join(HERE, d, "*.png"))
    return sorted(fs, key=lambda f: int(re.search(r"\.(\d+)\.png$", f).group(1)))


print("%-16s %s" % ("capture", "per stop: mean |arrival - settled| /255, % px > 8/255   (noise floor: settled vs settled-1)"))
for d in sys.argv[1:]:
    fs = frame_paths(d)
    assert len(fs) == len(schedule), (d, len(fs), len(schedule))
    cells, floor = [], []
    for a in arrivals:
        s = a + STOP_FRAMES
        A, Sx, S1 = (cv2.imread(fs[k]).astype(np.float32) for k in (a, s, s - 1))
        d_ = np.abs(A - Sx).max(axis=2)
        cells.append("%.2f (%.1f%%)" % (np.abs(A - Sx).mean(), 100 * (d_ > 8).mean()))
        floor.append(np.abs(Sx - S1).mean())
    print("%-16s %s   floor %.3f" % (d, "  ".join(cells), float(np.mean(floor))))
