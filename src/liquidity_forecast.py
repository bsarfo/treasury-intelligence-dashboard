"""
13-week cash flow forecast — the headline tile from the dashboard.

Methodology:
1. Pull last 3 years of quarterly cash flow from SEC.
2. Decompose into weekly cash inflows / outflows.
3. Apply seasonal index by ISO week of year.
4. Project forward 13 weeks from latest cash position.
5. Flag any week where cash dips below the minimum threshold.

For Carnival specifically, the seasonality is brutal and obvious:
- Q1 (Dec-Feb): wave season bookings → big customer deposit inflows
- Q2-Q3 (Mar-Aug): peak sailings → strongest operating cash
- Q4 (Sep-Nov): refurbishment + interest payments → cash drain

This is what makes the forecast useful — a flat extrapolation would miss
the wave-season cash inflow that funds the rest of the year.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd


@dataclass
class WeeklyForecast:
    """One row of the 13-week forecast."""
    week_ending: pd.Timestamp
    week_number: int                 # 1..13
    iso_week_of_year: int
    starting_cash: float
    cash_inflow: float
    cash_outflow: float
    ending_cash: float
    below_threshold: bool


def build_seasonal_index(
    quarterly_cfo: pd.Series,
    quarterly_capex: pd.Series | None = None,
) -> pd.DataFrame:
    """
    From historical quarterly cash flow data, derive a weekly seasonal index.
    Returns a DataFrame indexed by ISO week (1..53) with columns:
      [inflow_weight, outflow_weight]
    Weights are normalized so the 52-week sum equals 1.0 for each.
    """
    # Build a calendar of quarterly data spread evenly within each quarter
    cfo = quarterly_cfo.dropna().sort_index()

    if cfo.empty:
        # Fallback: flat seasonal index
        weeks = list(range(1, 54))
        return pd.DataFrame({
            "inflow_weight": [1 / 52] * 53,
            "outflow_weight": [1 / 52] * 53,
        }, index=pd.Index(weeks, name="iso_week"))

    # Expand quarterly cash flow into 13 equal weekly slices
    weekly_rows = []
    for q_end, q_value in cfo.items():
        q_start = q_end - pd.Timedelta(days=90)
        weeks_in_q = pd.date_range(q_start, q_end, freq="W-SUN")
        if len(weeks_in_q) == 0:
            continue
        per_week = q_value / len(weeks_in_q)
        for w in weeks_in_q:
            weekly_rows.append({
                "week_ending": w,
                "iso_week": w.isocalendar().week,
                "cfo": per_week,
            })

    weekly = pd.DataFrame(weekly_rows)
    if weekly.empty:
        weeks = list(range(1, 54))
        return pd.DataFrame({
            "inflow_weight": [1 / 52] * 53,
            "outflow_weight": [1 / 52] * 53,
        }, index=pd.Index(weeks, name="iso_week"))

    # Average across years by ISO week
    seasonal = weekly.groupby("iso_week")["cfo"].mean()

    # Split positive/negative — positive flows are inflows, negative are outflows
    pos = seasonal.clip(lower=0)
    neg = seasonal.clip(upper=0).abs()

    inflow_w = pos / pos.sum() if pos.sum() > 0 else pd.Series(1 / len(pos), index=pos.index)
    outflow_w = neg / neg.sum() if neg.sum() > 0 else pd.Series(1 / len(neg), index=neg.index)

    out = pd.DataFrame({
        "inflow_weight": inflow_w,
        "outflow_weight": outflow_w,
    })
    out.index.name = "iso_week"
    return out


def forecast_13_weeks(
    starting_cash: float,
    annual_cash_inflow: float,           # expected next-12-month inflows
    annual_cash_outflow: float,          # expected next-12-month outflows
    seasonal_index: pd.DataFrame,
    minimum_threshold: float = 0.0,
    start_date: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """
    Build the 13-week forecast.

    annual_cash_inflow:  e.g. customer deposits + revenue collections expected
    annual_cash_outflow: opex + capex + debt service + interest
    Both numbers get distributed across the 13 weeks using the seasonal index.
    """
    if start_date is None:
        start_date = pd.Timestamp.today().normalize()

    # Next 13 week-ending dates (Sundays)
    week_endings = pd.date_range(
        start=start_date + pd.Timedelta(days=(6 - start_date.weekday())),
        periods=13,
        freq="W-SUN",
    )

    rows = []
    cash = starting_cash

    for i, week_end in enumerate(week_endings, start=1):
        iso_w = week_end.isocalendar().week

        # Pull the seasonal weight for this ISO week
        if iso_w in seasonal_index.index:
            inflow_w = seasonal_index.loc[iso_w, "inflow_weight"]
            outflow_w = seasonal_index.loc[iso_w, "outflow_weight"]
        else:
            inflow_w = 1 / 52
            outflow_w = 1 / 52

        week_inflow = annual_cash_inflow * inflow_w
        week_outflow = annual_cash_outflow * outflow_w
        ending = cash + week_inflow - week_outflow

        rows.append(WeeklyForecast(
            week_ending=week_end,
            week_number=i,
            iso_week_of_year=iso_w,
            starting_cash=cash,
            cash_inflow=week_inflow,
            cash_outflow=week_outflow,
            ending_cash=ending,
            below_threshold=ending < minimum_threshold,
        ))
        cash = ending

    return pd.DataFrame([r.__dict__ for r in rows])


def liquidity_runway_quarters(
    cash: float,
    quarterly_burn: float,
) -> float:
    """How many quarters until cash hits zero at current burn?"""
    if quarterly_burn <= 0:
        return float("inf")
    return cash / quarterly_burn


if __name__ == "__main__":
    # Smoke test with Carnival-shaped seasonality
    print("=== 13-week forecast smoke test ===")
    # Simulate 3 years of quarterly CFO showing wave-season strength
    dates = pd.date_range("2023-02-28", "2025-11-30", freq="QE-NOV")
    # Carnival's pattern: Q1 strong (wave deposits), Q2-Q3 peak, Q4 weakest
    pattern = [2.0e9, 1.8e9, 1.5e9, 0.8e9]  # repeats by fiscal quarter
    cfo_values = [pattern[i % 4] for i in range(len(dates))]
    cfo = pd.Series(cfo_values, index=dates)

    seasonal = build_seasonal_index(cfo)
    print(f"Seasonal index built — {len(seasonal)} weeks")
    print(f"  Peak inflow week:  ISO {seasonal['inflow_weight'].idxmax()} (weight {seasonal['inflow_weight'].max():.3f})")
    print(f"  Peak outflow week: ISO {seasonal['outflow_weight'].idxmax()} (weight {seasonal['outflow_weight'].max():.3f})")

    forecast = forecast_13_weeks(
        starting_cash=1.9e9,
        annual_cash_inflow=26e9,
        annual_cash_outflow=22e9,
        seasonal_index=seasonal,
        minimum_threshold=1.0e9,
    )
    print(f"\nStarting cash:     ${forecast['starting_cash'].iloc[0]/1e9:.2f}B")
    print(f"Week 13 cash:      ${forecast['ending_cash'].iloc[-1]/1e9:.2f}B")
    print(f"Min over horizon:  ${forecast['ending_cash'].min()/1e9:.2f}B")
    print(f"Weeks below min:   {forecast['below_threshold'].sum()}")
