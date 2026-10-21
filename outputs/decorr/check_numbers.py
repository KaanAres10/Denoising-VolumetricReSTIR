"""Every number in the paper has a source (docs/superpowers/specs/2026-10-20-mutation-paper-design.md, criterion 1):
the numbers in paper.tex (and the tables it inputs) against the numbers ledger's first column.

    python check_numbers.py <paper.tex> <numbers_ledger.md> [<table.tex> ...]

A number is a decimal (0.0151), a percentage (84%, written 84\\% or $-$84\\%), or an integer of two digits or more
(200, 1080). Ignored: comments, optional arguments and layout lengths, citations, labels, references, one-digit
integers, signs. Exit 1 listing every number missing from the ledger.
"""
import re
import sys

DROP = [r"(?<!\\)%.*", r"\\(?:cite[a-z]*|ref|label|eqref|includegraphics|input|begin|end|usepackage|usetikzlibrary)"
        r"\*?(?:\[[^\]]*\])?\{[^}]*\}", r"\[[^\]]*\]", r"[0-9.]+\\(?:linewidth|textwidth|columnwidth)", r"\$-\$|−"]


def numbers(tex):
    s = tex
    for pat in DROP:
        s = re.sub(pat, " ", s)
    s = s.replace("\\%", "%")
    out = []
    for m in re.finditer(r"(?<![\w.])(\d+\.\d+|\d+)(%?)", s):
        value, pct = m.groups()
        if pct or "." in value or len(value) >= 2:
            out.append(value + pct)
    return out


def ledger(md):
    return {line.split("|")[1].strip() for line in md.splitlines() if line.startswith("|") and line.count("|") >= 3}


def missing(tex, md):
    have = ledger(md)
    return [n for n in dict.fromkeys(numbers(tex)) if n not in have]


if __name__ == "__main__":
    tex = "\n".join(open(p, encoding="utf-8").read() for p in [sys.argv[1]] + sys.argv[3:])
    gone = missing(tex, open(sys.argv[2], encoding="utf-8").read())
    print("\n".join("no ledger entry: " + n for n in gone) or "every number has a ledger entry")
    sys.exit(1 if gone else 0)
