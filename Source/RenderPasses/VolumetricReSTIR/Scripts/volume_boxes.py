"""Where each authored volume sits, in world units (metres): shared by make_volumes.py, which builds them, and
vr_graph.py, which places them. A volume's voxel (i, j, k) covers box min + voxel * (i, j, k) (gImportVDB keeps the
axes and writes the .vbx in the .vdb's world units), so the loader's worldTranslation is the box's min corner at
worldScaling 1. No imports: vr_graph runs inside Mogwai.
"""
BOXES = {
    # name: (min corner, max corner, voxel size)
    "stagehaze": ((-13.0, 0.0, -14.0), (13.0, 10.0, 8.0), 0.1),     # the stage's haze, floor to above the truss
    "groundmist": ((-40.0, 0.0, -40.0), (40.0, 8.0, 40.0), 0.2),     # mist banks on the ground, fading out by 40 m
    "smokepuffs": ((-30.0, 18.0, -20.0), (30.0, 62.0, 20.0), 0.2),   # what the firework bursts leave in the air
}

# The firework bursts (fireworks.pyscene's sparks and smokepuffs' smoke balls): centre (m) and spark-shell radius.
BURSTS = (((-14.0, 38.0, -4.0), 4.5), ((2.0, 46.0, 3.0), 5.5), ((15.0, 34.0, -2.0), 4.0),
          ((-4.0, 28.0, 6.0), 3.5), ((9.0, 52.0, -6.0), 4.5))


def dims(name):
    """The volume's voxel counts (nx, ny, nz)."""
    lo, hi, voxel = BOXES[name]
    return tuple(int(round((b - a) / voxel)) for a, b in zip(lo, hi))
