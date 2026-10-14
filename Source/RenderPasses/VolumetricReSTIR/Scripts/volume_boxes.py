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
    # centimetres, the swatch teapot's units: the fire over the pot's opening (centre x 0.2, z -0.6, rim at y 21.6),
    # from inside the pot to above the frame's top
    "teapotflame": ((-7.8, 17.0, -8.6), (8.2, 37.0, 7.4), 0.1),
}

# The firework bursts (fireworks.pyscene's sparks and smokepuffs' smoke balls): centre (m) and spark-shell radius.
BURSTS = (((-14.0, 38.0, -4.0), 4.5), ((2.0, 46.0, 3.0), 5.5), ((15.0, 34.0, -2.0), 4.0),
          ((-4.0, 28.0, 6.0), 3.5), ((9.0, 52.0, -6.0), 4.5))


def dims(name):
    """The volume's voxel counts (nx, ny, nz)."""
    lo, hi, voxel = BOXES[name]
    return tuple(int(round((b - a) / voxel)) for a, b in zip(lo, hi))


# The teapot fire's medium and glow, shared by make_volumes.py (its lights carry what it emits) and vr_graph.py (which
# renders it): extinction (sigma_a + sigma_s) x density per cm, smoke grey (albedo 0.75); temperature 0..1 in the grid
# read at (T - cutoff) x scale = 650 + 2350 T kelvin -- no glow below 650 K (the LUT is black there), so the smoke
# (T = 0) only scatters, the flame's edges glow deep red at 1300 K, its core yellow-white at 3000 K -- times LeScale.
TEAPOT_FIRE = {"sigma_a": 0.1, "sigma_s": 0.3, "density_scale": 1.0, "cutoff": -650.0 / 2350.0, "scale": 2350.0,
               "le_scale": 36.0, "lights": 1024}
