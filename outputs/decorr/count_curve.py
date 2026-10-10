"""run_counts.sh's verdict (spec V-C7): for each scene, the medium's and the colour's rho(8) against the number of
mutations per frame, and how much of the largest count's cut a single mutation already takes. A scene "needs more
than one" when the largest count removes at least 30% of the correlation and one mutation less than half of that.

    python count_curve.py <outputs/decorr> <label> [<label>...] [--prefix c200] [--json out.json]

Configs are <label>/<prefix>_m<N>/c.corr.json (m_corr.py's output), N the mutation count.
"""
import json
import os
import re
import sys

MIN_CUT = 0.3     # the largest count must remove at least this share of the correlation
MAX_SHARE = 0.5   # and one mutation less than this share of what it removes


def load_counts(root, label, prefix):
    """{N: {"medium": rho8, "colour": rho8, "dup": mean duplicates per tile}} for <label>/<prefix>_m<N>."""
    out = {}
    pat = re.compile(re.escape(prefix) + r"_m(\d+)$")
    base = os.path.join(root, label)
    for cfg in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        m = pat.match(cfg)
        p = os.path.join(base, cfg, "c.corr.json")
        if not m or not os.path.exists(p):
            continue
        with open(p) as fh:
            d = json.load(fh)
        out[int(m.group(1))] = {"medium": d["medium"]["rho"]["8"],
                                "colour": 0.5 * (d["color_rb"]["rho"]["8"] + d["color_gm"]["rho"]["8"]),
                                "dup": d.get("duplicates", {}).get("sample_mean")}
    return out


def cut_share(values):
    """(share of the largest count's cut that one mutation takes, that cut as a share of rho at 0); None if 0 or 1
    or a larger count is missing."""
    if 0 not in values or 1 not in values or max(values) <= 1:
        return None, None
    v0, v1, vn = values[0], values[1], values[max(values)]
    cut = (v0 - vn) / v0 if v0 > 0 else 0.0
    share = (v0 - v1) / (v0 - vn) if v0 != vn else 1.0
    return share, cut


def needs_more(share, cut):
    return share is not None and cut >= MIN_CUT and share < MAX_SHARE


def main(argv):
    args, prefix, jout = [], "c200", None
    it = iter(argv[1:])
    for a in it:
        if a == "--prefix":
            prefix = next(it)
        elif a == "--json":
            jout = next(it)
        else:
            args.append(a)
    root, labels = args[0], args[1:]
    summary = {}
    for label in labels:
        s = load_counts(root, label, prefix)
        if not s:
            print("%s: no %s_m<N> runs yet" % (label, prefix))
            continue
        print("%s (%s)" % (label, prefix))
        print("  %6s %12s %12s %10s" % ("muts", "medium r8", "colour r8", "dup/tile"))
        for n in sorted(s):
            dup = s[n]["dup"]
            print("  %6d %12.4f %12.4f %10s" % (n, s[n]["medium"], s[n]["colour"], "-" if dup is None else "%.2f" % dup))
        row = {"counts": s}
        for key in ("medium", "colour"):
            share, cut = cut_share({n: s[n][key] for n in s})
            row[key] = {"share_by_one": share, "cut": cut, "needs_more": needs_more(share, cut)}
            if share is not None:
                print("  %s: %d mutations cut %.0f%%; one mutation takes %.0f%% of that%s"
                      % (key, max(s), 100 * cut, 100 * share, "  -> NEEDS MORE THAN ONE" if needs_more(share, cut) else ""))
        summary[label] = row
    if jout:
        with open(jout, "w") as fh:
            json.dump(summary, fh, indent=1)


if __name__ == "__main__":
    main(sys.argv)
