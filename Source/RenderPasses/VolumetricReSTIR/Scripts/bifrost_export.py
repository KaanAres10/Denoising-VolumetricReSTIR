"""Bifrost simulations exported as OpenVDB for Volumetric ReSTIR (user, 2026-10-17: "I have Maya and Bifrost: can we use
this production pipeline to generate complex movie-production volumetrics and export them to Volumetric ReSTIR?").

A Bifrost graph -- one Bifrost ships (resources/graphs, e.g. Graphs::Aero::large_turbulent_fire) or one of ours -- is
wrapped (wrap_graph) in a copy that writes its volume to <out>/<stem>_####.vdb every frame (write_OpenVDB_volume, its
frame from Bifrost's own time), published to a private library for this process only (BIFROST_LIB_CONFIG_FILES: the
user's Autodesk folders are left alone), put on a bifrostBoard in a headless Maya and stepped frame by frame -- Aero is
stateful, so in order from the first frame -- each step pulled by reading the wrapper's `written` flag on the board
(Bifrost evaluates what a board output needs). The .vdb files then go through make_volumes.import_vdb.

Run under Maya's Python (the wrapping alone is plain Python, tested in tests/test_bifrost_export.py):

    mayapy bifrost_export.py <graph.json> <compound> <volume output> <out dir> <stem> <first> <last> [node.port=type:value ...]

e.g. ... large_turbulent_fire.json Graphs::Aero::large_turbulent_fire post_process_temperature.out_geometry D:/vdb fire 1 120
(`node.port=type:value` sets one of the graph's values, as the Bifrost editor would.)
"""
import copy
import json
import os
import sys
import time

NAMESPACE = "Lantern::Export"
BIFROST = r"C:\Program Files\Autodesk\Bifrost\Maya2027\3.1.0.8\bifrost"
GRAPHS = BIFROST + r"\resources\graphs"


PROPERTIES = "voxel_fog_density voxel_temperature"  # what the renderer reads (all of them: the fire's 120 frames, 7.3 GB)


def wrap_graph(definition, compound, volume_output, out_dir, stem, overrides, properties=PROPERTIES):
    """A copy of `definition` with `compound` renamed into NAMESPACE (<short name>_vdb) and extended to write
    `volume_output` (node.port of an Object holding volumes) to <out_dir>/<stem>_####.vdb each frame, its `properties`
    (space separated; "*" for all), raising its `written` output port when the file is written; `overrides`
    ({node.port: (type, value)}) replace or add the graph's values. The source is not modified."""
    d = copy.deepcopy(definition)
    c = next(c for c in d["compounds"] if c["name"] == compound)
    d["compounds"] = [c]
    c["name"] = "%s::%s_vdb" % (NAMESPACE, compound.split("::")[-1])
    c.setdefault("ports", []).append({"portName": "written", "portDirection": "output", "portType": "bool"})
    src_port = volume_output.split(".")[-1]
    c.setdefault("compoundNodes", []).extend([
        {"nodeName": "time", "nodeType": "Core::Time::time"},
        {"nodeName": "to_long", "nodeType": "Core::Type_Conversion::to_long"},
        # `volumes` is a fan-in port: each source gets its own sub-port, named after the source port
        {"nodeName": "write_OpenVDB_volume", "nodeType": "File::Geometry::write_OpenVDB_volume",
         "fanInPortNames": {"volumes": [src_port]}}])
    c.setdefault("connections", []).extend([
        {"source": volume_output, "target": "write_OpenVDB_volume.volumes.%s" % src_port},
        {"source": "time.frame", "target": "to_long.from"},
        {"source": "to_long.long", "target": "write_OpenVDB_volume.frame"},
        {"source": "write_OpenVDB_volume.success", "target": ".written"}])
    writer = {"filename": ("string", "%s_####.vdb" % stem), "directory": ("string", out_dir), "properties": ("string", properties),
              "overwrite": ("bool", "true"), "create_directories": ("bool", "true")}
    values = dict((v["valueName"], v) for v in c.get("values", []))
    for name, (vtype, value) in list({"write_OpenVDB_volume." + k: v for k, v in writer.items()}.items()) + list(overrides.items()):
        values[name] = {"valueName": name, "valueType": vtype, "value": value}
    c["values"] = list(values.values())
    return d


def library_config(lib_dir):
    """A Bifrost library configuration (BIFROST_LIB_CONFIG_FILES) loading every compound in `lib_dir`."""
    return {"AminoConfigurations": [{"vendorName": "Volumetric ReSTIR", "libraryVersion": "1.0.0", "libraryName": "lantern_export",
                                     "jsonLibs": [{"path": lib_dir, "files": []}]}]}


def parse_overrides(args):
    """["node.port=type:value", ...] -> {node.port: (type, value)}."""
    out = {}
    for a in args:
        name, rest = a.split("=", 1)
        vtype, value = rest.split(":", 1)
        out[name] = (vtype, value)
    return out


def simulate(compound, first, last, log=print):
    """Put `compound` (NAMESPACE::name, already in a loaded library) on a board in this headless Maya and step frames
    first..last in order, pulling each by its `written` flag. Returns the frames written."""
    import maya.cmds as cmds
    board = cmds.createNode("bifrostBoard", name="exportBoard")
    namespace, name = compound.rsplit("::", 1)
    node = cmds.vnnCompound(board, "/", addNode="BifrostGraph,%s,%s" % (namespace, name))[0]
    cmds.vnnNode(board, "/output", createInputPort=("written", "bool"))
    cmds.vnnConnect(board, ".%s.written" % node, ".written")
    written = []
    for f in range(first, last + 1):
        cmds.currentTime(f)
        t0 = time.time()
        ok = cmds.getAttr(board + ".written")
        log("frame %d %s %.1fs" % (f, "written" if ok else "NOT WRITTEN", time.time() - t0))
        if not ok:
            break
        written.append(f)
    return written


def main(argv):
    graph, compound, volume_output, out_dir, stem, first, last = argv[1:8]
    overrides = parse_overrides(argv[8:])
    out_dir = os.path.abspath(out_dir).replace("\\", "/")
    lib = os.path.join(out_dir, "_bifrost_lib").replace("\\", "/")
    os.makedirs(lib, exist_ok=True)
    with open(graph, encoding="utf-8") as fh:
        wrapped = wrap_graph(json.load(fh), compound, volume_output, out_dir, stem, overrides)
    with open(os.path.join(lib, stem + "_vdb.json"), "w", encoding="utf-8") as fh:
        json.dump(wrapped, fh, indent=1)
    config = os.path.join(lib, "config.json")
    with open(config, "w", encoding="utf-8") as fh:
        json.dump(library_config(lib), fh, indent=1)
    # this process only, and before Bifrost loads
    os.environ["BIFROST_LIB_CONFIG_FILES"] = os.pathsep.join(p for p in (config, os.environ.get("BIFROST_LIB_CONFIG_FILES")) if p)
    import maya.standalone
    maya.standalone.initialize(name="python")
    import maya.cmds as cmds
    cmds.loadPlugin("bifrostGraph", quiet=True)
    try:
        frames = simulate(wrapped["compounds"][0]["name"], int(first), int(last))
    finally:
        maya.standalone.uninitialize()
    print("BIFROST_EXPORT wrote %d frames to %s" % (len(frames), out_dir))
    return 0 if frames and frames[-1] == int(last) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
