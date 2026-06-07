"""Liquidity & Cash Position — compact view."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.layout import inject_compact_css
from src.liquidity_forecast import build_seasonal_index, forecast_13_weeks

st.set_page_config(page_title="Liquidity", page_icon="💧", layout="wide")
inject_compact_css()

if "financials" not in st.session_state:
    st.warning("⚠️ Please open the main dashboard first to load data.")
    st.stop()

fin = st.session_state["financials"]
metrics = st.session_state["metrics"]

st.title("💧 Liquidity & Cash Position")
st.caption(f"As of {fin.as_of_date.strftime('%B %d, %Y')}")

# KPI row — 4 tight tiles
c1, c2, c3, c4 = st.columns(4)
c1.metric("Unrestricted Cash", f"${fin.cash/1e6:,.0f}M")
c2.metric("Restricted Cash", f"${fin.restricted_cash/1e6:,.0f}M")
c3.metric("Customer Deposits", f"${fin.deferred_revenue/1e6:,.0f}M")
c4.metric("LTM Operating Cash Flow", f"${fin.ltm_cfo/1e6:,.0f}M",
          help="Cash generated from operations before investing & financing")

st.markdown("---")

# 13-week forecast
st.subheader("13-Week Liquidity Forecast")

col_left, col_right = st.columns([3, 1])

with col_right:
    st.caption("**Assumptions**")
    starting_cash = st.number_input(
        "Starting cash ($M)",
        value=float(fin.cash / 1e6),
        step=50.0,
    ) * 1e6
    annual_inflow = st.number_input(
        "12m inflows ($B)",
        value=float(max(fin.ltm_revenue, 20e9) / 1e9),
        step=0.5,
    ) * 1e9
    annual_outflow = st.number_input(
        "12m outflows ($B)",
        value=float(max(fin.ltm_revenue - fin.ltm_fcf, 18e9) / 1e9),
        step=0.5,
    ) * 1e9
    min_threshold = st.number_input(
        "Min cash ($M)",
        value=1000.0,
        step=100.0,
    ) * 1e6

# Build seasonal index (synthetic for now — wave-season pattern)
dates = pd.date_range("2023-02-28", "2025-11-30", freq="QE-NOV")
pattern = [2.0e9, 1.8e9, 1.5e9, 0.8e9]
cfo_synth = pd.Series([pattern[i % 4] for i in range(len(dates))], index=dates)
seasonal = build_seasonal_index(cfo_synth)

forecast = forecast_13_weeks(
    starting_cash=starting_cash,
    annual_cash_inflow=annual_inflow,
    annual_cash_outflow=annual_outflow,
    seasonal_index=seasonal,
    minimum_threshold=min_threshold,
)

with col_left:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=forecast["week_ending"], y=forecast["ending_cash"] / 1e6,
        mode="lines+markers", name="Cash",
        line=dict(color="#10B981", width=2.5),
        marker=dict(size=5),
    ))
    fig.add_hline(
        y=min_threshold / 1e6, line_dash="dash", line_color="#F87171",
        annotation_text="Min", annotation_position="top right",
    )
    fig.update_layout(
        template="plotly_dark",
        plot_bgcolor="#0E1117", paper_bgcolor="#0E1117",
        height=300,
        margin=dict(l=10, r=10, t=20, b=20),
        yaxis_title="Cash ($M)",
        xaxis_title=None,
        showlegend=False,
        font=dict(size=10),
    )
    st.plotly_chart(fig, use_container_width=True)

# Summary message right under the chart
weeks_below = forecast["below_threshold"].sum()
if weeks_below > 0:
    st.warning(f"⚠️ Cash dips below minimum in **{weeks_below}** week(s). "
               f"Min: \\${forecast['ending_cash'].min()/1e6:,.0f}M")
else:
    st.success(f"✓ Cash holds above \\${min_threshold/1e6:,.0f}M for all 13 weeks. "
               f"Min: \\${forecast['ending_cash'].min()/1e6:,.0f}M")

# Week-by-week table — collapsible to save space
with st.expander("📋 Week-by-week detail", expanded=False):
    display = forecast.copy()
    display["week_ending"] = display["week_ending"].dt.strftime("%Y-%m-%d")
    for col in ["starting_cash", "cash_inflow", "cash_outflow", "ending_cash"]:
        display[col] = (display[col] / 1e6).round(1)
    display = display.rename(columns={
        "week_ending": "Week", "week_number": "#",
        "iso_week_of_year": "ISO", "starting_cash": "Start",
        "cash_inflow": "In", "cash_outflow": "Out",
        "ending_cash": "End", "below_threshold": "Alert",
    })
    st.dataframe(display, hide_index=True, use_container_width=True, height=280)
