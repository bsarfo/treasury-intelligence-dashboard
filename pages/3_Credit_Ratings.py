"""Credit Ratings — S&P methodology and migration scenarios."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.config import COMPANY
from src.layout import inject_compact_css

st.set_page_config(page_title="Credit Ratings", page_icon="⭐", layout="wide")
inject_compact_css()

if "financials" not in st.session_state:
    st.warning("⚠️ Please open the main dashboard first to load data.")
    st.stop()

fin = st.session_state["financials"]
metrics = st.session_state["metrics"]
assessments = st.session_state["assessments"]

st.title("⭐ Credit Ratings & S&P Methodology")

# Rating summary row
c1, c2, c3 = st.columns(3)
c1.metric("Current S&P", COMPANY["current_sp_rating"], COMPANY["current_outlook"])
c2.metric("Implied by Metrics", assessments["_composite"]["implied_rating"])
c3.metric("Target", COMPANY["target_rating"], "Investment Grade")

st.markdown("---")

# Metric assessment table
st.subheader("S&P Methodology: Key Rating Factors")

metric_labels = {
    "net_debt_ebitda": ("Net Debt / EBITDA", "x", "lower"),
    "ffo_debt": ("FFO / Debt", "%", "higher"),
    "fixed_charge_coverage": ("Fixed Charge Coverage", "x", "higher"),
}

rows = []
for key, (label, unit, direction) in metric_labels.items():
    a = assessments[key]
    bbb_low, bbb_high = a["thresholds"]["BBB"]
    rows.append({
        "Metric": label,
        "Current": f"{a['value']:.2f}{unit}",
        "BBB Threshold": f"{bbb_low}-{bbb_high}" if direction == "lower" else f"≥{bbb_low}",
        "Implied Rating": a["implied_rating"],
        "Direction": "↓ Better" if direction == "lower" else "↑ Better",
    })

st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, height=160)

# Rating ladder visualization
st.subheader("Where Each Metric Sits on the Rating Ladder")

rating_order = ["CCC", "B", "BB", "BBB", "A", "AA", "AAA"]
position_map = {r: i for i, r in enumerate(rating_order)}

bar_data = []
for key, (label, _, _) in metric_labels.items():
    implied = assessments[key]["implied_rating"]
    bar_data.append({"Metric": label, "Position": position_map.get(implied, 0), "Implied": implied})
bar_df = pd.DataFrame(bar_data)

colors = ["#10B981" if r in ("BBB", "A", "AA", "AAA") else "#F59E0B" if r == "BB" else "#EF4444"
          for r in bar_df["Implied"]]

fig = go.Figure()
fig.add_trace(go.Bar(
    y=bar_df["Metric"],
    x=bar_df["Position"],
    orientation="h",
    text=bar_df["Implied"],
    textposition="outside",
    marker_color=colors,
))
fig.update_layout(
    template="plotly_dark",
    plot_bgcolor="#0E1117", paper_bgcolor="#0E1117",
    height=200,
    margin=dict(l=10, r=10, t=10, b=20),
    xaxis=dict(
        tickmode="array",
        tickvals=list(range(len(rating_order))),
        ticktext=rating_order,
    ),
    yaxis_title=None,
    showlegend=False,
    font=dict(size=10),
)
fig.add_vline(x=position_map["BBB"], line_dash="dash", line_color="#10B981",
              annotation_text="IG", annotation_position="top")
st.plotly_chart(fig, use_container_width=True)

# Actions and migration in collapsible
with st.expander("📈 Path to Upgrade — Actions & Migration Scenario", expanded=True):
    from src.ai_narrator import generate_actions, is_ai_enabled

    @st.cache_data(ttl=600, show_spinner=False)
    def _cached_actions(leverage, ffo, fcc, debt, ebitda, near_mat, cash, wtd_rate):
        return generate_actions(
            company_name=COMPANY["name"],
            current_rating=COMPANY["current_sp_rating"],
            target_rating=COMPANY["target_rating"],
            net_debt_ebitda=leverage,
            ffo_debt_pct=ffo,
            fixed_charge_coverage=fcc,
            total_debt=debt,
            ltm_ebitda=ebitda,
            near_term_maturities=near_mat,
            cash=cash,
            weighted_avg_rate=wtd_rate,
        )

    wtd_rate = fin.ltm_interest_expense / fin.total_debt if fin.total_debt else 0.07
    actions_data = _cached_actions(
        metrics.net_debt_ebitda, metrics.ffo_debt_pct, metrics.fixed_charge_coverage,
        fin.total_debt, fin.ltm_ebitda,
        fin.current_portion_lt_debt + fin.total_debt * 0.10,
        fin.cash, wtd_rate,
    )

    ai_badge = "🤖 AI-generated" if is_ai_enabled() else "📝 Template-based"
    st.caption(f"{ai_badge} — recalculated from live metrics")

    # Render as a DataFrame
    actions_df = pd.DataFrame([
        {"Action": a.get("action", ""), "Expected Impact": a.get("impact", ""), "Priority": a.get("priority", "Medium")}
        for a in actions_data
    ])
    st.dataframe(actions_df, hide_index=True, use_container_width=True, height=240)

    st.markdown("**Rating Migration Scenario**")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.caption("**CURRENT**")
        st.markdown(f"### {COMPANY['current_sp_rating']}")
        st.caption(f"{COMPANY['current_outlook']} outlook")
    with c2:
        st.caption("**NEXT 12-24M**")
        st.markdown("### BBB- / Baa3")
        st.caption("Positive outlook — IG threshold")
    with c3:
        st.caption("**TARGET**")
        st.markdown(f"### {COMPANY['target_rating']}")
        st.caption("Investment Grade")
    st.caption("Catalysts: Leverage < 3.5x sustained • FFO/Debt > 25% • Lower refi risk")
