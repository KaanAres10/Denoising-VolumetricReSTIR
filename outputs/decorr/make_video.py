"""Side-by-side video of consecutive denoised frames (run_apparent.sh's spacing-1 chains): plain ReSTIR next to the same ReSTIR
with mutations, same exposure, cropped to the lit part of the frame. Reuse's blotches crawl and boil from frame to
frame; with mutations what is left is fine noise the denoiser removes.

    python make_video.py <root> <label> [--configs restir,mut5,mut16] [--fps 12] [--out stem]

Writes <stem>.mp4 and a half-size <stem>.gif.
"""
import argparse
import glob
import json
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import artifacts as art
import m_corr as mc
from paper_figure import lit_region

NAMES = {"restir": "ReSTIR + denoiser", "mut5": "+ 5 mutations", "mut16": "+ 16 mutations"}


def burst_frames(d):
    s = json.load(open(os.path.join(d, "c.schedule.json")))
    out = []
    run = s["burst"] or s["chains"][0]  # consecutive frames: a burst, or one chain captured at spacing 1
    for f in run["frames"]:
        p = os.path.join(d, "c.%s.%d.exr" % (s["channel"], f))
        if os.path.exists(p):
            out.append(np.nan_to_num(mc.read_exr(p)[..., :3][..., ::-1].astype(np.float64), posinf=0.0))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("label")
    ap.add_argument("--configs", default="restir,mut5,mut16")
    ap.add_argument("--fps", type=int, default=12)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    cfgs = [c for c in a.configs.split(",") if os.path.isdir(os.path.join(a.root, "video", a.label, c))]
    clips = [burst_frames(os.path.join(a.root, "video", a.label, c)) for c in cfgs]
    n = min(len(c) for c in clips)
    h, w = clips[0][0].shape[:2]
    ref = art.reference(a.root, a.label)
    ref = cv2.resize(ref.astype(np.float32), (w, h), interpolation=cv2.INTER_AREA).astype(np.float64) if ref is not None \
        else np.mean(clips[0], axis=0)
    y0, y1, x0, x1 = lit_region(ref)
    k = np.percentile(ref @ mc.Y_RGB, 99) + 1e-9
    stem = a.out or os.path.join(a.root, "figs", "video_%s" % a.label)
    frames = []
    for t in range(n):
        tiles = []
        for c, clip in zip(cfgs, clips):
            img = (255 * art.tonemap(clip[t][y0:y1, x0:x1], k)).astype(np.uint8)[..., ::-1].copy()
            cv2.putText(img, NAMES.get(c, c), (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
            tiles.append(img)
        sep = np.full((tiles[0].shape[0], 4, 3), 255, np.uint8)
        row = tiles[0]
        for tile in tiles[1:]:
            row = np.hstack([row, sep, tile])
        cv2.putText(row, "frame %d" % t, (10, row.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)
        frames.append(row)
    H, W = frames[0].shape[:2]
    vw = cv2.VideoWriter(stem + ".mp4", cv2.VideoWriter_fourcc(*"mp4v"), a.fps, (W - W % 2, H - H % 2))
    for f in frames:
        vw.write(f[:H - H % 2, :W - W % 2])
    vw.release()
    try:
        from PIL import Image
        imgs = [Image.fromarray(cv2.cvtColor(cv2.resize(f, (W // 2, H // 2), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB))
                for f in frames]
        imgs[0].save(stem + ".gif", save_all=True, append_images=imgs[1:], duration=int(1000 / a.fps), loop=0)
    except ImportError:
        pass
    print(stem + ".mp4", "%d frames, %dx%d" % (n, W, H))


if __name__ == "__main__":
    main()
