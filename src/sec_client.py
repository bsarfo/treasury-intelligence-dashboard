"""
SEC EDGAR client.

Uses the public companyfacts JSON endpoint to pull historical financial data
straight from filings (10-K, 10-Q). No scraping required — SEC publishes
clean XBRL-tagged data for every filer.

Docs: https://www.sec.gov/edgar/sec-api-documentation
Key constraint: SEC requires a descriptive User-Agent header with contact info.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

from src.config import CACHE_DIR, CACHE_TTL_HOURS, COMPANY
from src.secrets_loader import get_secret

EDGAR_BASE = "https://data.sec.gov"


class SecClient:
    """Pulls company facts from SEC EDGAR XBRL API."""

    def __init__(self, user_agent: str | None = None):
        ua = user_agent or get_secret("SEC_USER_AGENT")
        if not ua or "your.email" in ua:
            ua = "Treasury Dashboard Project portfolio@example.com"
        self.headers = {"User-Agent": ua, "Accept": "application/json"}

    # ---------- caching ----------
    def _cache_path(self, cik: str) -> Path:
        return CACHE_DIR / f"sec_companyfacts_{cik}.json"

    def _is_fresh(self, path: Path, ttl_hours: int) -> bool:
        if not path.exists():
            return False
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        return age < timedelta(hours=ttl_hours)

    # ---------- raw fetch ----------
    def get_company_facts(self, cik: str | None = None, force_refresh: bool = False) -> dict:
        """
        Pull the full XBRL fact set for a company. Massive JSON — every
        tagged financial fact the company has ever filed. Cached aggressively.
        """
        cik = (cik or COMPANY["cik"]).zfill(10)
        path = self._cache_path(cik)

        if not force_refresh and self._is_fresh(path, CACHE_TTL_HOURS["sec_filings"]):
            return json.loads(path.read_text())

        url = f"{EDGAR_BASE}/api/xbrl/companyfacts/CIK{cik}.json"
        # SEC requests no more than 10 req/sec — we're fine but be polite
        time.sleep(0.15)
        r = requests.get(url, headers=self.headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        path.write_text(json.dumps(data))
        return data

    # ---------- fact extraction ----------
    def get_fact(
        self,
        concept: str,
        cik: str | None = None,
        unit: str = "USD",
        form_types: tuple[str, ...] = ("10-K", "10-Q"),
    ) -> pd.DataFrame:
        """
        Extract one XBRL concept as a tidy DataFrame.

        concept: e.g. 'Assets', 'LongTermDebt', 'CashAndCashEquivalentsAtCarryingValue'
        Returns columns: [end_date, value, form, fy, fp, filed]
        """
        facts = self.get_company_facts(cik)
        try:
            entries = facts["facts"]["us-gaap"][concept]["units"][unit]
        except KeyError:
            return pd.DataFrame()

        df = pd.DataFrame(entries)
        df = df[df["form"].isin(form_types)].copy()
        df["end_date"] = pd.to_datetime(df["end"])
        df["filed_date"] = pd.to_datetime(df["filed"])
        # Sort so that for the same end_date, latest-filed wins on .iloc[-1]/drop_duplicates(keep='last')
        df = df.sort_values(["end_date", "filed_date"]).reset_index(drop=True)
        return df[["end_date", "val", "form", "fy", "fp", "filed_date"]].rename(
            columns={"val": "value"}
        )

    def latest_value(self, concept: str, cik: str | None = None, unit: str = "USD") -> float | None:
        """Most recent reported value for a single concept."""
        df = self.get_fact(concept, cik=cik, unit=unit)
        if df.empty:
            return None
        return float(df.iloc[-1]["value"])

    # ---------- pre-built balance sheet snapshot ----------
    # Common XBRL tags for treasury-relevant concepts.
    # Note: companies sometimes use different tags — fall back gracefully.
    BALANCE_SHEET_TAGS = {
        "cash_and_equivalents": [
            "CashAndCashEquivalentsAtCarryingValue",
            "Cash",
        ],
        "short_term_investments": ["ShortTermInvestments"],
        "restricted_cash": [
            "RestrictedCash",
            "RestrictedCashAndCashEquivalents",
        ],
        "total_assets": ["Assets"],
        "long_term_debt": [
            "LongTermDebt",
            "LongTermDebtNoncurrent",
        ],
        "current_portion_lt_debt": ["LongTermDebtCurrent"],
        "short_term_borrowings": ["ShortTermBorrowings"],
        "total_liabilities": ["Liabilities"],
        "stockholders_equity": ["StockholdersEquity"],
        "revenue": [
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
        ],
        "operating_income": ["OperatingIncomeLoss"],
        "interest_expense": ["InterestExpense"],
        "net_income": ["NetIncomeLoss"],
        "depreciation_amortization": [
            "DepreciationDepletionAndAmortization",
            "DepreciationAndAmortization",
        ],
        "cash_from_operations": [
            "NetCashProvidedByUsedInOperatingActivities",
        ],
        "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    }

    def balance_sheet_snapshot(self, cik: str | None = None) -> dict:
        """
        Latest available value for each treasury-relevant concept.
        Tries each candidate tag until one returns data.
        Returns dict: {metric_name: {value, end_date, source_tag}}
        """
        out = {}
        for metric, candidates in self.BALANCE_SHEET_TAGS.items():
            for tag in candidates:
                df = self.get_fact(tag, cik=cik)
                if not df.empty:
                    last = df.iloc[-1]
                    out[metric] = {
                        "value": float(last["value"]),
                        "end_date": last["end_date"],
                        "source_tag": tag,
                    }
                    break
            else:
                out[metric] = None
        return out

    def quarterly_history(self, concept: str, cik: str | None = None) -> pd.DataFrame:
        """Quarterly time-series for charting (uses 10-Q + 10-K)."""
        df = self.get_fact(concept, cik=cik)
        if df.empty:
            return df
        # Keep one row per quarter end (latest filed wins if restated)
        df = df.sort_values(["end_date", "filed_date"]).drop_duplicates(
            "end_date", keep="last"
        )
        return df


def get_client() -> SecClient:
    return SecClient()


if __name__ == "__main__":
    # Smoke test: python -m src.sec_client
    sec = get_client()
    print(f"Fetching company facts for {COMPANY['name']} (CIK {COMPANY['cik']})…")
    snapshot = sec.balance_sheet_snapshot()
    print("\nTreasury snapshot:")
    for metric, data in snapshot.items():
        if data:
            v = data["value"] / 1e6
            print(f"  {metric:30s} ${v:>12,.1f}M   as of {data['end_date'].date()}  [{data['source_tag']}]")
        else:
            print(f"  {metric:30s} (not found)")
