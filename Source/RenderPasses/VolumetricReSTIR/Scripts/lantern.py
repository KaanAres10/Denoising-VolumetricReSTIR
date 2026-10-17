"""Green energy tornadoes (user, 2026-10-17: like the green tornado construct in the Lanterns TV series, from
TornadoLoopingVDB and Dust_Devil -- "it can be a bit different, but it has better volumetrics"): a frame of JangaFX's
looping tornado or its dust devil (CC0), as it is, in a green medium against a dark teal sky with a soft white glow at
the left edge and a soft key light from the upper left (make_volumes.py lantern_sky), lit from inside by a few big
green lights along its axis (the user: bigger lights, not many small ones) -- lights inside a scattering medium, where
the mutation count matters. Shared by make_volumes.py (write_lantern: the frame and its lights), vr_graph.load_lantern
(the volume, sky and camera) and scenes/lantern_<shot>.pyscene (the lights). No imports beyond swatch_fire's placement:
Mogwai's scene builder runs this. Centimetres.

  lantern: the tornado (z up, 447 voxels tall, its radius growing from ~13 voxels at its foot to ~56 at its top, its
mass in the upper half), stood up and leaned 60 degrees right about the view axis -- worldRotation (-90, 60, 0), its
axis (cos 30, sin 30, 0) -- as the reference's construct lies; its axis at voxel z -40 at the origin, 0.1 cm a voxel:
~11 cm across at its rounded top, which stays in frame at the right.
  lanterndust: the dust devil (z up, 385 voxels: a dense ground cloud 35 voxels in radius narrowing to a twisting
column of ~18 that wanders off its axis and flares to ~60 at the top), upright, its ground's centre below the frame's
middle, 0.065 cm a voxel: the column fills the frame's height.

Medium: green -- albedo (0.1, 0.85, 0.22), extinction 1 per channel (no tint in transmission) -- forward scattering
(g 0.5, the loader's default): it glows where the light comes through.
"""
import swatch_fire

GREEN = {"sigma_a": (0.9, 0.15, 0.78), "sigma_s": (0.1, 0.85, 0.22), "g": 0.5}
SHOTS = {
    "lantern": dict(GREEN, src="TornadoLoopingVDB/TornadoLooping/TornadoVDB/tornado_%04d.vdb", data="tornado", frame=64,
                    offset=(-175.5, -175.5, -319.5), scale=0.1, rotation=(-90.0, 60.0, 0.0), anchor=(0.0, 0.0, 0.0),
                    base=(-4.0, 1.0, -40.0), density_scale=0.6,  # 6 a cm at density 1 (densityScale x sigma_t / scale)
                    # the big lights: one per height (voxel z) on the axis, moved `outside` cm toward the key -- out of the
                    # funnel, lamps on its lit side (inside it each showed as a glowing orb) -- pale green, sharing `power`
                    glow={"n": 5, "heights": (-200.0, -130.0, -60.0, 10.0, 80.0), "rgb": (0.7, 1.0, 0.75), "power": 2400.0, "outside": 14.0},
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
