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


def streaky(sh, cell, octaves, seed, stretch=2.5):
    """fbm whose features are `stretch` times taller (axis 1) than wide: rising streaks."""
    small = (sh[0], max(4, int(round(sh[1] / stretch))), sh[2])
    f = fbm(small, cell=cell, octaves=octaves, seed=seed)
    return ndimage.zoom(f, (1, sh[1] / small[1], 1), order=1)[:, :sh[1], :]


TEAPOT_OPENING = (0.2, -0.6)  # the swatch pot's opening, x and z (cm); its rim at y 21.6, 5.7 cm across inside
FLAME_ROOT_Y = 19.5  # where the flame rises from, inside the pot


def teapot_flame(voxel=None, seed=0, height=9.5, radius=4.4, lean=0.3, embers=60):
    """An authored fire for the swatch teapot (user, 2026-10-13: our own fire, a complicated volume where the mutation
    count matters), in the teapot's centimetres, y up: (density, temperature 0..1).
      The flame: a cone of tongues rising from inside the pot (FLAME_ROOT_Y) `height` cm, `radius` cm at its root,
    leaning right (+x) and back as it rises, swaying; read at points displaced by rising streaky noise, more so higher
    up (a calm root, flickering tips), and cut into tongues by streaks thresholded harder with height, so its top
    breaks into separate flames. Hottest low in its core, cooling to the tips and edges. A little soot (density 0.35).
      The smoke: a plume out of the tips (above 55% of the height), drifting right and back, widening, billowed and
    eroded at two scales; no temperature, so it glows only by the fire's light it scatters.
      Embers: `embers` hot specks rising out of the flame."""
    name = "teapotflame"
    lo, hi, v0 = vb.BOXES[name]
    v = voxel or v0
    sh = shape(name, v)
    X, Y, Z = centres(name, v)
    grid = np.meshgrid(*(np.arange(n, dtype=np.float32) for n in sh), indexing="ij")
    h = Y - FLAME_ROOT_Y
    amp = (0.35 + 0.16 * np.clip(h, 0, None)) / v
    warp = [(streaky(sh, cell=1.6 / v, octaves=3, seed=seed + 10 + a) - 0.5) * 2 * amp for a in range(3)]
    Xw, Yw, Zw = (lo[a] + v * (grid[a] + warp[a] + 0.5) for a in range(3))
    del grid, warp
    hw = Yw - FLAME_ROOT_Y
    up = np.maximum(hw, 0)
    sway = (streaky((1, sh[1], 1), cell=40, octaves=2, seed=seed + 1)[0, :, 0] - 0.5)[None, :, None]
    t = np.clip(hw / height, 0, 1)
    axis_x = TEAPOT_OPENING[0] + lean * up + 0.015 * up ** 2 + 1.2 * sway * up / height
    axis_z = TEAPOT_OPENING[1] - 0.08 * up
    R = radius * (1 - t) ** 0.55 * smoothstep(-0.5, 0.8, hw)
    rr = np.hypot(Xw - axis_x, Zw - axis_z) / np.maximum(R, 1e-3)
    body = 1 - smoothstep(0.55, 1.0, rr)
    tongues = streaky(sh, cell=0.9 / v, octaves=3, seed=seed + 20, stretch=3.0)
    thr = 0.22 + 0.4 * t
    flame = body * smoothstep(thr - 0.12, thr + 0.12, tongues) * (1 - smoothstep(0.88, 1.0, t))
    temp = flame ** 0.6 * (1.0 - 0.35 * t) * (0.8 + 0.2 * np.clip(1 - rr, 0, 1))
    del body, tongues
    # the smoke
    base = 0.55 * height
    hs = np.clip(hw - base, 0, None)
    sx = TEAPOT_OPENING[0] + lean * base + 0.015 * base ** 2 + (lean + 0.45) * hs + 0.02 * hs ** 2
    sz = TEAPOT_OPENING[1] - 0.6 - 0.25 * hs
    plume = (1 - smoothstep(0.5, 1.0, np.hypot(Xw - sx, Zw - sz) / (1.8 + 0.6 * hs))) * smoothstep(base, base + 1.5, hw)
    billows = 0.6 * fbm(sh, cell=1.4 / v, octaves=3, seed=seed + 30) + 0.4 * fbm(sh, cell=0.45 / v, octaves=2, seed=seed + 31)
    top = 1 - smoothstep(0.85, 1.0, (Yw - lo[1]) / (hi[1] - lo[1]))
    smoke = smoothstep(0.0, 0.35, plume - 0.6 * (1 - billows)) * top
    del plume, billows, Xw, Yw, Zw
    # the embers
    rng = np.random.default_rng(seed + 40)
    specks = np.zeros(sh, np.float32)
    for _ in range(embers):
        e = (TEAPOT_OPENING[0] + rng.normal(1.5, 2.2), FLAME_ROOT_Y + rng.uniform(0.6, 1.5) * height, TEAPOT_OPENING[1] + rng.normal(0, 2.0))
        i = [int((e[a] - lo[a]) / v) for a in range(3)]
        if all(0 < i[a] < sh[a] - 1 for a in range(3)):
            specks[i[0], i[1], i[2]] = rng.uniform(0.6, 1.0)
    specks = np.clip(ndimage.gaussian_filter(specks, 0.7) * 6, 0, 1)
    temp = np.maximum(temp, specks)
    density = 0.35 * flame + 1.2 * smoke + 0.3 * specks
    return density.astype(np.float32), np.clip(temp, 0, 1).astype(np.float32)


def write_teapot_fire(seed=0):
    """VolumetricReSTIRData/authored/teapotflame (the .vbx mips and its temperature) and teapotflame_lights.json: the
    fire's point lights (emission_light_table, vb.TEAPOT_FIRE's medium and glow), positions in world cm."""
    import json
    name, f = "teapotflame", vb.TEAPOT_FIRE
    lo, _, v = vb.BOXES[name]
    density, temp = teapot_flame(seed=seed)
    with tempfile.TemporaryDirectory() as work:
        dest = convert(name, density, work, temperature=temp)
    table = emission_light_table(density * f["density_scale"], temp, n=f["lights"], cutoff=f["cutoff"], scale=f["scale"],
                                 voxel=v, sigma_a=f["sigma_a"], le_scale=f["le_scale"])
    for l in table["lights"]:
        l["p"] = [lo[a] + v * (l["p"][a] + 0.5) for a in range(3)]
    path = OUT_DIR / (name + "_lights.json")
    path.write_text(json.dumps(table, indent=1))
    return dest, path


def vdb_grid(vdb, name, clip=None):
    """One grid of a .vdb (VdbToRaw.exe): its active box's low corner, the box as an array (x slowest; a vector grid's
    components last) and the voxel size; `clip` ((lo, hi), inclusive index coordinates) cuts the box first."""
    with tempfile.TemporaryDirectory() as work:
        extra = [*clip[0], *clip[1]] if clip else []
        out = run([RELEASE / "VdbToRaw.exe", vdb, name, Path(work) / name, *extra], cwd=RELEASE).split()
        components = int(out[11]) if len(out) > 11 else 1
        shape = [int(v) for v in out[5:8]] + ([components] if components > 1 else [])
        arr = np.fromfile(str(Path(work) / name), np.float32).reshape(shape)
    return [int(v) for v in out[1:4]], arr, float(out[9])


def velocity_blur(d, v, voxel, shutter, steps=16, v_voxel=None, d_lo=(0, 0, 0), v_lo=(0, 0, 0), chunk=16):
    """Density `d` (x slowest; voxel size `voxel`, m) motion blurred along velocity `v` (m/s, components last), as a
    production renderer blurs a volume: the mean over the `shutter` (s, centred on the frame) of d at x - v(x) t,
    `steps` times -- smooth streaks along the flow, where frames averaged leave copies. `v` may be on its own grid
    (post_refine_aero leaves the velocity at the simulation's resolution): voxel size `v_voxel`, and each array's
    first voxel at index `d_lo` / `v_lo` of its grid (index i at i x voxel in the world, as OpenVDB's linear
    transform puts it)."""
    v_voxel = voxel if v_voxel is None else v_voxel
    same = v.shape[:3] == d.shape and v_voxel == voxel and tuple(d_lo) == tuple(v_lo)
    ts = ((np.arange(steps) + 0.5) / steps - 0.5) * shutter
    d = np.asarray(d, np.float32)
    out = np.zeros_like(d)
    for x0 in range(0, d.shape[0], chunk):
        x1 = min(x0 + chunk, d.shape[0])
        idx = np.indices((x1 - x0,) + d.shape[1:], dtype=np.float32)
        idx[0] += x0
        if same:
            vel = np.moveaxis(v[x0:x1], -1, 0)
        else:  # the velocity where each density voxel is, on the velocity's grid
            at = [(idx[a] + d_lo[a]) * (voxel / v_voxel) - v_lo[a] for a in range(3)]
            vel = np.stack([ndimage.map_coordinates(v[..., c], at, order=1, mode="nearest") for c in range(3)])
        vel = vel.astype(np.float32) / voxel  # voxels a second
        acc = np.zeros(idx.shape[1:], np.float32)
        for t in ts:
            acc += ndimage.map_coordinates(d, idx - vel * np.float32(t), order=1, mode="constant", cval=0.0)
        out[x0:x1] = acc / steps
    return out


def read_vdb_box(vdb, names, clip=None):
    """Grids of a .vdb (VdbToRaw.exe) in one index box: its low corner and {name: array}, x slowest; `clip` as
    vdb_grid's."""
    grids = {}
    for g in names:
        glo, arr, _ = vdb_grid(vdb, g, clip)
        grids[g] = (glo, arr)
    lo = [min(grids[g][0][a] for g in names) for a in range(3)]
    hi = [max(grids[g][0][a] + grids[g][1].shape[a] for g in names) for a in range(3)]
    box = {}
    for g, (glo, arr) in grids.items():
        b = np.zeros([h - l for l, h in zip(lo, hi)], np.float32)
        o = [glo[a] - lo[a] for a in range(3)]
        b[o[0]:o[0] + arr.shape[0], o[1]:o[1] + arr.shape[1], o[2]:o[2] + arr.shape[2]] = arr
        box[g] = b
    return lo, box


def fade_foot(d, start, end, floor=0.0):
    """Density `d` (x slowest, y up) with its foot faded into smoke (the Lanterns reference's construct thins toward
    its tail): x a smoothstep in the height of its column -- the slices holding at least 2% of the densest's smoke, so
    a faint ground haze does not count -- from `floor` at `start` to 1 at `end` (fractions of that height)."""
    prof = np.maximum(d, 0.0).sum((0, 2), dtype=np.float64)
    occupied = np.flatnonzero(prof > 0.02 * prof.max())
    y = (np.arange(d.shape[1]) - occupied.min()) / max(occupied.max() - occupied.min(), 1)
    t = np.clip((y - start) / (end - start), 0.0, 1.0)
    w = floor + (1.0 - floor) * t * t * (3.0 - 2.0 * t)
    return (d * w[None, :, None]).astype(np.float32)


def glitter_points(d, n, key, threshold, seed=0, power=4.0):
    """The construct's glitter (the Lanterns reference's sparkles): `n` points (array index coordinates, x slowest)
    on the surface of density `d` -- voxels at or above `threshold` with a 6-neighbour below it -- drawn by how
    squarely their outward normal (minus the density gradient, central differences two voxels apart) faces `key`
    (a direction in the same index frame), to the power `power`, jittered within their voxel. Seeded."""
    rng = np.random.default_rng(seed)
    mask = d >= threshold
    surf = np.argwhere(mask & ~ndimage.binary_erosion(mask))
    if len(surf) == 0:
        return np.zeros((0, 3))
    hi = np.array(d.shape) - 1
    grad = np.zeros((len(surf), 3))
    for a in range(3):
        up, dn = surf.copy(), surf.copy()
        up[:, a] = np.minimum(surf[:, a] + 2, hi[a])
        dn[:, a] = np.maximum(surf[:, a] - 2, 0)
        grad[:, a] = d[tuple(up.T)] - d[tuple(dn.T)]
    normal = -grad / np.maximum(np.linalg.norm(grad, axis=1, keepdims=True), 1e-12)
    k = np.asarray(key, float) / np.linalg.norm(key)
    w = np.clip(normal @ k, 0.0, None) ** power
    if w.sum() <= 0:
        return np.zeros((0, 3))
    pick = rng.choice(len(surf), size=min(n, int((w > 0).sum())), replace=False, p=w / w.sum())
    return surf[pick] + rng.uniform(-0.5, 0.5, (len(pick), 3))


def clean_bifrost_vdb(src, dst, density="voxel_fog_density", temperature="voxel_temperature", cutoff=1e-4):
    """A Bifrost frame (bifrost_export.py writes them) rewritten for gImportVDB: its fog density and temperature as
    `density` and `temperature` (VolFromRaw), in its own index placement -- so a sequence's frames line up -- and the
    temperature clipped to the smoke's box: Bifrost keeps it active far past the smoke at the ambient temperature,
    which would fill a dense copy and GVDB's atlas -- written a voxel a unit, as every volume here is (a shot's
    worldScaling gives it its size: GVDB places a .vbx in the .vdb's world units). Returns the box's low corner, its
    shape and Bifrost's voxel size."""
    return blur_bifrost_frames([src], dst, density, temperature, cutoff)


def blur_bifrost_frames(srcs, dst, density="voxel_fog_density", temperature="voxel_temperature", cutoff=1e-4):
    """Bifrost frames averaged into one, rewritten as clean_bifrost_vdb does: volume motion blur as a shutter's worth of
    frames (the Lanterns reference's construct is streaked along its rotation), over the union of their smoke's boxes
    (Bifrost's index space is the same for every frame). One frame: clean_bifrost_vdb. Returns the union's low corner,
    its shape and Bifrost's voxel size."""
    frames = []
    for src in srcs:
        lo, d, voxel = vdb_grid(src, density)
        hi = [lo[a] + d.shape[a] - 1 for a in range(3)]
        tlo, t_box, _ = vdb_grid(src, temperature, clip=(lo, hi))
        frames.append((lo, d, tlo, t_box))
    ulo = [min(f[0][a] for f in frames) for a in range(3)]
    uhi = [max(f[0][a] + f[1].shape[a] for f in frames) for a in range(3)]
    shape = tuple(uhi[a] - ulo[a] for a in range(3))
    dsum = np.zeros(shape, np.float32)
    tsum = np.zeros(shape, np.float32)
    for lo, d, tlo, t_box in frames:
        o = [lo[a] - ulo[a] for a in range(3)]
        dsum[o[0]:o[0] + d.shape[0], o[1]:o[1] + d.shape[1], o[2]:o[2] + d.shape[2]] += d
        o = [tlo[a] - ulo[a] for a in range(3)]
        tsum[o[0]:o[0] + t_box.shape[0], o[1]:o[1] + t_box.shape[1], o[2]:o[2] + t_box.shape[2]] += t_box
    dsum /= len(frames)
    tsum /= len(frames)
    with tempfile.TemporaryDirectory() as work:
        write_raw(dsum, Path(work) / "density.raw")
        write_raw(tsum, Path(work) / "temperature.raw")
        run([RELEASE / "VolFromRaw.exe", Path(work) / "density.raw", *shape, 1.0, dst, cutoff,
             Path(work) / "temperature.raw", *ulo], cwd=RELEASE)
    return ulo, shape, voxel


def blur_bifrost_velocity(src, dst, shutter, steps=16, density="voxel_fog_density", temperature="voxel_temperature",
                          velocity="voxel_velocity", cutoff=1e-4):
    """A Bifrost frame motion blurred along its own velocity (velocity_blur: the Lanterns reference's construct is
    streaked along its rotation) over `shutter` seconds, rewritten as clean_bifrost_vdb does -- its box grown by the
    longest smear. The frame must hold the velocity (bifrost_export.py with BIFROST_PROPERTIES naming voxel_velocity).
    Returns the box's low corner, its shape and Bifrost's voxel size."""
    lo, d, voxel = vdb_grid(src, density)
    hi = [lo[a] + d.shape[a] - 1 for a in range(3)]
    grids = [d]
    if temperature:  # (None: a frame exported without it)
        tlo, t_box, _ = vdb_grid(src, temperature, clip=(lo, hi))
        t = np.zeros_like(d)
        o = [tlo[a] - lo[a] for a in range(3)]
        t[o[0]:o[0] + t_box.shape[0], o[1]:o[1] + t_box.shape[1], o[2]:o[2] + t_box.shape[2]] = t_box
        grids.append(t)
    # the velocity under the smoke: on a grid as fine or coarser (post_refine_aero leaves it at the simulation's), so
    # the smoke's box scaled toward the origin -- inside the box spanning it and the origin -- holds what is needed
    vlo, v, v_voxel = vdb_grid(src, velocity, clip=([min(lo[a], 0) - 1 for a in range(3)],
                                                    [max(hi[a], 0) + 1 for a in range(3)]))
    pad = int(np.ceil(float(np.linalg.norm(v, axis=-1).max()) * shutter / 2.0 / voxel)) + 1
    lo = [lo[a] - pad for a in range(3)]
    blurred = [velocity_blur(np.pad(g, pad), v, voxel, shutter, steps, v_voxel=v_voxel, d_lo=lo, v_lo=vlo) for g in grids]
    shape = blurred[0].shape
    with tempfile.TemporaryDirectory() as work:
        write_raw(blurred[0], Path(work) / "density.raw")
        if temperature:
            write_raw(blurred[1], Path(work) / "temperature.raw")
        run([RELEASE / "VolFromRaw.exe", Path(work) / "density.raw", *shape, 1.0, dst, cutoff,
             Path(work) / "temperature.raw" if temperature else "-", *lo], cwd=RELEASE)
    return lo, shape, voxel


def write_sequence(seq, frame=None):
    """A frame of one of the user's EmberGen sequences (swatch_fire.SEQUENCES: gasoline, midair, plume) for the teapot:
    VolumetricReSTIRData/<seq>/<seq><frame> (gImportVDB, after VDBPrep's renames if the sequence has any) and
    <seq><frame>_lights.json: point lights where it glows (emission_light_table with the sequence's medium and glow,
    its density and its glow grid), positions in world cm as swatch_fire places it. Refuses a frame whose grid offset is
    not the sequence's."""
    import json
    import swatch_fire as sf
    g = sf.SEQUENCES[seq]
    frame = g["frame"] if frame is None else frame
    name = "%s%d" % (seq, frame)
    src = str(REPO / (g["src"] % frame))
    out_dir = REPO / "VolumetricReSTIRData" / seq
    if "bifrost_src" in g and not Path(src).exists():  # a Bifrost frame, rewritten for gImportVDB on first use
        Path(src).parent.mkdir(parents=True, exist_ok=True)
        clean_bifrost_vdb(REPO / (g["bifrost_src"] % frame), src)
    with tempfile.TemporaryDirectory() as work:
        vdb = Path(work) / (name + ".vdb")
        if g["renames"]:
            run([RELEASE / "VDBPrep.exe", src, vdb, g["renames"]], cwd=RELEASE)
        else:
            shutil.copy(src, str(vdb))
        dest = import_vdb(vdb, out_dir, emissive=True)
    lo, box = read_vdb_box(src, ("density", g["glow_grid"]))
    lo_d, _ = read_vdb_box(src, ("density",))
    off = vbx_offset(dest, name, lo_d)
    if any(abs(off[a] - g["offset"][a]) > 1e-3 for a in range(3)):
        raise SystemExit("FAILED: %s's grid offset %s is not %s" % (name, off, g["offset"]))
    # GVDB's extinction per cm: sigma x density x densityScale / the volume's scaling
    table = emission_light_table(box["density"] * g["density_scale"] / g["scale"], box[g["glow_grid"]], n=g["lights"],
                                 cutoff=g["cutoff"], scale=g["temperature_scale"], voxel=g["scale"], sigma_a=g["sigma_a"],
                                 le_scale=g["le_scale"])
    for l in table["lights"]:
        l["p"] = list(sf.to_world([l["p"][a] + lo[a] + g["offset"][a] + 0.5 for a in range(3)], **sf.pose(g)))
    path = out_dir / (name + "_lights.json")
    path.write_text(json.dumps(table, indent=1))
    return dest, path


def write_gasoline(frame=None):
    return write_sequence("gasoline", frame)


def unit_noise(shape, sigma, rng):
    """Smooth Gaussian noise: white noise blurred by `sigma` voxels (wrapping), scaled to unit standard deviation."""
    n = ndimage.gaussian_filter(rng.standard_normal(shape, dtype=np.float32), sigma, mode="wrap")
    return n / max(float(n.std()), 1e-12)


GVDB_BRICK = 8  # gImportVDB's bricks: 8^3 voxels (10^3 texels in the atlas with their apron), 16 x 16 to a layer
# gImportVDB's own atlas (16 x 16 bricks a layer) is a CUDA 3D texture, at most 16384 deep; Falcor's limit (two
# Texture3D parts of at most 2048) no longer binds: import_vdb re-lays a deep atlas wider (vbx_tools.widen_file)
GVDB_ATLAS_MAX = 16380
GVDB_ATLAS_SLACK = 1.12  # gImportVDB's atlas runs over gvdb_atlas_depth's count (measured 4310 against 3940: +9%)


def gvdb_atlas_depth(d, cutoff=1e-4):
    """The depth (texels) of the brick atlas gImportVDB builds for density `d` written a voxel a unit by VolFromRaw:
    a brick for every 8^3 block holding a voxel above VolFromRaw's cutoff, 16 x 16 bricks a layer, 10 texels a
    brick. Past GVDB_ATLAS_MAX gImportVDB cannot build it."""
    b = GVDB_BRICK
    m = d > cutoff
    m = np.pad(m, [(0, -s % b) for s in m.shape])
    n = int(m.reshape(m.shape[0] // b, b, m.shape[1] // b, b, m.shape[2] // b, b).any((1, 3, 5)).sum())
    return -(-n // 256) * 10


TILE = 64  # texels a side of a periodic noise tile
TILE_SIGMA = 2.5  # its blur, texels
TILE_FEATURE = 4 * TILE_SIGMA  # texels from one of its features to the next


def curl_tile(n, sigma, rng):
    """A periodic divergence-free field on an n^3 tile: the curl of three smooth noise potentials (central differences,
    wrapping), scaled to a unit mean magnitude. Returns its (x, y, z) components."""
    psi = [unit_noise((n, n, n), sigma, rng) for _ in range(3)]

    def dd(f, axis):
        return (np.roll(f, -1, axis) - np.roll(f, 1, axis)) / 2
    c = [dd(psi[2], 1) - dd(psi[1], 2), dd(psi[0], 2) - dd(psi[2], 0), dd(psi[1], 0) - dd(psi[0], 1)]
    k = 1.0 / max(float(np.sqrt(sum(f ** 2 for f in c)).mean()), 1e-12)
    return [(f * k).astype(np.float32) for f in c]


def tile_at(tile, coords):
    """A periodic tile sampled at texel coordinates (trilinear, wrapping)."""
    return ndimage.map_coordinates(tile, coords, order=1, mode="grid-wrap")


def tornado_detail(d, up=2.0, warp=(4.0, 1.2), warp_scales=(24.0, 6.0), streaks=0.0, streak_width=(6.0, 4.0),
                   grain=0.0, grain_scale=2.5, erode=0.0, erode_ref=0.15, erode_scales=(16.0, 6.0, 2.5), bands=0.45,
                   sharp=1.0, arms=2, pitch=54.0, meander=1.0, specks=5000, speck_density=2.5, speck_sigma=0.8,
                   speck_spread=0.0, speck_power=1.0, seed=1, chunk=8):
    """The looping tornado with film-style detail added (user, 2026-10-17: "more detail, like the lantern construct,
    movie production detail"), its own structure kept -- not reshaped -- as a production upres adds it to a
    simulation (Houdini's Pyro Upres: resampled finer, turbulence advected in, edges eroded by noise). Returns float32
    density on a grid `up` times finer (new voxel j's centre at source coordinate (j + 0.5) / up - 0.5). Lengths are
    in new voxels; noise comes from periodic tiles (TILE texels, a feature every TILE_FEATURE):
      warp: the frame sampled through a curl-noise displacement (divergence free: it swirls the smoke without
    compressing it), an octave per `warp_scales` feature size, `warp` voxels each -- smooth veils curl into filaments;
      streaks: the vortex's flow lines -- noise long around the funnel's axis (each slice's density centre, smoothed
    along z), ~6 features a turn, rising one tile a turn so it joins up, `streak_width` (radial, vertical) across --
    density x (1 + `streaks` n);
      grain: fine noise (`grain_scale`), density x (1 + `grain` n): dust's texture;
      bands: helices wrapping the axis, `arms` of them, one passing every `pitch` voxels along z, their phase
    meandering with smooth noise (`meander` radians: the reference's bands are irregular); `bands` of the density
    regrouped into them, the profile (1 + cos) / 2 to the power `sharp` (higher: narrower bands, emptier gaps -- seen
    through smoke, a soft ripple averages out along the view), its mean over a period 1;
      erode: the thin smoke carved by ridged noise (|n| over `erode_scales`, in [0, 1]) with the cloud modelling remap
    (Schneider 2015, Nubis): q -> (q - e D) / (1 - e D) on the density over `erode_ref`, capped at 1 -- the thin
    veils break into crisp wisps and sheets, the core (q >= 1) untouched;
      specks: `specks` small dense blobs (Gaussian; `speck_density` at the centre, `speck_sigma` across, both
    log-normal by `speck_spread`) drawn by the frame's density to the power `speck_power` (below 1: more out in the thin
    veils): glints where lit, the construct's glitter (against thin smoke an opaque speck reads up to 1 / its optical
    depth brighter), dark debris casting its own small shadow where not.
    Seeded: the same arguments give the same volume."""
    rng = np.random.default_rng(seed)
    nx, ny, nz = d.shape
    shape = tuple(int(round(up * n)) for n in d.shape)

    def k_tex(size):  # texels a voxel, for features `size` voxels apart
        return TILE_FEATURE / size
    curls = [curl_tile(TILE, TILE_SIGMA, rng) for _ in warp_scales] if warp else []
    streak_tile = unit_noise((TILE,) * 3, TILE_SIGMA, rng) if streaks else None
    grain_tile = unit_noise((TILE,) * 3, TILE_SIGMA, rng) if grain else None
    erode_tiles = [unit_noise((TILE,) * 3, TILE_SIGMA, rng) for _ in erode_scales] if erode else []
    phase = meander * unit_noise(d.shape, 12.0, rng) if bands else None
    band_mean = float(np.mean((0.5 + 0.5 * np.cos(np.linspace(0, 2 * np.pi, 4096, endpoint=False))) ** sharp))
    offsets = rng.uniform(0, TILE, (8, 3))  # each octave's own place in its tile
    # the funnel's axis, slice by slice, in source voxels
    w = d.sum((0, 1)).astype(np.float64)
    ix, iy = np.indices((nx, ny), dtype=np.float64)
    keep = w > 1e-6 * max(float(w.max()), 1e-30)
    axis = []
    for grid in (ix, iy):
        c = (d * grid[..., None]).sum((0, 1)) / np.maximum(w, 1e-30)
        c = np.interp(np.arange(nz), np.flatnonzero(keep), c[keep]) if keep.any() else np.full(nz, (len(grid) - 1) / 2)
        axis.append(ndimage.gaussian_filter1d(c, 8.0, mode="nearest"))
    jy = np.arange(shape[1])[None, :, None].astype(np.float64)
    jz = np.arange(shape[2])[None, None, :].astype(np.float64)
    sz = (jz + 0.5) / up - 0.5
    ax = np.interp(sz, np.arange(nz), axis[0])
    ay = np.interp(sz, np.arange(nz), axis[1])
    out = np.empty(shape, np.float32)
    for x0 in range(0, shape[0], chunk):
        jx = np.arange(x0, min(x0 + chunk, shape[0]))[:, None, None].astype(np.float64)
        J = np.broadcast_arrays(jx, jy, jz)  # new voxels
        S = [(j + 0.5) / up - 0.5 for j in J]  # source coordinates
        at = list(S)
        for (amp, size), curl, o in zip(zip(warp if warp else (), warp_scales), curls, offsets):
            t = [J[a] * k_tex(size) + o[a] for a in range(3)]
            for a in range(3):
                at[a] = at[a] + amp * tile_at(curl[a], t) / up
        val = ndimage.map_coordinates(d, at, order=1, mode="constant", cval=0.0)
        rx, ry = (S[0] - ax) * up, (S[1] - ay) * up  # from the axis, new voxels
        theta = np.arctan2(ry, rx)
        if streaks:
            turn = theta / (2 * np.pi) * TILE  # around: one tile a turn (joins up)
            t = [np.hypot(rx, ry) * k_tex(streak_width[0]) + offsets[3, 0], turn + offsets[3, 1],
                 J[2] * k_tex(streak_width[1]) - turn + offsets[3, 2]]  # rising one tile a turn: joins up too
            val *= np.maximum(1.0 + streaks * tile_at(streak_tile, t), 0.0)
        if grain:
            t = [J[a] * k_tex(grain_scale) + offsets[4, a] for a in range(3)]
            val *= np.maximum(1.0 + grain * tile_at(grain_tile, t), 0.0)
        if bands:
            m = ndimage.map_coordinates(phase, S, order=1, mode="nearest")
            band = (0.5 + 0.5 * np.cos(arms * theta - 2 * np.pi * J[2] / pitch + m)) ** sharp
            val *= (1.0 - bands) + bands * band / band_mean
        if erode:
            D = sum(np.abs(tile_at(tl, [J[a] * k_tex(size) + offsets[5 + i, a] for a in range(3)])) * 0.5 ** i
                    for i, (tl, size) in enumerate(zip(erode_tiles, erode_scales)))
            D = np.clip(D / (2.0 * sum(0.5 ** i for i in range(len(erode_scales)))), 0.0, 1.0)
            q = val / erode_ref
            qc = np.minimum(q, 1.0)
            val = erode_ref * (q - qc + np.maximum(qc - erode * D, 0.0) / (1.0 - erode * D))
        out[x0:x0 + jx.shape[0]] = val
    if specks:
        p = np.maximum(d.ravel().astype(np.float64), 0.0) ** speck_power
        p /= p.sum()
        src = np.array(np.unravel_index(rng.choice(p.size, specks, p=p), d.shape)).T + rng.uniform(-0.5, 0.5, (specks, 3))
        c = np.rint((src + 0.5) * up - 0.5).astype(np.int64)
        peak = speck_density * np.exp(speck_spread * rng.standard_normal(specks))
        sigma = speck_sigma * np.clip(np.exp(0.5 * speck_spread * rng.standard_normal(specks)), 0.6, 1.6)
        r = int(np.ceil(3 * sigma.max()))
        o = np.arange(-r, r + 1)
        ox, oy, oz = (a.ravel() for a in np.meshgrid(o, o, o, indexing="ij"))
        g = peak[:, None] * np.exp(-(ox ** 2 + oy ** 2 + oz ** 2)[None, :] / (2 * sigma[:, None] ** 2))
        pts = c[:, None, :] + np.stack([ox, oy, oz], 1)[None]
        inside = np.all((pts >= 0) & (pts < np.array(shape)), axis=2)
        np.add.at(out, tuple(pts[inside].T), g[inside].astype(np.float32))
    np.clip(out, 0.0, None, out=out)
    return out


def write_lantern(shot="lantern", frame=None):
    """A frame of a green tornado shot (lantern.SHOTS: the looping tornado or the dust devil): as it is, or with the
    shot's `detail` added (tornado_detail, written by VolFromRaw a voxel a unit: no grid offset), as
    VolumetricReSTIRData/<data>/<data><frame> (gImportVDB), and <data><frame>_lights.json -- the shot's `glow`, if it
    has one: its few big green lights, one at each of its heights on the funnel's axis (the slice's density-weighted
    centre), moved `outside` cm toward the shot's key, sharing its power, positions in world cm as lantern.py places
    the funnel (its soft boxes, `panels`, are the scene's own)."""
    import json
    import lantern
    import swatch_fire as sf
    g = lantern.SHOTS[shot]
    frame = g["frame"] if frame is None else frame
    name = "%s%d" % (g["data"], frame)
    src = str(REPO / (g["src"] % frame))
    out_dir = REPO / "VolumetricReSTIRData" / g["data"]
    if "bifrost_src" in g and not Path(src).exists():  # a Bifrost frame, rewritten for gImportVDB on first use --
        Path(src).parent.mkdir(parents=True, exist_ok=True)  # averaged with the frames before it over `shutter`
        if g.get("vblur"):  # -- or blurred along its own velocity
            blur_bifrost_velocity(REPO / (g["bifrost_src"] % frame), src, g["vblur"])
        else:
            k = g.get("shutter", 1)
            blur_bifrost_frames([REPO / (g["bifrost_src"] % f) for f in range(frame - k + 1, frame + 1)], src)
    lo, box = read_vdb_box(src, ("density",))
    d = d_fit = box["density"]
    grid = None
    with tempfile.TemporaryDirectory() as work:
        vdb = Path(work) / (name + ".vdb")
        if "detail" in g:
            spec = dict(g["detail"])
            up, src_off = spec["up"], spec.pop("source_offset")
            if "glow" in g:
                raise SystemExit("FAILED: %s: lamps are not placed on a detailed grid (soft boxes are the scene's)" % shot)
            # where the shot's middle is on this frame's finer grid (its index box starts at the frame's own `lo`): a
            # source .vbx point p sits at (p - source offset - lo) x up on it (vr_graph.load_lantern reads it; the voxel
            # and the density per voxel are lantern.py's over up)
            grid = {"up": up, "base": [(g["base"][a] - src_off[a] - lo[a]) * up for a in range(3)]}
            d = tornado_detail(d, **spec)
            box = None
            depth = gvdb_atlas_depth(d)
            if depth * GVDB_ATLAS_SLACK > GVDB_ATLAS_MAX:
                raise SystemExit("FAILED: %s's brick atlas would be ~%d deep, past the %d gImportVDB can build: a smaller "
                                 "`up`" % (name, depth * GVDB_ATLAS_SLACK, GVDB_ATLAS_MAX))
            print("%s: %s voxels, its atlas ~%d of %d deep" % (name, d.shape, depth * GVDB_ATLAS_SLACK, GVDB_ATLAS_MAX))
            lo = [0, 0, 0]
            raw = Path(work) / (name + ".raw")
            write_raw(d, raw)
            run([RELEASE / "VolFromRaw.exe", raw, *d.shape, 1.0, vdb], cwd=RELEASE)
            raw.unlink()
            lo_file, _ = read_vdb_box(vdb, ("density",))
        elif "foot" in g:  # its foot thinned into smoke (fade_foot), rewritten where it was; fitted as simulated
            d_fit, d = d, fade_foot(d, *g["foot"])
            raw = Path(work) / (name + ".raw")
            write_raw(d, raw)
            run([RELEASE / "VolFromRaw.exe", raw, *d.shape, 1.0, vdb, 1e-4, "-", *lo], cwd=RELEASE)
            raw.unlink()
            lo_file, _ = read_vdb_box(vdb, ("density",))
        else:
            shutil.copy(src, str(vdb))
            lo_file = lo
        dest = import_vdb(vdb, out_dir)
    off = vbx_offset(dest, name, lo_file)
    if any(abs(off[a] - g["offset"][a]) > 1e-3 for a in range(3)):
        raise SystemExit("FAILED: %s's grid offset %s is not %s" % (name, off, g["offset"]))
    if "bifrost_src" in g:  # a simulated column (y up), fitted to the shot's `fit` (the reference's construct)
        w = np.maximum(d_fit, 0.0).astype(np.float64)
        prof = w.sum((0, 2))
        occupied = np.flatnonzero(prof > 0.02 * prof.max())
        top = int(occupied.max())
        # its head (60-85% of its height: the reference's construct is sized by its head, its tail wider), centred on
        # itself (a bent column's top is off its foot's axis)
        y0 = int(occupied.min() + 0.60 * (top - occupied.min()))
        y1 = int(occupied.min() + 0.85 * (top - occupied.min())) + 1
        wh = w[:, y0:y1, :]
        cx = float((wh.sum((1, 2)) * np.arange(d.shape[0])).sum() / max(wh.sum(), 1e-30))
        cz = float((wh.sum((0, 1)) * np.arange(d.shape[2])).sum() / max(wh.sum(), 1e-30))
        # its diameter: twice the density-weighted rms distance from its axis x sqrt 2 (a uniform disc's radius)
        rx, rz = np.arange(d.shape[0]) - cx, np.arange(d.shape[2]) - cz
        r2 = (wh * (rx[:, None, None] ** 2 + rz[None, None, :] ** 2)).sum() / max(wh.sum(), 1e-30)
        diameter = 2.0 * float(np.sqrt(2.0 * r2))
        # its optical depth across at density_scale 1: the density summed along x through the axis, mid-height
        mid = int(np.average(np.arange(d.shape[1]), weights=prof))
        across = float(w[:, mid, int(round(cz))].sum())
        fit = g["fit"]
        grid = {"base": [cx + lo[0] + off[0] + 0.5, top + lo[1] + off[1] + 1.0, cz + lo[2] + off[2] + 0.5],  # the cap
                "diameter_voxels": diameter, "scale": fit["diameter"] / diameter,
                "density_scale": fit["tau"] / max(across, 1e-9)}
    glitter = None
    if "glitter" in g and grid is not None:  # tiny emitters on the funnel's key-lit surface (glitter_points)
        spec = g["glitter"]
        axes = [np.array(sf.rotate(e, g["rotation"])) for e in np.eye(3)]  # the volume's axes in the world
        key = np.asarray(g["key"], float) / np.linalg.norm(g["key"])
        pts = glitter_points(d, spec["n"], [float(a @ key) for a in axes], spec["threshold"], seed=spec.get("seed", 0),
                             power=spec.get("power", 4.0))
        pose = dict(lantern.pose(shot), base=grid["base"], scale=grid.get("scale", g["scale"]))
        glitter = {"p": [[float(v) for v in sf.to_world([q[a] + lo[a] + off[a] + 0.5 for a in range(3)], **pose)] for q in pts],
                   "size": spec["size"], "rgb": list(spec["rgb"]), "radiance": spec["radiance"]}
    ix, iy = np.indices(d.shape[:2], dtype=np.float64)
    spec = g.get("glow", {"heights": ()})
    lights = []
    for h in spec["heights"]:
        k = int(round(h - lo[2] - off[2] - 0.5))  # the slice's array index
        k = min(max(k, 0), d.shape[2] - 1)
        s = d[:, :, k].astype(np.float64)
        w = max(s.sum(), 1e-9)
        axis = ((s * ix).sum() / w + lo[0] + off[0] + 0.5, (s * iy).sum() / w + lo[1] + off[1] + 0.5, h)
        p = np.array(sf.to_world(axis, **lantern.pose(shot)))
        p = p + spec.get("outside", 0.0) * np.asarray(g["key"]) / np.linalg.norm(g["key"])  # out toward the key
        lights.append({"set": "glow", "p": [float(v) for v in p], "intensity": [spec["power"] / spec["n"] * c for c in spec["rgb"]]})
    path = out_dir / (name + "_lights.json")
    path.write_text(json.dumps(dict({"lights": lights}, **({"grid": grid} if grid else {}),
                                    **({"glitter": glitter} if glitter else {})), indent=1))
    return dest, path


def vbx_offset(dest, stem, lo):
    """The imported .vbx's coordinates minus the .vdb's index box corner `lo`: the VDB's own grid offset."""
    import struct
    with open(Path(dest) / (stem + "_mip0.vbx"), "rb") as fh:
        b = fh.read(260)
    origin = struct.unpack("<3f", b[98:110])
    return tuple(origin[a] - lo[a] for a in range(3))


FIRE01_SRC = str(REPO / "Fire_01" / "Fire_01" / "embergen_fire_a_%d.vdb")
FIRE01_DIR = REPO / "VolumetricReSTIRData" / "fire01"


def write_fire01(frame, n=1024):
    """A frame of EmberGen's fire (Fire_01, the user's dataset, CC0: frame 67 is the swatch's) for the teapot, prepared
    as the swatch's frame is: VolumetricReSTIRData/fire01/fire01_<frame> ('flames' renamed to density by VDBPrep) and
    fire01_<frame>_lights.json (fire_light_table, positions in the .vbx's coordinates for swatch_fire.to_world)."""
    import json
    name = "fire01_%d" % frame
    with tempfile.TemporaryDirectory() as work:
        vdb = Path(work) / (name + ".vdb")
        run([RELEASE / "VDBPrep.exe", FIRE01_SRC % frame, vdb, "flames=density"], cwd=RELEASE)
        dest = import_vdb(vdb, FIRE01_DIR, emissive=True)
    lo, box = read_vdb_box(FIRE01_SRC % frame, ("flames",))
    off = vbx_offset(dest, name, lo)
    if any(abs(off[a] - FIRE_OFFSET[a]) > 1e-3 for a in range(3)):
        raise SystemExit("FAILED: %s's grid offset %s is not the swatch frame's %s" % (name, off, FIRE_OFFSET))
    table = fire_light_table(box["flames"], n=n)
    for l in table["lights"]:
        l["p"] = [l["p"][a] + lo[a] + FIRE_OFFSET[a] + 0.5 for a in range(3)]
    path = FIRE01_DIR / (name + "_lights.json")
    path.write_text(json.dumps(table, indent=1))
    return dest, path


BUILDERS = {"stagehaze": stage_haze, "groundmist": ground_mist, "smokepuffs": smoke_puffs}


# The EmberGen dust shockwave, reshaped toward the user's reference render (2026-10-11: "keep frame 50's data, but
# clear the dust carpet out of the hole and rebuild the density at billow scale: smooth it coarsely, then sharpen it
# back into separate round puffs with fine fuzz on top"). The exported density is nearly binary -- active voxels sit at
# its 0.1 cap -- so every surface is a hard edge (the popcorn look), and a 12-voxel carpet covers the hole's floor.

def _column_radii(d):
    """The z-up volume's column density (x, y) and each column's distance from its centre of mass."""
    top = d.sum(2, dtype=np.float64)
    w = top / max(top.sum(), 1e-12)
    X, Y = np.meshgrid(np.arange(top.shape[0]), np.arange(top.shape[1]), indexing="ij")
    return top, np.hypot(X - (w * X).sum(), Y - (w * Y).sum())


def hole_radius(d, frac=0.1, step=1.0):
    """Where the ring's wall starts: the first radius (from the ring's axis) at which the column density has risen
    `frac` of the way from the carpet's level (the innermost tenth of the dust's radius) to the ring's peak."""
    top, r = _column_radii(d)
    edges = np.arange(0.0, r.max() + step, step)
    idx = np.digitize(r.ravel(), edges) - 1
    prof = np.bincount(idx, weights=top.ravel(), minlength=len(edges)) / np.maximum(np.bincount(idx, minlength=len(edges)), 1)
    r_max = edges[np.nonzero(prof > 0)[0].max()]
    carpet = prof[edges < 0.1 * r_max].mean()
    rise = np.nonzero((prof > carpet + frac * (prof.max() - carpet)) & (edges > 0.1 * r_max))[0]
    return float(edges[rise[0]]) if rise.size else 0.0


def clear_hole(d, r_hole, width):
    """The hole emptied: every column inside r_hole - width cleared, fading back in to the full dust at r_hole."""
    _, r = _column_radii(d)
    return (d * smoothstep(r_hole - width, r_hole, r)[..., None]).astype(np.float32)


def billows(d, coarse, level=0.5, softness=0.1, fuzz=0.5, fine=1.0):
    """The density rebuilt at billow scale (0..1): smoothed by `coarse` voxels (thin bridges and crumbs melt away,
    lumps round off), plus `fuzz` times the frame's own detail finer than that (its smoothing by `fine` voxels less
    the coarse one -- zero in the cores and in clear air, so it only roughens the edges), then sharpened back into
    puffs by a soft step `softness` wide at `level`."""
    n = d / max(float(d.max()), 1e-12)
    g = ndimage.gaussian_filter(n, coarse)
    s = g + fuzz * (ndimage.gaussian_filter(n, fine) - g) if fuzz else g
    return smoothstep(level - softness, level + softness, s).astype(np.float32)


def balls(shape, centres, radii):
    """The union (0..1) of soft balls: 1 out to 0.6 of each radius, falling to 0 at it."""
    out = np.zeros(shape, np.float32)
    for c, rad in zip(centres, radii):
        lo = [max(0, int(c[a] - rad - 1)) for a in range(3)]
        hi = [min(shape[a], int(c[a] + rad + 2)) for a in range(3)]
        ax = [np.arange(lo[a], hi[a], dtype=np.float32) - c[a] for a in range(3)]
        dist = np.sqrt(ax[0][:, None, None] ** 2 + ax[1][None, :, None] ** 2 + ax[2][None, None, :] ** 2)
        win = out[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]]
        np.maximum(win, 1 - smoothstep(0.6 * rad, rad, dist), out=win)
    return out


def puffs(d, scale, size=1.0, min_mass=0.2):
    """Round puffs where the frame's dust is massed: one at each local maximum of its density smoothed by `scale`
    voxels (above `min_mass`), a soft ball of radius size * scale * (0.6 + 0.8 * that smoothed density) -- more dust,
    a bigger puff. Returns their union (0..1), the centres (voxel indices) and the radii."""
    n = d / max(float(d.max()), 1e-12)
    g = ndimage.gaussian_filter(n, scale)
    centres = np.argwhere((g == ndimage.maximum_filter(g, size=int(2 * scale) + 1)) & (g > min_mass))
    radii = np.array([size * scale * (0.6 + 0.8 * float(g[tuple(c)])) for c in centres])
    return balls(n.shape, centres, radii), centres, radii


def puffed(d, scale, size=2.0, mix=0.35, fuzz=0.6, level=0.5, softness=0.15, coarse=6.0, fine=1.0,
           detail_scale=None, detail_size=1.5):
    """The frame rebuilt as puffs (0..1): puffs() at `scale`; with `detail_scale`, cauliflower -- smaller puffs at that
    scale wherever one's centre lies on a big puff's shell (its value there 0.15-0.85), none in the gaps; blended with
    `mix` of the frame's own density smoothed by `coarse` voxels (so the puffs keep the dust's shape, not perfect
    spheres); fuzzed by `fuzz` times its detail finer than that, only where there is a puff (no crumbs in the gaps);
    then a soft step `softness` wide at `level`."""
    n = d / max(float(d.max()), 1e-12)
    p, centres, _ = puffs(d, scale, size)
    if detail_scale:
        _, sc, sr = puffs(d, detail_scale, detail_size)
        on_shell = np.array([0.15 <= p[tuple(c)] <= 0.85 for c in sc], bool) if len(sc) else np.zeros(0, bool)
        p = np.maximum(p, balls(p.shape, sc[on_shell], sr[on_shell]))
    g = ndimage.gaussian_filter(n, coarse)
    s = (1 - mix) * p + mix * g
    if fuzz:
        s = s + fuzz * (ndimage.gaussian_filter(n, fine) - g) * smoothstep(0.05, 0.3, p)
    return smoothstep(level - softness, level + softness, s).astype(np.float32), len(centres)


def fur(d, depth=3.0, reach=4.0, strand=1.5, seed=0, soft=0.08, thin=0.6):
    """The frame's surfaces made fluffy (0..1), its shape kept: the exported dust is binary (every active voxel at the
    0.1 cap), so each billow is a hard wall that light cannot enter. Measured by the signed distance to that wall,
    voxels deeper than `depth` stay solid; across the shell from `depth` inside to `reach` outside, fine noise
    (strands about `strand` voxels thick) decides which are dust -- all at the inner edge, about half at the surface,
    none at the reach -- and the strands thin toward their tips (`thin`), so the fringe is translucent."""
    solid = d > 0.5 * float(d.max())
    s = (ndimage.distance_transform_edt(solid) - ndimage.distance_transform_edt(~solid)).astype(np.float32)
    t = np.clip((depth - s) / (depth + reach), 0.0, 1.0)  # 0 at `depth` inside, 1 at `reach` outside
    noise = fbm(d.shape, cell=2.0 * strand, octaves=2, seed=seed)
    # the noise's own distribution mapped to uniform, so a threshold t keeps a fraction 1 - t of the voxels
    sample = noise.ravel()[np.random.default_rng(seed).integers(0, noise.size, 200000)]
    q = np.percentile(sample, np.linspace(0, 100, 201))
    u = np.interp(noise, q, np.linspace(0.0, 1.0, 201)).astype(np.float32)
    keep = smoothstep(t * (1 + 2 * soft) - 2 * soft, t * (1 + 2 * soft), u)
    return (keep * (1 - thin * t)).astype(np.float32)


DUST_SOURCE = REPO / "DustShockwaveVDB" / "DustShockwave" / "DustShockwaveVDB"
DUST_OUT = REPO / "VolumetricReSTIRData" / "dustShockwave"
RESHAPE = {"coarse": 6.0, "level": 0.5, "softness": 0.15, "fuzz": 0.6, "fine": 1.0, "hole_width": 25.0}


def dust_reshaped(frame=50, work=None, **kw):
    """Frame `frame` of the EmberGen dust shockwave read back from its .vdb (VdbToRaw.exe), its hole cleared and its
    density rebuilt by billows(); returns the 0..1 density (x, y, z: z up, as the data)."""
    p = dict(RESHAPE, **kw)
    raw = Path(work) / ("dust%04d.raw" % frame)
    out = run([RELEASE / "VdbToRaw.exe", DUST_SOURCE / ("dustshockwave_%04d.vdb" % frame), "density", raw], cwd=RELEASE).split()
    dims = tuple(int(v) for v in out[5:8])
    d = np.fromfile(str(raw), dtype=np.float32).reshape(dims)
    r_hole = hole_radius(d)
    d = clear_hole(d, r_hole, p["hole_width"])
    print("  frame %d: %s voxels, hole radius %.0f" % (frame, "x".join(map(str, dims)), r_hole))
    return billows(d, p["coarse"], p["level"], p["softness"], p["fuzz"], p["fine"])


def latlong_dir(u, v):
    """The world direction of lat-long texture coordinates in Falcor's convention (world_to_latlong_map:
    u = atan2(x, -z) / 2pi + 0.5, v = acos(y) / pi), so u = 0.5 looks down -z and v = 0 straight up."""
    phi, theta = (np.asarray(u, float) - 0.5) * 2 * np.pi, np.asarray(v, float) * np.pi
    return np.stack(np.broadcast_arrays(np.sin(theta) * np.sin(phi), np.cos(theta), -np.sin(theta) * np.cos(phi)), axis=-1)


# The dust shockwave's studio, matched to the user's reference render (2026-10-11; outputs/decorr/match_reference.py,
# swept over key directions, heights, fills and ambients, the version the user chose): a soft box low behind the ring,
# a little to the left (18 degrees up, 20 degrees off straight behind) -- its tops lit, its near faces in shadow, its
# long shadow across the studio floor before it (scenes/dust_studio.pyscene) -- a weak fill behind the camera and a
# soft ambient sky that keeps that shadow from going black. Light from 99 degrees in the picture (the reference: 103),
# shading 102 (104), contrast and colour ratio as the reference's. The camera looks down -z.
def studio_dir(az_deg, el_deg):
    """A direction from the scene: `az_deg` around from straight behind the ring (-z) toward the camera's left (-x),
    `el_deg` up."""
    a, e = np.radians(az_deg), np.radians(el_deg)
    return (-np.sin(a) * np.cos(e), np.sin(e), -np.cos(a) * np.cos(e))


STUDIO_KEY = studio_dir(20, 18)
STUDIO_FILL = None  # the key's other side, behind the camera


def studio_sky(key=STUDIO_KEY, width=1024, key_radiance=320.0, key_radius=5.0, fill_radiance=0.5,
               backdrop=(0.0025, 0.006), fill=STUDIO_FILL, ambient=0.15):
    """A photo studio as an environment map (RGB, rows from the zenith): a slate cyclorama whose brightness runs from
    backdrop[0] (the floor, 33 degrees down and below) to backdrop[1] (7 degrees down and up) -- the camera, 20
    degrees down with a 70 mm lens, sees that range -- one large soft box toward `key` (soft-edged, `key_radius`
    degrees, a little brighter at its centre) and a fill toward `fill` (None: the key's other side, behind the
    camera), both out of shot; `ambient`: a uniform sky over the upper hemisphere (the soft light a studio's walls and
    ceiling give, which keeps a cast shadow from going black)."""
    h = width // 2
    d = latlong_dir(((np.arange(width) + 0.5) / width)[None, :], ((np.arange(h) + 0.5) / h)[:, None])
    k = np.asarray(key, float) / np.linalg.norm(key)
    c = d @ k
    r = np.radians(key_radius)
    box = smoothstep(np.cos(1.4 * r), np.cos(0.7 * r), c) + 0.05 * smoothstep(np.cos(0.7 * r), 1.0, c)
    # the fill: by default the key's other side, behind the camera too (out of shot)
    f = np.array([-k[0], 0.3, abs(k[2])]) if fill is None else np.asarray(fill, float)
    fill = smoothstep(np.cos(np.radians(40)), np.cos(np.radians(20)), d @ (f / np.linalg.norm(f)))
    base = backdrop[0] + (backdrop[1] - backdrop[0]) * smoothstep(-0.55, -0.12, d[..., 1])
    sky = base[..., None] * np.array([0.78, 0.88, 1.0]) + (key_radiance * box)[..., None] * np.array([1.0, 0.98, 0.95]) \
        + (fill_radiance * fill)[..., None] * np.array([0.9, 0.95, 1.0]) \
        + (ambient * smoothstep(-0.05, 0.1, d[..., 1]))[..., None] * np.array([0.9, 0.95, 1.0])
    return sky.astype(np.float32)


def lantern_sky(name="lantern_sky", width=1024):
    """A green tornado's sky (lantern.SKIES[name]): white Gaussian lobes -- the glow and the key -- over a teal,
    brighter below, scaled by the sky's `teal`."""
    import lantern
    spec = lantern.SKIES[name]
    h = width // 2
    d = latlong_dir(((np.arange(width) + 0.5) / width)[None, :], ((np.arange(h) + 0.5) / h)[:, None])
    sky = np.zeros(d.shape, np.float64)
    for lobe in ("glow", "key"):
        k = np.asarray(spec[lobe], float) / np.linalg.norm(spec[lobe])
        angle = np.degrees(np.arccos(np.clip(d @ k, -1, 1)))
        sky += (spec[lobe + "_radiance"] * np.exp(-(angle / spec[lobe + "_width"]) ** 2))[..., None] * np.array([1.0, 1.0, 0.96])
    teal_g = np.clip(0.1 - 0.13 * d[..., 1], 0.04, 0.2)  # brighter below
    sky += spec["teal"] * 1.12 * teal_g[..., None] * np.array([0.5, 1.0, 1.02])
    return sky.astype(np.float32)


SKIES = {"studio_softbox": studio_sky, "lantern_sky": lambda: lantern_sky("lantern_sky"),
         "lantern_night": lambda: lantern_sky("lantern_night")}


def cast_iron_normals(size=4096, seed=7, strength=1.0, features=(9, 90), pits=0.0):
    """A seamless tangent-space normal map (unit vectors, z out of the surface) of cast iron, for the swatch teapot
    (user's reference, 2026-10-11): a height field made periodic by building it in the Fourier domain (random phases
    under a power-law spectrum, band-limited to `features` texels), optionally deepened into casting pits (`pits`), its
    gradient by wrapped differences, scaled by `strength`. The teapot's UVs run 45 cm a unit, so at 4096 texels the
    default band is 0.1..1 cm -- the soft hammered dents of RenderMan's fractal bump (rman_teapot_fire.py: PxrFractal,
    frequency 1.2 a cm, six octaves); grains of a few texels shrink below a pixel in the shot and glitter."""
    rng = np.random.default_rng(seed)
    fx = np.fft.fftfreq(size)[None, :]
    fy = np.fft.fftfreq(size)[:, None]
    f = np.hypot(fx, fy)
    band = (f > 1.0 / features[1]) & (f < 1.0 / features[0])
    amp = np.where(band, 1.0 / np.maximum(f, 1e-6) ** 1.2, 0.0)
    spectrum = amp * np.exp(2j * np.pi * rng.random((size, size)))
    h = np.real(np.fft.ifft2(spectrum))
    h = (h - h.mean()) / (h.std() + 1e-12)
    h = h + pits * (np.minimum(h, -0.8) + 0.8)  # deepen the low spots
    dx = (np.roll(h, -1, axis=1) - np.roll(h, 1, axis=1)) * 0.5
    dy = (np.roll(h, -1, axis=0) - np.roll(h, 1, axis=0)) * 0.5
    k = 0.35 * strength * features[0] / 3.0  # the slope of the bumps, not of the texels, kept as the band moves
    n = np.stack([-k * dx, -k * dy, np.ones_like(h)], axis=-1)
    return (n / np.linalg.norm(n, axis=-1, keepdims=True)).astype(np.float32)


def encode_normals(n):
    """Unit normals -> an 8-bit RGB normal map (0.5 + 0.5 n), as Falcor's normal slot reads it (linear, not sRGB)."""
    return np.clip(np.round((0.5 + 0.5 * np.asarray(n)) * 255), 0, 255).astype(np.uint8)


def write_texture(name):
    import cv2
    path = REPO / "VolumetricReSTIRData" / "swatch" / (name + ".png")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), encode_normals(TEXTURES[name]())[..., ::-1].copy()):  # OpenCV writes BGR
        raise SystemExit("FAILED: could not write %s" % path)
    return path


# half strength: the target pot's level and matte look (the full slope sheens and darkens its lower half)
TEXTURES = {"castiron_normal": lambda: cast_iron_normals(strength=0.5)}


# The swatch fire's colour as RenderMan renders it: its PxrBlackBody reads the grid's temperature (0..1.27) as kelvin,
# below the node's 1000 K floor, so the whole flame emits the floor's colour -- its Rec.709 table's first knot -- times
# 2^exposure (rman_teapot_fire.py: measured on the render, green / red 0.0087, no blue). Deep red: the clipped display
# turns the dense core yellow (green past 1), the thin edges red.
RMAN_FIRE_RGB = (1.0, 0.008654, 0.0)
SWATCH_FIRE = REPO / "RenderMan_Swatch_Blender" / "VDB" / "embergen_fire_a_67.vdb"
FIRE_OFFSET = (-96.5, -96.5, -128.5)  # the VDB's index -> its .vbx coordinates (its grid transform)


def read_swatch_flames():
    """The swatch fire's 'flames' grid (VdbToRaw.exe): its index box's low corner and the array, x slowest."""
    with tempfile.TemporaryDirectory() as work:
        raw = Path(work) / "flames.raw"
        out = run([RELEASE / "VdbToRaw.exe", SWATCH_FIRE, "flames", raw], cwd=RELEASE).split()
        lo, dims = [int(v) for v in out[1:4]], [int(v) for v in out[5:8]]
        return lo, np.fromfile(str(raw), dtype=np.float32).reshape(dims)


def write_fire_lights(n=1024):
    """VolumetricReSTIRData/swatch/fire_lights.json: fire_light_table() on the swatch fire's 'flames' grid (read with
    VdbToRaw.exe), positions in the .vbx's voxel coordinates (swatch_fire.to_world places them). 1024 lights: with 256
    the pot's inner wall came out patchy, each light's 1 / r^2 where the target's flame lights it evenly."""
    import json
    lo, flames = read_swatch_flames()
    table = fire_light_table(flames, n=n)
    for l in table["lights"]:  # array index -> the VDB's index -> its .vbx coordinates, at the voxel's centre
        l["p"] = [l["p"][a] + lo[a] + FIRE_OFFSET[a] + 0.5 for a in range(3)]
    path = REPO / "VolumetricReSTIRData" / "swatch" / "fire_lights.json"
    path.write_text(json.dumps(table, indent=1))
    return path


def fire_light_table(flames, n=64, seed=0):
    """Point lights standing in for the fire's light on the surfaces around it (this renderer's surfaces take no light
    from a glowing volume; RenderMan renders the fire as a light, emitting density x colour per unit length): `n`
    voxels drawn in proportion to their flame density (array index coordinates), each carrying an equal share `w`.
    With the fire's total density `flames_sum` (summed over voxels) and its colour `rgb`, the scene gives each light
    the intensity w x flames_sum x (voxel size)^3 x 2^exposure x rgb: what its share of the volume emits."""
    flat = np.maximum(flames, 0.0).ravel().astype(np.float64)
    lights = []
    if flat.sum() > 0:
        rng = np.random.default_rng(seed)
        # stratified draws over the cumulative density: an even spread of the fire's power
        cdf = np.cumsum(flat) / flat.sum()
        for i in np.searchsorted(cdf, (np.arange(n) + rng.random(n)) / n):
            idx = np.unravel_index(int(min(i, flat.size - 1)), flames.shape)
            lights.append({"p": [float(v) for v in idx], "w": 1.0 / n})
    return {"rgb": list(RMAN_FIRE_RGB), "flames_sum": float(flat.sum()), "lights": lights}


def lut_array(kelvin):
    """blackbody.lut over an array of kelvin: (..., 3)."""
    import blackbody
    table = np.array(blackbody.rows())
    x = np.clip((np.minimum(kelvin, 6400.0) - 50.0) / 50.0, 0.0, 127.0)
    i = np.minimum(x.astype(int), 126)
    f = (x - i)[..., None]
    return table[i] * (1 - f) + table[i + 1] * f


def emission_light_table(density, temperature, n, cutoff, scale, voxel, sigma_a, le_scale, seed=0):
    """Point lights standing in for an emissive volume's glow on the surfaces around it (this renderer's surfaces take
    no light from a glowing volume by light sampling): what each voxel emits as GVDB renders it -- sigma_a x density x
    LeScale x the LUT at (T - cutoff) x scale kelvin, per unit length, times the voxel's volume -- and `n` voxels drawn
    in proportion to its luminance (stratified), each light in its voxel's colour with an equal share of the
    luminance. Positions are array indices; `total` the volume's emission (RGB intensity). Only voxels that can glow
    (temperature and density above 0) are evaluated: a fire plume frame has 62M voxels, too many to colour at once."""
    temperature = np.asarray(temperature)
    density = np.asarray(density)
    where = np.flatnonzero((temperature > 0) & (density > 0))  # C order, as the dense draw ran
    kelvin = np.minimum(6400.0, (temperature.ravel()[where].astype(np.float64) - cutoff) * scale)
    rgb = lut_array(kelvin) * (sigma_a * le_scale * voxel ** 3) * density.ravel()[where].astype(np.float64)[:, None]
    lum = rgb @ np.array([0.2126, 0.7152, 0.0722])
    total = rgb.sum(0) if len(where) else np.zeros(3)
    lights = []
    if lum.sum() > 0:
        rng = np.random.default_rng(seed)
        cdf = np.cumsum(lum) / lum.sum()
        share = lum.sum() / n
        # the first voxel whose cumulative share reaches each draw: always one that glows, as over the dense array
        for k in np.searchsorted(cdf, (np.arange(n) + rng.random(n)) / n):
            k = int(min(k, len(where) - 1))
            idx = np.unravel_index(int(where[k]), density.shape)
            c = rgb[k] / lum[k]
            lights.append({"p": [float(v) for v in idx], "intensity": [float(share * v) for v in c]})
    return {"total": [float(v) for v in total], "lights": lights}


def write_raw(d, path):
    """C order, x slowest: VolFromRaw reads data[(i * ny + j) * nz + k] as voxel (i, j, k)."""
    np.ascontiguousarray(d, dtype=np.float32).tofile(str(path))


def run(cmd, cwd):
    r = subprocess.run([str(c) for c in cmd], cwd=str(cwd), capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("FAILED (exit %d): %s\n%s" % (r.returncode, cmd[0], (r.stdout or "")[-2000:]))
    return r.stdout


def convert(name, d, work, voxel=None, out_dir=None, temperature=None):
    """density (and a temperature, for an emissive volume) -> <out_dir, default VolumetricReSTIRData/authored>/<name>/
    (.vbx mips, and <name>_temperature.vbx); voxel size from volume_boxes."""
    voxel = voxel or vb.BOXES[name][2]
    out_dir = Path(out_dir) if out_dir else OUT_DIR
    raw, vdb = Path(work) / (name + ".raw"), Path(work) / (name + ".vdb")
    write_raw(d, raw)
    extra = []
    if temperature is not None:
        extra = [1e-4, Path(work) / (name + "_temperature.raw")]
        write_raw(temperature, extra[1])
    print(run([RELEASE / "VolFromRaw.exe", raw, *d.shape, voxel, vdb, *extra], cwd=RELEASE).strip())
    return import_vdb(vdb, out_dir, emissive=temperature is not None)


def import_vdb(vdb, out_dir, emissive=False):
    """A .vdb with a 'density' grid (and 'temperature', if emissive) -> <out_dir>/<its stem>/ (.vbx mips and
    <stem>_temperature.vbx), by gImportVDB."""
    vdb, out_dir = Path(vdb), Path(out_dir)
    name = vdb.stem
    staged = GIMPORT_DIR / name   # gImportVDB writes a folder named after the .vdb into its cwd
    if staged.exists():
        shutil.rmtree(staged)
    run([GIMPORT_DIR / "gImportVDB.exe", vdb, NUM_MIPS], cwd=GIMPORT_DIR)
    dest = out_dir / name
    if dest.exists():
        shutil.rmtree(dest)
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staged), str(dest))
    if not vp.vbx_complete(dest, name, NUM_MIPS):
        raise SystemExit("FAILED: %s is missing .vbx files after import" % dest)
    import vbx_tools  # an atlas too deep for one Texture3D re-laid wider (untouched otherwise: byte-identical)
    for vbx in sorted(dest.glob("*.vbx")):
        vbx_tools.widen_file(vbx)
    if emissive and not (dest / (name + "_temperature.vbx")).exists():
        raise SystemExit("FAILED: %s has no temperature .vbx after import" % dest)
    return dest


def write_sky(name):
    """VolumetricReSTIRData/authored/<name>.exr (OpenEXR, float)."""
    import os
    os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
    import cv2
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / (name + ".exr")
    if not cv2.imwrite(str(path), SKIES[name]()[..., ::-1].copy()):  # OpenCV writes BGR
        raise SystemExit("FAILED: could not write %s" % path)
    return path


def main(argv):
    names = argv[1:] or list(BUILDERS) + list(SKIES)
    for name in names:
        if name in SKIES:
            print("%s -> %s" % (name, write_sky(name)))
            continue
        if name in TEXTURES:
            print("%s -> %s" % (name, write_texture(name)))
            continue
        if name == "teapotflame":  # an emissive volume: density, temperature and the lights standing in for its glow
            t0 = time.time()
            print("%s -> %s, %s (%.0fs)" % (name, *write_teapot_fire(), time.time() - t0))
            continue
        if name.startswith("dust") and name.endswith("r"):  # dust0050r: frame 50 of the shockwave, reshaped
            t0 = time.time()
            with tempfile.TemporaryDirectory() as work:
                d = dust_reshaped(int(name[4:-1]), work)
                print("%s: mean %.3f, %.0f%% above 0.01 (%.0fs)" % (name, d.mean(), 100 * (d > 0.01).mean(), time.time() - t0))
                print("  ->", convert("dustshockwave_%sr" % name[4:-1], d, work, voxel=1.0, out_dir=DUST_OUT))
            continue
        t0 = time.time()
        d = BUILDERS[name]()
        print("%s: %s voxels, mean %.3f, %.0f%% above 0.01 (%.0fs)" % (name, "x".join(map(str, d.shape)), d.mean(),
                                                                      100 * (d > 0.01).mean(), time.time() - t0))
        with tempfile.TemporaryDirectory() as work:
            print("  ->", convert(name, d, work))


if __name__ == "__main__":
    main(sys.argv)
