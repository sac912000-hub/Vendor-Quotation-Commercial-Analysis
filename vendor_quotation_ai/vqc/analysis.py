"""Comparison engine: L1 ranking, landed cost, scoring, scenarios, negotiation, red flags."""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd

from . import terms as T
from .config import Assumptions, Weights, OUTLIER_HIGH, OUTLIER_LOW
from .loader import Quotation

BASIS_LABELS = {"quoted": "Quoted price (as per each vendor's price basis)",
                "landed": "Landed cost at site (logistics + duty added)",
                "tco": "Landed cost + financing cost of advance"}


@dataclass
class Result:
    fx: float
    basis: str
    active: list
    items: pd.DataFrame
    final_rates: pd.DataFrame        # item_no x vendor, INR, as quoted
    basis_rates: pd.DataFrame        # item_no x vendor, INR, on selected basis
    item_table: pd.DataFrame
    vendor_table: pd.DataFrame
    scenarios: pd.DataFrame
    award: pd.DataFrame              # item-wise L1 award on active vendors
    negotiation: pd.DataFrame
    flags: pd.DataFrame
    audit: pd.DataFrame | None
    weights_used: dict
    recommended: str
    notes: list = field(default_factory=list)
    assumptions: Assumptions | None = None


# ------------------------------------------------------------------ helpers
def landed_factor(basis_cls: str, a: Assumptions) -> float:
    if basis_cls == "FOB":
        cif = 1 + a.freight_insurance_pct / 100
        return cif * (1 + a.import_duty_pct / 100) + a.clearance_inland_pct / 100
    if basis_cls == "CIF":
        return (1 + a.import_duty_pct / 100) + a.clearance_inland_pct / 100
    if basis_cls == "EXW":
        return 1 + a.exworks_inland_pct / 100
    return 1.0


def _itemwise_award(rates: pd.DataFrame, items: pd.DataFrame, vendors: list):
    """Cheapest vendor per item among `vendors`; None if any item has no quote."""
    sub = rates[vendors]
    if sub.isna().all(axis=1).any():
        return None
    rows = []
    for ino, r in sub.iterrows():
        v = r.idxmin()
        qty = items.loc[ino, "qty"]
        rows.append(dict(item_no=ino, item=items.loc[ino, "label"], qty=qty, vendor=v,
                         unit_rate=r[v], amount=r[v] * qty))
    return pd.DataFrame(rows)


# --------------------------------------------------------------- main entry
def run_analysis(q: Quotation, a: Assumptions | None = None, w: Weights | None = None,
                 basis: str = "landed", exclude=(), tech_ratings: dict | None = None) -> Result:
    a, w = a or Assumptions(), w or Weights()
    fx = a.fx_usd_inr or q.fx
    if not fx:
        raise ValueError("No USD->INR rate found in the sheet; please enter one.")
    fx_map = {"USD": fx, "INR": 1.0}
    bad = set(q.quotes.currency) - set(fx_map)
    if bad:
        raise ValueError(f"Unsupported currency {bad}. Add it to fx_map in analysis.py.")

    items = q.items.set_index("item_no")
    vendors = list(q.vendors.vendor)
    qs = q.quotes.copy()
    qs["rate_inr"] = qs.native_rate * qs.currency.map(fx_map)
    qs = qs.sort_values(["vendor", "item_no", "round"])
    final = qs.groupby(["vendor", "item_no"], as_index=False).last()
    initial = qs.groupby(["vendor", "item_no"], as_index=False).first()
    final_w = final.pivot(index="item_no", columns="vendor", values="rate_inr").reindex(index=items.index, columns=vendors)
    init_w = initial.pivot(index="item_no", columns="vendor", values="rate_inr").reindex(index=items.index, columns=vendors)

    # ---- parsed terms per vendor ------------------------------------------
    rows = []
    for v in vendors:
        t = q.terms.loc[v] if v in q.terms.index else pd.Series(dtype=object)
        pay = T.parse_payment(t.get("payment_terms"))
        dl = T.parse_delivery(t.get("delivery"))
        bcls = T.classify_basis(t.get("price_basis"))
        site = None if dl["full"] is None else dl["full"] + (a.transit_months_import if T.is_import(bcls) else 0)
        lf = landed_factor(bcls, a)
        fin = 1 + (pay["advance_pct"] or 0) / 100 * a.cost_of_capital_pct / 100 * ((site or 0) / 12)
        tr = (tech_ratings or {}).get(v)
        if tr is None and pd.notna(t.get("tech_rating", np.nan)):
            tr = t.get("tech_rating")
        rows.append(dict(vendor=v, make=t.get("make") if pd.notna(t.get("make", np.nan)) else "",
                         price_basis_text=T.clean(t.get("price_basis")), basis_class=bcls,
                         advance_pct=pay["advance_pct"], advance_secured=pay["secured"], has_lc=pay["has_lc"],
                         has_pbg=pay["has_pbg"], no_protection=pay["no_protection"],
                         payment_text=T.clean(t.get("payment_terms")),
                         delivery_first_m=dl["first"], delivery_full_m=dl["full"], delivery_to_site_m=site,
                         delivery_text=T.clean(t.get("delivery")),
                         warranty_m=T.parse_warranty(t.get("warranty")), warranty_text=T.clean(t.get("warranty")),
                         supervision=T.classify_supervision(t.get("supervision")),
                         supervision_text=T.clean(t.get("supervision")),
                         packing=T.clean(t.get("packing")),
                         landed_factor=lf, fin_factor=fin, tech_rating=tr,
                         payment_score=T.payment_score(pay)))
    vt = pd.DataFrame(rows).set_index("vendor")
    factor = {"quoted": pd.Series(1.0, index=vendors), "landed": vt.landed_factor,
              "tco": vt.landed_factor * vt.fin_factor}[basis]
    basis_w = final_w.mul(factor, axis=1)

    active = [v for v in vendors if v not in set(exclude)]
    if not active:
        raise ValueError("All vendors are excluded.")
    n_items = len(items)

    # ---- item-wise table -----------------------------------------------------
    it_rows = []
    for ino in items.index:
        s = basis_w.loc[ino, active].dropna().sort_values()
        l1 = s.index[0] if len(s) else None
        it_rows.append(dict(
            item_no=ino, item=items.loc[ino, "label"], qty=items.loc[ino, "qty"], n_quotes=len(s),
            l1_vendor=l1, l1_rate=s.iloc[0] if len(s) else np.nan,
            l2_vendor=s.index[1] if len(s) > 1 else None, l2_rate=s.iloc[1] if len(s) > 1 else np.nan,
            l2_gap_pct=(s.iloc[1] / s.iloc[0] - 1) * 100 if len(s) > 1 else np.nan,
            spread_pct=(s.iloc[-1] / s.iloc[0] - 1) * 100 if len(s) > 1 else np.nan,
            median_rate=s.median() if len(s) else np.nan,
            l1_amount=s.iloc[0] * items.loc[ino, "qty"] if len(s) else np.nan))
    item_table = pd.DataFrame(it_rows)
    l1_rate = item_table.set_index("item_no").l1_rate

    # ---- vendor table ----------------------------------------------------------
    vrows = []
    qty = items.qty
    for v in active:
        have = basis_w[v].dropna().index
        tot = float((basis_w.loc[have, v] * qty[have]).sum())
        tot_q = float((final_w.loc[have, v] * qty[have]).sum())
        tot_init = float((init_w.loc[have, v] * qty[have]).sum())
        l1_same = float((l1_rate[have] * qty[have]).sum())
        vrows.append(dict(
            vendor=v, origin=q.vendors.set_index("vendor").loc[v, "origin"], items_quoted=len(have),
            coverage_pct=len(have) / n_items * 100, full_scope=len(have) == n_items,
            initial_total=tot_init, quoted_total=tot_q, basis_total=tot, l1_same_items=l1_same,
            premium_pct=(tot / l1_same - 1) * 100,
            l1_wins=int((item_table.l1_vendor == v).sum()),
            neg_saving_pct=(1 - tot_q / tot_init) * 100 if tot_init else 0.0,
            neg_saving_inr=tot_init - tot_q,
            financing_cost=tot_q * (vt.loc[v, "landed_factor"]) * (vt.loc[v, "fin_factor"] - 1)))
    vtab = pd.DataFrame(vrows).set_index("vendor").join(vt.drop(columns=[]), how="left")

    # ---- scores ------------------------------------------------------------------
    vtab["price_score"] = 100 * vtab.l1_same_items / vtab.basis_total
    d = vtab.delivery_to_site_m
    vtab["delivery_score"] = (100 * d.min() / d).fillna(0) if d.notna().any() else 0.0
    wm = vtab.warranty_m
    vtab["warranty_score"] = (100 * wm / wm.max()).fillna(0) if wm.notna().any() else 0.0
    vtab["technical_score"] = pd.to_numeric(vtab.tech_rating, errors="coerce")
    wd = w.as_dict()
    notes = []
    if vtab.technical_score.isna().any():
        if wd["technical"] > 0:
            notes.append("Technical rating is not filled for every vendor, so it is excluded from the weighted score. "
                         "Enter ratings in the sidebar to include it.")
        wd["technical"] = 0.0
    tot_w = sum(wd.values()) or 1.0
    wn = {k: v / tot_w for k, v in wd.items()}
    for k in wn:
        col = f"{k}_score"
        vtab[f"{k}_pts"] = wn[k] * vtab[col].fillna(0) if wn[k] else 0.0
    vtab["weighted_score"] = vtab[[f"{k}_pts" for k in wn]].sum(axis=1)
    full = vtab[vtab.full_scope]
    pool = full if len(full) else vtab
    vtab["rank"] = np.nan
    vtab.loc[pool.index, "rank"] = pool.weighted_score.rank(ascending=False, method="min")
    recommended = pool.weighted_score.idxmax()
    if not len(full):
        notes.append("No vendor quoted every item; recommendation is across partial quotes.")
    vtab = vtab.sort_values(["full_scope", "weighted_score"], ascending=[False, False])

    # ---- award scenarios ---------------------------------------------------------
    scen = []
    if len(full):
        cheapest = full.basis_total.idxmin()
        scen.append(dict(scenario="Lowest-price single vendor", vendors=cheapest, n_vendors=1,
                         total=full.loc[cheapest, "basis_total"]))
        scen.append(dict(scenario="Highest-scoring single vendor (recommended)", vendors=recommended,
                         n_vendors=1, total=full.loc[recommended, "basis_total"]))
    award = _itemwise_award(basis_w, items, active)
    groups = {"Item-wise L1, all active vendors": active,
              "Item-wise L1, Indian vendors only": [v for v in active if vtab.loc[v, "origin"] == "India"],
              "Item-wise L1, foreign vendors only": [v for v in active if vtab.loc[v, "origin"] != "India"]}
    for name, grp in groups.items():
        if not grp:
            continue
        aw = _itemwise_award(basis_w, items, grp)
        if aw is None:
            scen.append(dict(scenario=name, vendors=", ".join(grp), n_vendors=len(grp), total=np.nan))
        else:
            scen.append(dict(scenario=name, vendors=", ".join(sorted(aw.vendor.unique())),
                             n_vendors=aw.vendor.nunique(), total=aw.amount.sum()))
    scen = pd.DataFrame(scen)
    base = vtab.loc[recommended, "basis_total"] if len(full) else np.nan
    scen["vs_recommended_inr"] = scen.total - base
    scen["vs_recommended_pct"] = (scen.total / base - 1) * 100

    # ---- negotiation progress -----------------------------------------------------
    neg = []
    for v in active:
        sub = qs[qs.vendor == v].pivot(index="item_no", columns="round", values="rate_inr").sort_index(axis=1)
        sub = sub.ffill(axis=1)
        for rnd in sub.columns:
            neg.append(dict(vendor=v, round=int(rnd), label="Initial" if rnd == 0 else f"Round {int(rnd)}",
                            total=float((sub[rnd] * qty.reindex(sub.index)).sum())))
    neg = pd.DataFrame(neg)
    if len(neg):
        first = neg.groupby("vendor").total.transform("first")
        neg["saving_vs_initial_pct"] = (1 - neg.total / first) * 100

    flags = _red_flags(q, a, final_w, items, vtab, active, fx, recommended)
    audit = _audit_manual_l1(q, final_w, items)
    if audit is not None and (~audit.ok).any():
        n = int((~audit.ok).sum())
        flags = pd.concat([flags, pd.DataFrame([dict(
            severity="High", vendor="(buyer sheet)", category="Manual sheet error",
            message=f"The sheet's own L1 column is not the lowest quote on {n} item(s): "
                    + ", ".join(f"#{i}" for i in audit.loc[~audit.ok, "item_no"]) + ". See 'Data checks' tab.")])],
            ignore_index=True)
    return Result(fx=fx, basis=basis, active=active, items=items, final_rates=final_w, basis_rates=basis_w,
                  item_table=item_table, vendor_table=vtab, scenarios=scen, award=award, negotiation=neg,
                  flags=flags, audit=audit, weights_used=wn, recommended=recommended, notes=notes, assumptions=a)


# ------------------------------------------------------------------ red flags
def _red_flags(q, a, final_w, items, vtab, active, fx, recommended) -> pd.DataFrame:
    F = []
    def add(sev, v, cat, msg): F.append(dict(severity=sev, vendor=v, category=cat, message=msg))
    n_items = len(items)
    inr = lambda x: f"₹{x/1e5:,.2f} lakh" if x < 1e7 else f"₹{x/1e7:,.2f} Cr"

    for v in active:
        r = vtab.loc[v]
        if not r.full_scope:
            add("Medium", v, "Partial quote", f"Quoted only {int(r.items_quoted)} of {n_items} items "
                f"({r.coverage_pct:.0f}%). Its headline total is NOT comparable with full-scope vendors.")
        if r.advance_pct and not r.advance_secured:
            add("Medium", v, "Payment risk", f"{r.advance_pct:.0f}% advance with no Advance Bank Guarantee mentioned.")
        if r.no_protection:
            add("High", v, "Payment risk", "Payment terms show no LC / bank guarantee protection (all TT payments).")
        if r.supervision in ("Not quoted", "Chargeable", "Unclear"):
            add("Low" if r.supervision == "Chargeable" else "Medium", v, "Commissioning cost",
                f"Erection & commissioning supervision is '{r.supervision}' - add the cost before final comparison.")
        if pd.isna(r.delivery_full_m):
            add("Medium", v, "Missing data", "Delivery schedule could not be read.")
        if pd.isna(r.warranty_m):
            add("Medium", v, "Missing data", "Warranty could not be read.")
    dmin = vtab.loc[active, "delivery_to_site_m"].min()
    for v in active:
        d = vtab.loc[v, "delivery_to_site_m"]
        if pd.notna(d) and pd.notna(dmin) and d > 1.5 * dmin:
            add("Medium", v, "Delivery", f"Delivery ~{d:.1f} months vs fastest {dmin:.1f} months.")
    bases = {vtab.loc[v, "basis_class"] for v in active}
    if len(bases) > 1:
        add("Info", "(all)", "Comparability", "Vendors quote on different price bases ("
            + ", ".join(sorted(bases)) + "). Use the 'Landed cost' basis for a fair comparison.")

    # systematically low vendors (checked first so we do not also flag every single item)
    low_vendors = set()
    for v in active:
        ratios = []
        for ino in final_w.index:
            others = final_w.loc[ino, [u for u in active if u != v]].dropna()
            if pd.notna(final_w.loc[ino, v]) and len(others) >= 2:
                ratios.append(final_w.loc[ino, v] / others.median())
        if len(ratios) >= 4 and np.median(ratios) < 0.75:
            low_vendors.add(v)
            add("Medium", v, "Abnormally low bid?", f"Typical rate is {np.median(ratios):.0%} of the market median "
                f"across {len(ratios)} items. Confirm it covers the full specification (efficiency class, "
                f"bearings, testing, spares) before treating it as a real saving.")

    # item-level price outliers vs median of the other vendors
    for ino in final_w.index:
        for v in active:
            x = final_w.loc[ino, v]
            others = final_w.loc[ino, [u for u in active if u != v]].dropna()
            if pd.isna(x) or len(others) < 2:
                continue
            ratio = x / others.median()
            high, low = ratio >= OUTLIER_HIGH, ratio <= OUTLIER_LOW and v not in low_vendors
            if high or low:
                add("High" if (ratio >= 2.5 or ratio <= 0.4) else "Medium", v, "Price outlier",
                    f"Item {ino} ({items.loc[ino,'item_name']}): {inr(x)} per unit is {ratio:.2f}x the median of other "
                    f"quotes ({inr(others.median())}). Verify scope/specification or ask for a re-quote.")

    # vendors that never negotiated
    rounds = q.quotes.groupby("vendor")["round"].max()
    for v in active:
        if rounds.get(v, 0) == 0:
            add("Info", v, "Negotiation", "Only the initial offer is recorded - no negotiation round yet, so price leverage is unused.")

    # sheet totals vs recomputed
    for v, sheet_total in q.sheet_totals.items():
        if v not in vtab.index:
            continue
        mine = vtab.loc[v, "quoted_total"]
        if sheet_total and abs(mine / sheet_total - 1) > 0.005:
            add("Medium", v, "Total mismatch", f"Sheet total {inr(sheet_total)} differs from recomputed {inr(mine)} "
                f"at FX {fx:.2f}.")
    sev = {"High": 0, "Medium": 1, "Low": 2, "Info": 3}
    df = pd.DataFrame(F, columns=["severity", "vendor", "category", "message"])
    return df.sort_values("severity", key=lambda s: s.map(sev), kind="stable").reset_index(drop=True)


def _audit_manual_l1(q: Quotation, final_w: pd.DataFrame, items: pd.DataFrame):
    if q.sheet_l1 is None:
        return None
    rows = []
    for _, r in q.sheet_l1.iterrows():
        ino = int(r.item_no)
        s = final_w.loc[ino].dropna()
        best_v, best = s.idxmin(), s.min()
        rows.append(dict(item_no=ino, item=items.loc[ino, "label"], sheet_l1_vendor=r.sheet_l1_vendor,
                         sheet_l1_rate=r.sheet_l1_inr, true_l1_vendor=best_v, true_l1_rate=best,
                         overstated_by=r.sheet_l1_inr - best, ok=bool(r.sheet_l1_inr <= best * 1.0005)))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ conclusion
def cr(x): return f"₹{x/1e7:,.2f} Cr"


def build_conclusion(res: Result) -> list[str]:
    vt, sc = res.vendor_table, res.scenarios
    full = vt[vt.full_scope]
    out = []
    if len(full):
        ranked = full.sort_values("basis_total")
        l1, l2 = ranked.index[0], ranked.index[1] if len(ranked) > 1 else None
        s = f"**Lowest full-scope price:** {l1} at {cr(ranked.iloc[0].basis_total)}"
        if l2:
            s += f", {ranked.iloc[1].basis_total / ranked.iloc[0].basis_total * 100 - 100:.1f}% below the next bidder ({l2}, {cr(ranked.iloc[1].basis_total)})."
        out.append(s)
        rec = vt.loc[res.recommended]
        if res.recommended != l1:
            names = {"delivery": "delivery time", "payment": "payment terms", "warranty": "warranty", "technical": "technical rating"}
            better = [n for k, n in names.items() if res.weights_used.get(k, 0) > 0
                      and rec[f"{k}_score"] > vt.loc[l1, f"{k}_score"]]
            why = (" It beats " + l1 + " on " + ", ".join(better) + ".") if better else ""
            out.append(f"**Recommended on weighted score:** {res.recommended} (score {rec.weighted_score:.1f}).{why} "
                       f"{l1} is {(1 - ranked.iloc[0].basis_total / rec.basis_total) * 100:.1f}% cheaper but scores "
                       f"{vt.loc[l1].weighted_score:.1f}.")
        else:
            out.append(f"**Recommended on weighted score:** {res.recommended} (score {rec.weighted_score:.1f}) - "
                       f"it is both cheapest and best overall.")
    split = sc[sc.scenario.str.contains("all active")]
    if len(split) and pd.notna(split.iloc[0].total) and len(full):
        sv = -split.iloc[0].vs_recommended_inr
        if sv > 0:
            out.append(f"**Split-award opportunity:** buying each item from its L1 vendor costs {cr(split.iloc[0].total)} "
                       f"across {int(split.iloc[0].n_vendors)} vendors, saving {cr(sv)} "
                       f"({-split.iloc[0].vs_recommended_pct:.1f}%) versus a single award to {res.recommended}. "
                       f"Weigh this against interface, spares and warranty complexity.")
    if res.audit is not None and (~res.audit.ok).any():
        bad = res.audit[~res.audit.ok]
        out.append("**Buyer-sheet check:** the manual L1 column is not the true lowest on item(s) "
                   + ", ".join(f"#{r.item_no} ({r.true_l1_vendor} is lower by {cr(r.overstated_by * res.items.loc[r.item_no, 'qty'])} on quantity)"
                               for r in bad.itertuples()) + ".")
    part = vt[~vt.full_scope]
    for v in part.index:
        out.append(f"**{v}** quoted only {int(part.loc[v,'items_quoted'])}/{len(res.items)} items - "
                   f"{part.loc[v,'premium_pct']:+.1f}% vs L1 on those items; eligible only for a partial/split award.")
    top = res.flags[res.flags.severity == "High"]
    if len(top):
        out.append(f"**{len(top)} high-severity flag(s)** need attention before award (see Risks & data checks).")
    best_neg = vt.neg_saving_pct.idxmax()
    if vt.loc[best_neg, "neg_saving_pct"] > 0:
        out.append(f"**Negotiation:** {best_neg} gave the largest reduction ({vt.loc[best_neg,'neg_saving_pct']:.1f}% "
                   f"from initial offer, {cr(vt.loc[best_neg,'neg_saving_inr'])}).")
    out.append(f"_Basis: {BASIS_LABELS[res.basis]}; FX ₹{res.fx:.2f}/USD. Landed-cost percentages are editable assumptions._")
    for n in res.notes:
        out.append(f"_Note: {n}_")
    return out


def to_facts(res: Result) -> dict:
    """Compact, number-only summary handed to Claude so it cannot invent figures."""
    vt = res.vendor_table
    cols = ["origin", "items_quoted", "coverage_pct", "basis_total", "quoted_total", "premium_pct", "l1_wins",
            "neg_saving_pct", "advance_pct", "advance_secured", "delivery_to_site_m", "warranty_m",
            "supervision", "basis_class", "price_score", "delivery_score", "payment_score", "warranty_score",
            "weighted_score", "rank"]
    return dict(
        fx_usd_inr=res.fx, comparison_basis=BASIS_LABELS[res.basis], currency="INR",
        recommended_vendor=res.recommended, weights=res.weights_used, vendors_in_scope=res.active,
        vendors=vt[cols].round(2).reset_index().to_dict("records"),
        items=res.item_table[["item_no", "item", "qty", "l1_vendor", "l1_rate", "l2_vendor", "l2_gap_pct", "spread_pct"]]
        .round(2).to_dict("records"),
        scenarios=res.scenarios.round(2).replace({np.nan: None}).to_dict("records"),
        red_flags=res.flags.to_dict("records"),
        landed_cost_assumptions=res.assumptions.__dict__ if res.assumptions else {})
