"""
Risk engine.

Three risk modules:
1. Interest Rate VaR — how much could interest expense rise under adverse rate move
2. FX Exposure — net exposure decomposed by currency
3. Debt Maturity Wall — laddering of debt by maturity year

These are the three calculation patterns that make the dashboard look like
something a treasury team actually uses, not a toy demo.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd


# ============================================================================
# 1. Interest Rate VaR
# ============================================================================
@dataclass
class InterestRateVaR:
    """Result of an interest rate Value at Risk calculation."""
    variable_rate_debt: float
    fixed_rate_debt: float
    weighted_avg_rate: float
    rate_volatility_annual: float    # annualized stdev of SOFR
    confidence_level: float          # e.g. 0.95
    horizon_days: int
    var_rate_bps: float              # adverse rate move in bps
    var_dollar_annual: float         # extra interest expense per year under VaR scenario


def compute_interest_rate_var(
    variable_rate_debt: float,
    fixed_rate_debt: float,
    weighted_avg_rate: float,
    sofr_history: pd.Series,         # FRED SOFR series, daily
    confidence_level: float = 0.95,
    horizon_days: int = 252,         # 1 year
) -> InterestRateVaR:
    """
    Parametric VaR on rate-sensitive debt.

    Approach:
    - Compute annualized stdev of daily SOFR changes
    - Scale by sqrt(horizon) and z-score for confidence level
    - Apply the adverse rate move to variable-rate debt to get $ VaR

    This is the simple parametric form. For Phase 6 scenarios we'll add
    Monte Carlo, but this is what 90% of corporate treasury teams use.
    """
    daily_changes = sofr_history.dropna().diff().dropna()
    daily_vol_bps = daily_changes.std() * 100   # SOFR is in %, so ×100 → bps
    annual_vol_bps = daily_vol_bps * np.sqrt(252)

    # Z-score from standard normal
    from scipy.stats import norm  # standard library would also work via lookup
    z = norm.ppf(confidence_level)

    horizon_vol_bps = daily_vol_bps * np.sqrt(horizon_days)
    adverse_move_bps = z * horizon_vol_bps

    # Extra interest if SOFR rises by adverse_move_bps
    extra_interest = variable_rate_debt * (adverse_move_bps / 10000)

    return InterestRateVaR(
        variable_rate_debt=variable_rate_debt,
        fixed_rate_debt=fixed_rate_debt,
        weighted_avg_rate=weighted_avg_rate,
        rate_volatility_annual=annual_vol_bps,
        confidence_level=confidence_level,
        horizon_days=horizon_days,
        var_rate_bps=adverse_move_bps,
        var_dollar_annual=extra_interest,
    )


# ============================================================================
# 2. FX Exposure
# ============================================================================
@dataclass
class FxExposureRow:
    currency: str
    notional_usd: float
    pct_of_total: float
    fx_volatility_annual: float
    var_95_10day_usd: float


def compute_fx_exposure(
    exposures_usd: dict[str, float],     # {currency_code: usd_value}
    fx_history: pd.DataFrame,            # daily FX rates from FRED, columns = currencies
    confidence_level: float = 0.95,
    horizon_days: int = 10,
) -> pd.DataFrame:
    """
    For each non-USD exposure, calculate the 10-day 95% VaR in USD terms.
    Standard treasury risk reporting horizon.
    """
    from scipy.stats import norm
    z = norm.ppf(confidence_level)

    total = sum(exposures_usd.values())
    rows = []

    for ccy, notional in exposures_usd.items():
        # Match the FX series for this currency
        col = None
        for c in fx_history.columns:
            if ccy.upper() in c.upper():
                col = c
                break

        if col is None:
            vol_annual = 0.0
            var = 0.0
        else:
            log_returns = np.log(fx_history[col] / fx_history[col].shift(1)).dropna()
            daily_vol = log_returns.std()
            vol_annual = daily_vol * np.sqrt(252) * 100   # as %
            horizon_vol = daily_vol * np.sqrt(horizon_days)
            var = abs(notional) * z * horizon_vol

        rows.append(FxExposureRow(
            currency=ccy,
            notional_usd=notional,
            pct_of_total=(notional / total * 100) if total else 0,
            fx_volatility_annual=vol_annual,
            var_95_10day_usd=var,
        ))

    return pd.DataFrame([r.__dict__ for r in rows])


# ============================================================================
# 3. Debt Maturity Wall
# ============================================================================
def build_debt_maturity_wall(
    debt_instruments: list[dict],    # [{principal, maturity_date, rate, instrument_name}]
    as_of: date | None = None,
    bucket_years: tuple[int, ...] = (1, 2, 3, 5, 10),
) -> pd.DataFrame:
    """
    Bucket debt by years-to-maturity.

    Returns DataFrame with columns: [bucket_label, principal, weighted_rate, count]
    For the chart from the screenshot: <1Y, 1-2Y, 2-3Y, 3-5Y, >5Y
    """
    as_of = as_of or date.today()
    rows = []

    for inst in debt_instruments:
        maturity = pd.Timestamp(inst["maturity_date"]).date()
        years_out = (maturity - as_of).days / 365.25
        rows.append({
            "principal": inst["principal"],
            "rate": inst.get("rate", 0),
            "years_to_maturity": years_out,
            "name": inst.get("instrument_name", ""),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Build bucket labels
    edges = [0] + list(bucket_years) + [999]
    labels = []
    for i in range(len(edges) - 1):
        if i == 0:
            labels.append(f"< {edges[1]}Y")
        elif edges[i + 1] == 999:
            labels.append(f"> {edges[i]}Y")
        else:
            labels.append(f"{edges[i]}-{edges[i+1]}Y")

    df["bucket"] = pd.cut(df["years_to_maturity"], bins=edges, labels=labels, include_lowest=True)

    summary = (df.groupby("bucket", observed=False)
               .agg(principal=("principal", "sum"),
                    weighted_rate=("rate", lambda x: np.average(
                        x, weights=df.loc[x.index, "principal"]
                    ) if df.loc[x.index, "principal"].sum() > 0 else 0),
                    count=("name", "count"))
               .reset_index())
    return summary


def near_term_maturity_risk(
    debt_instruments: list[dict],
    as_of: date | None = None,
    within_months: int = 24,
) -> dict:
    """
    Sum debt maturing in next N months — the 'refinancing wall' metric.
    Big near-term maturities = ratings risk if credit markets tighten.
    """
    as_of = as_of or date.today()
    cutoff_days = within_months * 30
    total = 0.0
    count = 0
    for inst in debt_instruments:
        maturity = pd.Timestamp(inst["maturity_date"]).date()
        days_out = (maturity - as_of).days
        if 0 <= days_out <= cutoff_days:
            total += inst["principal"]
            count += 1
    return {"total_maturing": total, "instrument_count": count,
            "horizon_months": within_months}


if __name__ == "__main__":
    print("=== Interest Rate VaR smoke test ===")
    # Synthetic SOFR series with ~50 bps annual vol
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", "2026-05-01", freq="B")
    sofr = pd.Series(
        4.5 + np.cumsum(np.random.normal(0, 0.03, len(dates))),
        index=dates,
    )
    var = compute_interest_rate_var(
        variable_rate_debt=10e9,
        fixed_rate_debt=18e9,
        weighted_avg_rate=0.072,
        sofr_history=sofr,
    )
    print(f"  Variable rate debt:  ${var.variable_rate_debt/1e9:.1f}B")
    print(f"  Annual SOFR vol:     {var.rate_volatility_annual:.0f} bps")
    print(f"  95% adverse move:    +{var.var_rate_bps:.0f} bps over {var.horizon_days}d")
    print(f"  $ VaR (annual):      ${var.var_dollar_annual/1e6:.0f}M extra interest")

    print("\n=== Debt maturity wall smoke test ===")
    # Carnival-shaped: ~$2B per year staggered through 2031
    instruments = [
        {"principal": 1.8e9, "maturity_date": "2026-08-01", "rate": 0.0775, "instrument_name": "1.875% Sr Unsec Notes"},
        {"principal": 1.5e9, "maturity_date": "2027-03-15", "rate": 0.063, "instrument_name": "5.75% Sr Unsec Notes"},
        {"principal": 2.0e9, "maturity_date": "2028-06-30", "rate": 0.069, "instrument_name": "6.0% Sr Unsec Notes"},
        {"principal": 2.5e9, "maturity_date": "2029-12-31", "rate": 0.0725, "instrument_name": "7.0% Sr Unsec Notes"},
        {"principal": 3.0e9, "maturity_date": "2031-05-01", "rate": 0.0625, "instrument_name": "6.125% Sr Unsec Notes"},
        {"principal": 4.0e9, "maturity_date": "2033-02-01", "rate": 0.0575, "instrument_name": "5.75% Sr Unsec Notes"},
    ]
    wall = build_debt_maturity_wall(instruments, as_of=date(2026, 6, 4))
    print(wall.to_string(index=False))

    risk = near_term_maturity_risk(instruments, as_of=date(2026, 6, 4))
    print(f"\n  Maturing in next 24m: ${risk['total_maturing']/1e9:.2f}B "
          f"across {risk['instrument_count']} instruments")
