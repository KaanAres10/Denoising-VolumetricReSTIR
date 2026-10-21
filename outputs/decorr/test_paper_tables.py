"""paper_tables.py: the recorded cells match their spec sections; the generated LaTeX.

    cd outputs/decorr && python -m unittest test_paper_tables -v
"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paper_tables as pt

SPECS = os.path.join(HERE, "..", "..", "docs", "superpowers", "specs")


class TestRecord(unittest.TestCase):
    def test_every_recorded_cell_is_in_its_section(self):
        with open(os.path.join(HERE, "paper_record.json"), encoding="utf-8") as fh:
            record = json.load(fh)
        for key, table in record.items():
            spec, sid = table["source"].split("#")
            text = pt.spec_section(os.path.join(SPECS, spec), sid)
            for row in table["rows"]:
                for cell in row:
                    if cell != "—":
                        self.assertIn(cell, text, "%s: %r not in %s" % (key, cell, sid))
            for note in table.get("notes", []):
                self.assertIn(note, text, "%s: %r not in %s" % (key, note, sid))

    def test_a_section_ends_at_the_next_heading(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.md")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("### V-C1 — a\nkeep 1\n### V-C1b — b\ndrop 2\n")
            self.assertEqual(pt.spec_section(p, "V-C1").strip(), "### V-C1 — a\nkeep 1")
            with self.assertRaises(KeyError):
                pt.spec_section(p, "V-C9")


class TestLatex(unittest.TestCase):
    def test_signs_percent_and_symbols(self):
        self.assertEqual(pt.latex("−0.56%"), "$-$0.56\\%")
        self.assertEqual(pt.latex("×60"), "$\\times$60")
        self.assertEqual(pt.latex("Δρ̄(8)"), "$\\Delta\\bar{\\rho}$(8)")
        self.assertEqual(pt.latex("bunnyback_g0.8"), "bunnyback\\_g0.8")
        self.assertEqual(pt.latex("-0.06% +- 0.44%"), "$-$0.06\\% $\\pm$ 0.44\\%")

    def test_recorded_row_labels_get_display_names(self):
        # the record keeps the spec's labels verbatim (checked above); the paper shows readable ones
        rows = pt.display_rows([["bunnysoftbox", "-0.02% +- 0.02%"], ["emerald fog (cap 10)", "0.010"], ["other", "1"]])
        self.assertEqual([r[0] for r in rows], ["panel lights", "Emerald Square, fog", "other"])
        self.assertEqual(rows[0][1], "-0.02% +- 0.02%")
        with open(os.path.join(HERE, "paper_record.json"), encoding="utf-8") as fh:
            record = json.load(fh)
        for key in ("bias", "mcap"):
            for row in pt.display_rows(record[key]["rows"]):
                self.assertNotIn("_", row[0])
                self.assertNotIn("(cap", row[0])

    def test_five_rows(self):
        dens = ("optix", "oidn", "relax", "reblur", "rr", "raw")
        res = {"bunnyspot": {"ref_own_relmse": 0.0012, "histories": {"c200": {
            "m0": {d: {"mean": 0.0336} for d in dens}, "m5": {d: {"mean": 0.0060} for d in dens}}}}}
        rows = pt.five_rows(res, "c200")
        self.assertEqual(rows[0][0], "Spotlight beam")
        self.assertEqual(rows[0][1:7], ["$-$82\\%"] * 6)
        self.assertEqual(rows[0][7], "0.0012")


if __name__ == "__main__":
    unittest.main()
