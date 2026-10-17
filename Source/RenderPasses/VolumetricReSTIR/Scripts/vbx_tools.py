"""GVDB .vbx files (what gImportVDB writes and Falcor's SceneGVDB loads): read, written and their brick atlas widened.

gImportVDB lays a volume's bricks out 16 x 16 to a layer (SetChannelDefault(16, 16, 1)), so a big volume's atlas grows
deep: past 2 x 2040 texels SceneGVDB cannot upload it (two Texture3D parts, each at most 2048 deep). The layout is the
file's own -- GVDB's LoadVBX sizes the atlas from the file's brick counts -- so widen() re-lays the bricks 32 or 64 to a
layer, moving each brick (with its apron) and the leaf node that points at it: the same voxels, a shallower atlas.

File layout (GVDB's SaveVBX, version 1.12, one grid): a header (version, the grid's transforms, for 1.12 the VDB
transforms, voxel bounds and value range), the grid count and the grid offset table; then the grid: its header (name,
data type, brick count, dims and apron, channel count, atlas size, topology and layout, the atlas's brick counts and
resolution, levels, root), a row per level (log2 dim, res, range, node and child-list counts and widths), the node
pools (pool 0, the nodes: per level, count x width bytes; then pool 1, the child lists), and the atlas, per channel:
its type, its stride and the atlas's z slices. A leaf node's mValue (bytes 16-27, int3) is its brick's interior's
position in the atlas: the brick's corner plus the apron.
"""
import struct
from pathlib import Path

import numpy as np

GRID_HEAD = struct.Struct("<256s3B3fi3iiiQBiB3i3iiQ")  # name .. root (SaveVBX's fields, in order)
LEVEL = struct.Struct("<ii3iiiii")  # log2 dim, res, range, pool-0 count, width, pool-1 count, width
MVALUE = 16  # a node's mValue (int3), bytes into its pool-0 row
MPOS = 4  # its mPos (int3)
MAX_DEPTH = 2040  # one Texture3D's worth of 10-texel brick layers (2048 // 10 x 10)
DTYPES = {1: np.uint8, 2: np.uint16, 4: np.float32}


def read_vbx(path):
    """A .vbx file as a dict: its leading bytes (header and grid table, kept as they are), the grid's header fields,
    its levels, its pools (bytes) and its channels (type, stride, atlas as an array, z by y by x)."""
    data = Path(path).read_bytes()
    major, minor = data[0], data[1]
    o = 2
    if (major == 1 and minor >= 11) or major > 1:
        o += 48  # pre-translation, angles, scale, translation
    if minor == 12:
        o += 64 + 64 + 12 + 12 + 4 + 4  # VDB transform and inverse, effective voxel bounds, value range
    ngrids = struct.unpack_from("<i", data, o)[0]
    o += 4 + (1 if major >= 2 else 0)
    if ngrids != 1:
        raise ValueError("%s: %d grids (only one supported)" % (path, ngrids))
    g0 = struct.unpack_from("<Q", data, o)[0]
    o += 8
    if g0 != o:
        raise ValueError("%s: the grid does not follow its offset table" % path)
    f = GRID_HEAD.unpack_from(data, o)
    o += GRID_HEAD.size
    keys = ("name", "dtype", "components", "compression", "voxel", "leafcnt", "leafdim", "apron", "nchan", "atlas_sz",
            "topology", "reuse", "layout", "axiscnt", "axisres", "levels", "root")
    vals = [f[0], f[1], f[2], f[3], f[4:7], f[7], f[8:11], f[11], f[12], f[13], f[14], f[15], f[16], f[17:20], f[20:23],
            f[23], f[24]]
    grid = dict(zip(keys, vals))
    levels = []
    for _ in range(grid["levels"]):
        lv = LEVEL.unpack_from(data, o)
        o += LEVEL.size
        levels.append({"logdim": lv[0], "res": lv[1], "range": lv[2:5], "cnt0": lv[5], "w0": lv[6], "cnt1": lv[7], "w1": lv[8]})
    pools = [[], []]
    for p, (cnt, wid) in enumerate((("cnt0", "w0"), ("cnt1", "w1"))):
        for lv in levels:
            n = lv[cnt] * lv[wid]
            pools[p].append(bytearray(data[o:o + n]))
            o += n
    channels = []
    W, H, D = grid["axisres"]
    for _ in range(grid["nchan"]):
        ctype, stride = struct.unpack_from("<ii", data, o)
        o += 8
        n = W * H * D * stride
        atlas = np.frombuffer(data, DTYPES[stride], W * H * D, o).reshape(D, H, W).copy()
        o += n
        channels.append({"type": ctype, "stride": stride, "atlas": atlas})
    return {"prefix": data[:g0], "grid": grid, "levels": levels, "pools": pools, "channels": channels, "tail": data[o:]}


def write_vbx(v, path):
    g = v["grid"]
    out = [v["prefix"], GRID_HEAD.pack(g["name"], g["dtype"], g["components"], g["compression"], *g["voxel"], g["leafcnt"],
                                       *g["leafdim"], g["apron"], g["nchan"], g["atlas_sz"], g["topology"], g["reuse"],
                                       g["layout"], *g["axiscnt"], *g["axisres"], g["levels"], g["root"])]
    for lv in v["levels"]:
        out.append(LEVEL.pack(lv["logdim"], lv["res"], *lv["range"], lv["cnt0"], lv["w0"], lv["cnt1"], lv["w1"]))
    for pool in v["pools"]:
        out.extend(bytes(b) for b in pool)
    for c in v["channels"]:
        out.append(struct.pack("<ii", c["type"], c["stride"]))
        out.append(np.ascontiguousarray(c["atlas"]).tobytes())
    out.append(v["tail"])
    Path(path).write_bytes(b"".join(out))


def _leaf_field(v, at):
    lv = v["levels"][0]
    rows = np.frombuffer(bytes(v["pools"][0][0]), np.uint8).reshape(lv["cnt0"], lv["w0"])
    return rows[:, at:at + 12].copy().view(np.int32).reshape(-1, 3)


def leaf_values(v):
    """Each leaf's brick interior's position in the atlas (x, y, z voxels)."""
    return _leaf_field(v, MVALUE)


def leaf_positions(v):
    """Each leaf's position in index space."""
    return _leaf_field(v, MPOS)


def width_needed(bricks, brick_res=10):
    """Bricks a layer for an atlas no deeper than one Texture3D (MAX_DEPTH): 16 -- as gImportVDB lays it -- if that
    fits, else 32, 64 or 128."""
    for w in (16, 32, 64, 128):
        if -(-bricks // (w * w)) * brick_res <= MAX_DEPTH:
            return w
    raise ValueError("%d bricks do not fit even 128 x 128 to a layer" % bricks)


def widen(v, bx, by):
    """A copy of v with its bricks laid out bx x by to a layer: leaf i's brick in slot i (x fastest), its mValue
    moved with it; the topology and every voxel unchanged."""
    g = dict(v["grid"])
    r = g["leafdim"][0] + 2 * g["apron"]
    vals = leaf_values(v)
    n = len(vals)
    bz = -(-n // (bx * by))
    corner = (vals - g["apron"]) // r  # old brick coordinates (x, y, z)
    W, H, D = g["axisres"]
    channels = []
    for c in v["channels"]:
        old = c["atlas"].reshape(D // r, r, H // r, r, W // r, r).transpose(0, 2, 4, 1, 3, 5)  # z, y, x bricks
        bricks = old[corner[:, 2], corner[:, 1], corner[:, 0]]  # n x r x r x r (z, y, x)
        new = np.zeros((bz * by * bx, r, r, r), c["atlas"].dtype)
        new[:n] = bricks
        atlas = new.reshape(bz, by, bx, r, r, r).transpose(0, 3, 1, 4, 2, 5).reshape(bz * r, by * r, bx * r)
        channels.append(dict(c, atlas=atlas))
    slot = np.arange(n)
    new_vals = np.stack([slot % bx, (slot // bx) % by, slot // (bx * by)], 1).astype(np.int32) * r + g["apron"]
    pools = [list(p) for p in v["pools"]]
    lv = v["levels"][0]
    rows = np.frombuffer(bytes(pools[0][0]), np.uint8).reshape(lv["cnt0"], lv["w0"]).copy()
    rows[:, MVALUE:MVALUE + 12] = new_vals.view(np.uint8).reshape(n, 12)
    pools[0][0] = bytearray(rows.tobytes())
    g["axiscnt"] = (bx, by, bz)
    g["axisres"] = (bx * r, by * r, bz * r)
    g["atlas_sz"] = sum(int(np.prod(g["axisres"])) * c["stride"] for c in v["channels"])
    return dict(v, grid=g, pools=pools, channels=channels)


def node_caches(path):
    """SceneGVDB's node caches beside a .vbx (<stem>_level<n>nodes.bin, written on first load): they hold each leaf's
    atlas position, so they go when the atlas is re-laid (SceneGVDB writes them again)."""
    path = Path(path)
    return sorted(path.parent.glob(path.stem + "_level*nodes.bin"))


def widen_file(path):
    """Widen a .vbx in place if its atlas is deeper than one Texture3D, dropping its node caches; returns its bricks a
    layer (16: untouched)."""
    v = read_vbx(path)
    w = width_needed(v["grid"]["leafcnt"], v["grid"]["leafdim"][0] + 2 * v["grid"]["apron"])
    if w != v["grid"]["axiscnt"][0]:
        write_vbx(widen(v, w, w), path)
        for cache in node_caches(path):
            cache.unlink()
    return w
