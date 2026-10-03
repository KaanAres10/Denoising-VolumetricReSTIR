"""paper_figure.py for every scene whose denoised M cap 200 pair (run_variety.sh / run_showcase.sh) is scored: plain
ReSTIR vs ReSTIR + 5 mutations through OptiX, zoom boxes, error row. One figure per effect, titled by it.

    python variety_figures.py <root> [--force]

Writes figs/variety_<label>.png (skips existing ones unless --force) and prints each scene's relMSE before/after.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paper_figure

DENOISERS = {"optix": "OptiX denoiser", "rr": "DLSS Ray Reconstruction"}


def pair(denoiser="optix"):
    """The configs compared: plain ReSTIR and ReSTIR + 5 mutations, M cap 200, through `denoiser`."""
    return ("den_%s_mut0cap200" % denoiser, "den_%s_mut5cap200" % denoiser)


PAIR = pair()
# Shown as the paper shows it (exposure 1, sRGB, clamped) -- the scene was matched to the paper's figure that way.
PAPER_DISPLAY = {"explosiondusk", "explosiondusk_b2"}
# Scenes whose lit part is a small bright patch of the medium: a higher exposure percentile keeps its texture.
EXPOSURE = {"bunnyspot": 99.9, "bunnyinside": 99.9, "plumeback_g0.9": 99.8, "bunnystripes": 99.8, "explosion": 99.95}
TITLES = {
    "wdassunset_g0.85": "Disney cloud at sunset, backlit: sun vs sky colour",
    "plumeconcert_g0.6": "Concert: six coloured beams crossing in stage smoke",
    "bunnycathedral_d0.3": "Cathedral: god rays through four windows into dust",
    "bunnylanterns": "48 coloured lanterns inside a cloud: each pixel takes one lantern's colour",
    "bunnysoftbox": "Warm and cool panel lights beside a cloud",
    "emeraldnight_d3": "City street at night in thick fog, lit by street lamps",
    "bunnyspot": "A spotlight beam through a cloud",
    "bunnyinside": "A lamp inside the cloud (near-field light)",
    "plumeback_g0.9": "Smoke backlit by one light, strong forward scattering",
    # (plume_g-0.9: left out -- its kept frame catches a transient burst at a thin edge in the mutated run; over
    #  100 frames relMSE 0.0082 -> 0.0076, no bias; kept as figs/caveat_plume_g-0.9_single_frame_burst.png)
    # "plume_g-0.9": "Smoke under a sky, strong back scattering",
    "explosion": "Explosion: self-emitting fire, colour set by depth",
    "explosiondusk": "Explosion as in the paper: fire in dark smoke under a dusk sky",
    # Two bounces (docs/superpowers/specs/2026-10-03-two-bounce-mutations-design.md): 5 moves of every kind.
    "explosiondusk_b2": "Explosion as in the paper, 2 bounces: the fire lights the smoke",
    "bunnycathedral_d0.3_b2": "Cathedral god rays, 2 bounces: light scattered off the beams fills the room",
    "bunnyback_g0.8_b2": "Cloud backlit by one light, 2 bounces: the rim and the light inside it",
    "bunnysoftbox_b2": "Warm and cool panel lights beside a cloud, 2 bounces",
    "wdassunset_g0.85_b2": "Disney cloud at sunset, 2 bounces",
    "bunnystripes": "Light through slats: sharp shadow stripes in a cloud",
    "bunnyback_g0.8": "Cloud backlit by one light: the silver-lining rim",
}


def scored(root, label, cfg):
    return os.path.exists(os.path.join(root, label, cfg, "c.corr.json"))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--denoiser", default="optix", choices=sorted(DENOISERS))
    a = ap.parse_args(argv)
    configs, den = pair(a.denoiser), DENOISERS[a.denoiser]
    for label, title in TITLES.items():
        if not all(scored(a.root, label, c) for c in configs):
            continue
        out = os.path.join(a.root, "figs", "variety_%s%s.png" % ("" if a.denoiser == "optix" else a.denoiser + "_", label))
        if a.force or not os.path.exists(out):
            rel = paper_figure.main([a.root, label, configs[0], configs[1], "--errors", "--out", out,
                                     "--names", "ReSTIR + %s,ReSTIR + 5 mutations + %s" % (den, den),
                                     "--title", "%s (M cap 200, one frame, both through %s)" % (title, den),
                                     "--exposure-pct", str(EXPOSURE.get(label, 99.0))]
                                    + (["--paper-display"] if label in PAPER_DISPLAY else []))
            print("%-22s relMSE in the medium %.4f -> %.4f (%+.0f%%)" % (label, rel[0], rel[1], 100 * (rel[1] / rel[0] - 1)))


if __name__ == "__main__":
    main()
