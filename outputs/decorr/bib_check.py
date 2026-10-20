"""The paper's bibliography against its text (docs/superpowers/specs/2026-10-20-mutation-paper-design.md, criterion 5):
every cited key is in references.bib, every entry is cited, and every entry is in citations_checked.md (how it was
checked). Prints the problems; exit 1 if any.

    python bib_check.py <paper.tex> <references.bib> <citations_checked.md>
"""
import re
import sys


def check(tex_path, bib_path, checked_path):
    tex = open(tex_path, encoding="utf-8").read()
    cited = {k.strip() for group in re.findall(r"\\cite[a-z]*\*?(?:\[[^\]]*\])?\{([^}]*)\}", tex) for k in group.split(",")}
    bib = set(re.findall(r"@\w+\{([^,\s]+),", open(bib_path, encoding="utf-8").read()))
    checked = set(re.findall(r"^\|\s*([^|\s]+)\s*\|", open(checked_path, encoding="utf-8").read(), flags=re.M))
    problems = ["cited but not in the bibliography: " + k for k in sorted(cited - bib)]
    problems += ["in the bibliography but never cited: " + k for k in sorted(bib - cited)]
    problems += ["not in citations_checked.md: " + k for k in sorted(bib - checked)]
    return problems


if __name__ == "__main__":
    found = check(*sys.argv[1:4])
    print("\n".join(found) or "bibliography OK")
    sys.exit(1 if found else 0)
