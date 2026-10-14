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


def translation(scale=SCALE, rotation=ROTATION, anchor=ANCHOR, middle=MIDDLE, bottom=BOTTOM):
    """The volume's worldTranslation: its middle (voxel x, y) and bottom (voxel z) at the anchor."""
    m = rotate((middle[0], middle[1], bottom), rotation)
    return tuple(anchor[i] - scale * m[i] for i in range(3))


def to_world(p, scale=SCALE, rotation=ROTATION, anchor=ANCHOR, middle=MIDDLE, bottom=BOTTOM):
    """A point in the .vbx's voxel coordinates -> world (cm, y up), as SceneGVDB places the volume."""
    t = translation(scale, rotation, anchor, middle, bottom)
    q = rotate(p, rotation)
    return tuple(t[i] + scale * q[i] for i in range(3))


# The other EmberGen volumes the user added (2026-10-13), stood on the opening the same way: the gasoline explosion
# (Gasoline_Explosion_01, z up, its ground at voxel z 0 -- .vbx z -192.5), its bottom at the pot's depth, scaled so its
# fireball spans the opening and its smoke the frame above.
# Its medium: smoke of albedo 0.6, extinction 0.45 a cm at density 1 (densityScale x sigma_t / scale); its temperature
# (0..2 in the grid) read at (T - cutoff) x scale = 180 + 1880 T kelvin, black below 650 K (T 0.25, most of the smoke),
# 2000-2600 K in the fireball; LeScale 120 makes its light ~6000 in red intensity, the backdrop the reference's level
# (at 200, the RenderMan-matched fire's 10^4, it was 1.5x the reference's and the fireball blew out: user, too exposed).
GASOLINE = {"scale": 0.06, "rotation": (-90.0, 0.0, 0.0), "anchor": (0.2, 19.5, -0.6), "middle": (5.5, 0.0),
            "bottom": -192.5, "offset": (-128.5, -128.5, -192.5), "frame": 40,
            "sigma_a": 0.4, "sigma_s": 0.6, "density_scale": 0.027, "cutoff": -0.0957, "temperature_scale": 1880.0,
            "le_scale": 120.0, "lights": 1024}


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
