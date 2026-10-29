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
        self.assertEqual(out.count(b"\n"), 152 + (19 + 19 + 18) * 2 * 2)  # the paper's, then the cap sweep


class TestPlan(unittest.TestCase):
    def test_scene_env_follows_run_study(self):
        self.assertEqual(fr.scene_env("bunnycathedral_d0.3_b2"),
                         ["VR_SCENE=bunnycathedral", "VR_DENSITY_MULT=0.3", "VR_MAX_BOUNCES=2"])
        self.assertEqual(fr.scene_env("wdasstorm_g0.5"), ["VR_SCENE=wdasstorm", "VR_PHASE_G=0.5"])
        self.assertEqual(fr.scene_env("explosion"), ["VR_SCENE=explosion"])

    def test_the_papers_152_captures_first_then_the_cap_sweep(self):
        runs = fr.runs()
        self.assertEqual(len({(r["label"], r["config"]) for r in runs}), len(runs))
        hist = [r["config"].split("_")[1] for r in runs]
        per = 19 * 2 * 2  # setups x (plain, + 5 mutations) x (the four denoisers' graph, RR's)
        self.assertEqual(hist, ["c200"] * per + ["ship"] * per + ["c20"] * per + ["c50"] * per + ["c10"] * (per - 4))

    def test_the_cap_sweep_sets_each_cap(self):
        for cap in (10, 20, 50):
            r = next(r for r in fr.runs() if r["label"] == "bunnyspot" and r["config"] == "fd_c%d_m5" % cap)
            env = env_of(r)
            self.assertEqual(env["VR_MTHRESH"], str(cap))
            self.assertEqual(env["VR_MUTATIONS"], "5")

    def test_the_night_streets_cap_10_is_its_shipped_run(self):
        configs = {r["config"] for r in fr.runs() if r["label"] == "emeraldnight_d3"}
        self.assertIn("fd_ship_m0", configs)  # Emerald Square's loader ships M cap 10
        self.assertFalse(any("_c10_" in c for c in configs))
        self.assertIn("fd_c20_m0", configs)

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
        self.assertEqual(len(runs), (19 * 4 + 18) * 2 * 3)  # 19 setups at four histories, 18 at cap 10
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

    def test_a_split_run_is_done_when_its_shared_run_finished(self):
        # the queue was split part-way (two lighter graphs per setup); a setup the shared graph finished is kept
        with tempfile.TemporaryDirectory() as root:
            shared = os.path.join(root, "fd_c200_m5")
            os.makedirs(shared)
            self.make(shared, 10)
            split = os.path.join(root, "fd1_c200_m5")
            self.assertTrue(fr.satisfied(split, 6))
            self.assertEqual(fr.main(["--complete", split, "6"]), 0)
            self.assertFalse(fr.satisfied(os.path.join(root, "fd1_c200_m0"), 6))

    def test_an_unfinished_shared_run_leaves_the_split_runs_to_do(self):
        with tempfile.TemporaryDirectory() as root:
            shared = os.path.join(root, "fd_c200_m5")
            os.makedirs(shared)
            self.make(shared, 5)  # one chain captured, then Mogwai hung
            split = os.path.join(root, "fd2_c200_m5")
            self.assertFalse(fr.satisfied(split, 6))
            os.makedirs(split)
            self.make(split, 6)
            self.assertTrue(fr.satisfied(split, 6))
            self.assertFalse(fr.satisfied(shared, 10))


if __name__ == "__main__":
    unittest.main()
