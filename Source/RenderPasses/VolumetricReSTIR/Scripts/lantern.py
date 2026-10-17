"""Green energy tornadoes (user, 2026-10-17: like the green tornado construct in the Lanterns TV series, from
TornadoLoopingVDB and Dust_Devil -- "it can be a bit different, but it has better volumetrics"): a frame of JangaFX's
looping tornado or its dust devil (CC0), as it is, in a green medium against a dark teal sky with a soft white glow at
the left edge and a soft key light from the upper left (make_volumes.py lantern_sky), lit from inside by a few big
green lights along its axis (the user: bigger lights, not many small ones) -- lights inside a scattering medium, where
the mutation count matters. Shared by make_volumes.py (write_lantern: the frame and its lights), vr_graph.load_lantern
(the volume, sky and camera) and scenes/lantern_<shot>.pyscene (the lights). No imports beyond swatch_fire's placement:
Mogwai's scene builder runs this. Centimetres.

  lantern: the looping tornado as JangaFX's preview shows it (user, 2026-10-17: "the original tornado loop ... but
make it green", every small wisp visible -- where the mutation count has its influence), the frame as simulated:
upright (z up, 432 voxels from its thin twisting foot to its wide billowing top, ~240 across there), seen along its
voxel x as the preview is (worldRotation z 90: its silhouette's best match, IoU 0.87 against the preview's frame 64,
0.76 along y), its middle at the frame's, 0.053 cm a voxel -- 23 cm, nine-tenths of the frame's height. Density 0.3:
its veils thin (the median column's optical depth ~0.4) and its core opaque enough that its swirls show (thinner, the
view averaged them into haze; denser, the veils were as solid as the core). Against a dark sky (lantern_night: the
Lanterns teal dimmed to near black, as the preview's black) lit by a key from the upper left in front, as the
preview's, a rim behind it to the right, out of shot, and its five big green lights on the key's side: its funnel's
median 33/89/48, the Lanterns construct's 36/96/52.
  lanterndust: the dust devil (z up, 385 voxels: a dense ground cloud 35 voxels in radius narrowing to a twisting
column of ~18 that wanders off its axis and flares to ~60 at the top), upright, its ground's centre below the frame's
middle, 0.065 cm a voxel: the column fills the frame's height.

Medium: green -- albedo (0.15, 0.82, 0.28), extinction 1 per channel (no tint in transmission) -- forward scattering
(g 0.5, the loader's default): it glows where the light comes through.

Skies (make_volumes.py lantern_sky writes each to VolumetricReSTIRData/authored/<name>.exr): Gaussian lobes of white,
a glow and a key (direction, peak radiance, width in degrees), over a teal brighter below, scaled by `teal`.
"""
import swatch_fire

GREEN = {"sigma_a": (0.85, 0.18, 0.72), "sigma_s": (0.15, 0.82, 0.28), "g": 0.5}
SHOTS = {
    "lantern": dict(GREEN, src="TornadoLoopingVDB/TornadoLooping/TornadoVDB/tornado_%04d.vdb", data="tornado", frame=64,
                    offset=(-175.5, -175.5, -319.5), scale=0.053, rotation=(-90.0, 0.0, 90.0), anchor=(0.0, 0.0, 0.0),
                    base=(-7.0, -6.0, -92.0), density_scale=0.3,  # optical depth 0.3 a voxel at density 1
                    sky="lantern_night", key=(-0.75, 0.5, 0.45),
                    # the big lights: one per height (voxel z) on the axis, moved `outside` cm toward the key -- out of the
                    # funnel, lamps on its lit side (inside it each showed as a glowing orb) -- pale green, sharing `power`
                    glow={"n": 5, "heights": (-250.0, -170.0, -90.0, -10.0, 70.0), "rgb": (0.7, 1.0, 0.75), "power": 2000.0, "outside": 14.0},
                    camera={"position": (0.0, 0.0, 52.0), "target": (0.0, 0.0, 0.0), "focal": 50.0}),
    "lanterndust": dict(GREEN, src="Dust_Devil/Dust_Devil/embergen_dust_devil_tornado_a_%d.vdb", data="dustdevil", frame=50,
                        offset=(-128.5, -128.5, -192.5), scale=0.065, rotation=(-90.0, 0.0, 0.0), anchor=(0.0, -11.5, 0.0),
                        base=(0.0, 0.0, -192.5), density_scale=0.13,  # 2 a cm at density 1: its base is dense (1.0)
                        sky="lantern_sky", key=(-0.85, 0.45, 0.25),  # the sky's key: upper left, a little in front
                        glow={"n": 5, "heights": (-170.0, -110.0, -40.0, 40.0, 120.0), "rgb": (0.7, 1.0, 0.75), "power": 4200.0, "outside": 8.0},
                        camera={"position": (0.0, 0.0, 52.0), "target": (0.0, 0.0, 0.0), "focal": 50.0}),
}
SKIES = {
    # matched to the user's Lanterns reference: a teal sky brighter below (55/78/78 at the top right, 81/110/111 at the
    # bottom right), a broad white glow behind the funnel filling the frame's left side, a soft key from the upper left
    "lantern_sky": {"glow": (-0.6, 0.1, -0.8), "glow_radiance": 6.0, "glow_width": 20.0,
                    "key": SHOTS["lanterndust"]["key"], "key_radiance": 3.5, "key_width": 18.0, "teal": 1.0},
    # the looping tornado's: near black, the rim narrow and out of shot (70 degrees right of the view), the key broad
    "lantern_night": {"glow": (0.94, 0.1, -0.34), "glow_radiance": 5.0, "glow_width": 15.0,
                      "key": SHOTS["lantern"]["key"], "key_radiance": 4.0, "key_width": 22.0, "teal": 0.06},
}


def pose(shot):
    return swatch_fire.pose(SHOTS[shot])


def frame(shot):
    return swatch_fire.frame(SHOTS[shot]["frame"])
