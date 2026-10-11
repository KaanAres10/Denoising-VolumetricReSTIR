"""Contact sheet of path-traced previews (run_study.sh refs into a scratch STUDY_OUT), for judging a new shot's look:

    python preview_shots.py <out.png> <label dir>...     (a label dir holds ref/; titled by its last two parts)

Each frame tone-mapped with film_figures.display, exposed at its lit pixels' median brightness.
"""
import glob
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import artifacts as art  # noqa: E402
import film_figures as ff  # noqa: E402


def frame(d):
    refs = sorted(glob.glob(os.path.join(d, "ref", "c.Accum.output.*.exr")), key=lambda p: int(p.split(".")[-2]))
    return art.reference(None, None, override=refs[-1]) if refs else None


def tile(img, label, width=640):
    v = img.max(-1)
    lit = v > 1e-3 * np.percentile(v, 99.9)
    out = ff.display(img, ff.exposure(v, lit))
    out = cv2.resize((out[..., ::-1] * 255).astype(np.uint8), (width, int(width * img.shape[0] / img.shape[1])),
                     interpolation=cv2.INTER_AREA)
    cv2.putText(out, label, (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4)
    cv2.putText(out, label, (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return out


def main(argv):
    out, dirs = argv[1], argv[2:]
    title = lambda d: "/".join(os.path.normpath(d).replace("\\", "/").split("/")[-2:])  # noqa: E731
    tiles = [tile(f, title(d)) for d in dirs for f in [frame(d)] if f is not None]
    if len(tiles) % 2:
        tiles.append(np.zeros_like(tiles[0]))
    cv2.imwrite(out, np.concatenate([np.concatenate(tiles[i:i + 2], 1) for i in range(0, len(tiles), 2)], 0))
    print(out, len(tiles))


if __name__ == "__main__":
    main(sys.argv)
