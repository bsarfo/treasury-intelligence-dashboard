"""Capital Structure — debt stack, maturity wall, rate composition."""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.layout import inject_compact_css
from src.risk_engine import build_debt_maturity_wall, near_term_maturity_risk

st.set_page_config(page_title="Capital Structure", page_icon="🏗️", layout="wide")
inject_compact_css()

if "financials" not in st.session_state:
    st.warning("⚠️ Please open the main dashboard first to load data.")
    st.stop()

fin = st.session_state["financials"]
metrics = st.session_state["metrics"]

st.title("🏗️ Capital Structure & Debt Profile")
st.caption(f"As of {fin.as_of_date.strftime('%B %d, %Y')}")

# KPI row
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Debt", f"${fin.total_debt/1e9:,.2f}B")
c2.metric("Net Debt", f"${metrics.net_debt/1e9:,.2f}B")
c3.metric("Net Debt/EBITDA", f"{metrics.net_debt_ebitda:.2f}x")
c4.metric("LTM Interest", f"${fin.ltm_interest_expense/1e6:,.0f}M")

st.markdown("---")

# Two-column layout: maturity wall (left) + rate composition (right)
left, right = st.columns([2, 1])

with left:
    st.subheader("Debt Maturity Wall")
    st.caption("Representative schedule — refine from 10-K Note on Debt")

    total_debt = fin.total_debt
    instruments = [
        {"principal": min(total_debt * 0.06, fin.current_portion_lt_debt), "maturity_date": "2026-12-01", "rate": 0.0775, "instrument_name": "Near-term"},
        {"principal": total_debt * 0.10, "maturity_date": "2027-08-01", "rate": 0.063, "instrument_name": "2027"},
        {"principal": total_debt * 0.12, "maturity_date": "2028-06-30", "rate": 0.069, "instrument_name": "2028"},
        {"principal": total_debt * 0.18, "maturity_date": "2029-12-31", "rate": 0.0725, "instrument_name": "2029"},
        {"principal": total_debt * 0.20, "maturity_date": "2031-05-01", "rate": 0.0625, "instrument_name": "2031"},
        {"principal": total_debt * 0.20, "maturity_date": "2033-02-01", "rate": 0.0575, "instrument_name": "2033"},
        {"principal": total_debt * 0.14, "maturity_date": "2035-01-15", "rate": 0.055, "instrument_name": "2035"},
    ]

    wall = build_debt_maturity_wall(instruments, as_of=date.today())
    wall["principal_b"] = wall["principal"] / 1e9

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=wall["bucket"].astype(str),
        y=wall["principal_b"],
        text=[f"${v:.1f}B" for v in wall["principal_b"]],
        textposition="outside",
        marker_color="#3B82F6",
    ))
    fig.update_layout(
        template="plotly_dark",
        plot_bgcolor="#0E1117", paper_bgcolor="#0E1117",
        height=300,
        margin=dict(l=10, r=10, t=20, b=20),
        yaxis_title="$B",
        xaxis_title=None,
        showlegend=False,
        font=dict(size=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    near = near_term_maturity_risk(instruments, within_months=24)
    st.info(f"📅 **Refi wall (24m):** ${near['total_maturing']/1e9:,.2f}B across {near['instrument_count']} issues")

with right:
    st.subheader("Rate Mix")

    fixed_pct = 0.62
    variable_pct = 0.38

    fig2 = go.Figure(data=[go.Pie(
        labels=["Fixed", "Variable"],
        values=[fixed_pct * fin.total_debt / 1e9, variable_pct * fin.total_debt / 1e9],
        hole=0.55,
        marker=dict(colors=["#3B82F6", "#F59E0B"]),
        textinfo="label+percent",
    )])
    fig2.update_layout(
        template="plotly_dark",
        plot_bgcolor="#0E1117", paper_bgcolor="#0E1117",
        height=240,
        margin=dict(l=10, r=10, t=20, b=20),
        annotations=[dict(text=f"${fin.total_debt/1e9:.1f}B", x=0.5, y=0.5,
                          font_size=14, showarrow=False, font_color="#FAFAFA")],
        showlegend=False,
        font=dict(size=10),
    )
    st.plotly_chart(fig2, use_container_width=True)

    weighted_rate = fin.ltm_interest_expense / fin.total_debt * 100 if fin.total_debt else 0
    st.metric("Wtd Avg Rate", f"{weighted_rate:.2f}%")
