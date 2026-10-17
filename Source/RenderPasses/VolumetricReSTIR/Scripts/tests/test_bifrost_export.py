"""bifrost_export.py's graph wrapping (pure JSON: no Maya needed)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import bifrost_export as bx  # noqa: E402


def example():
    return {"header": {"metadata": []}, "namespaces": [], "types": [],
            "compounds": [{"name": "Graphs::Aero::fire", "ports": [{"portName": "material", "portDirection": "input", "portType": "Object"}],
                           "compounds": [{"name": "post_process_temperature"}],
                           "compoundNodes": [{"nodeName": "simulate_aero", "nodeType": "Simulation::Aero::simulate_aero"},
                                             {"nodeName": "post_process_temperature", "nodeType": "post_process_temperature"},
                                             {"nodeName": "switch", "nodeType": "Core::Logic::if"}],
                           "connections": [{"source": "simulate_aero.aero_volume", "target": "post_process_temperature.first"}],
                           "values": [{"valueName": "switch.condition", "valueType": "bool", "value": "false"}]}]}


class TestWrapGraph(unittest.TestCase):
    def setUp(self):
        self.d = bx.wrap_graph(example(), "Graphs::Aero::fire", "post_process_temperature.out_geometry", "C:/out", "fire",
                               {"switch.condition": ("bool", "true")})
        self.c = self.d["compounds"][0]

    def test_renamed_into_our_namespace_with_its_own_graph_kept(self):
        self.assertEqual(self.c["name"], bx.NAMESPACE + "::fire_vdb")
        names = [n["nodeName"] for n in self.c["compoundNodes"]]
        self.assertTrue({"simulate_aero", "post_process_temperature", "switch"} <= set(names))
        self.assertIn({"source": "simulate_aero.aero_volume", "target": "post_process_temperature.first"}, self.c["connections"])
        self.assertEqual(self.c["compounds"], [{"name": "post_process_temperature"}])  # its local compounds travel with it

    def test_the_volume_is_written_every_frame(self):
        nodes = {n["nodeName"]: n for n in self.c["compoundNodes"]}
        w = nodes["write_OpenVDB_volume"]
        self.assertEqual(w["nodeType"], "File::Geometry::write_OpenVDB_volume")
        self.assertEqual(w["fanInPortNames"], {"volumes": ["out_geometry"]})  # a fan-in port: one sub-port per source
        conns = self.c["connections"]
        self.assertIn({"source": "post_process_temperature.out_geometry", "target": "write_OpenVDB_volume.volumes.out_geometry"}, conns)
        self.assertIn({"source": "time.frame", "target": "to_long.from"}, conns)
        self.assertIn({"source": "to_long.long", "target": "write_OpenVDB_volume.frame"}, conns)
        self.assertIn({"source": "write_OpenVDB_volume.success", "target": ".written"}, conns)
        self.assertIn({"portName": "written", "portDirection": "output", "portType": "bool"}, self.c["ports"])
        values = {v["valueName"]: v["value"] for v in self.c["values"]}
        self.assertEqual(values["write_OpenVDB_volume.filename"], "fire_####.vdb")
        self.assertEqual(values["write_OpenVDB_volume.directory"], "C:/out")
        # only what the renderer reads (every property, velocities and all, made the fire's 120 frames 7.3 GB)
        self.assertEqual(values["write_OpenVDB_volume.properties"], "voxel_fog_density voxel_temperature")

    def test_overrides_replace_the_graphs_values(self):
        values = [v for v in self.c["values"] if v["valueName"] == "switch.condition"]
        self.assertEqual(values, [{"valueName": "switch.condition", "valueType": "bool", "value": "true"}])

    def test_the_source_graph_is_left_alone(self):
        e = example()
        bx.wrap_graph(e, "Graphs::Aero::fire", "post_process_temperature.out_geometry", "C:/out", "fire", {})
        self.assertEqual(e, example())

    def test_library_config_points_at_the_compound_folder(self):
        cfg = bx.library_config("C:/work/lib")
        libs = cfg["AminoConfigurations"][0]["jsonLibs"]
        self.assertEqual(libs, [{"path": "C:/work/lib", "files": []}])

    def test_overrides_parse_from_the_command_line(self):
        self.assertEqual(bx.parse_overrides(["switch.condition=bool:true", "value.value=float:0.05"]),
                         {"switch.condition": ("bool", "true"), "value.value": ("float", "0.05")})


if __name__ == "__main__":
    unittest.main()
