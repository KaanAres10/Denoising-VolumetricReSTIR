"""check_numbers.py: every number in the paper's text has a ledger entry.

    cd outputs/decorr && python -m unittest test_check_numbers -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_numbers as cn

TEX = r"""
\begin{figure}[t]\includegraphics[width=0.48\linewidth]{figures/a.png}\end{figure}
Reuse correlates neighbours: $\Delta\bar\rho(8)$ 0.0053--0.0196 \citep{Lin21} at M cap 200, a cut of $-$84\% and ×60.
% a comment with 0.999 is ignored
Section~\ref{sec:intro} and 5 mutations.
"""


class TestCheckNumbers(unittest.TestCase):
    def test_finds_the_texts_numbers_only(self):
        self.assertEqual(cn.numbers(TEX), ["0.0053", "0.0196", "200", "84%", "60"])

    def test_missing_against_the_ledger(self):
        md = "| number | where | source |\n|---|---|---|\n| 0.0053 | §3 | V1 |\n| 0.0196 | §3 | V1 |\n| 200 | §3 | E3 |\n| 84% | §6 | results |\n"
        self.assertEqual(cn.missing(TEX, md), ["60"])


if __name__ == "__main__":
    unittest.main()
