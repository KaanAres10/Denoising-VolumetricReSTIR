"""vr_graph.add_gbuffer on a backend without rasterizer ordered views: GBufferRT, agreeing with GBufferRaster on pixels with no geometry.

Without rasterMiss, NRD reads those pixels as past its denoising range and the background comes out black, with no error.

    python -m unittest test_gbuffer_fallback -v
"""
import unittest

from test_vr_graph_study import Recorder, fresh_vr

ROV_ERROR = "GBufferRaster requires rasterizer ordered views (ROVs) support."


def add_gbuffer_with(vr, refuse):
    created = []

    def create_pass(name, props=None):
        if name == "GBufferRaster" and refuse:
            raise RuntimeError(refuse)
        created.append((name, dict(props)))
        return name

    vr.createPass = create_pass
    graph = Recorder()
    returned = vr.add_gbuffer(graph, (960, 540), jitter=False)
    return created, graph, returned


class TestGBufferFallback(unittest.TestCase):
    def setUp(self):
        self.vr, _ = fresh_vr()

    def test_d3d12_keeps_the_raster_pass_untouched(self):
        created, _, _ = add_gbuffer_with(self.vr, refuse=None)
        self.assertEqual([name for name, _ in created], ["GBufferRaster"])
        self.assertNotIn("rasterMiss", created[0][1])

    def test_vulkan_falls_back_to_rt_with_raster_misses(self):
        created, _, _ = add_gbuffer_with(self.vr, refuse=ROV_ERROR)
        self.assertEqual([name for name, _ in created], ["GBufferRT"])
        self.assertIs(created[0][1]["rasterMiss"], True)

    def test_the_fallback_keeps_the_settings_and_the_pass_name(self):
        raster, _, _ = add_gbuffer_with(self.vr, refuse=None)
        rt, graph, returned = add_gbuffer_with(self.vr, refuse=ROV_ERROR)
        self.assertEqual({k: v for k, v in rt[0][1].items() if k != "rasterMiss"}, raster[0][1])
        # The graph's edges name the pass GBufferRaster, whichever one it is.
        self.assertEqual(returned, "GBufferRaster")
        self.assertEqual(graph.calls[0][1], ("GBufferRT", "GBufferRaster"))

    def test_any_other_failure_still_raises(self):
        with self.assertRaises(RuntimeError):
            add_gbuffer_with(self.vr, refuse="GBufferRaster requires pixel shader barycentrics support.")


if __name__ == "__main__":
    unittest.main()
