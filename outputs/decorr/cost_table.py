"""The mutations' cost from run_cost.sh: per scene and bounce count, the estimator's GPU time (median ms per frame,
1080p, M cap 200), plain vs 1 and 5 mutations, the Mutate Samples pass alone, plain with 8 / 16 / 32 initial
candidates, and the candidate count that costs what 5 mutations cost (linear between the measured counts).

    python cost_table.py <root> [--json out.json]        (root: outputs/decorr)
"""
import argparse
import json
import os

PREFIX = "/onFrameRender/RenderGraphExe::execute()/VolumetricReSTIR"
LABELS = ["explosiondusk", "bunnycathedral_d0.3", "bunnyback_g0.8", "bunnysoftbox", "wdassunset_g0.85"]
CANDIDATES = (4, 8, 16, 32)  # 4 = shipped (the mut0 run)


def lane(passes, name=""):
    """Median GPU ms of a pass lane ('' = the whole VolumetricReSTIR pass), 0 if absent."""
    key = PREFIX + ("/" + name if name else "") + "/gpu_time"
    return passes.get(key, {}).get("median", 0.0)


def load(root, label, cfg):
    p = os.path.join(root, "cost", label, cfg, "c.passes.json")
    if not os.path.exists(p):
        return None
    with open(p) as fh:
        return json.load(fh)


def equal_time_candidates(times, target):
    """The initial-candidate count whose plain cost equals target, linear between measured counts and, above the
    largest, along the last measured segment (the cost is linear in the count); None below the cheapest.
    times: {count: ms}."""
    ks = sorted(times)
    for a, b in zip(ks, ks[1:]):
        if times[a] <= target <= times[b]:
            return a + (b - a) * (target - times[a]) / (times[b] - times[a]) if times[b] > times[a] else a
    if len(ks) >= 2 and target > times[ks[-1]] and times[ks[-1]] > times[ks[-2]]:
        a, b = ks[-2], ks[-1]
        return b + (b - a) * (target - times[b]) / (times[b] - times[a])
    return None


def row(root, label):
    runs = {cfg: load(root, label, cfg) for cfg in ("mut0", "mut1", "mut5", "im8", "im16", "im32")}
    if runs["mut0"] is None or runs["mut5"] is None:
        return None
    t = {cfg: lane(p) for cfg, p in runs.items() if p is not None}
    plain = {k: t["mut0" if k == 4 else "im%d" % k] for k in CANDIDATES if ("mut0" if k == 4 else "im%d" % k) in t}
    return {
        "label": label,
        "plain": t["mut0"],
        "mut1": t.get("mut1"),
        "mut5": t["mut5"],
        "pass1": lane(runs["mut1"], "Mutate Samples") if runs["mut1"] else None,
        "pass5": lane(runs["mut5"], "Mutate Samples"),
        "plain_by_candidates": plain,
        "equal_time_candidates_1": equal_time_candidates(plain, t["mut1"]) if "mut1" in t else None,
        "equal_time_candidates_5": equal_time_candidates(plain, t["mut5"]),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    rows = []
    for base in LABELS:
        for label in (base, base + "_b2"):
            r = row(a.root, label)
            if r:
                rows.append(r)
    fmt = "%-26s %7s %7s %7s %13s %13s %24s %9s"
    print(fmt % ("scene", "plain", "1 mut", "5 mut", "1 mut: pass", "5 mut: pass", "plain, 8/16/32 cand.", "= 5 mut"))
    for r in rows:
        p = r["plain_by_candidates"]
        print(fmt % (
            r["label"], "%.1f" % r["plain"],
            "%.1f" % r["mut1"] if r["mut1"] else "-", "%.1f" % r["mut5"],
            "%.1f (%+.0f%%)" % (r["pass1"], 100 * (r["mut1"] / r["plain"] - 1)) if r["pass1"] else "-",
            "%.1f (%+.0f%%)" % (r["pass5"], 100 * (r["mut5"] / r["plain"] - 1)),
            " / ".join("%.1f" % p[k] if k in p else "-" for k in CANDIDATES[1:]),
            ("%.1f" % r["equal_time_candidates_5"] + ("*" if r["equal_time_candidates_5"] > CANDIDATES[-1] else "")) if r["equal_time_candidates_5"] else "-"))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(rows, fh, indent=1)


if __name__ == "__main__":
    main()
