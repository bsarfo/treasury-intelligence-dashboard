"""
FRED (Federal Reserve Economic Data) client.

Wraps the fredapi library with local parquet caching so we don't hammer the API.
All time-series come back as pandas DataFrames with a DatetimeIndex.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from fredapi import Fred

from src.config import CACHE_DIR, CACHE_TTL_HOURS, FRED_SERIES
from src.secrets_loader import get_secret


class FredClient:
    """Thin wrapper around fredapi with disk caching."""

    def __init__(self, api_key: str | None = None):
        key = api_key or get_secret("FRED_API_KEY")
        if not key or key == "your_fred_key_here":
            raise ValueError(
                "FRED_API_KEY missing. Get one free at "
                "https://fred.stlouisfed.org/docs/api/api_key.html "
                "and add to your .env file (local) or Streamlit Cloud secrets (production)."
            )
        self.fred = Fred(api_key=key)

    # ---------- caching helpers ----------
    def _cache_path(self, series_id: str) -> Path:
        return CACHE_DIR / f"fred_{series_id}.parquet"

    def _is_fresh(self, path: Path, ttl_hours: int) -> bool:
        if not path.exists():
            return False
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        return age < timedelta(hours=ttl_hours)

    # ---------- public API ----------
    def get_series(
        self,
        series_id: str,
        start: str = "2020-01-01",
        end: str | None = None,
        ttl_hours: int = 24,
        force_refresh: bool = False,
    ) -> pd.Series:
        """
        Fetch a single FRED series. Returns a pd.Series indexed by date.
        Uses local parquet cache to avoid repeat API calls.
        """
        path = self._cache_path(series_id)

        if not force_refresh and self._is_fresh(path, ttl_hours):
            df = pd.read_parquet(path)
            return df["value"]

        # Pull from API
        s = self.fred.get_series(series_id, observation_start=start, observation_end=end)
        s.name = "value"
        s.index.name = "date"
        s.to_frame().to_parquet(path)
        return s

    def get_many(
        self,
        series_map: dict[str, str],
        start: str = "2020-01-01",
        ttl_hours: int = 24,
    ) -> pd.DataFrame:
        """
        Fetch multiple series into a single DataFrame.
        series_map: {column_name: fred_series_id}
        """
        frames = {}
        for col, sid in series_map.items():
            try:
                frames[col] = self.get_series(sid, start=start, ttl_hours=ttl_hours)
            except Exception as e:
                print(f"  ⚠️  Failed to fetch {col} ({sid}): {e}")
        return pd.DataFrame(frames)

    # ---------- pre-built bundles ----------
    def rates_bundle(self, start: str = "2020-01-01") -> pd.DataFrame:
        """All key US rates in one DataFrame."""
        return self.get_many(
            {k: FRED_SERIES[k] for k in
             ["SOFR", "FED_FUNDS", "TREASURY_2Y", "TREASURY_5Y",
              "TREASURY_10Y", "TREASURY_30Y", "PRIME_RATE"]},
            start=start,
            ttl_hours=CACHE_TTL_HOURS["fred_rates"],
        )

    def credit_spreads_bundle(self, start: str = "2020-01-01") -> pd.DataFrame:
        """High-yield and IG credit spreads (OAS)."""
        return self.get_many(
            {k: FRED_SERIES[k] for k in ["HY_OAS", "BB_OAS", "B_OAS", "IG_OAS"]},
            start=start,
            ttl_hours=CACHE_TTL_HOURS["fred_rates"],
        )

    def fx_bundle(self, start: str = "2020-01-01") -> pd.DataFrame:
        """FX rates relevant to Carnival (EUR, GBP, CAD, AUD)."""
        return self.get_many(
            {k: FRED_SERIES[k] for k in
             ["EUR_USD", "GBP_USD", "CAD_USD", "AUD_USD"]},
            start=start,
            ttl_hours=CACHE_TTL_HOURS["fred_rates"],
        )

    def macro_bundle(self, start: str = "2020-01-01") -> pd.DataFrame:
        """Recession indicators & consumer health."""
        return self.get_many(
            {k: FRED_SERIES[k] for k in
             ["CPI", "UNEMPLOYMENT", "CONSUMER_SENTIMENT",
              "RECESSION_PROB", "YIELD_CURVE_10Y_2Y"]},
            start=start,
            ttl_hours=CACHE_TTL_HOURS["fred_macro"],
        )

    def latest(self, series_id: str) -> tuple[pd.Timestamp, float]:
        """Latest observation: (date, value). Handy for headline KPI tiles."""
        s = self.get_series(series_id).dropna()
        return s.index[-1], float(s.iloc[-1])


# Convenience singleton — import and use
def get_client() -> FredClient:
    return FredClient()


if __name__ == "__main__":
    # Quick smoke test — run `python -m src.fred_client`
    fred = get_client()
    print("Fetching SOFR…")
    sofr = fred.get_series("SOFR", start="2024-01-01")
    print(f"  Latest SOFR: {sofr.dropna().iloc[-1]:.3f}% on {sofr.dropna().index[-1].date()}")
    print("Fetching rates bundle…")
    rates = fred.rates_bundle(start="2024-01-01")
    print(rates.tail())
