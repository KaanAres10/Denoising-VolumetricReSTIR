"""Authored volumes for the film shots (user, 2026-10-11: "you can also create your own volumetrics"): even stage haze
with drifting texture, ground mist banks, the smoke balls firework bursts leave. Built in numpy, converted to the
renderer's GVDB .vbx mips:

    python make_volumes.py [names...]    ->  VolumetricReSTIRData/authored/<name>/<name>_mip{0..3}[c].vbx

density (C order, x slowest) -> raw float32 -> VolFromRaw.exe (.vdb, Falcor's OpenVDB) -> gImportVDB.exe (.vbx mips),
the route ingest_vdb_sequence.py takes for external .vdb files. Placement: volume_boxes.py. Densities are 0..1; the
loader's sigma and densityScale set the extinction per metre.
"""
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vdb_pipeline as vp  # noqa: E402
import volume_boxes as vb  # noqa: E402

REPO = Path(__file__).resolve().parents[4]
RELEASE = REPO / "build" / "windows-vs2022" / "bin" / "Release"   # VolFromRaw must load Falcor's openvdb.dll
GIMPORT_DIR = REPO / "legacy" / "GVDBConverter"                    # gImportVDB finds its .ptx relative to cwd
OUT_DIR = REPO / "VolumetricReSTIRData" / "authored"
NUM_MIPS = 4


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def value_noise(shape, cell, rng):
    """Smooth noise with features `cell` voxels apart: a random lattice upsampled by a cubic spline."""
    lattice = rng.random(tuple(int(np.ceil(s / cell)) + 3 for s in shape)).astype(np.float32)
    up = ndimage.zoom(lattice, cell, order=3, mode="mirror")
    return up[tuple(slice(0, s) for s in shape)]


def fbm(shape, cell, octaves, seed, gain=0.5):
    """Fractal sum of value noise, octaves halving the cell (none finer than 2 voxels), rescaled to 0..1."""
    rng = np.random.default_rng(seed)
    total = np.zeros(shape, np.float32)
    w = 1.0
    for o in range(octaves):
        c = cell / 2 ** o
        if c < 2:
            break
        total += np.float32(w) * value_noise(shape, c, rng)
        w *= gain
    lo, hi = float(total.min()), float(total.max())
    return (total - lo) / max(hi - lo, 1e-12)


def shape(name, voxel=None):
    lo, hi, v = vb.BOXES[name]
    v = voxel or v
    return tuple(int(round((b - a) / v)) for a, b in zip(lo, hi))


def centres(name, voxel=None):
    """The voxel centres' world coordinates, as broadcastable (X, Y, Z)."""
    lo, _, v = vb.BOXES[name]
    v = voxel or v
    x, y, z = (np.float32(lo[a] + v * (np.arange(n) + 0.5)) for a, n in enumerate(shape(name, v)))
    return x[:, None, None], y[None, :, None], z[None, None, :]


def stage_haze(voxel=None):
    """A hazer's even haze over the stage: metre-scale banks and finer drifting wisps (what makes a beam look like a
    beam), a little denser near the floor, thinning out above the truss and fading over the last metres to the sides
    and the audience, so no wall of haze shows."""
    name = "stagehaze"
    lo, hi, v0 = vb.BOXES[name]
    v = voxel or v0
    sh = shape(name, v)
    X, Y, Z = centres(name, v)
    banks = fbm(sh, cell=4.0 / v, octaves=3, seed=11)
    wisps = fbm(sh, cell=0.9 / v, octaves=2, seed=12)
    height = 0.5 + 0.5 * np.exp(-Y / 2.5)
    top = 1 - smoothstep(7.0, 9.5, Y)
    sides = smoothstep(lo[0] + 0.5, lo[0] + 2.5, X) * (1 - smoothstep(hi[0] - 2.5, hi[0] - 0.5, X)) \
        * (1 - smoothstep(hi[2] - 3.0, hi[2] - 0.5, Z))
    d = height * top * sides * (0.35 + 0.65 * banks) * (0.45 + 0.55 * wisps)
    return np.clip(d, 0, 1).astype(np.float32)


def ground_mist(voxel=None):
    """Mist lying on the ground in banks: 0.4-1.6 m deep where a 12 m bank is, thin between them, wispy at the top,
    fading out 26-38 m from the centre (the distance swallows it)."""
    name = "groundmist"
    v = voxel or vb.BOXES[name][2]
    sh = shape(name, v)
    X, Y, Z = centres(name, v)
    banks = fbm(sh, cell=12.0 / v, octaves=3, seed=21)
    wisps = fbm(sh, cell=1.6 / v, octaves=3, seed=22)
    layer = np.exp(-(Y / (0.4 + 1.2 * banks)) ** 2)
    patches = smoothstep(0.3, 0.7, 0.65 * banks + 0.35 * wisps)
    far = 1 - smoothstep(26.0, 38.0, np.sqrt(X ** 2 + Z ** 2))
    d = layer * (0.25 + 0.75 * patches) * (0.75 + 0.25 * wisps) * far
    return np.clip(d, 0, 1).astype(np.float32)


def smoke_puffs(voxel=None):
    """The smoke a firework burst leaves: around each burst (volume_boxes.BURSTS) a core ball and fourteen balls
    scattered about it, plus a thinning trail of six drifting downwind (+x) and sagging, stretched along the wind;
    saturating where they overlap, domain-warped into lumps and eroded into billows at two scales."""
    name = "smokepuffs"
    lo, _, v0 = vb.BOXES[name]
    v = voxel or v0
    sh = shape(name, v)
    rng = np.random.default_rng(31)
    total = np.zeros(sh, np.float32)
    for c, radius in vb.BURSTS:
        balls = [(np.array(c, float), 0.9 * radius, 1.0)]
        for _ in range(14):
            off = rng.normal(0.0, 0.5 * radius, 3)
            off[0] += 0.5 * radius * rng.random()
            balls.append((np.array(c, float) + off, radius * rng.uniform(0.5, 1.0), 1.0))
        for t in range(1, 7):  # the trail: downwind, sinking, spreading and thinning
            off = np.array([1.1 * radius * t, -0.35 * radius * t, 0.0]) + rng.normal(0.0, 0.3 * radius, 3)
            balls.append((np.array(c, float) + off, radius * (0.7 + 0.12 * t), 0.75 ** t))
        for centre, r, weight in balls:
            # only the window the ball reaches (2.2 radii; 1.4x along the wind)
            reach = np.array([2.2 * 1.4 * r, 2.2 * r, 2.2 * r])
            i0 = [max(0, int((centre[a] - reach[a] - lo[a]) / v)) for a in range(3)]
            i1 = [min(sh[a], int((centre[a] + reach[a] - lo[a]) / v) + 1) for a in range(3)]
            if any(a >= b for a, b in zip(i0, i1)):
                continue
            x, y, z = (np.float32(lo[a] + v * (np.arange(i0[a], i1[a]) + 0.5) - centre[a]) for a in range(3))
            q = (x[:, None, None] / 1.4) ** 2 + y[None, :, None] ** 2 + z[None, None, :] ** 2
            total[i0[0]:i1[0], i0[1]:i1[1], i0[2]:i1[2]] += np.float32(weight) * np.exp(-2.0 * q / r ** 2)
    shaped = 1 - np.exp(-1.6 * total)
    # Domain warp (displace where the field is read by up to 1.5 m of smooth noise): round balls become lumps.
    amp = 1.5 / v
    warp = [(fbm(sh, cell=5.0 / v, octaves=2, seed=33 + a) - 0.5) * 2 * amp for a in range(3)]
    grid = np.meshgrid(*(np.arange(n, dtype=np.float32) for n in sh), indexing="ij")
    shaped = ndimage.map_coordinates(shaped, [g + w for g, w in zip(grid, warp)], order=1, mode="nearest")
    del grid, warp
    billows = 0.6 * fbm(sh, cell=2.5 / v, octaves=2, seed=32) + 0.4 * fbm(sh, cell=0.8 / v, octaves=2, seed=36)
    d = shaped - 0.55 * (1 - billows)  # erosion: thin smoke loses its edges first, cores keep their bulk
    return smoothstep(0.0, 0.45, d).astype(np.float32)


BUILDERS = {"stagehaze": stage_haze, "groundmist": ground_mist, "smokepuffs": smoke_puffs}


def write_raw(d, path):
    """C order, x slowest: VolFromRaw reads data[(i * ny + j) * nz + k] as voxel (i, j, k)."""
    np.ascontiguousarray(d, dtype=np.float32).tofile(str(path))


def run(cmd, cwd):
    r = subprocess.run([str(c) for c in cmd], cwd=str(cwd), capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("FAILED (exit %d): %s\n%s" % (r.returncode, cmd[0], (r.stdout or "")[-2000:]))
    return r.stdout


def convert(name, d, work):
    """density -> VolumetricReSTIRData/authored/<name>/ (.vbx mips)."""
    voxel = vb.BOXES[name][2]
    raw, vdb = Path(work) / (name + ".raw"), Path(work) / (name + ".vdb")
    write_raw(d, raw)
    print(run([RELEASE / "VolFromRaw.exe", raw, *d.shape, voxel, vdb], cwd=RELEASE).strip())
    staged = GIMPORT_DIR / name   # gImportVDB writes a folder named after the .vdb into its cwd
    if staged.exists():
        shutil.rmtree(staged)
    run([GIMPORT_DIR / "gImportVDB.exe", vdb, NUM_MIPS], cwd=GIMPORT_DIR)
    dest = OUT_DIR / name
    if dest.exists():
        shutil.rmtree(dest)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staged), str(dest))
    if not vp.vbx_complete(dest, name, NUM_MIPS):
        raise SystemExit("FAILED: %s is missing .vbx files after import" % dest)
    return dest


def main(argv):
    names = argv[1:] or list(BUILDERS)
    for name in names:
        t0 = time.time()
        d = BUILDERS[name]()
        print("%s: %s voxels, mean %.3f, %.0f%% above 0.01 (%.0fs)" % (name, "x".join(map(str, d.shape)), d.mean(),
                                                                      100 * (d > 0.01).mean(), time.time() - t0))
        with tempfile.TemporaryDirectory() as work:
            print("  ->", convert(name, d, work))


if __name__ == "__main__":
    main(sys.argv)
