"""Where the swatch fire (RenderMan_Swatch_Blender/VDB/embergen_fire_a_67.vdb) sits on the teapot: shared by vr_graph's
load_teapot_fire, which places the volume, and scenes/teapot_fire.pyscene, which places the lights derived from it
(make_volumes.py write_fire_lights); swatch/fire_pose_tool.py poses it interactively against the reference picture.
No imports beyond math: the scene builder runs this inside Mogwai.

The .vbx keeps the VDB's coordinates: voxel x -54.5..51.5, y -91.5..24.5, z (up) -128.5..-3.5; GVDB applies them, then
SceneGVDB's T Rx Ry Rz S (Rz first). Upright is -90 about x (voxel z up); a turn about the fire's own up axis is Rz.
"""
import math

SCALE = 0.12  # cm per voxel: the flame 15 cm tall
ROTATION = (-90.0, 0.0, 90.0)  # SceneGVDB's worldRotation, degrees: upright, the side whose flame leans right
ANCHOR = (0.2, 14.0, -0.6)  # where the fire's middle and bottom go: over the opening, inside the pot (rim at 21.8)
MIDDLE = (-1.5, -33.5)  # the fire's middle, voxel x and y
BOTTOM = -128.5  # voxel z


def rotate(p, rotation=ROTATION):
    """Rx Ry Rz p, degrees, right-handed (Falcor's matrixFromRotationX/Y/Z)."""
    a, b, c = (math.radians(v) for v in rotation)
    x, y, z = p
    x, y = x * math.cos(c) - y * math.sin(c), x * math.sin(c) + y * math.cos(c)
    x, z = x * math.cos(b) + z * math.sin(b), -x * math.sin(b) + z * math.cos(b)
    y, z = y * math.cos(a) - z * math.sin(a), y * math.sin(a) + z * math.cos(a)
    return (x, y, z)


def translation(scale=SCALE, rotation=ROTATION, anchor=ANCHOR, middle=MIDDLE, bottom=BOTTOM, base=None):
    """The volume's worldTranslation: its base -- a voxel point, by default its middle (voxel x, y) and bottom (voxel
    z) -- at the anchor."""
    m = rotate(base if base is not None else (middle[0], middle[1], bottom), rotation)
    return tuple(anchor[i] - scale * m[i] for i in range(3))


def to_world(p, scale=SCALE, rotation=ROTATION, anchor=ANCHOR, middle=MIDDLE, bottom=BOTTOM, base=None):
    """A point in the .vbx's voxel coordinates -> world (cm, y up), as SceneGVDB places the volume."""
    t = translation(scale, rotation, anchor, middle, bottom, base)
    q = rotate(p, rotation)
    return tuple(t[i] + scale * q[i] for i in range(3))


POSE_KEYS = ("scale", "rotation", "anchor", "middle", "bottom", "base")


def pose(seq):
    """A sequence's placement, as translation() / to_world() take it."""
    return {k: seq[k] for k in POSE_KEYS if k in seq}


# The other EmberGen volumes the user added (2026-10-13/14, CC0), each shown over the opening as one chosen frame
# (TEAPOT_FRAME to pick one; make_volumes.py write_sequence prepares a frame): where the source is, the grids it renders
# (renamed by VDBPrep when the source names them otherwise) and the one its glow and lights are read from (glow_grid); its pose (its
# .vbx grid offset from the source's index box, checked on every frame); its medium and glow. Their smoke is dark soot,
# albedo 0.1, extinction 0.45 a cm at density 1 (densityScale x sigma_t / scale); a temperature is read at
# (T - cutoff) x scale kelvin, black below 650 K (the LUT is). The LeScale its lights are made from sets the fire's
# light on the scene; the camera sees its glow at `glow` (1/8) of that. Shown as they emit, these fires were 10-50x
# display white -- half their own glow, half their lights' light scattered back by grey (0.6) smoke -- and clipped flat
# (user, 2026-10-14: no detail in the volume); the dark smoke and dimmer glow keep their turbulence in view (90th
# percentile 3x white, from 22x; the user chose 1/8 over 1/16) and the scene lit as before. Not energy-balanced: the
# lights carry 8x the glow seen.
#   gasoline: Gasoline_Explosion_01, z up, its ground at voxel z 0 (.vbx -192.5), its bottom at the pot's depth, scaled
# so its fireball spans the opening; 180 + 1880 T kelvin (T 0..2), 2000-2600 K in the fireball; LeScale 53.3 (120 at
# sigma_a 0.4) makes its light ~6000 in red intensity, the backdrop the reference's level (at 200, the RenderMan-matched fire's 10^4, it was
# 1.5x the reference's and the fireball blew out: user, too exposed).
#   midair: Midair_Explosion_01, y up: its fireball launches from the domain's floor (voxel y -188, which every frame
# touches) and shoots 110 voxels up by frame 25, then drifts in +z. Its launch point inside the pot, so it bursts from
# the opening (user, 2026-10-15: "comes from the teapot itself"; stood z-up it streaked sideways), turned 90 about the
# vertical so the drift goes right; the gasoline's medium and temperature scale, LeScale 40.9 (92 at sigma_a 0.4) for
# the same light (it emits 1.3x as much).
#   plume: FirePlumeVDB (fire_plume_VDB/firePlume_<frame:04d>), y up (rendered unturned, as run_volume_dataset.py
# does), its flames' centre in the opening and its smoke column rising out of the frame; 'flames' (0..4.5) is its
# temperature, 650 + 900 T kelvin; 0.05 cm a voxel (at 0.022 its flames were a wisp in the opening); its smoke is thin
# (density 0.05 typical), LeScale 180.9 (407 at sigma_a 0.4) for the others' light.
SEQUENCES = {
    "gasoline": {"src": "Gasoline_Explosion_01/Gasoline_Explosion_01/embergen_gasoline_explosion_a_%d.vdb",
                 "renames": None, "glow_grid": "temperature", "frame": 40,
                 "scale": 0.06, "rotation": (-90.0, 0.0, 0.0), "anchor": (0.2, 19.5, -0.6), "middle": (5.5, 0.0),
                 "bottom": -192.5, "offset": (-128.5, -128.5, -192.5),
                 "sigma_a": 0.9, "sigma_s": 0.1, "density_scale": 0.027, "cutoff": -0.0957, "temperature_scale": 1880.0,
                 "le_scale": 53.3, "lights": 1024, "glow": 0.125},
    "midair": {"src": "Midair_Explosion_01/Midair_Explosion_01/embergen_midair_explosion_a_%d.vdb",
               "renames": None, "glow_grid": "temperature", "frame": 40,
               "scale": 0.06, "rotation": (0.0, 90.0, 0.0), "anchor": (0.2, 17.0, -0.6), "base": (5.0, -175.0, -40.0),
               "offset": (-96.5, -192.5, -192.5),
               "sigma_a": 0.9, "sigma_s": 0.1, "density_scale": 0.027, "cutoff": -0.0957, "temperature_scale": 1880.0,
               "le_scale": 40.9, "lights": 1024, "glow": 0.125},
    # the user's Maya + Bifrost (2026-10-17): Bifrost's large_turbulent_fire example graph simulated headless
    # (bifrost_export.py, frames 1-120, its default detail size 0.1), each frame rewritten for gImportVDB on first use
    # (make_volumes.py clean_bifrost_vdb: `bifrost_src` -> `src`, a voxel a unit in Bifrost's own index placement); y up
    # as Maya is, its ground at voxel y 0; temperature already kelvin; its glow matched to the midair explosion's
    # frame 40 (emission_light_table's total)
    "bifrostfire": {"src": "BifrostVDB/turbulent_fire_clean/fire_%04d.vdb", "bifrost_src": "BifrostVDB/turbulent_fire/fire_%04d.vdb",
                    "renames": None, "glow_grid": "temperature", "frame": 100,
                    "scale": 0.09, "rotation": (0.0, 0.0, 0.0), "anchor": (0.2, 19.5, -0.6), "base": (5.0, 0.0, -5.0),
                    "offset": (0.0, 0.0, 0.0),
                    "sigma_a": 0.9, "sigma_s": 0.1, "density_scale": 0.06, "cutoff": 0.0, "temperature_scale": 1.0,
                    "le_scale": 18.0, "lights": 1024, "glow": 0.125},
    "plume": {"src": "FirePlumeVDB/fire_plume/fire_plume_VDB/firePlume_%04d.vdb",
              "renames": "flames=temperature", "glow_grid": "flames", "frame": 120,
              "scale": 0.05, "rotation": (0.0, 0.0, 0.0), "anchor": (0.2, 21.0, -0.6), "base": (2.2, 1.7, -204.2),
              "offset": (-111.5, -96.0, -287.5),
              "sigma_a": 0.9, "sigma_s": 0.1, "density_scale": 0.0225, "cutoff": -650.0 / 900.0, "temperature_scale": 900.0,
              "le_scale": 180.9, "lights": 1024, "glow": 0.125},
}
GASOLINE = SEQUENCES["gasoline"]


def frame(default):
    """The animation frame a teapot shot shows: TEAPOT_FRAME when set (for choosing one), else `default`."""
    import os
    return int(os.environ.get("TEAPOT_FRAME", default))


def fire01_data():
    """The EmberGen fire's data under VolumetricReSTIRData: the swatch's frame (67), or with TEAPOT_FRAME that frame
    of Fire_01 (make_volumes.py write_fire01: the same fire, prepared the same way)."""
    import os
    f = os.environ.get("TEAPOT_FRAME")
    return r"\fire01\fire01_%d" % int(f) if f else r"\swatch\embergen_fire_a_67"


def fire01_lights():
    """Its light table (make_volumes.py write_fire_lights / write_fire01), the path under VolumetricReSTIRData."""
    import os
    return fire01_data() + "_lights.json" if os.environ.get("TEAPOT_FRAME") else r"\swatch\fire_lights.json"
