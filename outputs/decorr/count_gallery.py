"""Speed-up C on one page (user, 2026-10-07: "try C"): per scene setup, the zoom box of plain ReSTIR and of 1, 3 and 5
mutations (the pass's defaults: coherent moves, early rejection), all through OptiX at M cap 200 (V-C2's chains and
kept frames), and the reference, each with its in-medium relMSE (this frame) and the run's whole-pass time per frame.
The box goes where plain ReSTIR's error is largest (paper_figure.py).

    python count_gallery.py <root>        (root: outputs/decorr; writes figs/count_gallery.png)
"""
import json
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import artifacts as art
import paper_figure
import stages_figure as sf
import variety_figures as vf

CONFIGS = (("den_optix_mut0cap200", "plain ReSTIR", 0), ("den_optix_mut1cohcap200", "1 mutation", 1),
           ("den_optix_mut3cohcap200", "3 mutations", 3), ("den_optix_mut5cohcap200", "5 mutations", 5))
LANE = "/onFrameRender/RenderGraphExe::execute()/VolumetricReSTIR/gpu_time"


def frame_ms(root, label, n):
    """Whole-pass ms per frame: run_fewer_mutations.sh's timing runs (the mean of a and b); plain from run_cost.sh."""
    if n == 0:
        runs = [os.path.join(root, "cost", label, "mut0")]
    else:
        runs = [os.path.join(root, "fewer_cost", label, "mut%d%s" % (n, v)) for v in "ab"]
    t = [json.load(open(os.path.join(r, "c.passes.json")))[LANE]["median"] for r in runs
         if os.path.exists(os.path.join(r, "c.passes.json"))]
    return float(np.mean(t)) if t else float("nan")


def main(argv):
    root = argv[1]
    labels = sf.LABELS
    cols = len(CONFIGS) + 1
    fig, axes = plt.subplots(len(labels), cols, figsize=(3.3 * cols, 3.5 * len(labels)), facecolor="white")
    fig.subplots_adjust(top=0.95, bottom=0.005, left=0.07, right=0.995, hspace=0.32, wspace=0.04)
    fig.suptitle("How many mutations: plain ReSTIR, 1, 3 and 5 mutations through OptiX, M cap 200\n"
                 "(zoomed where plain ReSTIR's error is largest; relMSE in the medium, this frame; whole ReSTIR pass ms "
                 "per frame at 1080p)", fontsize=14)
    for i, label in enumerate(labels):
        p = paper_figure.prepare(root, label, CONFIGS[0][0], CONFIGS[3][0], vf.EXPOSURE.get(label, 99.0),
                                 label in vf.PAPER_DISPLAY)
        (y, x), size = p.boxes[0], p.size
        imgs = [art.kept(os.path.join(root, label, c))[0][p.crop] for c, _, _ in CONFIGS] + [p.ref]
        notes = ["%s\n%.4f, %.0f ms" % (name, p.relmse(img), frame_ms(root, label, n))
                 for (c, name, n), img in zip(CONFIGS, imgs)] + ["reference\n"]
        for j, (img, note) in enumerate(zip(imgs, notes)):
            ax = axes[i, j]
            ax.imshow(p.show(img[y:y + size, x:x + size]), interpolation="nearest")
            ax.set_title(note, fontsize=10)
            ax.set_xticks([])
            ax.set_yticks([])
        axes[i, 0].set_ylabel(label.replace("_b2", "\n2 bounces").replace("_", " "), fontsize=11)
    out = os.path.join(root, "figs", "count_gallery.png")
    fig.savefig(out, dpi=72)
    plt.close(fig)
    print(out)


if __name__ == "__main__":
    main(sys.argv)
