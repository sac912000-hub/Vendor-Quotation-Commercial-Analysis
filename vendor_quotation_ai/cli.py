"""Command-line version (no browser needed).

    python cli.py data/Vendor_Quotation_Comparison.xlsx
    python cli.py data/Vendor_Quotation_Comparison.xlsx --basis quoted --exclude "Shanghai Electric" --ai
"""
import argparse
import json
import re
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from vqc import ai_assistant
from vqc.analysis import BASIS_LABELS, build_conclusion, run_analysis, to_facts
from vqc.export import build_excel_report
from vqc.loader import load_quotation


def main():
    p = argparse.ArgumentParser(description="Vendor quotation comparison")
    p.add_argument("workbook")
    p.add_argument("--basis", choices=list(BASIS_LABELS), default="landed")
    p.add_argument("--exclude", nargs="*", default=[], help="vendor names to leave out")
    p.add_argument("--out", default="Vendor_Comparison_Report.xlsx")
    p.add_argument("--ai", action="store_true", help="add a Claude executive summary (needs ANTHROPIC_API_KEY)")
    args = p.parse_args()

    q = load_quotation(args.workbook)
    res = run_analysis(q, basis=args.basis, exclude=args.exclude)

    print(f"\n{q.title}\n{'=' * 70}")
    for line in build_conclusion(res):
        print("-", re.sub(r"[*_]{1,2}", "", line))
    print("\nVendor scorecard")
    print(res.vendor_table[["coverage_pct", "basis_total", "premium_pct", "weighted_score", "rank"]]
          .round(1).to_string())
    print("\nAward scenarios")
    print(res.scenarios[["scenario", "vendors", "total"]].round(0).to_string(index=False))

    Path(args.out).write_bytes(build_excel_report(res, q.title))
    print(f"\nExcel report written to {args.out}")

    if args.ai:
        if not ai_assistant.available():
            print("Set ANTHROPIC_API_KEY to use --ai.")
        else:
            print("\n--- Claude executive summary ---\n")
            print(ai_assistant.executive_summary(to_facts(res)))


if __name__ == "__main__":
    main()
