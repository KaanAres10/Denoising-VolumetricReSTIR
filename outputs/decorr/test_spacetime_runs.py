"""spacetime_runs.py: the space-time strips' runs, each a replay of one of the paper's five-denoiser runs.

    cd outputs/decorr && python -m unittest test_spacetime_runs -v
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spacetime_runs as sr


def run_dir(root, label, cfg, env=None, strip=None, log="", npys=()):
    d = os.path.join(root, label, cfg)
    os.makedirs(d)
    sched = {"env": env or {}}
    if strip:
        sched["strip"] = strip
    with open(os.path.join(d, "c.schedule.json"), "w") as fh:
        json.dump(sched, fh)
    with open(os.path.join(d, "run.log"), "w") as fh:
        fh.write(log)
    for name in npys:
        open(os.path.join(d, "c.strip.%s.npy" % name), "wb").close()
    return d


class TestList(unittest.TestCase):
    def test_the_list_has_no_carriage_returns_for_bash_to_keep(self):
        import subprocess
        with tempfile.TemporaryDirectory() as root:
            for label in sr.SCENES:
                run_dir(root, label, "fd_c200_m0", {"VR_SCENE": "x", "VR_VOL_NORMAL": "gradient"})
            out = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                               "spacetime_runs.py"), "--list", root],
                                 capture_output=True, check=True).stdout
        self.assertNotIn(b"\r", out)  # bash's read keeps it on a line's last value: VR_VOL_NORMAL=gradient\r
        self.assertEqual(out.count(b"\n"), len(sr.SCENES))

    def test_night_lists_the_night_streets_replays_alone(self):
        import subprocess
        with tempfile.TemporaryDirectory() as root:
            for label in sr.SCENES:
                run_dir(root, label, "fd_c200_m0", {"VR_SCENE": "x"})
            run_dir(root, "emeraldnight_d3", "fr_c50_m0", {"VR_SCENE": "emeraldnight"})
            out = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                               "spacetime_runs.py"), "--list", root, "--night"],
                                 capture_output=True, check=True).stdout
        self.assertEqual(out.decode().split()[:2], ["emeraldnight_d3", "st_fr_c50_m0"])
        self.assertEqual(out.count(b"\n"), 1)  # not the paper's setups


class TestRuns(unittest.TestCase):
    def test_each_paper_run_is_replayed_with_its_own_environment(self):
        with tempfile.TemporaryDirectory() as root:
            env = {"VR_SCENE": "bunny", "VR_MTHRESH": "200", "VR_OUT_DIR": "C:/x/fd_c200_m0", "VR_TAG": "c"}
            run_dir(root, "bunnylanterns", "fd_c200_m0", env)
            run_dir(root, "bunnylanterns", "fr_ship_m5", {"VR_SCENE": "bunny", "VR_DENOISER": "rr"})
            os.makedirs(os.path.join(root, "bunnylanterns", "noreuse"))  # not one of the paper's runs
            os.makedirs(os.path.join(root, "bunnylanterns", "st_fd_c200_m0"))  # nor a replay itself
            runs = sr.runs(root, scenes={"bunnylanterns": (208, 240)}, frames=128)
        self.assertEqual([r["config"] for r in runs], ["st_fd_c200_m0", "st_fr_ship_m5"])
        first = runs[0]["env"]
        self.assertNotIn("VR_OUT_DIR", first)  # the replay writes to its own folder
        self.assertNotIn("VR_TAG", first)
        self.assertEqual(first["VR_MTHRESH"], "200")  # everything else as the paper ran it
        self.assertEqual((first["VR_STRIP_FRAMES"], first["VR_STRIP_ROWS"]), ("128", "208:240"))

    def test_the_night_streets_m_cap_50_runs_plain_and_with_five_mutations(self):
        label = next(iter(sr.NIGHT))
        with tempfile.TemporaryDirectory() as root:
            for cfg in ("fd1_c50_m0", "fr_c50_m5", "fd2_c50_m5",
                        "fd1_c50_m1", "fd1_c50_m5_jsel", "fd1_c200_m5", "fd1_ship_m0", "st_fd1_c50_m0"):  # not these
                run_dir(root, label, cfg, {"VR_SCENE": "emeraldnight", "VR_MTHRESH": "50"})
            runs = sr.runs(root, scenes=sr.NIGHT, frames=128, source=sr.NIGHT_SOURCE)
        self.assertEqual([r["config"] for r in runs], ["st_fd1_c50_m0", "st_fd2_c50_m5", "st_fr_c50_m5"])
        self.assertEqual(runs[0]["env"]["VR_STRIP_ROWS"], "%d:%d" % sr.NIGHT[label])
        self.assertEqual(runs[0]["env"]["VR_MTHRESH"], "50")

    def test_a_run_is_complete_with_every_strip_and_a_clean_log(self):
        strip = {"rows": [0, 32], "frames": [1602], "channels": {"raw": "a", "optix": "b"}}
        with tempfile.TemporaryDirectory() as root:
            half = run_dir(root, "s", "st_a", strip=strip, npys=["raw"])
            full = run_dir(root, "s", "st_b", strip=strip, npys=["raw", "optix"])
            failed = run_dir(root, "s", "st_c", strip=strip, npys=["raw", "optix"], log="(Error) device lost\n")
            plain = run_dir(root, "s", "st_d", npys=["raw"])  # a schedule without a strip
            self.assertFalse(sr.complete(half))
            self.assertTrue(sr.complete(full))
            self.assertFalse(sr.complete(failed))
            self.assertFalse(sr.complete(plain))
            self.assertFalse(sr.complete(os.path.join(root, "s", "missing")))


if __name__ == "__main__":
    unittest.main()
