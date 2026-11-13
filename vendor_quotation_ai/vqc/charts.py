"""Plotly figures (dark theme)."""
from __future__ import annotations
import pandas as pd
import plotly.graph_objects as go

PALETTE = ["#4aa3ff", "#f0b429", "#3fcf9b", "#c18bff", "#ff7a6b", "#9fb1c4", "#5ad1e6", "#d4e157"]
CRITERIA_COLORS = {"price": "#4aa3ff", "delivery": "#5ad1e6", "payment": "#3fcf9b", "warranty": "#f0b429",
                   "technical": "#c18bff"}
TEXT, MUTED, GRID = "#e6edf5", "#8fa3b8", "#243247"


def vendor_colors(vendors) -> dict:
    return {v: PALETTE[i % len(PALETTE)] for i, v in enumerate(vendors)}


def _layout(fig, title, height=380, **kw):
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=TEXT), x=0.01), height=height,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color=TEXT, size=12),
        margin=dict(l=10, r=20, t=50, b=10), legend=dict(orientation="h", y=-0.18, font=dict(color=MUTED)), **kw)
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID)
    return fig


def total_cost_bar(res, colors):
    vt = res.vendor_table
    full = vt[vt.full_scope].sort_values("basis_total")
    fig = go.Figure(go.Bar(x=full.index, y=full.basis_total / 1e7, marker_color=[colors[v] for v in full.index],
                           text=[f"₹{x:,.2f} Cr" for x in full.basis_total / 1e7], textposition="outside",
                           cliponaxis=False))
    split = res.scenarios[res.scenarios.scenario.str.contains("all active")]
    if len(split) and pd.notna(split.iloc[0].total):
        y = split.iloc[0].total / 1e7
        fig.add_hline(y=y, line_dash="dash", line_color="#f0b429",
                      annotation_text=f"If each item goes to its cheapest vendor: ₹{y:,.2f} Cr",
                      annotation_font_color="#f0b429", annotation_position="top left")
    fig.update_yaxes(title="₹ crore", rangemode="tozero")
    fig.update_layout(showlegend=False)
    return _layout(fig, "Total cost per vendor", height=390)


def premium_bar(res, colors):
    vt = res.vendor_table.sort_values("premium_pct")
    fig = go.Figure(go.Bar(y=vt.index, x=vt.premium_pct, orientation="h", marker_color=[colors[v] for v in vt.index],
                           text=[f"+{x:.1f}%" if x > 0.05 else "lowest" for x in vt.premium_pct],
                           textposition="outside", cliponaxis=False))
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(title="% more expensive than the cheapest rate for the same items")
    return _layout(fig, "How much more each vendor charges", height=360)


def score_stack(res):
    vt = res.vendor_table.sort_values("weighted_score")
    fig = go.Figure()
    for k, w in res.weights_used.items():
        if w > 0:
            fig.add_bar(y=vt.index, x=vt[f"{k}_pts"], name=f"{k.title()} ({w:.0%})", orientation="h",
                        marker_color=CRITERIA_COLORS[k])
    for v, s in vt.weighted_score.items():
        fig.add_annotation(y=v, x=s, text=f"<b>{s:.1f}</b>", showarrow=False, xanchor="left", xshift=6,
                           font=dict(color=TEXT))
    fig.update_layout(barmode="stack")
    fig.update_xaxes(range=[0, 108], title="Overall score out of 100")
    return _layout(fig, "Overall score (price + delivery + payment + warranty)", height=390)


def radar(res, colors):
    cats = [k for k, w in res.weights_used.items() if w > 0]
    fig = go.Figure()
    for v, r in res.vendor_table.iterrows():
        vals = [float(r[f"{k}_score"]) for k in cats]
        fig.add_trace(go.Scatterpolar(r=vals + vals[:1], theta=[c.title() for c in cats] + [cats[0].title()],
                                      name=v, line_color=colors[v], opacity=0.9))
    fig.update_polars(bgcolor="rgba(0,0,0,0)", radialaxis=dict(range=[0, 100], gridcolor=GRID, linecolor=GRID,
                                                              tickfont=dict(color=MUTED)),
                      angularaxis=dict(gridcolor=GRID, linecolor=GRID))
    return _layout(fig, "Strengths and weaknesses (bigger = better)", height=360)


def heatmap(res):
    br, items = res.basis_rates[res.active], res.items
    l1 = res.item_table.set_index("item_no").l1_rate
    z = br.div(l1, axis=0).sub(1).mul(100)
    text = z.map(lambda x: "" if pd.isna(x) else ("CHEAPEST" if x < 0.05 else f"+{x:.0f}%"))
    fig = go.Figure(go.Heatmap(
        z=z.values, x=list(z.columns), y=[items.loc[i, "label"] for i in z.index],
        text=text.values, texttemplate="%{text}", textfont=dict(color="#ffffff", size=12), zmin=0, zmax=150,
        colorscale=[[0, "#1f7a5c"], [0.2, "#8a7a2b"], [0.6, "#a8553f"], [1, "#7a2b2b"]],
        colorbar=dict(title="% over<br>cheapest"), hoverongaps=False, xgap=3, ygap=3))
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(side="top")
    return _layout(fig, "", height=470)


def item_bar(res, item_no, colors):
    s = res.basis_rates.loc[item_no, res.active].dropna().sort_values()
    if s.empty:
        return None
    best = s.index[0]
    fig = go.Figure(go.Bar(x=s.index, y=s.values / 1e5, marker_color=[colors[v] for v in s.index],
                           marker_line_width=[3 if v == best else 0 for v in s.index], marker_line_color="#ffffff",
                           text=[f"₹{x/1e5:,.2f}L" for x in s.values], textposition="outside", cliponaxis=False))
    fig.update_yaxes(title="₹ lakh per unit", rangemode="tozero")
    fig.update_layout(showlegend=False)
    return _layout(fig, f"{res.items.loc[item_no, 'label']}  (white outline = cheapest)", height=340)


def negotiation_line(res, colors):
    n = res.negotiation
    fig = go.Figure()
    for v, g in n.groupby("vendor", sort=False):
        fig.add_trace(go.Scatter(x=g.label, y=g.total / 1e7, mode="lines+markers", name=v,
                                 line=dict(color=colors[v], width=3), marker_size=9))
    order = ["Initial"] + [f"Round {i}" for i in range(1, int(n["round"].max()) + 1)]
    fig.update_xaxes(categoryorder="array", categoryarray=order)
    fig.update_yaxes(title="₹ crore (as quoted)")
    return _layout(fig, "Price after each negotiation round", height=360)


def scenario_bar(res):
    s = res.scenarios.dropna(subset=["total"]).sort_values("total")
    fig = go.Figure(go.Bar(y=s.scenario, x=s.total / 1e7, orientation="h", marker_color="#4aa3ff",
                           text=[f"₹{t/1e7:,.2f} Cr  ({p:+.1f}%)" for t, p in zip(s.total, s.vs_recommended_pct)],
                           textposition="outside", cliponaxis=False))
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(title="₹ crore", rangemode="tozero", range=[0, s.total.max() / 1e7 * 1.35])
    return _layout(fig, "Ways to place the order (% = vs recommended vendor)", height=320)


def award_donut(res, colors):
    a = res.award
    if a is None:
        return None
    g = a.groupby("vendor").amount.sum()
    fig = go.Figure(go.Pie(labels=g.index, values=g.values, hole=0.58, marker_colors=[colors[v] for v in g.index],
                           textinfo="label+percent", marker_line_color="#0e1621", marker_line_width=3))
    fig.update_layout(showlegend=False)
    return _layout(fig, "Share of spend if each item goes to its cheapest vendor", height=340)
