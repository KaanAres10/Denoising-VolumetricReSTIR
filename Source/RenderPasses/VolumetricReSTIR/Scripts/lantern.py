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
import hashlib
import os

import swatch_fire

def _env(name, parse=lambda v: tuple(float(x) for x in v.split(","))):
    """A tuning knob from the environment (Mogwai inherits it, as make_volumes.py does), or None."""
    return parse(os.environ[name]) if os.environ.get(name) else None


# The construct shot's tuning knobs; unset, each is the construct as matched to the Lanterns reference (2026-10-18).
# which Bifrost run it reads (BifrostVDB/<it>, bifrost_graphs.vortex_construct's frames): F3, the tuned simulation
# (0.05 m) refined to 0.025 m, its velocity exported
CONSTRUCT = os.environ.get("LANTERN_CONSTRUCT", "shape_F4")  # (F4: refined inside the simulation, fine turbulence)
# its fine detail: LANTERN_DETAIL "warp1,warp2,scale1,scale2,streaks,streak_w_r,streak_w_v,grain,grain_scale,erode,
# erode_ref" (make_volumes.py construct_detail, tornado_detail's: curl-noise filaments, streaks round its axis, grain,
# erosion of its thin smoke; voxels) -- the reference's texture is at a voxel or two, the simulation smooth there
DETAIL_KNOB = _env("LANTERN_DETAIL")
DETAIL = DETAIL_KNOB
FINE = DETAIL and {"warp": (DETAIL[0], DETAIL[1]), "warp_scales": (DETAIL[2], DETAIL[3]), "streaks": DETAIL[4],
                   "streak_width": (DETAIL[5], DETAIL[6]), "grain": DETAIL[7], "grain_scale": DETAIL[8], "erode": DETAIL[9],
                   "erode_ref": DETAIL[10]}
# ... applied before the velocity blur when there is one (LANTERN_DETAIL_PRE=1): the blur smears it into streaks
DETAIL_PRE = os.environ.get("LANTERN_DETAIL_PRE", "0") == "1"
# its motion blur: along its own velocity over LANTERN_VBLUR seconds (make_volumes.py blur_bifrost_velocity, as a
# production renderer blurs a volume: smooth streaks along the flow; the run must have exported voxel_velocity), or,
# for LANTERN_VBLUR 0, LANTERN_SHUTTER frames averaged (make_volumes.py blur_bifrost_frames; 1: none)
# LANTERN_VBLUR "shutter[,drift[,grain_amp,grain_cell]]": drift (m/s) along its axis -- the construct moving as a
# whole, which tilts its streaks from rings toward the reference's helices -- and grain (make_volumes.py grain): fine
# variation in its density for the blur to draw into streak lines
VBLUR_SPEC = _env("LANTERN_VBLUR") or (0.15, 0.0, 0.0, 0.0, 1.2, 1.0, 0.4)
VBLUR = VBLUR_SPEC[0]
DRIFT = VBLUR_SPEC[1] if len(VBLUR_SPEC) > 1 else 0.0
GRAIN = tuple(VBLUR_SPEC[2:4]) if len(VBLUR_SPEC) > 3 and VBLUR_SPEC[2] else None
# ... ",streak_amp,streak_cell,streak_shutter": a texture of fine lines along the flow (make_volumes.py flow_streaks)
STREAKS = tuple(VBLUR_SPEC[4:7]) if len(VBLUR_SPEC) > 6 and VBLUR_SPEC[4] else None
SHUTTER = int(os.environ.get("LANTERN_SHUTTER", "5"))
BLUR_TAG = (("_v%g" % VBLUR + ("_d%g" % DRIFT if DRIFT else "") + ("_g%g_%g" % GRAIN if GRAIN else "")
             + ("_l%g_%g_%g" % STREAKS if STREAKS else "")
             + ("_e" + hashlib.md5(repr(DETAIL).encode()).hexdigest()[:6] if DETAIL and DETAIL_PRE else "")) if VBLUR
            else ("_s%d" % SHUTTER if SHUTTER > 1 else ""))
# its pose: LANTERN_POSE "yaw,roll[,size,dx,dy]" -- worldRotation (0, yaw, roll), the fitted diameter x size, the cap
# moved (dx, dy) cm. Its tail comes toward the camera and its head goes away, as the reference's do (its rings curve
# round its head's far end, its tail fills the frame's lower left, wide, pale and soft): a 40 degree yaw, sized and
# placed by the silhouette (preview and render: IoU 0.891 to the side-on 0.872)
POSE_KNOB = _env("LANTERN_POSE")
POSE = POSE_KNOB or (32.5, -68.25, 1.065, -1.75, -0.12)  # (fitted on its density as rendered, at 320 cm)
POSE = POSE + (1.0, 0.0, 0.0)[len(POSE) - 2:]
ROTATION = (0.0, POSE[0], POSE[1])
CAP = (17.1 + POSE[3], 6.5 + POSE[4], 0.0)
# its glitter: LANTERN_GLITTER "shadowed,size_sigma[,n[,size[,radiance]]]" -- drawn only where its key reaches (1;
# make_volumes.py glitter_points), its sizes spread lognormally (glitter_sizes): the reference's sheen of fine sparkles
# on its lit side
GLITTER_KNOB = _env("LANTERN_GLITTER")
GLITTER = GLITTER_KNOB or (1.0, 0.4, 10000, 0.08, 0.6)
# its glints' look: LANTERN_GLINT "cluster_mean,cluster_radius,streak,sprite_sigma" -- in foam-like clumps (glints a
# group, their scatter in voxels; make_volumes.py glitter_clusters), each streaked along its motion over `streak`
# seconds (lantern.glitter_quads), soft (a Gaussian `sprite_sigma` of its quad: make_volumes.py glitter_sprite);
# 0 turns each off
GLINT_KNOB = _env("LANTERN_GLINT")
# ... and a second population: LANTERN_FLAKES "n,size,size_sigma,cluster_mean,cluster_radius,per,width,streak" -- fewer,
# bigger, brighter flakes over the fine sheen (each a spray of `per` micro-glints: the reference's bright flakes on its
# upper flank), through the same mask; needs the sheen's spray (LANTERN_GLINT's)
FLAKES_KNOB = _env("LANTERN_FLAKES")
FLAKES = FLAKES_KNOB or (300, 0.25, 0.4, 3.0, 3.0, 40, 0.3, 0.015)
GLINT = GLINT_KNOB or (1.5, 2.0, 0.01, 0.0, 4, 0.02, 0.3)
GLINT = GLINT + (0.0, 0.0, 0.0)[:max(0, 7 - len(GLINT))]  # ... ",spray_per,spray_micro,spray_width" (glint_sprays)
# its tail: LANTERN_TAIL "warp_amp,warp_cell,warp_top,mist_amp,mist_cell,mist_reach,mist_top,focus,ramp,sigma_max" --
# churned out of its helical bands below warp_top of its height (make_volumes.py warp: voxels), wrapped in a pale wispy
# veil below mist_top (mist: at most mist_amp, features mist_cell voxels, within ~mist_reach of its smoke) and softened
# where nearer the camera than `focus` cm (defocus: sigma_max voxels by focus - ramp): the reference's tail is near and
# out of focus, turbulent, pale with smoke; 0 turns each off
TAIL_KNOB = _env("LANTERN_TAIL")
TAIL = TAIL_KNOB or (8.0, 12.0, 0.6, 0.01, 16.0, 16.0, 0.6, 44.0, 10.0, 5.0)
# its optical depth across its middle (LANTERN_TAU; the fit's, 8): thicker smoke shows its fine structure as a surface,
# thin smoke averages it over its depth (at 8 the mean free path was ~40 voxels)
TAU_KNOB = _env("LANTERN_TAU", float)
# its key soft box's side (LANTERN_KEYSIZE cm, 14; its radiance scaled to keep its power): a smaller, harder key casts
# the fine structure's own small shadows
KEYSIZE_KNOB = _env("LANTERN_KEYSIZE", float)
# its soft boxes' radiance: LANTERN_LIGHTS "key,rim,fill" (40, 8, 9; the key's for its 14 cm side)
LIGHTS_KNOB = _env("LANTERN_LIGHTS")
LIGHTS = LIGHTS_KNOB or (70.0, 10.0, 14.0)
# its camera: LANTERN_CAMERA "distance" cm from its target (52), the focal length scaled to keep the framing at the
# target (50 mm at 52) and the sky seen through a lens that much longer (make_volumes.py lantern_sky tele) -- the
# reference's narrow neck and big head are a long lens's: at 52 cm its near body came out 1.7x magnified
CAMERA_KNOB = _env("LANTERN_CAMERA", float)
CAM_DIST = CAMERA_KNOB or 320.0
# its key: LANTERN_KEY "x,y,z" -- the key soft box's direction and the glitter's
KEY = _env("LANTERN_KEY")
# its foot faded into smoke (make_volumes.py fade_foot): LANTERN_FOOT "start,end[,floor]", fractions of its height
FOOT_KNOB = _env("LANTERN_FOOT")
FOOT = FOOT_KNOB or (0.4, 0.62, 0.22)  # (its visible tail to smoke)
# a tuning variant's import folder: the run's, plus a short hash of the knobs set (the glitter is posed and keyed) --
# spelled out, the names passed Windows' 260-character path limit and Falcor could not cache the volume's nodes
VARIANT = "".join("_%s%s" % (k, "_".join("%g" % v for v in t)) for k, t in (("f", FOOT_KNOB), ("p", POSE_KNOB),
                                                                         ("g", GLITTER_KNOB), ("k", KEY),
                                                                         ("l", GLINT_KNOB), ("t", TAIL_KNOB),
                                                                         ("e", DETAIL_KNOB),
                                                                         ("u", TAU_KNOB and (TAU_KNOB,)),
                                                                         ("z", KEYSIZE_KNOB and (KEYSIZE_KNOB,)),
                                                                         ("o", LIGHTS_KNOB), ("x", FLAKES_KNOB),
                                                                         ("c", CAMERA_KNOB and (CAMERA_KNOB,))) if t)
VARIANT = VARIANT and "_" + hashlib.md5(VARIANT.encode()).hexdigest()[:8]

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
                           src="BifrostVDB/%s_clean%s/construct_%%04d.vdb" % (CONSTRUCT, BLUR_TAG),
                           shutter=SHUTTER, **({"vblur": VBLUR, "drift": (0.0, DRIFT, 0.0)} if VBLUR else {}),
                           **({"grain": GRAIN + (2, 0)} if VBLUR and GRAIN else {}), **({"foot": FOOT} if FOOT else {}),
                           **({"streaks": STREAKS} if VBLUR and STREAKS else {}),
                           **({"pre_fine": FINE} if DETAIL and DETAIL_PRE and VBLUR else ({"fine": FINE} if DETAIL else {})),
                           **({"warp": {"amplitude": TAIL[0], "cell": TAIL[1], "top": TAIL[2]}} if TAIL[0] else {}),
                           **({"mist": {"amplitude": TAIL[3], "cell": TAIL[4], "reach": TAIL[5], "top": TAIL[6]}} if TAIL[3] else {}),
                           **({"defocus": {"focus": TAIL[7], "ramp": TAIL[8], "sigma_max": TAIL[9]}} if TAIL[9] else {}),
                           bifrost_src="BifrostVDB/%s/construct_%%04d.vdb" % CONSTRUCT,
                           data="bc_%s%s%s" % (CONSTRUCT, BLUR_TAG, VARIANT), frame=150,  # each variant its own import
                           # fitted per frame (make_volumes.py write_lantern; its _lights.json "grid"): sized so its
                           # diameter is the reference's (12.2 cm: half the frame's height, 265 px of 540), its density
                           # for an optical depth of `tau` across its middle, its cap pinned where the reference's ends
                           # (x 880, y 210 of 960 x 540)
                           fit={"diameter": 13.0 * POSE[2], "tau": TAU_KNOB or 20.0, "cap": CAP},
                           offset=(0.0, 0.0, 0.0), scale=0.06, rotation=ROTATION, anchor=CAP,
                           base=(0.0, 0.0, 0.0), density_scale=0.25,  # (overridden by the fit)
                           sky="lantern_sky" + ("_t%d" % round(CAM_DIST) if round(CAM_DIST) != 52 else ""), key=KEY or (-0.75, 0.5, 0.45),
                           # the reference's sparkles: 4000 tiny emitters where its surface faces the key (upper left)
                           # (at radiance 40 in a pale green they clipped to white, spread evenly; the reference's
                           # are green, clustered where the surface faces the key squarely: power 8)
                           # (particles: in its smoke where the key's light reaches and the camera sees them, through
                           # the reference's own sparkle density -- the user's 13tornado.png, measured where it is
                           # prepared (make_volumes.py sparkle_mask) -- as a painted emission mask: its sparkles are a
                           # band along the lit upper flank of the neck into the head's top, none on the head's
                           # shadowed body or the soft foreground tail; drawn on the smoke's boundary they ran in
                           # streams along its ridges, half of them on the tail)
                           glitter=dict({"n": 15000, "threshold": 0.04, "power": 6.0, "size": 0.035, "rgb": (0.3, 1.0, 0.42),
                                         "radiance": 3.0, "seed": 1,  # pale green, as the reference's (109/187/123 over its smoke)
                                         "particles": True, "mask": "13tornado.png", "mask_sigma": 12.0, "mask_floor": 0.003},
                                        shadowed=bool(GLITTER[0]), size_sigma=GLITTER[1],
                                        **({"n": int(GLITTER[2])} if len(GLITTER) > 2 else {}),
                                        **({"size": GLITTER[3]} if len(GLITTER) > 3 else {}),
                                        **({"radiance": GLITTER[4]} if len(GLITTER) > 4 else {}),
                                        **({"cluster": (GLINT[0], GLINT[1])} if GLINT[0] > 1 else {}),
                                        **({"streak": GLINT[2]} if GLINT[2] > 0 else {}),
                                        **({"sprite_sigma": GLINT[3]} if GLINT[3] > 0 else {}),
                                        **({"spray": (GLINT[4], GLINT[5], GLINT[6])} if GLINT[4] > 0 else {}),
                                        **({"flakes": {"n": int(FLAKES[0]), "size": FLAKES[1], "size_sigma": FLAKES[2],
                                                       "cluster": (FLAKES[3], FLAKES[4]),
                                                       "spray": (FLAKES[5], GLINT[5], FLAKES[6]),
                                                       "streak": FLAKES[7], "seed": 2}} if FLAKES else {})),
                           # its own soft boxes: the tornado's, the fill raised (its mid-tones were 105 green to the
                           # reference's 125, its shadows 61 to 80)
                           panels=({"name": "Key", "dir": KEY or (-0.75, 0.5, 0.45), "dist": 36.0, "side": KEYSIZE_KNOB or 14.0, "rgb": (0.75, 1.0, 0.8),
                                    "radiance": LIGHTS[0] * (14.0 / (KEYSIZE_KNOB or 14.0)) ** 2},
                                   {"name": "Rim", "dir": (0.92, 0.2, -0.35), "dist": 44.0, "side": 14.0, "rgb": (0.55, 1.0, 0.95), "radiance": LIGHTS[1]},
                                   {"name": "Fill", "dir": (0.6, -0.55, 0.6), "dist": 34.0, "side": 12.0, "rgb": (0.3, 1.0, 0.45), "radiance": LIGHTS[2]}),
                           # (debris: the reference's dark flecks, each where its camera ray meets the smoke's surface:
                           # make_volumes.py dark_flecks, surface_hit -- LANTERN_DEBRIS=0 leaves them out)
                           **({"debris": {"mask": "13tornado.png", "tau_hit": 0.7, "rgb": (0.02, 0.03, 0.02)}}
                              if os.environ.get("LANTERN_DEBRIS", "1") != "0" else {}),
                           camera={"position": (0.0, 0.0, CAM_DIST), "target": (0.0, 0.0, 0.0), "focal": 50.0 * CAM_DIST / 52.0}),
    "lanterndust": dict(GREEN, src="Dust_Devil/Dust_Devil/embergen_dust_devil_tornado_a_%d.vdb", data="dustdevil", frame=50,
                        offset=(-128.5, -128.5, -192.5), scale=0.065, rotation=(-90.0, 0.0, 0.0), anchor=(0.0, -11.5, 0.0),
                        base=(0.0, 0.0, -192.5), density_scale=0.13,  # 2 a cm at density 1: its base is dense (1.0)
                        sky="lantern_sky", key=(-0.85, 0.45, 0.25),  # the sky's key: upper left, a little in front
                        glow={"n": 5, "heights": (-170.0, -110.0, -40.0, 40.0, 120.0), "rgb": (0.7, 1.0, 0.75), "power": 4200.0, "outside": 8.0},
                        camera={"position": (0.0, 0.0, 52.0), "target": (0.0, 0.0, 0.0), "focal": 50.0}),
}
# The construct for the decorrelation study, glowing from within (user, 2026-10-18: "make the scene such that mutation
# is useful", choosing "multiple scattering" and "construct glows itself"): the matched construct's smoke (its draw,
# fit and glitter) emitting by Bifrost's own simulated temperature -- the blackbody at (T - cutoff) x scale kelvin
# (black below ~800 K, white by 6400) times LeScale, tinted its energy's green (with little red, the cooler smoke's
# orange blackbody glows a dim green, not brown) -- motion blurred with its density. Its glow varies through its depth,
# which the mutations' depth moves explore; its multiple scattering is the study's 2 bounces (label lanternglow_b2).
# Lit by two big yellow soft boxes instead of the three tinted ones (user: "not many lights but maybe big yellow
# lights"; of a Yellow Lantern lit by his own light, "I want this yellow to appear on the volumetric to influence
# greatly"; and, of this look, "keep this look"): a key from the upper left and a rim from behind the right, each
# twice the side (28 cm, close to the smoke: its light varies across each, which the light moves explore). Its smoke
# near-neutral, a little warm -- the matched construct's green albedo scatters little red, so yellow light came off it
# lime -- its extinction the same (1 in each channel: its density, silhouette and fit unchanged): yellow where the
# light falls, its own glow green within. Without its sparkles (user: "you still added those sparkle lights, I don't
# want that"): their thousands of emitters are left out of the scene (its table still holds them).
# LANTERN_EMISSION "le_scale,cutoff,scale,lights" (0.004, 22, 600, 1): all read when the scene loads
EMISSION = _env("LANTERN_EMISSION") or (0.004, 22.0, 600.0, 1.0)
SHOTS["lanternglow"] = dict(SHOTS["lanternbifrost"], sigma_a=(0.25, 0.15, 0.45), sigma_s=(0.75, 0.85, 0.55),
                            src="BifrostVDB/%s_clean%s_t/construct_%%04d.vdb" % (CONSTRUCT, BLUR_TAG),  # (its temperature kept)
                            data=SHOTS["lanternbifrost"]["data"] + "_gl", sparkles=False,
                            panels=({"name": "Key", "dir": KEY or (-0.75, 0.5, 0.45), "dist": 36.0, "side": 28.0,
                                     "rgb": (1.0, 0.78, 0.12), "radiance": 30.0 * EMISSION[3]},
                                    {"name": "Rim", "dir": (0.92, 0.2, -0.35), "dist": 44.0, "side": 28.0,
                                     "rgb": (1.0, 0.72, 0.1), "radiance": 30.0 * EMISSION[3]}),
                            emission={"le_scale": EMISSION[0], "cutoff": EMISSION[1], "scale": EMISSION[2],
                                      "tint": (0.05, 1.0, 0.3)})
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


def glitter_quads(points, camera, size, stretch=None):
    """The construct's glitter (make_volumes.py write_lantern samples it): each point a square `size` cm across (or
    its own, a list) facing the camera -- lengthened by its `stretch` (a world vector each: how far it moves over the
    shutter) along that motion as the camera sees it, a motion-blurred glint -- wound so its emitting side faces the
    camera (corners a, b, c, d: triangles a b c, a c d; texture coordinates 0,0 1,0 1,1 0,1 along, across). Pure
    Python: Mogwai's scene builder runs it."""
    eye, target = camera["position"], camera["target"]
    f = [target[i] - eye[i] for i in range(3)]
    n = sum(v * v for v in f) ** 0.5
    f = [v / n for v in f]
    r = [f[1] * 0 - f[2] * 1, f[2] * 0 - f[0] * 0, f[0] * 1 - f[1] * 0]  # f x up(0, 1, 0)
    n = sum(v * v for v in r) ** 0.5
    r = [v / n for v in r]
    u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]]  # r x f
    sizes = size if isinstance(size, (list, tuple)) else [size] * len(points)
    quads = []
    for k, (p, h) in enumerate(zip(points, sizes)):
        sr = su = 0.0
        if stretch is not None:
            sr = sum(stretch[k][i] * r[i] for i in range(3))
            su = sum(stretch[k][i] * u[i] for i in range(3))
        length = (sr * sr + su * su) ** 0.5
        ca, sa = (sr / length, su / length) if length > 1e-12 else (1.0, 0.0)
        a = [ca * r[i] + sa * u[i] for i in range(3)]  # along its motion, in the camera's plane
        b = [-sa * r[i] + ca * u[i] for i in range(3)]  # across it (a, b: (r, u) turned, so the winding holds)
        quads.append([[p[i] + (h + length) / 2 * s * a[i] + h / 2 * t * b[i] for i in range(3)]
                      for s, t in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
    return quads
