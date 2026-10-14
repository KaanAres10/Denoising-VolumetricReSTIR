"""Contact sheet and looping animation of a teapot shot's frames (previews/anim_<set>/f<frame>/<label>, rendered for the
user to choose a frame from, 2026-10-14), each through Blender's Standard view as the RenderMan target was shown, the
sheet led by the user's reference picture:

    python anim_sheet.py <set> [<out stem>]     ->  <out stem>_sheet.png, <out stem>.gif (default figs/anim_<set>)
"""
import glob
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import match_teapot as mt  # noqa: E402
import preview_shots as ps  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REFERENCE = os.path.join(HERE, "..", "..", "VolumetricReSTIRData", "swatch", "reference_teapot_fire.png")


def frames(name):
    """(frame number, scene-linear image) for every rendered frame of the set, in order."""
    out = []
    for d in sorted(glob.glob(os.path.join(HERE, "previews", "anim_" + name, "f*"))):
        labels = [p for p in glob.glob(os.path.join(d, "*")) if os.path.isdir(p)]
        img = ps.frame(labels[0]) if labels else None
        if img is not None:
            out.append((int(os.path.basename(d)[1:]), img))
    return out


def labelled(bgr, text, size):
    t = cv2.resize(bgr, (size, size), interpolation=cv2.INTER_AREA)
    cv2.putText(t, text, (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 4)
    cv2.putText(t, text, (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    return t


def display(img):
    return (mt.standard_view(img)[..., ::-1] * 255).astype(np.uint8)


def sheet(name, tiles, size=256, cols=7):
    ref = cv2.imread(REFERENCE)
    cells = [labelled(cv2.resize(ref[10:625, 5:620], (512, 512), interpolation=cv2.INTER_AREA), "reference", size)]
    cells += [labelled(display(img), "frame %d" % f, size) for f, img in tiles]
    while len(cells) % cols:
        cells.append(np.zeros_like(cells[0]))
    rows = [np.concatenate(cells[i:i + cols], 1) for i in range(0, len(cells), cols)]
    return np.concatenate(rows, 0)


def gif(tiles, path, size=384, ms=300):
    from PIL import Image
    images = [Image.fromarray(labelled(display(img), "frame %d" % f, size)[..., ::-1]) for f, img in tiles]
    images[0].save(path, save_all=True, append_images=images[1:], duration=ms, loop=0)


def main(argv):
    name = argv[1]
    stem = argv[2] if len(argv) > 2 else os.path.join(HERE, "figs", "anim_" + name)
    tiles = frames(name)
    if not tiles:
        print("no frames rendered for", name)
        return 1
    cv2.imwrite(stem + "_sheet.png", sheet(name, tiles))
    gif(tiles, stem + ".gif")
    print("%s: %d frames -> %s_sheet.png, %s.gif" % (name, len(tiles), stem, stem))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
