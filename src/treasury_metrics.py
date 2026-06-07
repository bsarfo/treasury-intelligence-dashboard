"""
Treasury & credit metric calculations.

Takes raw SEC fact data + FRED rates and produces the credit ratios that
S&P, Moody's, and Fitch actually look at when assigning ratings.

Key methodology references:
- S&P Corporate Methodology (publicly available)
- For cruise lines specifically: S&P uses FFO/Debt and Net Debt/EBITDA
  as the two anchor metrics. Fixed Charge Coverage is the tiebreaker.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime

import pandas as pd

from src.config import SP_RATING_THRESHOLDS


# ----------------------------------------------------------------------------
# Data containers
# ----------------------------------------------------------------------------
@dataclass
class CreditMetrics:
    """Snapshot of the metrics S&P uses to assign a corporate rating."""
    as_of_date: datetime
    # Liquidity
    unrestricted_cash: float
    restricted_cash: float
    total_liquidity: float           # cash + revolver availability
    revolver_availability: float
    liquidity_coverage_ratio: float  # sources / uses next 12 months
    # Leverage
    total_debt: float
    net_debt: float
    ltm_ebitda: float
    net_debt_ebitda: float
    # Cash flow strength
    ffo: float                       # Funds From Operations
    ffo_debt_pct: float              # FFO / Total Debt × 100
    free_cash_flow: float
    # Coverage
    interest_expense: float
    fixed_charges: float
    fixed_charge_coverage: float     # EBITDA / Fixed Charges

    def to_dict(self) -> dict:
        return asdict(self)


# ----------------------------------------------------------------------------
# Core calculations
# ----------------------------------------------------------------------------
def compute_ltm(quarterly_series: pd.Series, as_of: pd.Timestamp | None = None) -> float:
    """
    Last Twelve Months (trailing 4 quarters) sum of a flow item.
    Use for income-statement / cash-flow line items (revenue, EBITDA, etc.).
    """
    s = quarterly_series.dropna().sort_index()
    if as_of is not None:
        s = s[s.index <= as_of]
    return float(s.tail(4).sum())


def compute_ebitda(
    operating_income: float,
    depreciation_amortization: float,
) -> float:
    """
    EBITDA = Operating Income + D&A.
    Cleanest definition for credit work. Excludes one-time / non-cash items
    that S&P typically strips out anyway.
    """
    return operating_income + depreciation_amortization


def compute_ffo(
    net_income: float,
    depreciation_amortization: float,
    deferred_taxes: float = 0.0,
    other_noncash: float = 0.0,
) -> float:
    """
    Funds From Operations.
    FFO = Net Income + D&A + Deferred Taxes + Other Non-Cash Charges
    This is S&P's preferred numerator for the FFO/Debt ratio.
    Differs from CFO because it excludes working capital changes.
    """
    return net_income + depreciation_amortization + deferred_taxes + other_noncash


def compute_net_debt(
    total_debt: float,
    cash_and_equivalents: float,
    short_term_investments: float = 0.0,
    restricted_cash_excluded: float = 0.0,
) -> float:
    """
    Net Debt = Total Debt - Unrestricted Cash - ST Investments.
    Restricted cash is typically excluded since it's not available to repay debt.
    """
    available_cash = cash_and_equivalents + short_term_investments - restricted_cash_excluded
    return total_debt - max(available_cash, 0)


def compute_fixed_charges(
    interest_expense: float,
    capitalized_interest: float = 0.0,
    operating_lease_expense: float = 0.0,
    preferred_dividends: float = 0.0,
) -> float:
    """
    Fixed Charges = Interest + Capitalized Interest + Operating Lease + Pref Divs.
    S&P treats operating leases as debt-like since ASC 842 / IFRS 16.
    """
    return (interest_expense + capitalized_interest
            + operating_lease_expense + preferred_dividends)


def compute_liquidity_coverage_ratio(
    cash: float,
    revolver_availability: float,
    operating_cash_inflow_12m: float,
    debt_maturities_12m: float,
    capex_12m: float,
    other_uses_12m: float = 0.0,
) -> float:
    """
    Sources / Uses over next 12 months.
    S&P calls liquidity 'adequate' at >1.2x, 'strong' at >1.5x, 'exceptional' at >2.0x.
    """
    sources = cash + revolver_availability + max(operating_cash_inflow_12m, 0)
    uses = debt_maturities_12m + max(capex_12m, 0) + other_uses_12m
    if uses <= 0:
        return float("inf")
    return sources / uses


# ----------------------------------------------------------------------------
# S&P rating assessment
# ----------------------------------------------------------------------------
def assess_rating_for_metric(metric_name: str, value: float) -> str:
    """
    Map a metric value to the S&P rating notch it implies.
    Returns one of: AAA, AA, A, BBB, BB, B, CCC.
    """
    if metric_name not in SP_RATING_THRESHOLDS:
        return "N/A"

    bands = SP_RATING_THRESHOLDS[metric_name]

    # For Net Debt/EBITDA: lower is better → check from AAA down
    # For FFO/Debt and FCC: higher is better → check from AAA down (range high-to-low)
    if metric_name == "net_debt_ebitda":
        for rating, (low, high) in bands.items():
            if low <= value < high:
                return rating
        return "CCC"
    else:  # ffo_debt or fixed_charge_coverage — higher is better
        for rating, (low, high) in bands.items():
            if low <= value < high:
                return rating
        return "CCC"


def assess_all_metrics(metrics: CreditMetrics) -> dict[str, dict]:
    """
    Run each metric through the S&P framework.
    Returns: {metric: {value, implied_rating, threshold_for_next_notch}}
    """
    assessments = {}

    pairs = {
        "net_debt_ebitda": metrics.net_debt_ebitda,
        "ffo_debt": metrics.ffo_debt_pct,
        "fixed_charge_coverage": metrics.fixed_charge_coverage,
    }

    for metric, value in pairs.items():
        implied = assess_rating_for_metric(metric, value)
        assessments[metric] = {
            "value": round(value, 2),
            "implied_rating": implied,
            "thresholds": SP_RATING_THRESHOLDS[metric],
        }

    # Composite: most conservative (lowest) of the three drives the rating
    rating_order = ["AAA", "AA", "A", "BBB", "BB", "B", "CCC"]
    implied_ratings = [a["implied_rating"] for a in assessments.values()]
    worst = max(implied_ratings, key=lambda r: rating_order.index(r))
    assessments["_composite"] = {"implied_rating": worst}

    return assessments


# ----------------------------------------------------------------------------
# Builder: snapshot → CreditMetrics
# ----------------------------------------------------------------------------
def build_credit_metrics(
    snapshot: dict,           # output of SecClient.balance_sheet_snapshot()
    ltm_ebitda: float,
    ltm_ffo: float,
    ltm_interest: float,
    ltm_fcf: float,
    revolver_availability: float = 0.0,
    operating_lease_expense: float = 0.0,
    debt_maturities_12m: float = 0.0,
    capex_12m: float = 0.0,
    operating_cash_inflow_12m: float | None = None,
) -> CreditMetrics:
    """
    Take a treasury snapshot + LTM flow figures and build the full credit picture.
    The flow figures (LTM EBITDA, FFO, etc.) come from the SEC client's
    quarterly_history method, summed via compute_ltm().
    """
    def _v(key: str) -> float:
        d = snapshot.get(key)
        return float(d["value"]) if d else 0.0

    cash = _v("cash_and_equivalents")
    st_inv = _v("short_term_investments")
    restricted = _v("restricted_cash")
    long_term_debt = _v("long_term_debt")
    current_lt_debt = _v("current_portion_lt_debt")
    short_term_debt = _v("short_term_borrowings")

    total_debt = long_term_debt + current_lt_debt + short_term_debt
    net_debt = compute_net_debt(total_debt, cash, st_inv)

    fixed_charges = compute_fixed_charges(
        interest_expense=ltm_interest,
        operating_lease_expense=operating_lease_expense,
    )

    if operating_cash_inflow_12m is None:
        # Reasonable proxy: LTM EBITDA - interest - cash taxes (assume 20%)
        operating_cash_inflow_12m = ltm_ebitda - ltm_interest - 0.2 * max(ltm_ebitda - ltm_interest, 0)

    return CreditMetrics(
        as_of_date=snapshot["cash_and_equivalents"]["end_date"] if snapshot.get("cash_and_equivalents") else datetime.now(),
        unrestricted_cash=cash,
        restricted_cash=restricted,
        total_liquidity=cash + revolver_availability,
        revolver_availability=revolver_availability,
        liquidity_coverage_ratio=compute_liquidity_coverage_ratio(
            cash=cash,
            revolver_availability=revolver_availability,
            operating_cash_inflow_12m=operating_cash_inflow_12m,
            debt_maturities_12m=debt_maturities_12m,
            capex_12m=capex_12m,
        ),
        total_debt=total_debt,
        net_debt=net_debt,
        ltm_ebitda=ltm_ebitda,
        net_debt_ebitda=net_debt / ltm_ebitda if ltm_ebitda > 0 else float("inf"),
        ffo=ltm_ffo,
        ffo_debt_pct=(ltm_ffo / total_debt * 100) if total_debt > 0 else 0,
        free_cash_flow=ltm_fcf,
        interest_expense=ltm_interest,
        fixed_charges=fixed_charges,
        fixed_charge_coverage=ltm_ebitda / fixed_charges if fixed_charges > 0 else float("inf"),
    )


if __name__ == "__main__":
    # Smoke test with synthetic Carnival-ish numbers
    print("=== Synthetic Carnival credit metrics smoke test ===")
    fake_snapshot = {
        "cash_and_equivalents": {"value": 1.9e9, "end_date": datetime(2026, 2, 28), "source_tag": "test"},
        "short_term_investments": {"value": 0, "end_date": datetime(2026, 2, 28), "source_tag": "test"},
        "restricted_cash": None,
        "long_term_debt": {"value": 26.0e9, "end_date": datetime(2026, 2, 28), "source_tag": "test"},
        "current_portion_lt_debt": {"value": 1.5e9, "end_date": datetime(2026, 2, 28), "source_tag": "test"},
        "short_term_borrowings": None,
    }
    m = build_credit_metrics(
        snapshot=fake_snapshot,
        ltm_ebitda=6.8e9,
        ltm_ffo=4.5e9,
        ltm_interest=1.85e9,
        ltm_fcf=2.6e9,
        revolver_availability=2.5e9,
        debt_maturities_12m=1.8e9,
        capex_12m=2.5e9,
    )
    print(f"  Net Debt:           ${m.net_debt/1e9:,.2f}B")
    print(f"  LTM EBITDA:         ${m.ltm_ebitda/1e9:,.2f}B")
    print(f"  Net Debt / EBITDA:  {m.net_debt_ebitda:.2f}x")
    print(f"  FFO / Debt:         {m.ffo_debt_pct:.1f}%")
    print(f"  Fixed Charge Cov:   {m.fixed_charge_coverage:.2f}x")
    print(f"  Liquidity Coverage: {m.liquidity_coverage_ratio:.2f}x")
    print()
    print("=== S&P rating assessment ===")
    assessments = assess_all_metrics(m)
    for metric, data in assessments.items():
        if metric == "_composite":
            print(f"\n  COMPOSITE IMPLIED RATING:  {data['implied_rating']}")
        else:
            print(f"  {metric:30s} {data['value']:>8.2f}  →  {data['implied_rating']}")
