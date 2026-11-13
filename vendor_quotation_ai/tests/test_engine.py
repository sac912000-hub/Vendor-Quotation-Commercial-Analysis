"""Run with:  python -m pytest -q   (pip install pytest)  or just  python tests/test_engine.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vqc import terms
from vqc.analysis import run_analysis
from vqc.loader import load_quotation

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "Vendor_Quotation_Comparison.xlsx"


def test_term_parsing():
    assert terms.parse_payment("20% advance against ABG, Balance 80% against LC")["advance_pct"] == 20
    assert terms.parse_payment("30% TT in advance, Balance 70% TT")["no_protection"] is True
    assert terms.parse_delivery("16 Weeks ... 7 months ... 12 months")["full"] == 12
    assert terms.parse_delivery("with in 220 days")["full"] == 7.2
    assert terms.parse_warranty("18/24 months") == 24
    assert terms.classify_basis("FOR Site Durg") == "DELIVERED"
    assert terms.classify_basis("F.O.B Shanghai Port basis") == "FOB"


def test_sheet_totals_match_recomputed():
    q = load_quotation(SAMPLE)
    res = run_analysis(q, basis="quoted")
    for v, sheet_total in q.sheet_totals.items():
        assert abs(res.vendor_table.loc[v, "quoted_total"] / sheet_total - 1) < 0.001, v


def test_l1_audit_finds_items_5_and_9():
    res = run_analysis(load_quotation(SAMPLE), basis="quoted")
    assert list(res.audit.loc[~res.audit.ok, "item_no"]) == [5, 9]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("PASS", name)
