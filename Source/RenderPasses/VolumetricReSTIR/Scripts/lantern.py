"""Green energy tornadoes (user, 2026-10-17: like the green tornado construct in the Lanterns TV series, from
TornadoLoopingVDB and Dust_Devil -- "it can be a bit different, but it has better volumetrics"): a frame of JangaFX's
looping tornado or its dust devil (CC0), as it is, in a green medium against a dark teal sky with a soft white glow at
the left edge and a soft key light from the upper left (make_volumes.py lantern_sky), lit from inside by a few big
green lights along its axis (the user: bigger lights, not many small ones) -- lights inside a scattering medium, where
the mutation count matters. Shared by make_volumes.py (write_lantern: the frame and its lights), vr_graph.load_lantern
(the volume, sky and camera) and scenes/lantern_<shot>.pyscene (the lights). No imports beyond swatch_fire's placement:
Mogwai's scene builder runs this. Centimetres.

  lantern: the tornado reshaped into the construct (make_volumes.py lantern_funnel: the user asked for it to look
exactly like the reference, editing the data as needed): a straight funnel with the tornado's own swirl structure
inside, smoky and thin at its lower-left start, a neck, then a dense banded head closed by a round cap; lying
diagonally (worldRotation (-90, 68, 0): its axis 22 degrees up to the right), the head at the upper right, its cap in
frame; 0.133 cm a voxel, the head ~16 cm across, two-thirds of the frame's height.
  lanterndust: the dust devil (z up, 385 voxels: a dense ground cloud 35 voxels in radius narrowing to a twisting
column of ~18 that wanders off its axis and flares to ~60 at the top), upright, its ground's centre below the frame's
middle, 0.065 cm a voxel: the column fills the frame's height.

Medium: green -- albedo (0.1, 0.85, 0.22), extinction 1 per channel (no tint in transmission) -- forward scattering
(g 0.5, the loader's default): it glows where the light comes through.
"""
import swatch_fire

GREEN = {"sigma_a": (0.9, 0.15, 0.78), "sigma_s": (0.1, 0.85, 0.22), "g": 0.5}
SHOTS = {
    "lantern": dict(GREEN, src="TornadoLoopingVDB/TornadoLooping/TornadoVDB/tornado_%04d.vdb", data="lanternfunnel",
                    frame=64, author="funnel",  # reshaped into the construct (make_volumes.py lantern_funnel)
                    offset=(0.0, 0.0, 0.0), scale=0.133, rotation=(-90.0, 68.0, 0.0), anchor=(-3.0, 0.5, 0.0),
                    base=(75.0, 75.0, 268.0), density_scale=0.15,  # 1.1 a cm at density 1 (densityScale x sigma_t / scale)
                    # the big lights: one per height (voxel z) on the axis, moved `outside` cm toward the key -- out of the
                    # funnel, lamps on its lit side (inside it each showed as a glowing orb) -- pale green, sharing `power`
                    glow={"n": 5, "heights": (150.0, 230.0, 300.0, 360.0, 410.0), "rgb": (0.7, 1.0, 0.75), "power": 2400.0, "outside": 14.0},
                    camera={"position": (0.0, 0.0, 52.0), "target": (0.0, 0.0, 0.0), "focal": 50.0}),
    "lanterndust": dict(GREEN, src="Dust_Devil/Dust_Devil/embergen_dust_devil_tornado_a_%d.vdb", data="dustdevil", frame=50,
                        offset=(-128.5, -128.5, -192.5), scale=0.065, rotation=(-90.0, 0.0, 0.0), anchor=(0.0, -11.5, 0.0),
                        base=(0.0, 0.0, -192.5), density_scale=0.13,  # 2 a cm at density 1: its base is dense (1.0)
                        glow={"n": 5, "heights": (-170.0, -110.0, -40.0, 40.0, 120.0), "rgb": (0.7, 1.0, 0.75), "power": 4200.0, "outside": 8.0},
                        camera={"position": (0.0, 0.0, 52.0), "target": (0.0, 0.0, 0.0), "focal": 50.0}),
}
KEY = (-0.85, 0.45, 0.25)  # the sky's key light: upper left, a little in front (make_volumes.py lantern_sky)


def pose(shot):
    return swatch_fire.pose(SHOTS[shot])


def frame(shot):
    return swatch_fire.frame(SHOTS[shot]["frame"])
