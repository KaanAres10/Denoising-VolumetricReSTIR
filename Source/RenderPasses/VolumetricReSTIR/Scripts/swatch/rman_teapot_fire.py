r"""The fire teapot rendered by RenderMan itself (user's reference picture, 2026-10-11; RenderMan for Blender 27.3), as
the target the Falcor shot (scenes/teapot_fire.pyscene) is matched against. Builds the shot in the swatch .blend --
which does not keep it: its teapot wears a checker test texture and its fire VDB sits untransformed below the floor --
and renders it:

    set RMANTREE=C:\Program Files\Pixar\RenderManProServer-27.3\
    blender -b RenderMan_Swatch_Blender/Prman_Swatch.blend --python rman_teapot_fire.py -- <out.png> [options]

options: rig=night|studio|day (the file's light rigs: a dome and four soft boxes), size=512, samples=256, rects=1
(the soft boxes' intensity factor), dome=1, fireexp=8 (PxrBlackBody exposure, the file's), iron=r,g,b, bump=0.08,
bumpfreq=3, view=Standard (Blender's view transform; the file's Filmic washes the fire toward white), exposure=0,
scale=0.12 (cm a voxel), base=14 (the fire's bottom, cm), yaw=90, specface / specedge = r,g,b, specrough=0.35;
hdr=1 also writes scene-linear radiance (below). For measuring the renderer, light by light: fire=0 (the fire hidden),
hide=name,... (objects hidden), densityvar= / tempvar= (the grids the fire's density and temperature read),
firealbedo= (the flame's scattering colour, 1 in the file), diffdepth= (diffuse bounces, 1 in the file).

The target (VolumetricReSTIRData/swatch/rman_target: full, and by light fire / dome / rects with the others at 0):
rig=night size=512 samples=512 view=Standard fireexp=10 rects=0.25 dome=0.5 iron=0.1,0.05,0.04
specface=0.1,0.08,0.07 specedge=0.5,0.45,0.4 bumpfreq=1.2 bump=0.15 hdr=1.

The fire goes where swatch_fire.py puts it in Falcor (its middle over the opening, its bottom at 14 cm, turned 90
degrees, 0.12 cm a voxel), with the file's own fire material (PxrVolume, islight = 1: RenderMan renders it as a light).
"""
import math
import os
import sys
import time

import addon_utils
import bpy

args = sys.argv[sys.argv.index("--") + 1:]
OUT = args[0]
OPT = dict(a.split("=", 1) for a in args[1:])
RIG = OPT.get("rig", "night")
HERE = os.path.dirname(bpy.data.filepath)

addon_utils.enable("RenderManForBlender", default_set=True, persistent=True)
import RenderManForBlender.rfb_api as rfb_api  # noqa: E402

sc = bpy.context.scene
vl = sc.view_layers["teapot_solid_" + RIG]
print('engine', sc.render.engine, 'window', bpy.context.window)
# the shot's view layer alone: Blender renders every view layer, and a saved image may be any one's result (switching
# the others off instead -- view_layer.use -- leaves RenderMan rendering nothing)
for other in [v for v in sc.view_layers if v != vl]:
    sc.view_layers.remove(other)

KEEP = {"TEAPOT", "Teapot_Hollow", "VOLUMES", "Fire", "LIGHTS", "Lights_" + RIG.capitalize(), "MISC", "Floor_Grid"}


def show(lc):
    keep = lc.name in KEEP or lc.name == "Scene Collection"
    if lc.name != "Scene Collection":
        lc.exclude = not keep
    lc.hide_viewport = False
    for child in lc.children:
        show(child)


show(vl.layer_collection)
for name in ("renderman_Text", "ten_cm_text"):
    if name in bpy.data.objects:
        bpy.data.objects[name].hide_render = True

# the floor: plain light grey (the swatch's floor_clean_mat, PxrSurface diffuse 0.69)
# (RenderMan for Blender 27.3 cannot create a complete PxrSurface under Blender 5.0 -- its array inputs fail -- so the
# shot reuses the file's own PxrSurface materials, copied)
floor_mat = bpy.data.materials["floor_clean_mat"]
for name in ("floor_W_Grid", "floor"):
    if name in bpy.data.objects:
        rfb_api.attach_material(floor_mat, bpy.data.objects[name])

# the pot: rough cast iron -- dark red-brown, a rough dielectric specular, pitted by a fractal bump in object space
iron = tuple(float(v) for v in OPT.get("iron", "0.05,0.025,0.02").split(","))
pot_mat = bpy.data.materials["midGrey_mat"].copy()
pot_mat.name = "castIron_mat"
pot = next(n for n in pot_mat.node_tree.nodes if n.bl_idname.startswith("PxrSurface"))
pot.diffuseColor = iron
pot.specularFaceColor = tuple(float(v) for v in OPT.get("specface", "0.06,0.05,0.045").split(","))
pot.specularEdgeColor = tuple(float(v) for v in OPT.get("specedge", "0.25,0.22,0.2").split(","))
pot.specularRoughness = float(OPT.get("specrough", "0.35"))
fractal = rfb_api.create_pattern("PxrFractal", pot_mat)
fractal.frequency = float(OPT.get("bumpfreq", "3.0"))
fractal.layers = 6
bump = rfb_api.create_pattern("PxrBump", pot_mat)
bump.scale = float(OPT.get("bump", "0.08"))
rfb_api.connect_nodes(fractal, "resultF", bump, "inputBump")
rfb_api.connect_nodes(bump, "resultN", pot, "bumpNormal")
for name in ("teapot_Body_Hollow.001", "teapot_Base_02.001", "teapot_Foot_Left_02.001", "teapot_Foot_Right_02.001",
             "teapot_Steps_02.001"):
    rfb_api.attach_material(pot_mat, bpy.data.objects[name])

# the fire: the local VDB, placed as in Falcor (swatch_fire.py), the file's PxrVolume (islight = 1)
fire = bpy.data.objects["fire_VDB"]
fire.data.filepath = os.path.join(HERE, "VDB", "embergen_fire_a_67.vdb")
s = float(OPT.get("scale", "0.12"))
yaw = math.radians(float(OPT.get("yaw", "90")))
base = float(OPT.get("base", "14"))
mx, my, mz = -1.5, -33.5, -128.5  # the fire's middle and bottom, voxels
rx, ry = mx * math.cos(yaw) - my * math.sin(yaw), mx * math.sin(yaw) + my * math.cos(yaw)
fire.parent = None
fire.rotation_mode = "XYZ"
fire.rotation_euler = (0.0, 0.0, yaw)
fire.scale = (s, s, s)
fire.location = (0.2 - s * rx, 0.6 - s * ry, base - s * mz)  # Blender: the opening at (0.2, 0.6), y = -Falcor z
fire_mat = fire.data.materials[0]
for n in fire_mat.node_tree.nodes:
    if n.bl_idname.startswith("PxrBlackBody"):
        n.exposure = float(OPT.get("fireexp", "8"))
    if n.bl_idname.startswith("PxrVolume") and "densityvar" in OPT:
        n.densityFloatPrimVar = OPT["densityvar"]
    if n.bl_idname.startswith("PxrVolume") and "firealbedo" in OPT:
        n.diffuseColor = (float(OPT["firealbedo"]),) * 3
    if n.bl_idname.startswith("PxrPrimvar") and "tempvar" in OPT:
        n.varname = OPT["tempvar"]
if OPT.get("fire", "1") == "0":
    fire.hide_render = True
for name in OPT.get("hide", "").split(","):
    if name in bpy.data.objects:
        bpy.data.objects[name].hide_render = True

# light levels
for ob in bpy.data.objects:
    if ob.type == "LIGHT" and ob.data.node_tree:
        for n in ob.data.node_tree.nodes:
            if n.bl_idname.startswith("PxrRectLight"):
                n.intensity = n.intensity * float(OPT.get("rects", "1"))
            if n.bl_idname.startswith("PxrDomeLight"):
                n.intensity = getattr(n, "intensity", 1.0) * float(OPT.get("dome", "1"))

size = int(OPT.get("size", "512"))
sc.render.resolution_x = sc.render.resolution_y = size
sc.render.resolution_percentage = 100
sc.renderman.hider_maxSamples = int(OPT.get("samples", "256"))
sc.renderman.hider_minSamples = min(16, sc.renderman.hider_maxSamples)
if "diffdepth" in OPT:
    sc.renderman.ri_maxDiffuseDepth = int(OPT["diffdepth"])
sc.camera = bpy.data.objects["RenderManCam"]
print('view transform was', sc.view_settings.view_transform, 'look', sc.view_settings.look)
sc.view_settings.view_transform = OPT.get("view", "Standard")
sc.view_settings.look = "None"
sc.view_settings.exposure = float(OPT.get("exposure", "0"))
sc.render.filepath = OUT
sc.render.image_settings.file_format = "PNG"
t0 = time.time()
if OPT.get("hdr") == "1":
    # Scene-linear radiance, for comparing with Falcor: two 16-bit linear PNGs (view Raw) at exposure 0 and -10 stops,
    # <out>_lo.png (0..1) and <out>_hi.png (0..1024), merged by outputs/decorr/match_teapot.py; <out> as viewed.
    bpy.ops.render.render(write_still=False, layer=vl.name)
    img = bpy.data.images["Render Result"]
    img.save_render(OUT, scene=sc)
    sc.render.image_settings.color_depth = "16"
    sc.view_settings.view_transform = "Raw"
    for tag, ev in (("_lo", 0.0), ("_hi", -10.0)):
        sc.view_settings.exposure = ev
        img.save_render(OUT[:-4] + tag + ".png", scene=sc)
else:
    bpy.ops.render.render(write_still=True, layer=vl.name)
print("RENDER DONE in %.1fs -> %s (rig %s)" % (time.time() - t0, OUT, RIG))
