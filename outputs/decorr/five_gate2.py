"""Gate 2's verdict (paper spec E4): each denoiser's channel in the four-denoiser capture against its single capture
with the same seeds -- bit for bit where two single captures agree bit for bit, otherwise within twice their mean
difference -- and, for information, the shared graph's raw frame against a run with no denoiser.

    python five_gate2.py outputs/decorr/five_denoisers/gate2
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import five_gate as fg  # noqa: E402

SINGLE = {"optix": "Denoiser.output", "oidn": "Denoiser.dst", "relax": "ModulateIllumination.output",
          "reblur": "ModulateIllumination.output"}


def verdict(g):
    with open(os.path.join(g, "multi", "c.schedule.json")) as fh:
        multi = json.load(fh)["channels"]
    ok = True
    for d, ch in SINGLE.items():
        own = fg.compare(os.path.join(g, d + "1"), ch, os.path.join(g, d + "2"), ch)
        shared = fg.compare(os.path.join(g, "multi"), multi[d], os.path.join(g, d + "1"), ch)
        if own["identical"] == own["frames"]:
            passed = shared["identical"] == shared["frames"]
        else:
            passed = shared["mean_abs"] <= 2 * own["mean_abs"]
        ok = ok and passed
        print("%-7s alone twice %s | shared vs alone %s  %s" % (d, own, shared, "PASS" if passed else "FAIL"))
    raw = fg.compare(os.path.join(g, "multi"), multi["raw"], os.path.join(g, "raw"), "VolumetricReSTIR.accumulated_color")
    print("raw (information only): shared graph vs no denoiser %s" % raw)
    print("GATE 2 " + ("PASSED" if ok else "FAILED"))
    return ok


if __name__ == "__main__":
    sys.exit(0 if verdict(sys.argv[1]) else 1)
