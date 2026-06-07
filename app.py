"""
Treasury Intelligence Dashboard — Main entry point (compact laptop-friendly layout).

Run with:  streamlit run app.py
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.config import COMPANY
from src.data_loader import load_company_financials
from src.fred_client import FredClient
from src.treasury_metrics import build_credit_metrics, assess_all_metrics


# ============================================================================
# Page config
# ============================================================================
st.set_page_config(
    page_title="Treasury Intelligence Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Tight CSS — designed for 1366×768 laptop screens and up
st.markdown("""
<style>
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 1rem !important;
        padding-left: 1.5rem !important;
        padding-right: 1.5rem !important;
        max-width: 1400px !important;
    }
    header[data-testid="stHeader"] { height: 0 !important; background: transparent; }
    [data-testid="stToolbar"] { display: none; }

    [data-testid="stMetricValue"] {
        font-size: 1.25rem !important; font-weight: 700;
        color: #FAFAFA; line-height: 1.2;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.65rem !important; color: #9CA3AF;
        text-transform: uppercase; letter-spacing: 0.04em; line-height: 1.1;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    [data-testid="stMetricDelta"] { font-size: 0.7rem !important; }

    .stCaption, [data-testid="stCaptionContainer"] {
        font-size: 0.72rem !important; line-height: 1.2;
    }

    .section-header {
        font-size: 0.85rem; font-weight: 600; color: #FAFAFA;
        margin-top: 0.75rem; margin-bottom: 0.5rem;
        padding-bottom: 0.2rem; border-bottom: 1px solid #374151;
        text-transform: uppercase; letter-spacing: 0.05em;
    }

    .dashboard-header {
        background: linear-gradient(135deg, #1F2937 0%, #111827 100%);
        padding: 0.75rem 1rem; border-radius: 6px;
        border: 1px solid #374151; margin-bottom: 0.75rem;
    }
    .dashboard-title {
        font-size: 1.15rem; font-weight: 700; color: #FAFAFA;
        margin: 0; line-height: 1.2;
    }
    .dashboard-subtitle {
        font-size: 0.75rem; color: #9CA3AF; margin-top: 0.15rem;
    }

    .key-message {
        background: rgba(245, 158, 11, 0.1);
        border-left: 3px solid #F59E0B;
        padding: 0.5rem 0.75rem; border-radius: 4px; margin: 0.5rem 0;
        color: #FCD34D; font-size: 0.78rem; line-height: 1.4;
    }
    .key-message.positive {
        background: rgba(16, 185, 129, 0.1);
        border-left-color: #10B981; color: #6EE7B7;
    }

    [data-testid="stSidebar"] .stCaption { font-size: 0.7rem !important; }
    [data-testid="stDataFrame"] { font-size: 0.78rem; }
    hr { margin: 0.5rem 0 !important; }

    /* Hide the default "app" entry in sidebar navigation - the dashboard banner serves as home */
    [data-testid="stSidebarNav"] ul li:first-child a span {
        visibility: hidden;
        position: relative;
    }
    [data-testid="stSidebarNav"] ul li:first-child a span:before {
        content: "🏠 Overview";
        visibility: visible;
        position: absolute;
        left: 0;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================================
# Data loading (cached)
# ============================================================================
@st.cache_data(ttl=3600, show_spinner="Loading financial data...")
def get_financials():
    return load_company_financials(company_name=COMPANY["name"], cik=COMPANY["cik"])


@st.cache_data(ttl=3600, show_spinner="Loading FRED data...")
def get_macro_data():
    fred = FredClient()
    rates = fred.rates_bundle(start="2024-01-01")
    spreads = fred.credit_spreads_bundle(start="2024-01-01")
    fx = fred.fx_bundle(start="2024-01-01")
    return rates, spreads, fx


# ============================================================================
# Sidebar
# ============================================================================
with st.sidebar:
    st.markdown("### 🏛️ Treasury Intel")
    st.caption(f"**{COMPANY['name']}**")
    st.caption(f"{COMPANY['ticker']} | CIK {COMPANY['cik']}")
    st.divider()

    audience = st.radio(
        "View For",
        ["C-Level", "Board", "Lenders", "Rating Agencies"],
        index=0,
    )

    st.divider()
    st.caption("**Profile**")
    st.caption(f"Industry: {COMPANY['industry']}")
    st.caption(f"Current: **{COMPANY['current_sp_rating']}** ({COMPANY['current_outlook']})")
    st.caption(f"Target: {COMPANY['target_rating']}")

    st.divider()
    from src.ai_narrator import is_ai_enabled as _ai_check
    if _ai_check():
        st.caption("🤖 **AI narratives: ON** (Claude)")
    else:
        st.caption("📝 AI narratives: off — using fallback templates. Add ANTHROPIC_API_KEY to .env to enable.")


# ============================================================================
# Load data
# ============================================================================
try:
    fin = get_financials()
    rates, spreads, fx = get_macro_data()
except Exception as e:
    st.error(f"Failed to load data: {e}")
    st.stop()


metrics = build_credit_metrics(
    snapshot={
        "cash_and_equivalents": {"value": fin.cash, "end_date": fin.as_of_date, "source_tag": ""},
        "short_term_investments": None,
        "restricted_cash": {"value": fin.restricted_cash, "end_date": fin.as_of_date, "source_tag": ""},
        "long_term_debt": {"value": fin.long_term_debt, "end_date": fin.as_of_date, "source_tag": ""},
        "current_portion_lt_debt": {"value": fin.current_portion_lt_debt, "end_date": fin.as_of_date, "source_tag": ""},
        "short_term_borrowings": None,
    },
    ltm_ebitda=fin.ltm_ebitda,
    ltm_ffo=fin.ltm_ffo,
    ltm_interest=fin.ltm_interest_expense,
    ltm_fcf=fin.ltm_fcf,
    revolver_availability=2.5e9,
    operating_lease_expense=fin.operating_lease_liability * 0.1,
    debt_maturities_12m=fin.current_portion_lt_debt,
    capex_12m=fin.ltm_capex,
)
assessments = assess_all_metrics(metrics)

st.session_state["financials"] = fin
st.session_state["metrics"] = metrics
st.session_state["assessments"] = assessments
st.session_state["rates"] = rates
st.session_state["spreads"] = spreads
st.session_state["fx"] = fx
st.session_state["audience"] = audience


# ============================================================================
# Header banner
# ============================================================================
as_of_str = fin.as_of_date.strftime('%B %d, %Y') if fin.as_of_date else 'N/A'
st.markdown(f"""
<div class="dashboard-header">
    <div class="dashboard-title">🏛️ TREASURY INTELLIGENCE DASHBOARD</div>
    <div class="dashboard-subtitle">Executive Treasury & Capital Overview • {COMPANY['name']} • As of {as_of_str}</div>
</div>
""", unsafe_allow_html=True)


# ============================================================================
# Key Message (AI-generated, with deterministic fallback)
# ============================================================================
from src.ai_narrator import generate_key_message, is_ai_enabled

composite_rating = assessments["_composite"]["implied_rating"]
current_rating = COMPANY["current_sp_rating"]

@st.cache_data(ttl=600, show_spinner=False)
def _cached_key_message(audience, current, target, implied, leverage, ffo_pct, fcc, liq_cov, cash, debt, near_mat, ebitda):
    """Cached wrapper so we don't re-call the API on every re-render."""
    return generate_key_message(
        company_name=COMPANY["name"],
        audience=audience,
        current_rating=current,
        target_rating=target,
        implied_rating=implied,
        net_debt_ebitda=leverage,
        ffo_debt_pct=ffo_pct,
        fixed_charge_coverage=fcc,
        liquidity_coverage_ratio=liq_cov,
        cash=cash,
        total_debt=debt,
        near_term_maturities=near_mat,
        ltm_ebitda=ebitda,
    )

msg = _cached_key_message(
    audience, current_rating, COMPANY["target_rating"], composite_rating,
    metrics.net_debt_ebitda, metrics.ffo_debt_pct, metrics.fixed_charge_coverage,
    metrics.liquidity_coverage_ratio, fin.cash, fin.total_debt,
    fin.current_portion_lt_debt + fin.total_debt * 0.10,  # rough 24m maturity estimate
    fin.ltm_ebitda,
)

rating_order = ["AAA", "AA", "A", "BBB", "BB", "B", "CCC"]
banner_class = "positive" if rating_order.index(composite_rating) <= rating_order.index(current_rating.rstrip("+-")) else ""

ai_badge = "🤖" if is_ai_enabled() else "📝"
st.markdown(f'<div class="key-message {banner_class}">{ai_badge} <b>KEY MESSAGE:</b> {msg}</div>', unsafe_allow_html=True)


# ============================================================================
# KPI Tiles
# ============================================================================
st.markdown('<div class="section-header">Executive Summary</div>', unsafe_allow_html=True)

c1, c2, c3, c4, c5, c6 = st.columns(6)
with c1:
    st.metric("Unrestricted Cash", f"${fin.cash/1e6:,.0f}M")
    st.caption(f"Restricted: ${fin.restricted_cash/1e6:,.0f}M")
with c2:
    st.metric("Total Liquidity", f"${(fin.cash + 2.5e9)/1e9:,.2f}B")
    st.caption("Cash + revolver")
with c3:
    st.metric("Liq. Coverage", f"{metrics.liquidity_coverage_ratio:.2f}x",
              delta=f"{(metrics.liquidity_coverage_ratio - 1.25):+.2f}x")
    st.caption("Target > 1.25x")
with c4:
    st.metric("Net Debt/EBITDA", f"{metrics.net_debt_ebitda:.2f}x",
              delta=f"{(4.5 - metrics.net_debt_ebitda):+.2f}x", delta_color="inverse")
    st.caption("Target < 4.5x")
with c5:
    st.metric("FFO / Debt", f"{metrics.ffo_debt_pct:.1f}%",
              delta=f"{(metrics.ffo_debt_pct - 20):+.1f}pp")
    st.caption("Target > 20%")
with c6:
    st.metric("S&P Rating", current_rating,
              delta=f"Implied: {composite_rating}", delta_color="off")
    st.caption(f"{COMPANY['current_outlook']}")


# ============================================================================
# Financial position
# ============================================================================
st.markdown('<div class="section-header">Financial Position (LTM)</div>', unsafe_allow_html=True)

left, right = st.columns(2)

with left:
    st.caption("**Income Statement (LTM)**")
    pl_data = pd.DataFrame({
        "Metric": ["Revenue", "Op. Income", "D&A", "EBITDA", "Interest", "Net Income", "FFO"],
        "$M": [
            f"{fin.ltm_revenue/1e6:,.0f}",
            f"{fin.ltm_operating_income/1e6:,.0f}",
            f"{fin.ltm_da/1e6:,.0f}",
            f"{fin.ltm_ebitda/1e6:,.0f}",
            f"{fin.ltm_interest_expense/1e6:,.0f}",
            f"{fin.ltm_net_income/1e6:,.0f}",
            f"{fin.ltm_ffo/1e6:,.0f}",
        ],
    })
    st.dataframe(pl_data, hide_index=True, use_container_width=True, height=280)

with right:
    st.caption("**Capital Structure**")
    cs_data = pd.DataFrame({
        "Item": ["Cash", "Total Debt", "  Long-term", "  Current", "Net Debt", "Op. Leases", "Total Assets", "Equity"],
        "$M": [
            f"{fin.cash/1e6:,.0f}",
            f"{fin.total_debt/1e6:,.0f}",
            f"{fin.long_term_debt/1e6:,.0f}",
            f"{fin.current_portion_lt_debt/1e6:,.0f}",
            f"{metrics.net_debt/1e6:,.0f}",
            f"{fin.operating_lease_liability/1e6:,.0f}",
            f"{fin.total_assets/1e6:,.0f}",
            f"{fin.stockholders_equity/1e6:,.0f}",
        ],
    })
    st.dataframe(cs_data, hide_index=True, use_container_width=True, height=310)


st.caption(
    f"📊 SEC EDGAR + FRED | Filing: {fin.as_of_date.strftime('%Y-%m-%d') if fin.as_of_date else 'N/A'} | "
    f"Use sidebar pages for detail • Informational only"
)
