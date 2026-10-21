"""five_runs.py: the paper's planned captures, and the finished-run check.

    cd outputs/decorr && python -m unittest test_five_runs -v
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import five_runs as fr


def env_of(r):
    return dict(kv.split("=", 1) for kv in r["env"])


class TestList(unittest.TestCase):
    def test_lines_end_in_lf_only(self):
        # run_five.sh reads the list with `read`, which keeps a \r in the last field (VR_DENOISERS=...reblur\r)
        here = os.path.dirname(os.path.abspath(__file__))
        out = subprocess.run([sys.executable, os.path.join(here, "five_runs.py"), "--list"],
                             capture_output=True, check=True).stdout
        self.assertNotIn(b"\r", out)
        self.assertEqual(out.count(b"\n"), 152)


class TestPlan(unittest.TestCase):
    def test_scene_env_follows_run_study(self):
        self.assertEqual(fr.scene_env("bunnycathedral_d0.3_b2"),
                         ["VR_SCENE=bunnycathedral", "VR_DENSITY_MULT=0.3", "VR_MAX_BOUNCES=2"])
        self.assertEqual(fr.scene_env("wdasstorm_g0.5"), ["VR_SCENE=wdasstorm", "VR_PHASE_G=0.5"])
        self.assertEqual(fr.scene_env("explosion"), ["VR_SCENE=explosion"])

    def test_152_captures_the_long_history_first(self):
        runs = fr.runs()
        self.assertEqual(len(runs), 19 * 2 * 2 * 2)
        self.assertEqual(len({(r["label"], r["config"]) for r in runs}), len(runs))
        hist = [r["config"].split("_")[1] for r in runs]
        self.assertEqual(hist, ["c200"] * (len(runs) // 2) + ["ship"] * (len(runs) // 2))

    def test_a_two_bounce_mutated_long_history_capture(self):
        r = next(r for r in fr.runs() if r["label"] == "bunnysoftbox_b2" and r["config"] == "fd_c200_m5")
        env = env_of(r)
        self.assertEqual(env["VR_MTHRESH"], "200")
        self.assertEqual(env["VR_MUT_STRAT"], "light,depth,select,flight,direction,distance,rebounce")
        self.assertEqual((env["VR_MUTATIONS"], env["VR_MUT_AFTER_SPATIAL"]), ("5", "1"))
        self.assertEqual(env["VR_DENOISERS"], "optix,oidn,relax,reblur")
        self.assertEqual((env["VR_DISPLAY"], env["VR_CHAINS"], env["VR_PER_CHAIN"]), ("1920x1080", "2", "1"))
        self.assertEqual(env["VR_NRD_SPLIT"], "1")
        self.assertEqual(r["captures"], 10)  # 2 frames x (4 denoisers + raw)

    def test_the_shipped_rr_capture_of_a_small_setup(self):
        r = next(r for r in fr.runs() if r["label"] == "bunnyswarm_d3" and r["config"] == "fr_ship_m0")
        env = env_of(r)
        self.assertNotIn("VR_MTHRESH", env)
        self.assertNotIn("VR_MUTATIONS", env)
        self.assertEqual((env["VR_DENOISER"], env["VR_DISPLAY"], r["captures"]), ("rr", "960x540", 2))

    def test_one_bounce_setups_get_the_four_first_vertex_moves(self):
        r = next(r for r in fr.runs() if r["label"] == "bunnylanterns" and r["config"] == "fr_c200_m5")
        self.assertEqual(env_of(r)["VR_MUT_STRAT"], "light,depth,select,flight")

    def test_split_sets(self):
        runs = fr.runs(("optix,oidn", "relax,reblur"))
        names = {r["config"] for r in runs if r["label"] == "explosion"}
        self.assertTrue({"fd1_c200_m0", "fd2_ship_m5", "fr_ship_m5"} <= names)
        self.assertEqual(len(runs), 19 * 2 * 2 * 3)
        self.assertEqual(next(r for r in runs if r["config"] == "fd1_c200_m0")["captures"], 6)


class TestComplete(unittest.TestCase):
    def make(self, root, n, log="frames rendered"):
        with open(os.path.join(root, "c.schedule.json"), "w") as fh:
            fh.write("{}")
        with open(os.path.join(root, "run.log"), "w") as fh:
            fh.write(log)
        for i in range(n):
            with open(os.path.join(root, "c.X.output.%d.exr" % i), "w") as fh:
                fh.write("x")

    def test_finished(self):
        with tempfile.TemporaryDirectory() as root:
            self.make(root, 10)
            self.assertTrue(fr.complete(root, 10))

    def test_too_few_or_too_many_captures(self):
        with tempfile.TemporaryDirectory() as root:
            self.make(root, 9)
            self.assertFalse(fr.complete(root, 10))
        with tempfile.TemporaryDirectory() as root:
            self.make(root, 11)
            self.assertFalse(fr.complete(root, 10))

    def test_a_falcor_error(self):
        with tempfile.TemporaryDirectory() as root:
            self.make(root, 10, log="(Error) shader compilation failed")
            self.assertFalse(fr.complete(root, 10))

    def test_nothing_there(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertFalse(fr.complete(root, 10))
            self.assertFalse(fr.complete(os.path.join(root, "missing"), 10))


if __name__ == "__main__":
    unittest.main()
