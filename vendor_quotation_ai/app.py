"""AI-Based Vendor Quotation Comparison - dark Streamlit dashboard.

Run:  streamlit run app.py
"""
from __future__ import annotations
import html
import io
import os
import re
from pathlib import Path

import pandas as pd
import streamlit as st

try:                                    # optional: load ANTHROPIC_API_KEY from a .env file
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from vqc import charts, ai_assistant
from vqc.analysis import BASIS_LABELS, build_conclusion, run_analysis, to_facts
from vqc.config import Assumptions, Weights
from vqc.export import build_excel_report
from vqc.loader import load_quotation

SAMPLE = Path(__file__).parent / "data" / "Vendor_Quotation_Comparison.xlsx"
SEV_COLOR = {"High": "#ef6b5b", "Medium": "#f0b429", "Low": "#8fa3b8", "Info": "#4aa3ff"}

st.set_page_config(page_title="Vendor Quotation Comparison", page_icon="📊", layout="wide")
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');
.stApp {font-family: 'IBM Plex Sans', system-ui, -apple-system, 'Segoe UI', sans-serif;}
.block-container {padding-top: 1.4rem; max-width: 1400px;}
h1 {font-weight: 700; letter-spacing: -0.5px; margin-bottom: 0;}
h3 {font-weight: 600; margin-top: 0.4rem;}
.hero {background:#162131; border:1px solid #243247; border-left:5px solid #3fcf9b; border-radius:10px;
       padding:20px 26px; margin:14px 0 14px 0;}
.hero-k {color:#8fa3b8; font-size:0.85rem; margin-bottom:2px;}
.hero-v {font-size:2rem; font-weight:700; line-height:1.15;}
.hero-s {color:#8fa3b8; margin:4px 0 12px 0;}
.hero ul {margin:0; padding-left:1.1rem;} .hero li {margin:3px 0;}
.kpi {background:#162131; border:1px solid #243247; border-radius:10px; padding:14px 18px; height:100%;}
.kpi-l {color:#8fa3b8; font-size:0.82rem;}
.kpi-v {font-size:1.6rem; font-weight:700; font-variant-numeric: tabular-nums; margin:2px 0;}
.kpi-s {color:#8fa3b8; font-size:0.82rem;}
.kpi.bad {border-left:4px solid #ef6b5b;} .kpi.good {border-left:4px solid #3fcf9b;}
.kpi.warn {border-left:4px solid #f0b429;}
.flag {background:#162131; border:1px solid #243247; border-left:4px solid #8fa3b8; border-radius:8px;
       padding:10px 14px; margin:8px 0; font-size:0.93rem;}
.flag b {font-weight:600;} .flag small {color:#8fa3b8;}
.how {color:#8fa3b8; font-size:0.9rem; margin:-4px 0 10px 0;}
div[data-testid="stTabs"] button {font-size:1rem; font-weight:500;}
</style>""", unsafe_allow_html=True)


# ------------------------------------------------------------------ helpers
def inr(x):
    if pd.isna(x):
        return "–"
    s = str(abs(int(round(x))))
    if len(s) > 3:
        s = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", s[:-3]) + "," + s[-3:]
    return ("-" if x < 0 else "") + "₹" + s


def cr(x):
    return f"₹{x / 1e7:,.2f} Cr"


def kpi(label, value, sub, tone=""):
    return (f'<div class="kpi {tone}"><div class="kpi-l">{html.escape(label)}</div>'
            f'<div class="kpi-v">{html.escape(str(value))}</div><div class="kpi-s">{html.escape(sub)}</div></div>')


def how(text):
    st.markdown(f'<div class="how">{text}</div>', unsafe_allow_html=True)


@st.cache_data(show_spinner="Reading workbook...")
def read_workbook(file_bytes: bytes):
    return load_quotation(io.BytesIO(file_bytes))


# ------------------------------------------------------------------ sidebar
st.sidebar.title("Settings")
up = st.sidebar.file_uploader("Your comparison file (.xlsx)", type=["xlsx"])
if up is not None:
    raw = up.getvalue()
elif SAMPLE.exists():
    raw = SAMPLE.read_bytes()
    st.sidebar.caption("Showing the sample file. Upload your own above.")
else:
    st.info("Upload your comparative-statement workbook in the sidebar to begin.")
    st.stop()

try:
    q = read_workbook(raw)
except Exception as e:
    st.error(f"Could not read the workbook: {e}")
    st.stop()

all_vendors = list(q.vendors.vendor)
colors = charts.vendor_colors(all_vendors)

basis_key = st.sidebar.radio("How to compare prices", list(BASIS_LABELS), index=1, format_func=lambda k: BASIS_LABELS[k])
include = st.sidebar.multiselect("Vendors to include", all_vendors, default=all_vendors)
fx = st.sidebar.number_input("USD → INR rate", value=float(q.fx or 90.0), step=0.1, format="%.2f")

with st.sidebar.expander("How important is each factor?"):
    w = Weights(price=st.slider("Price", 0, 100, 50), delivery=st.slider("Delivery time", 0, 100, 15),
                payment=st.slider("Payment terms", 0, 100, 15), warranty=st.slider("Warranty", 0, 100, 10),
                technical=st.slider("Technical rating", 0, 100, 10))
    st.caption("Weights adjust automatically to add up to 100%. Technical counts only if every vendor has a rating.")

tech = None
with st.sidebar.expander("Technical ratings (optional)"):
    if st.checkbox("I want to enter technical ratings"):
        tech = {v: st.number_input(v, 0, 100, 70, key=f"tech_{v}") for v in include}

with st.sidebar.expander("Import cost assumptions"):
    st.caption("These are placeholders. Replace them with your logistics / customs numbers.")
    a = Assumptions(
        fx_usd_inr=fx,
        freight_insurance_pct=st.number_input("Sea freight + insurance (% of FOB)", 0.0, 30.0, 5.0, 0.5),
        import_duty_pct=st.number_input("Customs duty (%)", 0.0, 50.0, 8.25, 0.25),
        clearance_inland_pct=st.number_input("Port clearing + transport to site (%)", 0.0, 20.0, 2.5, 0.5),
        exworks_inland_pct=st.number_input("Transport for Ex-works quotes (%)", 0.0, 20.0, 2.0, 0.5),
        cost_of_capital_pct=st.number_input("Cost of money (% per year)", 0.0, 30.0, 10.0, 0.5),
        transit_months_import=st.number_input("Shipping time to site (months)", 0.0, 6.0, 1.5, 0.5))

with st.sidebar.expander("Claude AI key (optional)"):
    key = st.text_input("Anthropic API key", value=os.getenv("ANTHROPIC_API_KEY", ""), type="password",
                        help="Kept only for this session.")
    model = st.text_input("Model", value=ai_assistant.DEFAULT_MODEL)

if not include:
    st.warning("Pick at least one vendor in the sidebar.")
    st.stop()

try:
    res = run_analysis(q, a, w, basis_key, exclude=[v for v in all_vendors if v not in include], tech_ratings=tech)
except Exception as e:
    st.error(f"Analysis failed: {e}")
    st.stop()

st.sidebar.download_button("⬇ Download Excel report", data=build_excel_report(res, q.title),
                           file_name="Vendor_Comparison_Report.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ------------------------------------------------------------------ header
vt = res.vendor_table
full = vt[vt.full_scope]
st.title("Vendor Quotation Comparison")
st.caption(f"{q.title}   |   {q.rfq}   |   {len(include)} vendors, {len(res.items)} items")

# ---- decision banner
rec = vt.loc[res.recommended]
ranked = full.sort_values("basis_total")
reasons = []
if len(ranked):
    cheapest = ranked.index[0]
    if res.recommended == cheapest:
        reasons.append("Lowest total price among vendors who quoted every item")
    else:
        gap = (rec.basis_total / ranked.iloc[0].basis_total - 1) * 100
        reasons.append(f"Price is {gap:.1f}% above the cheapest full bid ({cheapest}), "
                       f"but it scores better on other factors")
if pd.notna(rec.delivery_to_site_m):
    reasons.append(f"Delivery to site in about {rec.delivery_to_site_m:.1f} months "
                   f"(fastest bid: {vt.delivery_to_site_m.min():.1f} months)")
if pd.notna(rec.advance_pct):
    reasons.append(f"{rec.advance_pct:.0f}% advance payment, "
                   f"{'covered by a bank guarantee' if rec.advance_secured else 'with no bank guarantee mentioned'}")
if pd.notna(rec.warranty_m):
    reasons.append(f"Warranty up to {rec.warranty_m:.0f} months")
st.markdown(
    f'<div class="hero"><div class="hero-k">Best overall vendor</div>'
    f'<div class="hero-v">{html.escape(res.recommended)}</div>'
    f'<div class="hero-s">Score {rec.weighted_score:.1f} / 100   |   Total {cr(rec.basis_total)}   |   '
    f'{html.escape(BASIS_LABELS[res.basis].split(" (")[0])}</div>'
    f'<ul>{"".join(f"<li>{html.escape(r)}</li>" for r in reasons)}</ul></div>', unsafe_allow_html=True)

split = res.scenarios[res.scenarios.scenario.str.contains("all active")]
nh = int((res.flags.severity == "High").sum())
c1, c2, c3, c4 = st.columns(4)
if len(ranked):
    c1.markdown(kpi("Cheapest full bid", cr(ranked.iloc[0].basis_total), ranked.index[0], "good"), unsafe_allow_html=True)
c2.markdown(kpi("Recommended vendor total", cr(rec.basis_total), res.recommended), unsafe_allow_html=True)
if len(split) and pd.notna(split.iloc[0].total) and len(full):
    sv = -split.iloc[0].vs_recommended_inr
    c3.markdown(kpi("Saving if order is split", cr(max(sv, 0)),
                    f"{max(-split.iloc[0].vs_recommended_pct, 0):.1f}% less, using {int(split.iloc[0].n_vendors)} vendors",
                    "warn"), unsafe_allow_html=True)
c4.markdown(kpi("Serious issues to check", nh, f"{len(res.flags)} warnings in total",
                "bad" if nh else "good"), unsafe_allow_html=True)
st.write("")

# ------------------------------------------------------------------ tabs
tabs = st.tabs(["Summary", "Item prices", "Vendors", "Award options", "Terms & risks", "Ask Claude"])

# ---- 1. Summary
with tabs[0]:
    l, r = st.columns(2)
    with l:
        st.markdown("### Who is cheapest?")
        how("Each bar is the full price for all items. Only vendors who quoted every item are shown.")
        st.plotly_chart(charts.total_cost_bar(res, colors))
    with r:
        st.markdown("### Who is best overall?")
        how("Score mixes price, delivery, payment terms and warranty. Longer bar = better.")
        st.plotly_chart(charts.score_stack(res))
    st.markdown("### Key findings")
    for line in build_conclusion(res):
        st.markdown(f"- {line}")

# ---- 2. Item prices
with tabs[1]:
    st.markdown("### Price of every item, vendor by vendor")
    how("Green = cheapest for that item. The % shows how much more a vendor charges than the cheapest one.")
    st.plotly_chart(charts.heatmap(res))
    st.markdown("### Look closer at one item")
    pick = st.selectbox("Choose an item", list(res.items.index), format_func=lambda i: res.items.loc[i, "label"],
                        label_visibility="collapsed")
    fig_item = charts.item_bar(res, pick, colors)
    if fig_item is None:
        st.info("None of the selected vendors quoted this item.")
    else:
        st.plotly_chart(fig_item)
    with st.expander("Show full price table (₹ lakh per unit)"):
        tbl = res.basis_rates[res.active].copy() / 1e5
        tbl.insert(0, "Qty", res.items.qty)
        tbl.insert(0, "Item", res.items.label)
        tbl["Cheapest vendor"] = res.item_table.set_index("item_no").l1_vendor
        tbl["Next cheapest is more by %"] = res.item_table.set_index("item_no").l2_gap_pct
        st.dataframe(tbl.style.highlight_min(subset=res.active, axis=1, color="#1f5d49")
                     .format({**{v: "{:,.2f}" for v in res.active}, "Next cheapest is more by %": "{:.1f}",
                              "Qty": "{:.0f}"}, na_rep="–"), hide_index=True)

# ---- 3. Vendors
with tabs[2]:
    st.markdown("### Vendor scorecard")
    how("Scores are out of 100 (higher is better). Vendors that quoted only some items are scored but not ranked.")
    show = vt[["origin", "coverage_pct", "basis_total", "premium_pct", "l1_wins", "price_score", "delivery_score",
               "payment_score", "warranty_score", "weighted_score", "rank"]].copy()
    show["basis_total"] = show.basis_total.map(cr)
    show.columns = ["Country", "Items quoted %", "Total price", "More than cheapest %", "Items won", "Price", "Delivery",
                    "Payment", "Warranty", "Overall", "Rank"]
    st.dataframe(show.style.format({"Items quoted %": "{:.0f}", "More than cheapest %": "{:.1f}", "Price": "{:.0f}",
                                    "Delivery": "{:.0f}", "Payment": "{:.0f}", "Warranty": "{:.0f}",
                                    "Overall": "{:.1f}", "Rank": "{:.0f}"}, na_rep="partial")
                 .background_gradient(subset=["Price", "Delivery", "Payment", "Warranty", "Overall"],
                                      cmap="Greens", vmin=30, vmax=110))
    for n in res.notes:
        st.warning(n)
    l, r = st.columns(2)
    with l:
        st.plotly_chart(charts.premium_bar(res, colors))
    with r:
        st.plotly_chart(charts.radar(res, colors))
    st.markdown("### Negotiation progress")
    how("Shows how much each vendor reduced its price round by round. Vendors with one point have not negotiated yet.")
    if len(res.negotiation):
        st.plotly_chart(charts.negotiation_line(res, colors))
        t = vt[["initial_total", "quoted_total", "neg_saving_inr", "neg_saving_pct"]].reset_index()
        t.columns = ["Vendor", "First offer", "Latest offer", "Reduced by", "Reduced by %"]
        for c in ("First offer", "Latest offer", "Reduced by"):
            t[c] = t[c].map(inr)
        t["Rounds"] = t.Vendor.map(q.quotes.groupby("vendor")["round"].max())
        st.dataframe(t.style.format({"Reduced by %": "{:.1f}"}), hide_index=True)

# ---- 4. Award options
with tabs[3]:
    st.markdown("### Ways to place the order")
    how("Compare giving everything to one vendor with giving each item to its cheapest vendor.")
    st.plotly_chart(charts.scenario_bar(res))
    s = res.scenarios.copy()
    s["total"] = s.total.map(inr)
    s["vs_recommended_inr"] = s.vs_recommended_inr.map(inr)
    s.columns = ["Option", "Vendor(s)", "No. of vendors", "Total", "Difference vs recommended", "Difference %"]
    st.dataframe(s.style.format({"Difference %": "{:+.1f}"}, na_rep="incomplete"), hide_index=True)
    if res.award is not None:
        l, r = st.columns([1, 1.4])
        with l:
            st.plotly_chart(charts.award_donut(res, colors))
        with r:
            st.markdown("**Who wins each item**")
            aw = res.award.copy()
            aw["unit_rate"], aw["amount"] = aw.unit_rate.map(inr), aw.amount.map(inr)
            aw.columns = ["#", "Item", "Qty", "Vendor", "Rate per unit", "Amount"]
            st.dataframe(aw.drop(columns="#"), hide_index=True)

# ---- 5. Terms & risks
with tabs[4]:
    st.markdown("### What could go wrong?")
    how("Red = fix before ordering. Amber = ask the vendor. Grey/blue = for your information.")
    counts = res.flags.severity.value_counts()
    labels = {"High": "Serious", "Medium": "Warning", "Low": "Minor", "Info": "Info"}
    sev = st.multiselect("Show", list(labels), default=["High", "Medium"],
                         format_func=lambda s: f"{labels[s]} ({counts.get(s, 0)})")
    for _, f in res.flags[res.flags.severity.isin(sev)].iterrows():
        st.markdown(f'<div class="flag" style="border-left-color:{SEV_COLOR[f.severity]}">'
                    f'<b>{html.escape(f.vendor)}</b> <small>{html.escape(f.category)}</small><br>'
                    f'{html.escape(f.message)}</div>', unsafe_allow_html=True)
    if res.audit is not None and (~res.audit.ok).any():
        st.markdown("### Errors in your original sheet's L1 column")
        how("Red rows are items where the sheet's 'lowest' price is not actually the lowest quote.")
        au = res.audit.copy()
        for c in ("sheet_l1_rate", "true_l1_rate", "overstated_by"):
            au[c] = au[c].map(inr)
        au = au.drop(columns="item_no")
        au.columns = ["Item", "Sheet says", "Sheet price", "Actually cheapest", "Actual price", "Sheet is higher by", "OK"]
        st.dataframe(au.style.apply(lambda r: ["background-color:#5a2a27" if not r["OK"] else "" for _ in r], axis=1),
                     hide_index=True)

    st.markdown("### Commercial terms side by side")
    how("Read from the text in your sheet. Open a vendor below to see the original wording.")
    tt = vt[["basis_class", "advance_pct", "advance_secured", "delivery_full_m", "delivery_to_site_m", "warranty_m",
             "supervision"]].copy()
    tt.columns = ["Price basis", "Advance %", "Bank guarantee on advance", "Delivery (months)", "Reaches site (months)",
                  "Warranty (months)", "Erection & commissioning"]
    st.dataframe(tt.style.format({"Advance %": "{:.0f}", "Delivery (months)": "{:.1f}", "Reaches site (months)": "{:.1f}",
                                  "Warranty (months)": "{:.0f}"}, na_rep="–"))
    for v in include:
        with st.expander(f"{v} - original wording"):
            r = vt.loc[v]
            st.markdown(f"**Price basis:** {r.price_basis_text or '–'}  \n**Payment:** {r.payment_text or '–'}  \n"
                        f"**Delivery:** {r.delivery_text or '–'}  \n**Warranty:** {r.warranty_text or '–'}  \n"
                        f"**Supervision:** {r.supervision_text or '–'}")

# ---- 6. Ask Claude
with tabs[5]:
    st.markdown("### Ask Claude about these results")
    how("Claude explains the numbers above in plain language. It does not calculate or invent any figures.")
    if not ai_assistant.available(key):
        st.info("To turn this on, open **Claude AI key** in the sidebar and paste your Anthropic API key. "
                "Everything else in the dashboard works without it.")
    else:
        facts = to_facts(res)
        if st.button("Write executive summary", type="primary"):
            with st.spinner("Claude is writing..."):
                try:
                    st.session_state["summary"] = ai_assistant.executive_summary(facts, key, model)
                except Exception as e:
                    st.error(f"Claude request failed: {e}")
        if st.session_state.get("summary"):
            with st.container(border=True):
                st.markdown(st.session_state["summary"])
        st.divider()
        hist = st.session_state.setdefault("chat", [])
        for m in hist:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])
        if prompt := st.chat_input("Ask e.g. 'Why not give everything to Beijing?' or 'What should we negotiate with ABB?'"):
            hist.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    try:
                        ans = ai_assistant.ask(prompt, facts, hist[:-1], key, model)
                    except Exception as e:
                        ans = f"Claude request failed: {e}"
                st.markdown(ans)
            hist.append({"role": "assistant", "content": ans})
