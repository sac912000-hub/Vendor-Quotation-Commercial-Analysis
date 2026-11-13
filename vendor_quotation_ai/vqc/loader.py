"""Read a buyer's comparative-statement workbook into clean, tidy tables.

Layout expected (same as your sample):
  * vendor names across one header row, each vendor owning a block of columns
  * one column per negotiation round ("Unit Rate", "Unit Rate_R1", "_R2" ...)
  * a currency row under the header, columns marked "Price in INR" are derived and ignored
  * commercial terms (price basis, payment, delivery, warranty ...) in rows below the table
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from .config import VENDOR_SHORT_NAMES, INDIAN_CITIES

TERM_LABELS = [  # (substring in label, key)
    ("make", "make"), ("packing", "packing"), ("price basis", "price_basis"),
    ("payment", "payment_terms"), ("delivery schedule", "delivery"), ("warranty", "warranty"),
    ("supervision", "supervision"), ("technical rating", "tech_rating"),
    ("commercial rating", "comm_rating"), ("delivery rating", "delivery_rating"),
]


@dataclass
class Quotation:
    items: pd.DataFrame            # item_no, item_name, uom, qty, rpm, kw, volt, label
    quotes: pd.DataFrame           # vendor, item_no, round, currency, native_rate
    vendors: pd.DataFrame          # vendor, full_name, location, origin, contact, quote_ref
    terms: pd.DataFrame            # index=vendor, one column per term key (raw text)
    fx: float | None
    title: str = ""
    rfq: str = ""
    sheet_totals: dict = field(default_factory=dict)   # vendor -> "Last negotiated" total in the sheet
    sheet_l1: pd.DataFrame | None = None               # buyer's manual L1 column, if present


def _t(v) -> str:
    return "" if v is None else str(v).strip()


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _oneline(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _short_name(full: str) -> str:
    low = full.lower()
    for key, short in VENDOR_SHORT_NAMES.items():
        if key in low:
            return short
    name = re.sub(r"\b(co\.?,?|ltd\.?|pvt\.?|private|limited|group)\b", "", full, flags=re.I)
    return _oneline(name).strip(" ,.")


def _origin(name: str, location: str) -> str:
    blob = f"{name} {location}".lower()
    if any(c in blob for c in INDIAN_CITIES):
        return "India"
    return location.strip() or "Unknown"


def load_quotation(source, sheet: str | None = None) -> Quotation:
    wb = load_workbook(source, data_only=True)
    ws = wb[sheet] if sheet else wb.worksheets[0]
    max_row = min(ws.max_row, 250)
    max_col = min(ws.max_column, 80)

    # ---- locate the item-table header row ---------------------------------
    hdr = next((r for r in range(1, 20) for c in range(1, 8)
                if _t(ws.cell(r, c).value).lower() == "item name"), None)
    if hdr is None:
        raise ValueError("Could not find an 'Item Name' header. Is this the right sheet?")
    cur_row = hdr + 1

    attr = {}
    for c in range(1, max_col + 1):
        h = _t(ws.cell(hdr, c).value).lower().replace(".", "")
        for key, names in dict(sl=["sl no"], item_name=["item name"], uom=["uom"],
                               qty=["qty"], rpm=["rpm"], kw=["kw"], volt=["volt"]).items():
            if h in names and key not in attr:
                attr[key] = c
    last_attr = max(attr.values())

    # ---- items -------------------------------------------------------------
    items, r = [], cur_row + 1
    total_row = None
    while r <= max_row:
        b = _t(ws.cell(r, attr["item_name"]).value)
        if b.lower().startswith("total"):
            total_row = r
            break
        no = ws.cell(r, attr["sl"]).value
        if b and isinstance(no, (int, float)):
            items.append(dict(
                item_no=int(no), item_name=_oneline(b), uom=_t(ws.cell(r, attr["uom"]).value),
                qty=_num(ws.cell(r, attr["qty"]).value) or 0,
                rpm=_t(ws.cell(r, attr["rpm"]).value), kw=ws.cell(r, attr["kw"]).value,
                volt=ws.cell(r, attr["volt"]).value, row=r))
        r += 1
    if not items or total_row is None:
        raise ValueError("No item rows found above a 'Total' row.")
    items_df = pd.DataFrame(items)
    items_df["label"] = items_df.item_no.astype(str) + ". " + items_df.item_name

    # ---- FX ----------------------------------------------------------------
    fx = None
    for rr in range(1, hdr):
        for c in range(1, max_col + 1):
            if _t(ws.cell(rr, c).value).lower().startswith("usd to inr"):
                fx = next((_num(ws.cell(rr, k).value) for k in range(c + 1, max_col + 1)
                           if _num(ws.cell(rr, k).value)), None)

    # ---- vendor blocks -----------------------------------------------------
    vendor_row = max(range(1, hdr), key=lambda rr: (
        sum(1 for c in range(last_attr + 1, max_col + 1) if _t(ws.cell(rr, c).value)), -rr))
    starts = [c for c in range(last_attr + 1, max_col + 1) if _t(ws.cell(vendor_row, c).value)]
    l1_col = next((c for c in range(last_attr + 1, max_col + 1)
                   if _t(ws.cell(hdr, c).value).lower().startswith("l1")), None)
    hdr_cols = [c for c in range(last_attr + 1, max_col + 1) if _t(ws.cell(hdr, c).value)]
    table_end = (l1_col - 1) if l1_col else max(hdr_cols)
    starts = [c for c in starts if c <= table_end]
    ends = [s - 1 for s in starts[1:]] + [table_end]

    vendors, quotes = [], []
    for s, e in zip(starts, ends):
        raw = _t(ws.cell(vendor_row, s).value)
        lines = [x.strip() for x in raw.split("\n") if x.strip()]
        full = lines[0]
        loc = lines[1].strip("() ") if len(lines) > 1 else ""
        short = _short_name(full)

        cols = []
        for c in range(s, e + 1):
            head = _t(ws.cell(hdr, c).value).replace("\n", "").replace(" ", "")
            curt = _t(ws.cell(cur_row, c).value).lower()
            m = re.search(r"R(\d+)", head)
            cols.append(dict(col=c, round=int(m.group(1)) if m else 0,
                             derived="price in inr" in curt,
                             currency="USD" if ("$" in curt or "dollar" in curt or "usd" in curt) else "INR"))
        native = [x for x in cols if not x["derived"]] or cols
        got = {}
        for x in native:
            for it in items:
                v = _num(ws.cell(it["row"], x["col"]).value)
                if v and v > 0:
                    got[(it["item_no"], x["round"])] = (x["currency"], v)
        if not got:
            continue
        for (ino, rnd), (cur, v) in got.items():
            quotes.append(dict(vendor=short, item_no=ino, round=rnd, currency=cur, native_rate=v))
        vendors.append(dict(
            vendor=short, full_name=_oneline(full), location=loc, origin=_origin(full, loc),
            contact=_oneline(_t(ws.cell(vendor_row + 1, s).value).replace("\n", "; ")),
            quote_ref=_oneline(_t(ws.cell(vendor_row + 2, s).value).replace("\n", " | ")),
            first_col=s))

    vendors_df = pd.DataFrame(vendors)
    quotes_df = pd.DataFrame(quotes)

    # ---- commercial terms & sheet totals (rows below the table) -------------
    terms = {v: {} for v in vendors_df.vendor}
    sheet_totals = {}
    for rr in range(total_row + 1, min(total_row + 45, max_row) + 1):
        label = _t(ws.cell(rr, attr["item_name"]).value).lower()
        if not label:
            continue
        for _, v in vendors_df.iterrows():
            val = ws.cell(rr, int(v.first_col)).value
            if "last negotiated" in label and _num(val):
                sheet_totals[v.vendor] = _num(val)
            for sub, key in TERM_LABELS:
                if sub in label:
                    if val is not None and _t(val):
                        terms[v.vendor][key] = val if key.endswith("rating") else _t(val)
                    break
    terms_df = pd.DataFrame.from_dict(terms, orient="index").reindex(columns=[k for _, k in TERM_LABELS])
    terms_df.index.name = "vendor"

    # ---- buyer's manual L1 column (optional audit) ---------------------------
    sheet_l1 = None
    if l1_col:
        rows = []
        for it in items:
            v = _num(ws.cell(it["row"], l1_col).value)
            if v:
                rows.append(dict(item_no=it["item_no"], sheet_l1_inr=v,
                                 sheet_l1_vendor=_t(ws.cell(it["row"], l1_col + 1).value)))
        sheet_l1 = pd.DataFrame(rows) if rows else None

    return Quotation(
        items=items_df.drop(columns="row"), quotes=quotes_df, vendors=vendors_df.drop(columns="first_col"),
        terms=terms_df, fx=fx, title=_oneline(_t(ws.cell(3, 2).value)),
        rfq=_oneline(_t(ws.cell(2, 2).value)), sheet_totals=sheet_totals, sheet_l1=sheet_l1)
