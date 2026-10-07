"""run_move_cost.sh's table: per scene setup and move kind, the Mutate Samples time of one step ((t5 - t1) / 4, the
kind alone for the whole frame) and the pass's fixed part (t1 minus one step), in GPU ms at 1080p.

    python move_cost_table.py <root>        (root: outputs/decorr)
"""
import json
import os
import sys

LANE = "/onFrameRender/RenderGraphExe::execute()/VolumetricReSTIR/Mutate Samples/gpu_time"
KINDS = ("light", "depth", "select", "flight", "direction", "distance", "rebounce")


def mutate_ms(run_dir):
    p = os.path.join(run_dir, "c.passes.json")
    if not os.path.exists(p):
        return None
    with open(p) as fh:
        return json.load(fh).get(LANE, {}).get("median")


def step_cost(t1, t5):
    """(one step, the fixed part) from the pass times at 1 and 5 steps."""
    step = (t5 - t1) / 4.0
    return step, t1 - step


def main(argv):
    root = os.path.join(argv[1] if len(argv) > 1 else ".", "movecost")
    print("%-20s " % "setup" + " ".join("%10s" % k for k in KINDS) + "   (ms per step; fixed part in brackets)")
    for label in sorted(os.listdir(root)):
        cells, fixed = [], []
        for k in KINDS:
            t1, t5 = mutate_ms(os.path.join(root, label, k + "_1")), mutate_ms(os.path.join(root, label, k + "_5"))
            if t1 is None or t5 is None:
                cells.append("%10s" % "-")
                continue
            step, f = step_cost(t1, t5)
            cells.append("%10.2f" % step)
            fixed.append(f)
        print("%-20s " % label + " ".join(cells) + "   [%.1f]" % (sum(fixed) / len(fixed) if fixed else float("nan")))


if __name__ == "__main__":
    main(sys.argv)
