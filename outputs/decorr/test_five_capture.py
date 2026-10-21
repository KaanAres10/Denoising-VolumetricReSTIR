"""five_capture.sh with a stand-in for Mogwai (FIVE_MOGWAI): a run whose log shows a Falcor error stops at once.

    cd outputs/decorr && python -m unittest test_five_capture -v

Needs no Mogwai running (five_capture.sh waits for one to exit first).
"""
import os
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
# Git Bash, which runs the queue; a bare "bash" from Windows' process search finds System32's (WSL) first
GIT_BASH = r"C:\Program Files\Git\usr\bin\bash.exe"
BASH = GIT_BASH if os.path.exists(GIT_BASH) else shutil.which("bash")


def capture(fake_body, timeout_s, old_log=None):
    d = tempfile.mkdtemp().replace("\\", "/")
    if old_log is not None:  # a failed earlier attempt in the same run directory
        os.makedirs(d + "/run")
        with open(d + "/run/run.log", "w") as fh:
            fh.write(old_log)
    fake = d + "/fake_mogwai.sh"
    with open(fake, "w", newline="\n") as fh:
        fh.write("#!/bin/bash\n" + fake_body + "\n")
    env = dict(os.environ, FIVE_MOGWAI=fake, FIVE_TIMEOUT=str(timeout_s))
    t0 = time.time()
    p = subprocess.run([BASH, os.path.join(HERE, "five_capture.sh").replace("\\", "/"), d + "/run", "VR_SCENE=x"],
                       env=env, capture_output=True, text=True)
    with open(d + "/run/run.log") as fh:
        return p.returncode, time.time() - t0, fh.read()


class TestFiveCapture(unittest.TestCase):
    def test_a_falcor_error_stops_the_run(self):
        # Mogwai logs a failed script and stays open; the capture must not wait out FIVE_TIMEOUT
        code, secs, log = capture('echo "(Error) Error when loading configuration file: x"; sleep 120', 120)
        self.assertLess(secs, 30)
        self.assertIn("(Error) Error when loading configuration file", log)
        self.assertNotEqual(code, 0)

    def test_a_clean_run_is_left_alone(self):
        code, secs, log = capture('echo "scene $VR_SCENE"; sleep 6; echo finished', 120)
        self.assertEqual(code, 0)
        self.assertEqual(log, "scene x\nfinished\n")

    def test_an_earlier_attempts_error_does_not_stop_a_rerun(self):
        # run_five.sh re-runs a failed run in the same directory: its old run.log still holds the error
        code, secs, log = capture('echo "scene $VR_SCENE"; sleep 6; echo finished', 120,
                                  old_log="(Error) Error when loading configuration file: old\n")
        self.assertEqual(code, 0)
        self.assertEqual(log, "scene x\nfinished\n")


if __name__ == "__main__":
    unittest.main()
