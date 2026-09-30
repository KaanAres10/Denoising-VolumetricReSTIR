"""prune.py and summarize.py, on synthetic run directories.

    cd outputs/decorr && python -m unittest test_study_tools -v
"""
import json
import os
import sys

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")  # before any cv2 import
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prune
import summarize


def write(path, text="x"):
    with open(path, "w") as fh:
        fh.write(text)


class TestPrune(unittest.TestCase):
    def make(self, root):
        chains = [{"seed": 1000 * c, "first": 1 + 10 * c, "length": 10, "frames": [5 + 10 * c, 7 + 10 * c, 9 + 10 * c]}
                  for c in range(3)]
        burst = {"seed": 9000, "first": 31, "length": 8, "frames": [35, 36, 37, 38]}
        with open(os.path.join(root, "c.schedule.json"), "w") as fh:
            json.dump({"chains": chains, "burst": burst}, fh)
        for f in [f for c in chains for f in c["frames"]] + burst["frames"]:
            for ch in ("VolumetricReSTIR.accumulated_color", "VolumetricReSTIR.sampleIdentity"):
                write(os.path.join(root, "c.%s.%d.exr" % (ch, f)))
        write(os.path.join(root, "c.corr.json"), "{}")
        write(os.path.join(root, "notes.txt"))

    def test_keeps_the_first_capture_of_the_first_chains(self):
        with tempfile.TemporaryDirectory() as root:
            self.make(root)
            removed = prune.prune(root, "c", keep_chains=2)
            left = sorted(os.listdir(root))
            self.assertEqual(left, sorted([
                "c.VolumetricReSTIR.accumulated_color.5.exr", "c.VolumetricReSTIR.sampleIdentity.5.exr",
                "c.VolumetricReSTIR.accumulated_color.15.exr", "c.VolumetricReSTIR.sampleIdentity.15.exr",
                "c.VolumetricReSTIR.accumulated_color.35.exr", "c.VolumetricReSTIR.sampleIdentity.35.exr",
                "c.corr.json", "c.schedule.json", "notes.txt"]))
            self.assertEqual(len(removed), 2 * (9 + 4) - 6)

    def test_uses_the_scheduled_channel(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "c.schedule.json"), "w") as fh:
                json.dump({"chains": [{"frames": [3, 4]}], "burst": None, "channel": "Denoiser.output"}, fh)
            write(os.path.join(root, "c.Denoiser.output.3.exr"))
            write(os.path.join(root, "c.Denoiser.output.4.exr"))
            prune.prune(root, "c", keep_chains=1)
            self.assertEqual(sorted(os.listdir(root)), ["c.Denoiser.output.3.exr", "c.schedule.json"])

    def test_missing_files_are_not_an_error(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "c.schedule.json"), "w") as fh:
                json.dump({"chains": [{"frames": [3, 4]}], "burst": None}, fh)
            self.assertEqual(prune.prune(root, "c"), [])


class TestSummarize(unittest.TestCase):
    def corr(self, rho8, delta=None, dup=None):
        d = {"K": 100, "mean_level": 0.5, "env": {"VR_SCENE": "plume"},
             "raw": {"rho": {"1": 0.1, "8": rho8}, "ci": {"8": [rho8 - 0.01, rho8 + 0.01]}},
             "robust": {"rho": {"1": 0.1, "4": 0.05, "8": rho8}, "ci": {"8": [rho8 - 0.01, rho8 + 0.01]}},
             "autocorr": {"length_0.1": 3, "top_offsets": [[0, 1, 0.4]]}}
        if delta is not None:
            d["delta"] = {"robust": {"8": {"value": delta, "ci": [delta - 0.002, delta + 0.002]}}}
        if dup is not None:
            d["duplicates"] = {"sample_mean": dup, "light_mean": 0.0}
        return d

    def test_rows_per_run(self):
        with tempfile.TemporaryDirectory() as root:
            for cfg, rho8, delta in (("noreuse", 0.001, None), ("shipped", 0.021, 0.02)):
                os.makedirs(os.path.join(root, "plume", cfg))
                with open(os.path.join(root, "plume", cfg, "c.corr.json"), "w") as fh:
                    json.dump(self.corr(rho8, delta, dup=12.5), fh)
            rows = summarize.summarize(root)
            self.assertEqual([(r["label"], r["config"]) for r in rows], [("plume", "noreuse"), ("plume", "shipped")])
            shipped = rows[1]
            self.assertAlmostEqual(shipped["rho_robust_r8"], 0.021)
            self.assertAlmostEqual(shipped["delta_robust_r8"], 0.02)
            self.assertEqual(shipped["dup_sample"], 12.5)
            self.assertEqual(rows[0]["delta_robust_r8"], "")
            self.assertEqual(rows[0]["rho_medium_r8"], "")  # scored before the medium block existed
            with open(os.path.join(root, "summary.tsv")) as fh:
                lines = fh.read().splitlines()
            self.assertEqual(len(lines), 3)
            self.assertTrue(lines[0].startswith("label\tconfig\t"))

    def test_medium_columns(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "plume", "shipped"))
            r = self.corr(0.02, 0.019)
            r["medium"] = {"mask": "baseline", "pixels": 370000, "rho": {"1": 0.05, "8": 0.04}}
            r["delta"]["medium"] = {"8": {"value": 0.039, "ci": [0.038, 0.041]}}
            with open(os.path.join(root, "plume", "shipped", "c.corr.json"), "w") as fh:
                json.dump(r, fh)
            row, = summarize.summarize(root)
            self.assertEqual((row["medium_px"], row["rho_medium_r1"], row["rho_medium_r8"]), (370000, 0.05, 0.04))
            self.assertEqual((row["delta_medium_r8"], row["delta_medium_r8_lo"], row["delta_medium_r8_hi"]),
                             (0.039, 0.038, 0.041))


class TestSheet(unittest.TestCase):
    def test_sheet_renders_every_config(self):
        import cv2
        import numpy as np
        import sheet
        with tempfile.TemporaryDirectory() as root:
            label = os.path.join(root, "plume")
            for cfg, rho in (("noreuse", 0.001), ("shipped", 0.03)):
                d = os.path.join(label, cfg)
                os.makedirs(d)
                corr = {"K": 100, "radii": [1, 2, 4, 8], "tag": "c",
                        "raw": {"rho": {"1": rho, "2": rho, "4": rho / 2, "8": rho / 4},
                                "ci": {k: [0.0, 2 * rho] for k in ("1", "2", "4", "8")}},
                        "robust": {"rho": {"1": rho, "2": rho, "4": rho / 2, "8": rho / 4},
                                   "ci": {k: [0.0, 2 * rho] for k in ("1", "2", "4", "8")}}}
                with open(os.path.join(d, "c.corr.json"), "w") as fh:
                    json.dump(corr, fh)
                with open(os.path.join(d, "c.schedule.json"), "w") as fh:
                    json.dump({"chains": [{"frames": [9]}], "burst": None}, fh)
                cv2.imwrite(os.path.join(d, "c.VolumetricReSTIR.accumulated_color.9.exr"),
                            np.full((90, 160, 3), 0.5, np.float32))
                np.save(os.path.join(d, "c.autocorr.npy"), np.eye(65))
                np.save(os.path.join(d, "c.dup_sample.npy"), np.ones((4, 8)))
            out = sheet.make_sheet(label)
            self.assertTrue(os.path.exists(out))
            self.assertGreater(os.path.getsize(out), 10000)


class TestAtlasConfigs(unittest.TestCase):
    def test_first_scored_alternative(self):
        import atlas_figure
        with tempfile.TemporaryDirectory() as root:
            for cfg in ("mcap_50_mut5", "shipped"):
                os.makedirs(os.path.join(root, "bunnyone", cfg))
                write(os.path.join(root, "bunnyone", cfg, "c.corr.json"), "{}")
            os.makedirs(os.path.join(root, "bunnyone", "mcap_50_mut5_all"))  # rendered, never scored
            self.assertEqual(atlas_figure.resolve(root, "bunnyone", "mcap_50_mut5_all|mcap_50_mut5"), "mcap_50_mut5")
            self.assertEqual(atlas_figure.resolve(root, "bunnyone", "shipped"), "shipped")
            self.assertIsNone(atlas_figure.resolve(root, "bunnyone", "dec_mcap_200"))


class TestConfigNames(unittest.TestCase):
    def test_mutation_configs(self):
        import mutation_figure
        self.assertEqual(mutation_figure.name("mcap_50_mut5_flight"), "M cap 50 + 5 mutations (free flight)")
        self.assertEqual(mutation_figure.name("dec_mcap_200_mut5_all4_post"),
                         "decoupled history, M cap 200 + 5 mutations (all four) after spatial reuse")
        self.assertEqual(mutation_figure.name("mcap_50_mut5_all"), "M cap 50 + 5 mutations (all)")
        self.assertEqual(mutation_figure.name("tmip3_mcap_50_mut5_all4_post"),
                         "target on mip 3, M cap 50 + 5 mutations (all four) after spatial reuse")


if __name__ == "__main__":
    unittest.main()
