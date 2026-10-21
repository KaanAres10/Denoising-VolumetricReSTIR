"""The paper's tables (docs/superpowers/specs/2026-10-20-mutation-paper-design.md): the recorded ones from
paper_record.json (each cell copied from its spec section; test_paper_tables.py checks every cell is there) and the
five-denoiser ones from five_denoisers/results.json, as LaTeX tabulars (booktabs) for \\input.

    python paper_tables.py <paper dir>/tables [--results five_denoisers/results.json]
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SETUP_NAMES = {
    "bunnycathedral_d0.3": "Cathedral god rays", "bunnyspot": "Spotlight beam", "bunnysoftbox": "Warm and cool panels",
    "bunnyinside": "Lamp inside the cloud", "bunnyback_g0.8": "Backlit rim", "bunnystripes": "Light through slats",
    "explosion": "Self-emitting explosion", "bunnylanterns": "48 coloured lanterns", "wdassunset_g0.85": "Cloud at sunset",
    "plumeback_g0.9": "Backlit smoke", "plumeconcert_g0.6": "Concert beams", "emeraldnight_d3": "Night street in fog",
    "explosiondusk_b2": "Explosion (paper setup), 2b", "bunnycathedral_d0.3_b2": "Cathedral god rays, 2b",
    "bunnyback_g0.8_b2": "Backlit rim, 2b", "bunnysoftbox_b2": "Warm and cool panels, 2b",
    "wdassunset_g0.85_b2": "Cloud at sunset, 2b", "bunnyswarm_d3": "192 coloured lights", "wdasstorm_g0.5": "Thunderstorm"}
COLUMNS = ("optix", "oidn", "relax", "reblur", "rr", "raw")
# The recorded tables keep the spec's row labels verbatim (test_paper_tables checks them against the spec); the
# paper shows these names instead, the same in every table.
ROW_NAMES = {
    "explosiondusk": "explosion", "bunnycathedral_d0.3": "cathedral", "bunnyback_g0.8": "backlit rim",
    "bunnysoftbox": "panel lights", "wdassunset_g0.85": "sunset cloud", "sunset": "sunset cloud",
    "plume g = −0.9 (shipped cap 4)": "plume g = −0.9", "bistro whole (cap 10)": "Bistro, frame",
    "emerald fog (cap 10)": "Emerald Square, fog", "emerald (fog + surfaces)": "Emerald Square (fog + surfaces)",
    "bistro (smoke + surfaces)": "Bistro (smoke + surfaces)", "wdas 1×": "Disney cloud",
    "large close panels, 2 bounces": "close panels, 2b", "hidden backlight, 2 bounces": "hidden backlight, 2b",
    "192 coloured lights, dense (fixed reference)": "192 coloured lights"}


def display_rows(rows):
    """`rows` with each first cell (the row label) replaced by its ROW_NAMES name, if it has one."""
    return [[ROW_NAMES.get(row[0], row[0])] + list(row[1:]) for row in rows]


def spec_section(path, sid):
    """The text of section `sid` ("### <sid> ..." up to the next "### ")."""
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    start = next((i for i, l in enumerate(lines) if l.startswith("### %s " % sid)), None)
    if start is None:
        raise KeyError(sid)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("### ")), len(lines))
    return "\n".join(lines[start:end])


def latex(cell):
    s = cell.replace("\\", "\\textbackslash{}").replace("_", "\\_").replace("&", "\\&")
    s = s.replace("+-", "$\\pm$").replace("%", "\\%")
    s = s.replace("Δρ̄", "$\\Delta\\bar{\\rho}$").replace("ρ̄", "$\\bar{\\rho}$").replace("×", "$\\times$")
    s = re.sub(r"(?<![\w$])[−-](?=\d)", "$-$", s)
    return s.replace("−", "$-$").replace("—", "---")


def tabular(header, rows, spec):
    out = ["\\begin{tabular}{%s}" % spec, "\\toprule", " & ".join(latex(h) for h in header) + " \\\\", "\\midrule"]
    out += [" & ".join(latex(c) for c in row) + " \\\\" for row in rows]
    return "\n".join(out + ["\\bottomrule", "\\end{tabular}", ""])


def change(cfgs, d):
    return "%+.0f%%" % (100 * (cfgs["m5"][d]["mean"] / cfgs["m0"][d]["mean"] - 1)) if d in cfgs["m0"] and d in cfgs["m5"] else "—"


def five_rows(results, hist):
    rows = []
    for label, name in SETUP_NAMES.items():
        if label not in results or hist not in results[label]["histories"]:
            continue
        cfgs = results[label]["histories"][hist]
        rows.append([name] + [latex(change(cfgs, d)) for d in COLUMNS] + ["%.4f" % results[label]["ref_own_relmse"]])
    return rows


def five_table(results, hist):
    head = ["Setup", "OptiX", "OIDN", "RELAX", "REBLUR", "DLSS RR", "raw", "ref."]
    body = ["\\begin{tabular}{lrrrrrrr}", "\\toprule", " & ".join(head) + " \\\\", "\\midrule"]
    body += [" & ".join(r) + " \\\\" for r in five_rows(results, hist)]
    return "\n".join(body + ["\\bottomrule", "\\end{tabular}", ""])


def five_values(results):
    head = ["Setup", "history"] + ["OptiX", "OIDN", "RELAX", "REBLUR", "DLSS RR", "raw"]
    body = ["\\begin{tabular}{llrrrrrr}", "\\toprule", " & ".join(head) + " \\\\", "\\midrule"]
    for label, name in SETUP_NAMES.items():
        for hist in ("c200", "ship"):
            cfgs = results.get(label, {}).get("histories", {}).get(hist)
            if not cfgs:
                continue
            cells = ["%.4f$\\to$%.4f" % (cfgs["m0"][d]["mean"], cfgs["m5"][d]["mean"]) if d in cfgs["m0"] and d in cfgs["m5"]
                     else "---" for d in COLUMNS]
            body.append(" & ".join([name, "200" if hist == "c200" else "shipped"] + cells) + " \\\\")
    return "\n".join(body + ["\\bottomrule", "\\end{tabular}", ""])


SPECS = {"phase_a": "lrrr", "mcap": "lrrrrrr", "reuse_denoisers": "lrr", "bias": "lrrrr", "speed": "lrrr",
         "equal_time": "lrrr", "counts": "lrrrrrr", "acceptance": "lrrr"}


def write_all(record, results, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    for key, table in record.items():
        with open(os.path.join(out_dir, key + ".tex"), "w", encoding="utf-8") as fh:
            fh.write(tabular(table["header"], display_rows(table["rows"]), SPECS[key]))
    if results:
        for hist in ("c200", "ship"):
            with open(os.path.join(out_dir, "five_%s.tex" % hist), "w", encoding="utf-8") as fh:
                fh.write(five_table(results, hist))
        with open(os.path.join(out_dir, "five_values.tex"), "w", encoding="utf-8") as fh:
            fh.write(five_values(results))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--results", default=os.path.join(HERE, "five_denoisers", "results.json"))
    a = ap.parse_args(argv)
    with open(os.path.join(HERE, "paper_record.json"), encoding="utf-8") as fh:
        record = json.load(fh)
    results = None
    if os.path.exists(a.results):
        with open(a.results) as fh:
            results = json.load(fh)
    write_all(record, results, a.out_dir)
    print("tables written to", a.out_dir, "(five-denoiser tables %s)" % ("included" if results else "not yet: no results"))


if __name__ == "__main__":
    main()
