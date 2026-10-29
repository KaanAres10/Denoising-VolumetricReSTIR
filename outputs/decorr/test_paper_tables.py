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
        for row in pt.display_rows(record["counts"]["rows"]):  # the counts table fits a column only with short names
            self.assertLessEqual(len(row[0]), 24, row[0])

    def test_both_histories_side_by_side(self):
        dens = ("optix", "oidn", "relax", "reblur", "rr", "raw")
        res = {"bunnyspot": {"ref_own_relmse": 0.0012, "histories": {
            "c200": {"m0": {d: {"mean": 0.0336} for d in dens}, "m5": {d: {"mean": 0.0060} for d in dens}},
            "ship": {"m0": {d: {"mean": 0.0336} for d in dens}, "m5": {d: {"mean": 0.0286} for d in dens}}}}}
        rows = pt.both_rows(res)
        self.assertEqual(rows[0][0], "Spotlight beam")
        self.assertEqual(rows[0][1:7], ["$-$82 / $-$15"] * 6)  # percent at M cap 200 / at the shipped cap
        self.assertEqual(rows[0][7], "1.2")  # the reference's own relMSE in units of 1e-3, two significant digits
        self.assertEqual(pt.ref_cell(4.09e-6), "0.0041")
        self.assertEqual(pt.ref_cell(0.0562), "56")

    def test_a_change_that_rounds_to_zero_has_no_sign(self):
        cfgs = {"m0": {"optix": {"mean": 0.1}, "rr": {"mean": 0.1}}, "m5": {"optix": {"mean": 0.0996}, "rr": {"mean": 0.1004}}}
        self.assertEqual(pt.change(cfgs, "optix"), "0%")  # not "-0%"
        self.assertEqual(pt.change(cfgs, "rr"), "0%")  # not "+0%"

    def test_a_setup_without_both_histories_is_left_out(self):
        dens = ("optix", "oidn", "relax", "reblur", "rr", "raw")
        res = {"bunnyspot": {"ref_own_relmse": 0.0012, "histories": {
            "c200": {"m0": {d: {"mean": 0.0336} for d in dens}, "m5": {d: {"mean": 0.0060} for d in dens}}}}}
        self.assertEqual(pt.both_rows(res), [])



class TestSpacetime(unittest.TestCase):
    def data(self):
        def cell(e, st, b, t3, t30, s8):
            return {"energy": e, "static": st, "bias": b, "rho_t1": 0.0, "rho_t3": t3, "rho_t10": 0.0,
                    "rho_t30": t30, "rho_s8": s8}
        dens = ("raw", "optix", "oidn", "relax", "reblur", "rr")
        out = {"bunnyswarm_d3": {"ref_noise": 0.00407, "histories": {
            "ship": {"m0": {d: cell(0.480, 0.15, 0.13, 0.19, 0.001, 0.009) for d in dens},
                     "m5": {d: cell(0.469, 0.14, 0.12, 0.14, -0.01, 0.010) for d in dens}},
            "c200": {"m0": {d: cell(0.357, 0.32, 0.002, 0.55, 0.30, 0.093) for d in dens},
                     "m5": {d: cell(0.247, 0.09, 0.03, 0.25, 0.03, 0.030) for d in dens}}}}}
        out["bunnyswarm_d3"]["histories"]["ship"]["m0"]["rr"].update(rho_t3=None, rho_t30=None, rho_s8=None)
        return out

    def test_each_cell_holds_the_shipped_cap_then_m_cap_200_plain_and_with_mutations(self):
        tex = pt.spacetime_table(self.data())
        self.assertIn("192 coloured lights", tex)
        self.assertIn("4.1", tex)  # the reference's own relMSE in the band, in units of 1e-3
        row = next(l for l in tex.split("\n") if l.startswith("raw"))
        self.assertEqual(row, "raw & 0.480 / 0.357 / 0.247 & 13 / 0 / 3 & 2 / 32 / 6 & 0.19 / 0.55 / 0.25 "
                              "& 0.00 / 0.30 / 0.03 & 0.009 / 0.093 / 0.030 \\\\")  # -0.01 is no sign; 0.002 is 0%
        rr = next(l for l in tex.split("\n") if l.startswith("DLSS RR"))
        self.assertIn("--- / 0.55 / 0.25", rr)  # too little noise at the shipped cap to correlate
        for den in ("OptiX", "OIDN", "RELAX", "REBLUR", "DLSS RR"):
            self.assertEqual(sum(l.startswith(den + " &") for l in tex.split("\n")), 1, den)

    def test_correlations_are_shown_within_minus_1_and_1(self):
        self.assertEqual(pt._rho(1.013), "1.00")  # over 1 only by the bias estimate's own error
        self.assertEqual(pt._rho(-0.004), "0.00")  # and no sign on one that rounds to zero
        self.assertEqual(pt._rho(0.0934, 3), "0.093")

    def test_shares_are_shown_within_0_and_100_percent(self):
        self.assertEqual(pt._share(1.06), "100")  # an estimate a few percent over all of the error: all of it
        self.assertEqual(pt._share(-0.02), "0")
        self.assertEqual(pt._share(0.315), "32")

    def test_its_latex_commands_are_whole(self):
        tex = pt.spacetime_table(self.data())
        for command in ("\\begin{tabular}{lcccccc}", "\\toprule", "\\midrule", "\\bottomrule", "\\end{tabular}",
                        "bias (\\%)", "$\\rho_t(3)$", "$\\rho_t(30)$", "$\\bar\\rho(8)$",
                        "\\multicolumn{7}{l}{\\emph{192 coloured lights}", "$\\times 10^{-3}$"):
            self.assertIn(command, tex)
        self.assertFalse(any(c in tex for c in "\b\t\r"), "a backslash eaten as an escape")

    def test_it_is_written_with_the_others_when_there_are_strips(self):
        with tempfile.TemporaryDirectory() as d:
            pt.write_all({}, None, d, spacetime=self.data())
            self.assertTrue(os.path.exists(os.path.join(d, "spacetime.tex")))

if __name__ == "__main__":
    unittest.main()
