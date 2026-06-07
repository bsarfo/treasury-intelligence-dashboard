"""Risk Dashboard — Interest Rate VaR, FX exposure, scenario stress tests."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.layout import inject_compact_css
from src.risk_engine import compute_interest_rate_var, compute_fx_exposure

st.set_page_config(page_title="Risk Dashboard", page_icon="⚠️", layout="wide")
inject_compact_css()

if "financials" not in st.session_state:
    st.warning("⚠️ Please open the main dashboard first to load data.")
    st.stop()

fin = st.session_state["financials"]
metrics = st.session_state["metrics"]
rates = st.session_state["rates"]
fx = st.session_state["fx"]

st.title("⚠️ Risk Dashboard")
st.caption("Interest rate, FX, and capital risk")

# ---- Interest Rate Risk ----
st.subheader("Interest Rate Risk")

fixed_pct = 0.62
variable_pct = 0.38
variable_debt = fin.total_debt * variable_pct
fixed_debt = fin.total_debt * fixed_pct
weighted_rate = fin.ltm_interest_expense / fin.total_debt if fin.total_debt else 0

sofr_series = rates.get("SOFR", pd.Series(dtype=float)).dropna()
if not sofr_series.empty:
    var = compute_interest_rate_var(
        variable_rate_debt=variable_debt,
        fixed_rate_debt=fixed_debt,
        weighted_avg_rate=weighted_rate,
        sofr_history=sofr_series,
        confidence_level=0.95,
        horizon_days=252,
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Variable Debt", f"${variable_debt/1e9:.2f}B", f"{variable_pct*100:.0f}%")
    c2.metric("Annual SOFR Vol", f"{var.rate_volatility_annual:.0f} bps")
    c3.metric("95% Move (1Y)", f"+{var.var_rate_bps:.0f} bps")
    c4.metric("Annual $ VaR", f"${var.var_dollar_annual/1e6:,.0f}M")

    with st.expander("📊 Interest Expense Sensitivity Table"):
        sensitivity = pd.DataFrame({
            "Rate Move": ["-100", "-50", "Base", "+50", "+100", "+200"],
            "$ Impact": [
                f"${(-100/10000 * variable_debt)/1e6:+,.0f}M",
                f"${(-50/10000 * variable_debt)/1e6:+,.0f}M",
                "$0M",
                f"${(50/10000 * variable_debt)/1e6:+,.0f}M",
                f"${(100/10000 * variable_debt)/1e6:+,.0f}M",
                f"${(200/10000 * variable_debt)/1e6:+,.0f}M",
            ],
        })
        st.dataframe(sensitivity, hide_index=True, use_container_width=True, height=240)

st.markdown("---")

# ---- FX Risk ----
st.subheader("FX Risk Exposure")

fx_exposures = {"EUR": 950e6, "GBP": 620e6, "AUD": 180e6, "CAD": 90e6}

if not fx.empty:
    fx_df = compute_fx_exposure(fx_exposures, fx, confidence_level=0.95, horizon_days=10)

    left, right = st.columns([1, 1])
    with left:
        total = fx_df["notional_usd"].sum()
        fig = go.Figure(data=[go.Pie(
            labels=fx_df["currency"],
            values=fx_df["notional_usd"] / 1e6,
            hole=0.55,
            marker=dict(colors=["#3B82F6", "#10B981", "#F59E0B", "#EF4444"]),
            textinfo="label+percent",
        )])
        fig.update_layout(
            template="plotly_dark",
            plot_bgcolor="#0E1117", paper_bgcolor="#0E1117",
            height=240,
            margin=dict(l=10, r=10, t=10, b=10),
            annotations=[dict(text=f"${total/1e6:,.0f}M", x=0.5, y=0.5,
                              font_size=14, showarrow=False, font_color="#FAFAFA")],
            showlegend=False,
            font=dict(size=10),
        )
        st.plotly_chart(fig, use_container_width=True)

    with right:
        display = fx_df.copy()
        display["Notional ($M)"] = (display["notional_usd"] / 1e6).round(0)
        display["%"] = display["pct_of_total"].round(1)
        display["Vol %"] = display["fx_volatility_annual"].round(1)
        display["10d VaR $M"] = (display["var_95_10day_usd"] / 1e6).round(1)
        display = display[["currency", "Notional ($M)", "%", "Vol %", "10d VaR $M"]]
        display = display.rename(columns={"currency": "CCY"})
        st.dataframe(display, hide_index=True, use_container_width=True, height=200)
        total_var = fx_df["var_95_10day_usd"].sum()
        st.metric("Aggregate 10d VaR", f"${total_var/1e6:.1f}M")

st.markdown("---")

# ---- AI Risk Commentary ----
from src.ai_narrator import generate_risk_commentary, is_ai_enabled as _ai_check

@st.cache_data(ttl=600, show_spinner=False)
def _cached_risk_commentary(var_debt, sofr_vol, annual_var, dom_ccy, dom_pct, fx_var, near_mat):
    return generate_risk_commentary(
        variable_debt=var_debt,
        annual_sofr_vol_bps=sofr_vol,
        annual_var_usd=annual_var,
        dominant_fx_currency=dom_ccy,
        dominant_fx_pct=dom_pct,
        aggregate_fx_var=fx_var,
        near_term_maturities=near_mat,
    )

if not sofr_series.empty and not fx.empty:
    # Find dominant FX exposure
    dominant_row = fx_df.iloc[fx_df["notional_usd"].idxmax()]
    dom_ccy = dominant_row["currency"]
    dom_pct = dominant_row["pct_of_total"]

    commentary = _cached_risk_commentary(
        variable_debt, var.rate_volatility_annual, var.var_dollar_annual,
        dom_ccy, dom_pct, fx_df["var_95_10day_usd"].sum(),
        fin.current_portion_lt_debt + fin.total_debt * 0.10,
    )

    ai_badge = "🤖" if _ai_check() else "📝"
    st.markdown(
        f'<div style="background: rgba(59, 130, 246, 0.1); border-left: 3px solid #3B82F6; '
        f'padding: 0.6rem 0.9rem; border-radius: 4px; margin: 0.5rem 0; color: #93C5FD; '
        f'font-size: 0.82rem; line-height: 1.45;">{ai_badge} <b>RISK READ-OUT:</b> {commentary}</div>',
        unsafe_allow_html=True,
    )

st.markdown("---")

# ---- Scenario Stress Tests ----
st.subheader("Scenario Stress Tests")
st.caption("Adjust the levers to see impact on credit metrics")

c1, c2, c3 = st.columns(3)
with c1:
    rate_shock = st.slider("SOFR change (bps)", -200, 300, 0, 25)
with c2:
    rev_shock = st.slider("Revenue change (%)", -25, 15, 0, 5)
with c3:
    fx_shock = st.slider("USD strength (%)", -10, 15, 0, 1)

new_interest = fin.ltm_interest_expense + (rate_shock / 10000) * variable_debt
new_ebitda = fin.ltm_ebitda * (1 + rev_shock / 100)
new_ffo = fin.ltm_ffo * (1 + rev_shock / 100) - (rate_shock / 10000) * variable_debt * 0.8

new_leverage = metrics.net_debt / new_ebitda if new_ebitda > 0 else float("inf")
new_ffo_debt = (new_ffo / fin.total_debt * 100) if fin.total_debt > 0 else 0
new_fcc = new_ebitda / (new_interest + fin.operating_lease_liability * 0.1) if new_interest > 0 else float("inf")

c1, c2, c3 = st.columns(3)
c1.metric("Net Debt/EBITDA", f"{new_leverage:.2f}x",
          delta=f"{(new_leverage - metrics.net_debt_ebitda):+.2f}x", delta_color="inverse")
c2.metric("FFO/Debt", f"{new_ffo_debt:.1f}%",
          delta=f"{(new_ffo_debt - metrics.ffo_debt_pct):+.1f}pp")
c3.metric("Fixed Charge Coverage", f"{new_fcc:.2f}x",
          delta=f"{(new_fcc - metrics.fixed_charge_coverage):+.2f}x")

if new_leverage > 4.5 or new_ffo_debt < 12:
    st.warning("⚠️ Scenario implies downgrade pressure")
elif new_leverage < 3.0 and new_ffo_debt > 25:
    st.success("✓ Scenario supports upgrade to BBB-")
