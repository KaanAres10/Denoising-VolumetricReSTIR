"""bib_check.py on small files.

    cd outputs/decorr && python -m unittest test_bib_check -v
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bib_check


class TestBibCheck(unittest.TestCase):
    def files(self, tex, bib, checked):
        d = tempfile.mkdtemp()
        paths = []
        for name, text in (("p.tex", tex), ("r.bib", bib), ("c.md", checked)):
            with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
                fh.write(text)
            paths.append(os.path.join(d, name))
        return paths

    def test_clean(self):
        p = self.files("see \\citet{Lin21} and \\cite{Bitterli20, Sawhney24}", "@article{Lin21,\n}\n@article{Bitterli20,\n}\n"
                       "@article{Sawhney24,\n}\n", "| Lin21 | Papers/x.pdf |\n| Bitterli20 | doi |\n| Sawhney24 | Papers/y.pdf |\n")
        self.assertEqual(bib_check.check(*p), [])

    def test_undefined_unused_and_unchecked(self):
        p = self.files("\\cite{Lin21,Missing}", "@article{Lin21,\n}\n@misc{Unused,\n}\n", "| Unused | doi |\n")
        problems = bib_check.check(*p)
        self.assertIn("cited but not in the bibliography: Missing", problems)
        self.assertIn("in the bibliography but never cited: Unused", problems)
        self.assertIn("not in citations_checked.md: Lin21", problems)


if __name__ == "__main__":
    unittest.main()
