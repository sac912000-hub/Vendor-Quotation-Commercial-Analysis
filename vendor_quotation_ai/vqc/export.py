"""Excel report for sharing with management (values + one native Excel chart)."""
from __future__ import annotations
import io
import re
import pandas as pd
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .analysis import Result, build_conclusion, BASIS_LABELS

HDR_FILL = PatternFill("solid", start_color="2F5D8A")
HDR_FONT = Font(name="Arial", bold=True, color="FFFFFF")
BODY_FONT = Font(name="Arial", size=10)


def _plain(md: str) -> str:
    return re.sub(r"[*_]{1,2}", "", md)


def _style(ws, widths=None, wrap_cols=(), money_cols=(), pct_cols=(), dec_cols=()):
    for c in ws[1]:
        c.fill, c.font = HDR_FILL, HDR_FONT
        c.alignment = Alignment(wrap_text=True, vertical="center")
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.font = BODY_FONT
            name = ws.cell(1, c.column).value
            if name in wrap_cols:
                c.alignment = Alignment(wrap_text=True, vertical="top")
            if name in money_cols:
                c.number_format = "#,##0"
            elif name in pct_cols or name in dec_cols:
                c.number_format = "0.0"
    for i, col in enumerate(ws.columns, 1):
        letter = get_column_letter(i)
        w = (widths or {}).get(ws.cell(1, i).value)
        if not w:
            longest = max((len(str(c.value)) for c in col[:60] if c.value is not None), default=8)
            w = min(max(longest + 2, 10), 40)
        ws.column_dimensions[letter].width = w
    ws.freeze_panes = "B2"


def build_excel_report(res: Result, title: str = "") -> bytes:
    buf = io.BytesIO()
    vt = res.vendor_table
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        # Summary
        lines = [title, f"Comparison basis: {BASIS_LABELS[res.basis]}", f"FX (USD->INR): {res.fx}", ""] \
            + [_plain(x) for x in build_conclusion(res)]
        pd.DataFrame({"Executive summary": lines}).to_excel(xw, sheet_name="Summary", index=False)
        # Scorecard
        sc = vt.reset_index()[["vendor", "origin", "coverage_pct", "full_scope", "basis_total", "premium_pct", "l1_wins",
                               "price_score", "delivery_score", "payment_score", "warranty_score",
                               "weighted_score", "rank"]].round(2)
        sc.columns = ["Vendor", "Origin", "Coverage %", "Full scope", "Total (INR, selected basis)", "Premium vs item L1 %",
                      "Items L1", "Price score", "Delivery score", "Payment score", "Warranty score",
                      "Weighted score", "Rank"]
        sc.to_excel(xw, sheet_name="Vendor Scorecard", index=False)
        # Item comparison
        ib = res.basis_rates.copy()
        ib.insert(0, "Item", res.items.label)
        ib.insert(1, "Qty", res.items.qty)
        ib["L1 vendor"] = res.item_table.set_index("item_no").l1_vendor
        ib["L1 rate"] = res.item_table.set_index("item_no").l1_rate
        ib["L2 gap %"] = res.item_table.set_index("item_no").l2_gap_pct.round(1)
        ib.reset_index(drop=True).to_excel(xw, sheet_name="Item Comparison", index=False)
        res.scenarios.round(2).to_excel(xw, sheet_name="Award Scenarios", index=False)
        res.negotiation.round(2).to_excel(xw, sheet_name="Negotiation", index=False)
        terms = vt.reset_index()[["vendor", "basis_class", "price_basis_text", "advance_pct", "advance_secured",
                                  "payment_text", "delivery_full_m", "delivery_to_site_m", "delivery_text",
                                  "warranty_m", "supervision", "landed_factor"]].round(3)
        terms.to_excel(xw, sheet_name="Commercial Terms", index=False)
        res.flags.to_excel(xw, sheet_name="Red Flags", index=False)
        if res.audit is not None:
            res.audit.to_excel(xw, sheet_name="Manual L1 Audit", index=False)

        wb = xw.book
        _style(wb["Summary"], widths={"Executive summary": 120}, wrap_cols=("Executive summary",))
        _style(wb["Vendor Scorecard"], money_cols=("Total (INR, selected basis)",))
        _style(wb["Item Comparison"], widths={"Item": 38}, money_cols=tuple(res.basis_rates.columns) + ("L1 rate",))
        _style(wb["Award Scenarios"], widths={"scenario": 44, "vendors": 36}, money_cols=("total", "vs_recommended_inr"))
        _style(wb["Negotiation"], money_cols=("total",))
        _style(wb["Commercial Terms"], widths={"price_basis_text": 28, "payment_text": 60, "delivery_text": 50},
               wrap_cols=("price_basis_text", "payment_text", "delivery_text"))
        _style(wb["Red Flags"], widths={"message": 110}, wrap_cols=("message",))
        if res.audit is not None:
            _style(wb["Manual L1 Audit"], widths={"item": 40},
                   money_cols=("sheet_l1_rate", "true_l1_rate", "overstated_by"))

        # native Excel chart on the scorecard sheet
        ws = wb["Vendor Scorecard"]
        ch = BarChart()
        ch.type, ch.title = "bar", "Weighted score by vendor"
        ch.add_data(Reference(ws, min_col=12, min_row=1, max_row=ws.max_row), titles_from_data=True)
        ch.set_categories(Reference(ws, min_col=1, min_row=2, max_row=ws.max_row))
        ch.legend, ch.height, ch.width = None, 8, 16
        ws.add_chart(ch, f"B{ws.max_row + 3}")
    return buf.getvalue()
