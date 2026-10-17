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
view averaged them into haze; denser, the veils were as solid as the core). With the construct's detail added
(user, 2026-10-17: "add detail such that it looks like the lantern construct, the volumetrics more complicated, so
that mutation is useful"; make_volumes.py tornado_detail), its own structure kept: 1.5x finer, its veils curled into
filaments, banded by helices wrapping its axis (the construct's rings: 80% of the smoke regrouped into them, sharp
enough to show through the smoke), and 6000 specks, a pixel or two each -- glints where lit, the construct's glitter,
dark debris and small shadows where not. Against a dark sky (lantern_night: the Lanterns teal dimmed to near black, as
the preview's black) with a key from the upper left in front, as the preview's, a rim behind it to the right, out of
shot, and lit by three big emissive soft boxes out of shot (key, rim, fill), each its own green: a pixel's sample
carries its box's colour and a point on it -- where the study found mutations most useful (softbox -81..-89%, many
coloured lights -91%). Its funnel's median 34/97/54, the Lanterns construct's 36/96/52.
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
    "lantern": dict(GREEN, src="TornadoLoopingVDB/TornadoLooping/TornadoVDB/tornado_%04d.vdb", data="tornadodetail",
                    frame=64,
                    # the construct's detail on the frame (make_volumes.py tornado_detail): 1.5x finer, its veils curled
                    # into filaments, banded, specked -- written a voxel a unit (no grid offset)
                    detail={"up": 1.5, "warp": (3.0, 1.2), "bands": 0.8, "sharp": 2.5, "arms": 2, "pitch": 54.0,
                            "meander": 1.0, "specks": 6000, "speck_density": 5.0, "speck_sigma": 0.45, "speck_spread": 0.5,
                            "speck_power": 0.5, "seed": 1},
                    # the frame's pose on the finer grid: 0.053 / 1.5 cm a voxel, its middle (voxel (-7, -6, -92) of the
                    # source .vbx) at (v - lo - offset) x 1.5; density 0.3 / 1.5 a voxel, the same optical depth
                    offset=(0.0, 0.0, 0.0), scale=0.053 / 1.5, rotation=(-90.0, 0.0, 90.0), anchor=(0.0, 0.0, 0.0),
                    base=(219.75, 224.25, 330.75), density_scale=0.2,
                    sky="lantern_night", key=(-0.75, 0.5, 0.45),
                    # big lights (the user: bigger lights, not many small ones): emissive soft boxes, each `side` cm square,
                    # `dist` cm from the funnel's middle along `dir`, facing it, out of shot; each its own tint, so a
                    # pixel's sample carries its light's colour, and the point on a box is the light-vertex move's
                    panels=({"name": "Key", "dir": (-0.75, 0.5, 0.45), "dist": 36.0, "side": 14.0, "rgb": (0.75, 1.0, 0.8), "radiance": 50.0},
                            {"name": "Rim", "dir": (0.92, 0.2, -0.35), "dist": 44.0, "side": 14.0, "rgb": (0.55, 1.0, 0.95), "radiance": 40.0},
                            {"name": "Fill", "dir": (0.6, -0.55, 0.6), "dist": 34.0, "side": 12.0, "rgb": (0.3, 1.0, 0.45), "radiance": 5.0}),
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


def panel_corners(panel, target=(0.0, 0.0, 0.0)):
    """A soft box's four corners (world cm), wound so the quad (0, 1, 2), (0, 2, 3) faces `target`."""
    k = [c / sum(v * v for v in panel["dir"]) ** 0.5 for c in panel["dir"]]
    centre = [t + panel["dist"] * c for t, c in zip(target, k)]
    a = [-k[2], 0.0, k[0]]  # k x up
    n = sum(v * v for v in a) ** 0.5
    a = [v / n for v in a]
    b = [a[1] * k[2] - a[2] * k[1], a[2] * k[0] - a[0] * k[2], a[0] * k[1] - a[1] * k[0]]  # a x k
    h = panel["side"] / 2
    return [[centre[i] + h * (u * a[i] + v * b[i]) for i in range(3)] for u, v in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
