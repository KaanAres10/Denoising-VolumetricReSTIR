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
MAX_SHARE = 0.5   # and one mutation less than this share of what it removes,
MIN_LEFT = 2.0    # or leave at least this many times what the largest count leaves


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
        ref = d.get("reference") or {}
        out[int(m.group(1))] = {"medium": d["medium"]["rho"]["8"],
                                "colour": 0.5 * (d["color_rb"]["rho"]["8"] + d["color_gm"]["rho"]["8"]),
                                "dup": d.get("duplicates", {}).get("sample_mean"),
                                "relmse": ref.get("relmse"), "blur8": (ref.get("blur_rms") or {}).get("8")}
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


def left_ratio(values):
    """What one mutation leaves over what the largest count leaves (rho_1 / rho_N); None without both."""
    if 1 not in values or max(values) <= 1 or not values[max(values)] > 0:
        return None
    return values[1] / values[max(values)]


def needs_more(share, cut, left=None):
    """One mutation is not enough when the largest count cuts a real share and either one mutation takes less than
    half of that cut, or what one mutation leaves is at least MIN_LEFT times what the largest count leaves."""
    if share is None or cut < MIN_CUT:
        return False
    return share < MAX_SHARE or (left is not None and left >= MIN_LEFT)


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
        print("  %6s %12s %12s %10s %10s" % ("muts", "medium r8", "colour r8", "dup/tile", "relMSE"))
        fmt = lambda v, f: "-" if v is None else f % v  # noqa: E731
        for n in sorted(s):
            print("  %6d %12.4f %12.4f %10s %10s" % (n, s[n]["medium"], s[n]["colour"], fmt(s[n]["dup"], "%.2f"),
                                                    fmt(s[n]["relmse"], "%.4f")))
        row = {"counts": s}
        for key in ("medium", "colour"):
            vals = {n: s[n][key] for n in s}
            share, cut = cut_share(vals)
            left = left_ratio(vals)
            more = needs_more(share, cut, left)
            row[key] = {"share_by_one": share, "cut": cut, "left_ratio": left, "needs_more": more}
            if share is not None:
                print("  %s: %d mutations cut %.0f%%; one mutation takes %.0f%% of that and leaves %.1fx what %d leave%s"
                      % (key, max(s), 100 * cut, 100 * share, left or float("nan"), max(s),
                         "  -> NEEDS MORE THAN ONE" if more else ""))
        summary[label] = row
    if jout:
        with open(jout, "w") as fh:
            json.dump(summary, fh, indent=1)


if __name__ == "__main__":
    main(sys.argv)
