"""Do mutations break up the copies among paths whose first vertex is a SURFACE? On a run pair's raw captures
(run_study.sh's sampleIdentity output, kept captures of every chain), the share of surface samples that hold exactly
the same sample as a neighbour (9x9 window), split by what the sample connects to: the env map (lightID -1, the
light move reaches these) and everything else but self-emission without a bounce (lightID -3: no random state, so
every such pixel hashes alike, a "copy" by construction, and no bounce move applies) -- on the night shots (no soft
boxes, no point lights) the paths that bounce off the surface into the glowing smoke (path tag 1, whose lightID
holds the glowing point's position).

Passes when the mutated run's copies among those glow paths are below `--ratio` of the plain run's.

    python surface_moves_check.py <root> <label> <plain config> <mutated config> [--ratio 0.5]
"""
import argparse
import json
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m_corr as mc  # noqa: E402

AT_SURFACE = 256  # FinalShading.cs.slang's sampleIdentity: .y = (hash >> 24) | 256 for a surface sample
SELF_EMISSION = -3  # HostDeviceSharedConstants.slang kSelfEmissionLightID


def identities(run_dir):
    """Each kept capture's sample identity: (key, at a surface, lightID) per pixel."""
    s = json.load(open(os.path.join(run_dir, "c.schedule.json")))
    out = []
    for c in s["chains"]:
        p = os.path.join(run_dir, "c.VolumetricReSTIR.sampleIdentity.%d.exr" % c["frames"][0])
        if not os.path.exists(p):
            continue
        sid = mc.read_exr(p)[..., ::-1]  # BGR(A) on disk -> R = hash & 0xFFFFFF, G = (hash >> 24) | surface, B = lightID + 4
        g = sid[..., 1].astype(np.int64)
        key = sid[..., 0].astype(np.int64) * 1024 + g
        out.append((key, (g & AT_SURFACE) > 0, np.round(sid[..., 2]).astype(np.int64) - 4))
    if not out:
        raise SystemExit("FAILED: %s has no sampleIdentity captures" % run_dir)
    return out


def copies(key, r=4):
    """Pixels whose sample is also some other pixel's within a (2r+1)^2 window."""
    dup = np.zeros(key.shape, bool)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dy or dx:
                dup |= np.roll(np.roll(key, dy, 0), dx, 1) == key
    return dup & (key != 0)


def shares(run_dir):
    sky, glow = [], []
    for key, surf, lid in identities(run_dir):
        d = copies(key)
        sky.append(d[surf & (lid == -1)].mean())
        glow.append(d[surf & (lid != -1) & (lid != SELF_EMISSION) & (key != 0)].mean())
    return float(np.mean(sky)), float(np.mean(glow))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("label")
    ap.add_argument("plain")
    ap.add_argument("mutated")
    ap.add_argument("--ratio", type=float, default=0.5)
    a = ap.parse_args(argv)
    (s0, g0), (s1, g1) = (shares(os.path.join(a.root, a.label, c)) for c in (a.plain, a.mutated))
    print("surface samples copied from a neighbour: to the sky %.1f%% -> %.1f%%, into the glow %.1f%% -> %.1f%%"
          % (100 * s0, 100 * s1, 100 * g0, 100 * g1))
    if not g1 < a.ratio * g0:
        print("FAILED: the glow paths' copies are not below %.2f of the plain run's" % a.ratio)
        return 1
    print("PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
