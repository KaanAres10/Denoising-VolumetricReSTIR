"""Where the swatch fire (RenderMan_Swatch_Blender/VDB/embergen_fire_a_67.vdb) sits on the teapot: shared by vr_graph's
load_teapot_fire, which places the volume, and scenes/teapot_fire.pyscene, which places the lights derived from it
(make_volumes.py write_fire_lights); swatch/rman_teapot_fire.py places it in the .blend for the RenderMan target by the
same formula. No imports beyond math: the scene builder runs this inside Mogwai.

The .vbx keeps the VDB's coordinates: voxel x -54.5..51.5, y -91.5..24.5, z (up) -128.5..-3.5; GVDB applies them, then
SceneGVDB's T Rx Ry Rz S. Stood upright by -90 about x (voxel z up), turned YAW about its own up axis (Rz, first).
"""
import math

SCALE = 0.12  # cm per voxel: the flame 15 cm tall
BASE_Y = 14.0  # the fire's bottom, inside the pot (its rim is at 21.8)
YAW = 90  # the side whose flame leans right, as in the reference
OPENING = (0.2, -0.6)  # the pot's opening, x and z
MIDDLE = (-1.5, -33.5)  # the fire's middle, voxel x and y
BOTTOM = -128.5  # voxel z


def _turned(x, y):
    """Voxel (x, y) after Rz(YAW)."""
    a = math.radians(YAW)
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


def translation():
    """The volume's worldTranslation: its middle over the opening, its bottom at BASE_Y."""
    mx, my = _turned(*MIDDLE)
    # Rx(-90) maps (a, b, c) to (a, c, -b)
    return (OPENING[0] - SCALE * mx, BASE_Y - SCALE * BOTTOM, OPENING[1] + SCALE * my)


def to_world(p):
    """A point in the .vbx's voxel coordinates -> world (cm, y up)."""
    tx, ty, tz = translation()
    a, b = _turned(p[0], p[1])
    return (tx + SCALE * a, ty + SCALE * p[2], tz - SCALE * b)
