import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import swatch_fire as sf  # noqa: E402


def gvdb_matrix(rotation):
    """SceneGVDB's rotation: Rx Ry Rz (Rz applied first), right-handed, degrees."""
    a, b, c = (math.radians(v) for v in rotation)
    rx = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
    ry = np.array([[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]])
    rz = np.array([[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]])
    return rx @ ry @ rz


class TestSwatchFire(unittest.TestCase):
    def test_to_world_is_gvdbs_transform(self):
        # what the lights' positions must agree with: T + s Rx Ry Rz p, as SceneGVDB places the volume
        rotation, scale = (-80.0, 12.0, 135.0), 0.1
        t = sf.translation(scale=scale, rotation=rotation)
        p = (3.0, -40.0, -60.0)
        expect = np.array(t) + scale * gvdb_matrix(rotation) @ np.array(p)
        np.testing.assert_allclose(sf.to_world(p, scale=scale, rotation=rotation), expect, atol=1e-9)

    def test_the_fire_stands_on_its_anchor(self):
        # the fire's middle (voxel x, y) and bottom (voxel z) at the anchor, whatever the pose
        for rotation in ((-90.0, 0.0, 90.0), (-70.0, 15.0, 200.0)):
            w = sf.to_world((sf.MIDDLE[0], sf.MIDDLE[1], sf.BOTTOM), scale=0.09, rotation=rotation, anchor=(1.0, 16.0, -2.0))
            np.testing.assert_allclose(w, (1.0, 16.0, -2.0), atol=1e-9)

    def test_upright_pose_turns_about_the_vertical(self):
        # stood up by -90 about x, the voxel z axis is world up and a yaw turns about it
        up = np.array(sf.to_world((0.0, 0.0, 1.0), rotation=(-90.0, 0.0, 37.0))) - np.array(sf.to_world((0.0, 0.0, 0.0), rotation=(-90.0, 0.0, 37.0)))
        np.testing.assert_allclose(up / np.linalg.norm(up), (0.0, 1.0, 0.0), atol=1e-9)


if __name__ == "__main__":
    unittest.main()


class TestGlitterQuads(unittest.TestCase):
    """lantern.glitter_quads: the construct's glitter as tiny emissive squares facing the camera."""

    def test_each_point_becomes_a_square_facing_the_camera(self):
        import lantern
        cam = {"position": (0.0, 0.0, 52.0), "target": (0.0, 0.0, 0.0)}
        quads = lantern.glitter_quads([(1.0, 2.0, 3.0), (-4.0, 0.0, 0.0)], cam, 0.1)
        self.assertEqual(len(quads), 2)
        a, b, c, d = [tuple(x) for x in quads[0]]
        centre = [sum(v[i] for v in (a, b, c, d)) / 4 for i in range(3)]
        self.assertTrue(all(abs(centre[i] - (1.0, 2.0, 3.0)[i]) < 1e-9 for i in range(3)))
        side = sum((b[i] - a[i]) ** 2 for i in range(3)) ** 0.5
        self.assertAlmostEqual(side, 0.1)
        # wound so (b - a) x (c - a) points at the camera (the emitting side)
        e1 = [b[i] - a[i] for i in range(3)]
        e2 = [c[i] - a[i] for i in range(3)]
        n = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
        to_cam = [cam["position"][i] - centre[i] for i in range(3)]
        self.assertGreater(sum(n[i] * to_cam[i] for i in range(3)), 0.0)

