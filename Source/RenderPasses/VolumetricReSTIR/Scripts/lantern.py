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
0.76 along y), its middle at the frame's, 0.053 cm a source voxel -- 23 cm, nine-tenths of the frame's height. With
film-style detail added (user, 2026-10-17: "more detail, like the lantern construct, movie production detail";
make_volumes.py tornado_detail), its own structure kept, as a production upres adds it to a simulation: 1.6x finer
(at 2x, and at 1.75x once its body is kept whole, its bricks overflow SceneGVDB's atlas), curl-noise turbulence, the
vortex's flow-line streaks, dust grain, the construct's rings (60% of the smoke regrouped into helices), the faintest
haze eroded into crisp wisps (the Nubis remap, against density 0.04: against 0.12 it carved the body away), 3000 faint
specks (opaque ones read as dark dirt against the backlight). Density 1.6 a source voxel, so its body reads solid as
the construct's does. Against the construct's own sky (lantern_sky: teal, the white glow at the left), lit by three
big emissive soft boxes out of shot (key, rim, fill), each its own green: a pixel's sample carries its box's colour and
a point on it -- where the study found mutations most useful (softbox -81..-89%, many coloured lights -91%); on an
earlier, lighter version of this shot 5 mutations at M cap 200 cut the in-medium correlation rho(8) 0.110 -> 0.016
and the raw error 15%. Its funnel's green median 49/116/70, the Lanterns construct's 36/96/52.
  lanterndust: the dust devil (z up, 385 voxels: a dense ground cloud 35 voxels in radius narrowing to a twisting
column of ~18 that wanders off its axis and flares to ~60 at the top), upright, its ground's centre below the frame's
middle, 0.065 cm a voxel: the column fills the frame's height.

Medium: green -- albedo (0.15, 0.82, 0.28), extinction 1 per channel (no tint in transmission) -- forward scattering
(g 0.5, the loader's default): it glows where the light comes through.

Skies (make_volumes.py lantern_sky writes each to VolumetricReSTIRData/authored/<name>.exr): Gaussian lobes of white,
a glow and a key (direction, peak radiance, width in degrees), over a teal brighter below, scaled by `teal`.
"""
import os

import swatch_fire

# which Bifrost run the construct shot reads (BifrostVDB/<it>, bifrost_graphs.vortex_construct's frames): a variant
# being tuned is picked by LANTERN_CONSTRUCT, which Mogwai inherits as make_volumes.py does
CONSTRUCT = os.environ.get("LANTERN_CONSTRUCT", "shape_C5")
# its motion blur: frames averaged (make_volumes.py blur_bifrost_frames), LANTERN_SHUTTER of them (1: none)
SHUTTER = int(os.environ.get("LANTERN_SHUTTER", "1"))

GREEN = {"sigma_a": (0.85, 0.18, 0.72), "sigma_s": (0.15, 0.82, 0.28), "g": 0.5}
SHOTS = {
    "lantern": dict(GREEN, src="TornadoLoopingVDB/TornadoLooping/TornadoVDB/tornado_%04d.vdb", data="tornadodetail",
                    frame=64,
                    # film-style detail on the frame (make_volumes.py tornado_detail, all lengths in its finer voxels):
                    # 1.6x as fine, curl-noise turbulence, the vortex's streaks, dust grain, the construct's rings, the
                    # thin smoke eroded into crisp wisps, glitter -- written a voxel a unit (no grid offset) from the
                    # frame's own index box, the source's grid offset `source_offset`
                    # 1.6x: at 2x its 8^3 bricks (~130k) overflow SceneGVDB's atlas, and at 1.75x once the body is
                    # kept whole (make_volumes.py gvdb_atlas_depth)
                    detail={"up": 1.6, "source_offset": (-175.5, -175.5, -319.5),
                            "warp": (4.0, 1.2), "warp_scales": (24.0, 6.0), "streaks": 0.45, "streak_width": (6.0, 3.0),
                            "grain": 0.25, "grain_scale": 2.5, "erode": 0.5, "erode_ref": 0.04, "erode_scales": (16.0, 6.0, 2.5),
                            "bands": 0.6, "sharp": 2.5, "arms": 2, "pitch": 58.0, "meander": 1.0,
                            "specks": 3000, "speck_density": 1.5, "speck_sigma": 0.5, "speck_spread": 0.5, "speck_power": 1.0,
                            "seed": 1},
                    # the pose and density in the source's terms -- 0.053 cm a source voxel, its middle at source voxel
                    # (-7, -6, -92), 1.6 a source voxel at density 1 -- which write_lantern turns into each frame's finer
                    # grid's (its _lights.json "grid", which vr_graph.load_lantern reads); `offset` the written grid's
                    offset=(0.0, 0.0, 0.0), scale=0.053, rotation=(-90.0, 0.0, 90.0), anchor=(0.0, 0.0, 0.0),
                    base=(-7.0, -6.0, -92.0), density_scale=1.6,
                    sky="lantern_sky", key=(-0.75, 0.5, 0.45),
                    # big lights (the user: bigger lights, not many small ones): emissive soft boxes, each `side` cm square,
                    # `dist` cm from the funnel's middle along `dir`, facing it, out of shot; each its own tint, so a
                    # pixel's sample carries its light's colour, and the point on a box is the light-vertex move's
                    panels=({"name": "Key", "dir": (-0.75, 0.5, 0.45), "dist": 36.0, "side": 14.0, "rgb": (0.75, 1.0, 0.8), "radiance": 22.0},
                            {"name": "Rim", "dir": (0.92, 0.2, -0.35), "dist": 44.0, "side": 14.0, "rgb": (0.55, 1.0, 0.95), "radiance": 18.0},
                            {"name": "Fill", "dir": (0.6, -0.55, 0.6), "dist": 34.0, "side": 12.0, "rgb": (0.3, 1.0, 0.45), "radiance": 3.0}),
                    camera={"position": (0.0, 0.0, 52.0), "target": (0.0, 0.0, 0.0), "focal": 50.0}),
    # the construct simulated in Bifrost (the user's Maya + Bifrost, 2026-10-17; bifrost_graphs.vortex_construct: a smoke
    # column driven round its axis, detail 0.03 m, its source 1 m in radius; bifrost_export.py, frames 1-120), each frame
    # rewritten for gImportVDB on first use (make_volumes.py clean_bifrost_vdb: Bifrost's own index placement, its axis
    # at voxel x = z = 0); at frame 120 the column is 385 voxels long (11.5 m), twisting, flared where it tops out;
    # lying diagonally as the reference's construct (worldRotation z -62: its axis 28 degrees up to the right), its
    # middle at the frame's
    # its green a touch less saturated than the tornado's (the reference's mid-tones: red / green 0.5, ours was 0.42),
    # its blue lower (the sky's teal lifted its shadows' blue: 32 to the reference's 22)
    "lanternbifrost": dict(GREEN, sigma_a=(0.80, 0.15, 0.72), sigma_s=(0.20, 0.85, 0.28), g=0.6,
                           src="BifrostVDB/%s_clean%s/construct_%%04d.vdb" % (CONSTRUCT, "_s%d" % SHUTTER if SHUTTER > 1 else ""),
                           shutter=SHUTTER,
                           bifrost_src="BifrostVDB/%s/construct_%%04d.vdb" % CONSTRUCT,
                           data="bifrostconstruct", frame=150,
                           # fitted per frame (make_volumes.py write_lantern; its _lights.json "grid"): sized so its
                           # diameter is the reference's (12.2 cm: half the frame's height, 265 px of 540), its density
                           # for an optical depth of `tau` across its middle, its cap pinned where the reference's ends
                           # (x 880, y 210 of 960 x 540)
                           fit={"diameter": 13.0, "tau": 8.0, "cap": (17.1, 6.5, 0.0)},
                           offset=(0.0, 0.0, 0.0), scale=0.06, rotation=(0.0, 0.0, -66.0), anchor=(17.1, 6.5, 0.0),
                           base=(0.0, 0.0, 0.0), density_scale=0.25,  # (overridden by the fit)
                           sky="lantern_sky", key=(-0.75, 0.5, 0.45),
                           # the reference's sparkles: 4000 tiny emitters where its surface faces the key (upper left)
                           # (at radiance 40 in a pale green they clipped to white, spread evenly; the reference's
                           # are green, clustered where the surface faces the key squarely: power 8)
                           glitter={"n": 5000, "threshold": 0.04, "power": 8.0, "size": 0.07, "rgb": (0.15, 1.0, 0.25),
                                    "radiance": 1.8, "seed": 1},  # red and blue under display white: green, not white
                           # its own soft boxes: the tornado's, the fill raised (its mid-tones were 105 green to the
                           # reference's 125, its shadows 61 to 80)
                           panels=({"name": "Key", "dir": (-0.75, 0.5, 0.45), "dist": 36.0, "side": 14.0, "rgb": (0.75, 1.0, 0.8), "radiance": 40.0},
                                   {"name": "Rim", "dir": (0.92, 0.2, -0.35), "dist": 44.0, "side": 14.0, "rgb": (0.55, 1.0, 0.95), "radiance": 15.0},
                                   {"name": "Fill", "dir": (0.6, -0.55, 0.6), "dist": 34.0, "side": 12.0, "rgb": (0.3, 1.0, 0.45), "radiance": 9.0}),
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


def glitter_quads(points, camera, size):
    """The construct's glitter (make_volumes.py write_lantern samples it on the funnel's key-lit surface): each point a
    square `size` cm across facing the camera, wound so its emitting side does (corners a, b, c, d: triangles a b c,
    a c d). Pure Python: Mogwai's scene builder runs it."""
    eye, target = camera["position"], camera["target"]
    f = [target[i] - eye[i] for i in range(3)]
    n = sum(v * v for v in f) ** 0.5
    f = [v / n for v in f]
    r = [f[1] * 0 - f[2] * 1, f[2] * 0 - f[0] * 0, f[0] * 1 - f[1] * 0]  # f x up(0, 1, 0)
    n = sum(v * v for v in r) ** 0.5
    r = [v / n for v in r]
    u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]]  # r x f
    h = size / 2
    return [[[p[i] + h * (s * r[i] + t * u[i]) for i in range(3)] for s, t in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
            for p in points]
