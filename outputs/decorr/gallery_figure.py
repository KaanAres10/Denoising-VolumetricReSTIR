"""One sheet of every variety scene (variety_figures.py): per row the effect, then the zoom box where plain ReSTIR's
error is largest -- plain ReSTIR + OptiX | ReSTIR + 5 mutations + OptiX | path-traced reference -- and the in-medium
relMSE before and after. M cap 200, no decoupled history, same denoiser.

    python gallery_figure.py <root> [--out F] [--scenes a,b,..]
"""
import argparse
import os
import textwrap
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import artifacts as art
import paper_figure
from variety_figures import DENOISERS, EXPOSURE, PAPER_DISPLAY, TITLES, pair, scored

# Strongest first; the night street (emissive lamps, -14%) and the sky-lit plume (a transient burst in its kept
# frame) are left out, see variety_figures.py and the spec. Stripes carry a caveat (patches next to the slats).
ORDER = ["bunnycathedral_d0.3", "bunnyspot", "bunnysoftbox", "bunnyinside", "bunnyback_g0.8", "bunnystripes",
         "explosion", "bunnylanterns", "wdassunset_g0.85", "plumeback_g0.9", "plumeconcert_g0.6"]
NOTES = {"bunnystripes": " *"}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--out")
    ap.add_argument("--scenes", default=",".join(ORDER))
    ap.add_argument("--denoiser", default="optix", choices=sorted(DENOISERS))
    a = ap.parse_args(argv)
    PAIR, den = pair(a.denoiser), DENOISERS[a.denoiser]
    notes = NOTES if a.denoiser == "optix" else {}  # the slats caveat was seen through OptiX
    labels = [l for l in a.scenes.split(",") if all(scored(a.root, l, c) for c in PAIR)]
    fig, ax = plt.subplots(len(labels), 4, figsize=(15, 3.6 * len(labels)), squeeze=False,
                           gridspec_kw={"width_ratios": [1.25, 1, 1, 1], "wspace": 0.04, "hspace": 0.08})
    for i, label in enumerate(labels):
        p = paper_figure.prepare(a.root, label, PAIR[0], PAIR[1], EXPOSURE.get(label, 99.0), label in PAPER_DISPLAY)
        r0, r1 = (p.relmse(img) for img in p.imgs)
        y, x = p.boxes[0]
        name = "\n".join(textwrap.wrap(TITLES[label] + notes.get(label, ""), 30))
        ax[i][0].text(0.02, 0.5, "%s\n\nerror in the medium\n%.4f -> %.4f  (%+.0f%%)" % (name, r0, r1, 100 * (r1 / r0 - 1)),
                      ha="left", va="center", fontsize=11.5, transform=ax[i][0].transAxes)
        for j, img in enumerate(p.imgs + [p.ref]):
            ax[i][j + 1].imshow(p.show(img[y:y + p.size, x:x + p.size]), interpolation="nearest")
            if i == 0:
                ax[i][j + 1].set_title(["ReSTIR + %s" % den.replace(" denoiser", ""), "+ 5 mutations, same denoiser",
                                        "path-traced reference"][j], fontsize=13)
        for x_ in ax[i]:
            x_.set_xticks([])
            x_.set_yticks([])
        for s in ax[i][0].spines.values():
            s.set_visible(False)
    fig.suptitle("Where Metropolis-Hastings mutations remove volumetric ReSTIR's artifacts (M cap 200, one frame, %s,\n"
                 "zoom where plain ReSTIR's error is largest; mutations alone, no decoupled history)" % den,
                 fontsize=14, y=0.997)
    fig.subplots_adjust(top=0.975, bottom=0.01)
    if any(l in notes for l in labels):
        fig.text(0.01, 0.002, "* next to the slats the mutated run shows a few larger patches (see its full figure).",
                 fontsize=10)
    out = a.out or os.path.join(a.root, "figs", "gallery_mutations%s.png" % ("" if a.denoiser == "optix" else "_" + a.denoiser))
    fig.savefig(out, dpi=80, bbox_inches="tight")
    print(out)


if __name__ == "__main__":
    main()
