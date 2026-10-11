# The RenderMan swatch teapot for scenes/teapot_fire.pyscene (user, 2026-10-11). Run inside Blender:
#     blender -b RenderMan_Swatch_Blender/Prman_Swatch.blend --python blend_export.py -- VolumetricReSTIRData/swatch
# then convert the fire (its density lives in a grid named 'flames', which gImportVDB skips) with
#     VDBPrep.exe RenderMan_Swatch_Blender/VDB/embergen_fire_a_67.vdb <tmp>/embergen_fire_a_67.vdb flames=density
#     gImportVDB.exe <tmp>/embergen_fire_a_67.vdb 4        (from legacy/GVDBConverter; move the folder to swatch/)
# Points the two VDB objects at their local files and prints their world bounds; exports the hollow teapot, its stand
# and the clean floor (cm, Blender's z-up) as one OBJ in Falcor's y-up (forward -z), materials kept by name.
import os
import sys

import bpy
from mathutils import Vector

out_dir = sys.argv[sys.argv.index("--") + 1]
here = os.path.dirname(bpy.data.filepath)

for name, f in (("fire_VDB", "embergen_fire_a_67.vdb"), ("teapot_volume_VDB", "teapot_Volume_Thick.vdb")):
    o = bpy.data.objects[name]
    o.data.filepath = os.path.join(here, "VDB", f)
    o.data.grids.load()
    print("== %s grids %s" % (name, [g.name for g in o.data.grids]))
    corners = [o.matrix_world @ Vector(c) for c in o.bound_box]
    lo = [min(c[i] for c in corners) for i in range(3)]
    hi = [max(c[i] for c in corners) for i in range(3)]
    print("   world bounds (cm, z up): min (%.3f, %.3f, %.3f) max (%.3f, %.3f, %.3f)" % (*lo, *hi))
    for g in o.data.grids:
        try:
            print("   grid %s matrix_object %s" % (g.name, [list(r) for r in g.matrix_object]))
        except Exception as e:  # noqa: BLE001
            print("   grid", g.name, "no matrix:", e)
    mat = o.data.materials[0] if o.data.materials else None
    if mat and mat.use_nodes:
        for n in mat.node_tree.nodes:
            vals = {i.name: (tuple(i.default_value) if hasattr(i.default_value, "__len__") else i.default_value)
                    for i in n.inputs if hasattr(i, "default_value") and not i.is_linked}
            print("   node %s %s %s" % (n.type, n.name, {k: v for k, v in list(vals.items())[:12]}))

keep = ["teapot_Body_Hollow.001", "teapot_Base_02.001", "teapot_Foot_Left_02.001", "teapot_Foot_Right_02.001",
        "teapot_Steps_02.001", "floor"]


def include(layer_collection, names):
    """Un-exclude (and show) the named collections and their parents in the active view layer."""
    found = layer_collection.name in names
    for child in layer_collection.children:
        found = include(child, names) or found
    if found:
        layer_collection.exclude = False
        layer_collection.hide_viewport = False
        layer_collection.collection.hide_viewport = False
    return found


include(bpy.context.view_layer.layer_collection, {"Teapot_Hollow", "Floor_Clean"})
bpy.context.view_layer.update()
bpy.ops.object.select_all(action="DESELECT")
for n in keep:
    o = bpy.data.objects[n]
    o.hide_set(False)
    o.hide_viewport = False
    o.select_set(True)
    corners = [o.matrix_world @ Vector(c) for c in o.bound_box]
    print("== %-26s bounds min %s max %s materials %s" % (
        n, tuple(round(min(c[i] for c in corners), 2) for i in range(3)),
        tuple(round(max(c[i] for c in corners), 2) for i in range(3)), [m.name for m in o.data.materials if m]))
bpy.context.view_layer.objects.active = bpy.data.objects[keep[0]]
path = os.path.join(out_dir, "teapot_swatch.obj")
bpy.ops.wm.obj_export(filepath=path, export_selected_objects=True, forward_axis="NEGATIVE_Z", up_axis="Y",
                      export_materials=True, export_uv=True, export_normals=True, apply_modifiers=True)
print("== exported", path, os.path.getsize(path))
