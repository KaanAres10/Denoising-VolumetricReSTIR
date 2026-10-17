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


def read_vdb_box(vdb, names):
    """Grids of a .vdb (VdbToRaw.exe) in one index box: its low corner and {name: array}, x slowest."""
    grids = {}
    with tempfile.TemporaryDirectory() as work:
        for g in names:
            out = run([RELEASE / "VdbToRaw.exe", vdb, g, Path(work) / g], cwd=RELEASE).split()
            grids[g] = ([int(v) for v in out[1:4]], np.fromfile(str(Path(work) / g), np.float32).reshape([int(v) for v in out[5:8]]))
    lo = [min(grids[g][0][a] for g in names) for a in range(3)]
    hi = [max(grids[g][0][a] + grids[g][1].shape[a] for g in names) for a in range(3)]
    box = {}
    for g, (glo, arr) in grids.items():
        b = np.zeros([h - l for l, h in zip(lo, hi)], np.float32)
        o = [glo[a] - lo[a] for a in range(3)]
        b[o[0]:o[0] + arr.shape[0], o[1]:o[1] + arr.shape[1], o[2]:o[2] + arr.shape[2]] = arr
        box[g] = b
    return lo, box


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


# The Lanterns construct's profile along its axis (its radius over the head's, by the fraction of the way from the
# smoky lower-left end to the rounded head at the upper right), read off the user's reference picture: a wide smoky
# start, a neck at 50%, the head swelling to its full width at 75%, closed by a half-round cap from 82%.
FUNNEL_PROFILE = ((0.0, 0.7), (0.35, 0.55), (0.5, 0.32), (0.62, 0.72), (0.75, 1.0), (0.82, 1.0))
FUNNEL_CAP = 0.82  # where the cap starts


def funnel_radius(t, head):
    """The construct's radius (voxels) at fraction t of its length: FUNNEL_PROFILE, then a half-round cap to t = 1."""
    t = np.asarray(t, float)
    knots = np.array(FUNNEL_PROFILE)
    r = np.interp(t, knots[:, 0], knots[:, 1])
    cap = np.clip((t - FUNNEL_CAP) / (1.0 - FUNNEL_CAP), 0.0, 1.0)
    return head * r * np.sqrt(np.clip(1.0 - cap ** 2, 0.0, 1.0))


def lantern_funnel(d, head=60.0, half=75, arms=2, pitch=16.0, ridge=0.04, warp=2.5):
    """The looping tornado reshaped into the Lanterns construct (user, 2026-10-17: "make it exactly look like the
    lantern tornado; you can edit the file extensively"): a straight funnel along the tornado's own axis (its density's
    mean centre), its radius following funnel_radius() (`head` voxels at its widest), filled -- slice by slice -- with
    the tornado's own swirl structure stretched radially to that radius (its rms radius x 1.1, where it is still
    dense, lands on the new surface), so the detail is the simulation's. A crisp surface (the construct is solid: 0.55 at
    least, plus the simulation's detail), denser inside, with bands wrapping it like rings near the surface -- `arms`
    helices, so a band comes round every `pitch` voxels along the axis (~8 across the head, as in the reference) -- as
    soft ridges `ridge` of its radius high and as density in its shell, meandering with the simulation's structure
    (the reference's bands are irregular); and its lower-left end, up to the neck, left smoky
    and thin, as the reference's. Returns (density, its z-length), a (2 half)^2 x z box with the axis at its centre."""
    nx, ny, nz = d.shape
    w = d.sum((0, 1)).astype(np.float64)
    ix, iy = np.indices((nx, ny), dtype=np.float64)
    cx = float((d * ix[..., None]).sum() / max(d.sum(), 1e-9))
    cy = float((d * iy[..., None]).sum() / max(d.sum(), 1e-9))
    r2 = ((d * ((ix[..., None] - cx) ** 2 + (iy[..., None] - cy) ** 2)).sum((0, 1)) / np.maximum(w, 1e-9))
    r_src = np.maximum(ndimage.gaussian_filter1d(np.sqrt(r2), 10.0), 8.0)
    u, v = np.meshgrid(np.arange(2 * half) - half + 0.5, np.arange(2 * half) - half + 0.5, indexing="ij")
    rr, theta = np.hypot(u, v), np.arctan2(v, u)
    out = np.zeros((2 * half, 2 * half, nz), np.float32)
    ref = max(float(np.percentile(d[d > 0.01], 95)), 1e-6)
    for z in range(nz):
        t = z / (nz - 1)
        R = float(funnel_radius(t, head))
        if R < 0.5:
            continue
        k = 1.1 * r_src[z] / R
        slab = ndimage.map_coordinates(d[:, :, z], [cx + u * k, cy + v * k], order=1, mode="constant", cval=0.0)
        inner = np.clip(slab / ref, 0.0, 1.0) ** 0.7
        q = rr / R
        smoky = 1.0 - smoothstep(0.36, 0.48, t)  # the lower-left end, to the neck: the tornado's own wisps, thin
        # the solid part: a surface that follows the simulation's detail (a bumpy silhouette), denser inside, cut into
        # spiral ridges in its outer shell
        # the rings meander with the simulation's own structure (`warp` radians of phase at full density)
        bands = 0.5 + 0.5 * np.sin(arms * theta - 2 * np.pi * z / pitch + warp * inner)
        # ridges: the surface pushed out along the bands, for the key light to catch
        envelope = 1.0 - smoothstep(0.8, 1.0, q * (1.1 - 0.15 * inner) / (1.0 - ridge + ridge * bands))
        shell = smoothstep(0.55, 0.9, q)
        solid = envelope * (0.55 + 0.45 * inner) * (1.0 - shell + shell * (0.45 + 0.55 * bands))
        wisps = 0.25 * inner * (1.0 - smoothstep(0.6, 1.4, q))
        out[:, :, z] = (1 - smoky) * solid + smoky * wisps
    return out, nz


def write_lantern(shot="lantern", frame=None):
    """A frame of a green tornado shot (lantern.SHOTS: the looping tornado or the dust devil) as it is:
    VolumetricReSTIRData/<data>/<data><frame> (gImportVDB) and <data><frame>_lights.json -- its few big green lights,
    one at each of the shot's heights on the funnel's axis (the slice's density-weighted centre), moved `outside` cm
    toward the key (lantern.KEY), sharing its power, positions in world cm as lantern.py places the funnel."""
    import json
    import lantern
    import swatch_fire as sf
    g = lantern.SHOTS[shot]
    frame = g["frame"] if frame is None else frame
    name = "%s%d" % (g["data"], frame)
    src = str(REPO / (g["src"] % frame))
    out_dir = REPO / "VolumetricReSTIRData" / g["data"]
    lo, box = read_vdb_box(src, ("density",))
    d = box["density"]
    with tempfile.TemporaryDirectory() as work:
        vdb = Path(work) / (name + ".vdb")
        if g.get("author") == "funnel":  # reshaped into the Lanterns construct, written a voxel a unit (no grid offset)
            d, _ = lantern_funnel(d)
            lo = [0, 0, 0]
            raw = Path(work) / (name + ".raw")
            write_raw(d, raw)
            run([RELEASE / "VolFromRaw.exe", raw, *d.shape, 1.0, vdb], cwd=RELEASE)
            lo_file, _ = read_vdb_box(vdb, ("density",))
        else:
            shutil.copy(src, str(vdb))
            lo_file = lo
        dest = import_vdb(vdb, out_dir)
    off = vbx_offset(dest, name, lo_file)
    if any(abs(off[a] - g["offset"][a]) > 1e-3 for a in range(3)):
        raise SystemExit("FAILED: %s's grid offset %s is not %s" % (name, off, g["offset"]))
    ix, iy = np.indices(d.shape[:2], dtype=np.float64)
    spec = g["glow"]
    lights = []
    for h in spec["heights"]:
        k = int(round(h - lo[2] - off[2] - 0.5))  # the slice's array index
        k = min(max(k, 0), d.shape[2] - 1)
        s = d[:, :, k].astype(np.float64)
        w = max(s.sum(), 1e-9)
        axis = ((s * ix).sum() / w + lo[0] + off[0] + 0.5, (s * iy).sum() / w + lo[1] + off[1] + 0.5, h)
        p = np.array(sf.to_world(axis, **lantern.pose(shot)))
        p = p + spec.get("outside", 0.0) * np.asarray(lantern.KEY) / np.linalg.norm(lantern.KEY)  # out toward the key
        lights.append({"set": "glow", "p": [float(v) for v in p], "intensity": [spec["power"] / spec["n"] * c for c in spec["rgb"]]})
    path = out_dir / (name + "_lights.json")
    path.write_text(json.dumps({"lights": lights}, indent=1))
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


def lantern_sky(width=1024, glow=(-0.55, 0.35, -0.75), glow_radiance=5.0, glow_width=22.0, key=None,
                key_radiance=6.0, key_width=14.0):
    """The green tornado construct's backdrop (lantern.py): a grey-teal gradient (darker below and to the right), a
    soft white glow behind the funnel at the frame's left edge, as in the reference, and the key: a soft light from the
    upper left, in front of the funnel and out of shot, that shades its banded surface and makes it glitter."""
    key = lantern_key() if key is None else key
    h = width // 2
    d = latlong_dir(((np.arange(width) + 0.5) / width)[None, :], ((np.arange(h) + 0.5) / h)[:, None])
    sky = np.zeros(d.shape, np.float64)
    for direction, radiance, width_deg in ((glow, glow_radiance, glow_width), (key, key_radiance, key_width)):
        k = np.asarray(direction, float) / np.linalg.norm(direction)
        angle = np.degrees(np.arccos(np.clip(d @ k, -1, 1)))
        sky += (radiance * np.exp(-(angle / width_deg) ** 2))[..., None] * np.array([1.0, 1.0, 0.96])
    up = smoothstep(-0.6, 0.6, d[..., 1])
    sky += (0.03 + 0.06 * up)[..., None] * np.array([0.55, 0.85, 0.95])  # teal
    return sky.astype(np.float32)


def lantern_key():
    import lantern
    return lantern.KEY


SKIES = {"studio_softbox": studio_sky, "lantern_sky": lantern_sky}


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
