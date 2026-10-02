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

PAIR = ("den_optix_mut0cap200", "den_optix_mut5cap200")
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
    "plume_g-0.9": "Smoke under a sky, strong back scattering",
    "explosion": "Explosion: self-emitting fire, colour set by depth",
    "bunnystripes": "Light through slats: sharp shadow stripes in a cloud",
    "bunnyback_g0.8": "Cloud backlit by one light: the silver-lining rim",
}


def scored(root, label, cfg):
    return os.path.exists(os.path.join(root, label, cfg, "c.corr.json"))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    for label, title in TITLES.items():
        if not all(scored(a.root, label, c) for c in PAIR):
            continue
        out = os.path.join(a.root, "figs", "variety_%s.png" % label)
        rel = [json.load(open(os.path.join(a.root, label, c, "c.corr.json"))).get("reference", {}).get("relmse") for c in PAIR]
        if a.force or not os.path.exists(out):
            paper_figure.main([a.root, label, PAIR[0], PAIR[1], "--errors", "--out", out,
                               "--names", "ReSTIR + OptiX denoiser,ReSTIR + 5 mutations + OptiX denoiser",
                               "--title", "%s (M cap 200, one frame, same denoiser)" % title])
        if None not in rel:
            print("%-22s relMSE %.4f -> %.4f (%+.0f%%)" % (label, rel[0], rel[1], 100 * (rel[1] / rel[0] - 1)))


if __name__ == "__main__":
    main()
