"""
Data loader — bridges raw SEC client output and the metrics engine.

Two things this handles that the raw SEC client doesn't:
1. **Fallback tag chains**: companies change XBRL tags over time.
   Revenue was 'Revenues' until 2018, then 'RevenueFromContractWithCustomer...'.
   We try each candidate and pick the freshest match.
2. **LTM rollups**: income statement / cash flow items are point-in-time
   *quarterly* in 10-Q filings. To get LTM (last twelve months), sum the
   last 4 quarters — but be careful, 10-K filings already give the full
   FY total. We dedupe smartly.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from src.sec_client import SecClient


# Expanded tag chains — try each in order, first one with recent data wins
EXTENDED_TAGS = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "operating_income": [
        "OperatingIncomeLoss",
    ],
    "net_income": [
        "NetIncomeLoss",
        "ProfitLoss",
    ],
    "depreciation_amortization": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
        "Depreciation",
    ],
    "interest_expense": [
        "InterestExpense",
        "InterestExpenseDebt",
    ],
    "cash_from_operations": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForCapitalImprovements",
        "PaymentsToAcquireProductiveAssets",
    ],
    "capex_ships": [
        # Cruise lines and airlines often report ship/aircraft purchases separately
        "CapitalExpendituresShipsAndAircraft",
        "PaymentsToAcquireShips",
        "PaymentsToAcquireVessels",
    ],
    "cash_and_equivalents": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "Cash",
    ],
    "long_term_debt": [
        "LongTermDebtNoncurrent",
        "LongTermDebt",
    ],
    "current_portion_lt_debt": [
        "LongTermDebtCurrent",
    ],
    "operating_lease_liability": [
        "OperatingLeaseLiability",
        "OperatingLeaseLiabilityNoncurrent",
    ],
    "deferred_revenue": [
        "ContractWithCustomerLiabilityCurrent",
        "DeferredRevenueCurrent",
        "CustomerDepositsCurrent",
    ],
}


@dataclass
class CompanyFinancials:
    """Cleaned, LTM-rolled-up financial snapshot ready for metric calcs."""
    company_name: str
    as_of_date: pd.Timestamp

    # Balance sheet (point-in-time)
    cash: float
    restricted_cash: float
    total_assets: float
    long_term_debt: float
    current_portion_lt_debt: float
    short_term_borrowings: float
    total_debt: float
    stockholders_equity: float
    operating_lease_liability: float
    deferred_revenue: float

    # Income statement (LTM)
    ltm_revenue: float
    ltm_operating_income: float
    ltm_da: float
    ltm_ebitda: float
    ltm_interest_expense: float
    ltm_net_income: float
    ltm_ffo: float                  # NI + D&A (proxy)

    # Cash flow (LTM)
    ltm_cfo: float
    ltm_capex: float
    ltm_fcf: float

    # Metadata
    data_freshness: dict             # which tag was used + as-of date per metric


def _latest_with_form(df: pd.DataFrame, form_pref: tuple = ("10-Q", "10-K")) -> tuple[float | None, pd.Timestamp | None, str | None]:
    """Most recent row, preferring 10-Q for point-in-time, falling back to 10-K."""
    if df.empty:
        return None, None, None
    last = df.iloc[-1]
    return float(last["value"]), last["end_date"], last["form"]


def _ltm_rollup(df: pd.DataFrame, as_of: pd.Timestamp | None = None) -> tuple[float, pd.Timestamp | None]:
    """
    Compute LTM (last twelve months) by properly separating quarterly vs annual data.

    SEC EDGAR returns a mix of:
      - 10-K rows: full fiscal-year totals (one row = 12 months)
      - 10-Q rows: single-quarter totals (one row = 3 months)

    Naive approach (sum last 4 rows) breaks when data mixes both types.

    Correct approach:
      1. Identify each row as ~quarter or ~year by the period it covers
         (we use the SEC-provided 'start'/'end' dates via period length)
      2. Take the latest 10-Q's end date as our LTM anchor
      3. Sum the 4 most recent NON-OVERLAPPING quarters ending at/before that date
      4. If we don't have 4 quarters but have a 10-K, use:
         LTM = full-year 10-K + (Q1..Qn current FY) - (Q1..Qn prior FY)

    Returns (ltm_value, as_of_date).
    """
    if df.empty:
        return 0.0, None

    df = df.copy()
    if as_of is not None:
        df = df[df["end_date"] <= as_of]
    if df.empty:
        return 0.0, None

    # Period length proxy: 10-Q with fp ∈ {Q1, Q2, Q3} = quarterly; 10-K = annual; 10-Q with fp=FY occasionally appears.
    # We use the 'fp' (fiscal period) field which the SEC includes for every fact.
    if "fp" not in df.columns:
        # Fallback: assume 10-Q = quarter, 10-K = year
        df["is_quarter"] = df["form"] == "10-Q"
        df["is_annual"] = df["form"] == "10-K"
    else:
        df["is_quarter"] = df["fp"].isin(["Q1", "Q2", "Q3"]) | ((df["form"] == "10-Q") & (df["fp"] != "FY"))
        df["is_annual"] = (df["fp"] == "FY") | (df["form"] == "10-K")

    # Some 10-Q filings report Q4 implicitly via the FY 10-K, so we deduplicate end_date keeping the annual form when both exist
    df = df.sort_values(["end_date", "is_annual"]).drop_duplicates("end_date", keep="last").reset_index(drop=True)

    quarters = df[df["is_quarter"]].sort_values("end_date")
    annuals = df[df["is_annual"]].sort_values("end_date")

    # Strategy 1: We have at least 4 distinct quarterly observations → just sum the last 4
    if len(quarters) >= 4:
        last_four = quarters.tail(4)
        return float(last_four["value"].sum()), last_four["end_date"].max()

    # Strategy 2: Use annual + delta method
    # LTM = most-recent-FY-annual + (current-FY quarters reported so far) - (same quarters from prior FY)
    if not annuals.empty and not quarters.empty:
        latest_annual = annuals.iloc[-1]
        annual_value = float(latest_annual["value"])
        annual_fy = latest_annual.get("fy", None)
        annual_end = latest_annual["end_date"]

        # Quarters since the latest annual (current-year YTD)
        current_ytd = quarters[quarters["end_date"] > annual_end]
        # Same fiscal quarters from prior year (prior-year YTD up to same point)
        prior_ytd_end = annual_end
        prior_ytd_start = annual_end - pd.Timedelta(days=365)
        prior_ytd = quarters[(quarters["end_date"] > prior_ytd_start) & (quarters["end_date"] <= prior_ytd_end)]

        if not current_ytd.empty:
            # Match by fiscal period (Q1, Q2, Q3) so we subtract apples-to-apples
            current_fps = set(current_ytd.get("fp", pd.Series()).dropna().unique())
            if current_fps and "fp" in prior_ytd.columns:
                prior_matching = prior_ytd[prior_ytd["fp"].isin(current_fps)]
            else:
                # Take the same NUMBER of quarters from prior FY
                prior_matching = prior_ytd.tail(len(current_ytd))

            ltm = annual_value + float(current_ytd["value"].sum()) - float(prior_matching["value"].sum())
            return ltm, current_ytd["end_date"].max()
        else:
            # No quarters past latest annual — just use the annual
            return annual_value, annual_end

    # Strategy 3: Only quarters, fewer than 4 — annualize
    if not quarters.empty:
        return float(quarters["value"].sum() * (4 / len(quarters))), quarters["end_date"].max()

    # Strategy 4: Only annuals — use latest
    if not annuals.empty:
        latest = annuals.iloc[-1]
        return float(latest["value"]), latest["end_date"]

    return 0.0, None


def _find_first_with_data(
    sec: SecClient,
    tag_chain: list[str],
    cik: str | None = None,
    min_year: int = 2023,
) -> pd.DataFrame:
    """Try each candidate tag; return the first one that has data more recent than min_year."""
    for tag in tag_chain:
        df = sec.get_fact(tag, cik=cik)
        if df.empty:
            continue
        if df["end_date"].max().year >= min_year:
            df.attrs["source_tag"] = tag
            return df
    # Nothing fresh — return whatever the first tag had, even if stale
    for tag in tag_chain:
        df = sec.get_fact(tag, cik=cik)
        if not df.empty:
            df.attrs["source_tag"] = tag
            return df
    return pd.DataFrame()


def load_company_financials(company_name: str = "Carnival Corporation", cik: str | None = None) -> CompanyFinancials:
    """
    Pull, clean, and roll up all the data needed for the dashboard.
    This is the function the Streamlit app will call.
    """
    sec = SecClient()
    freshness = {}

    # ---- Balance sheet (point-in-time) ----
    def _bs(key: str) -> tuple[float, pd.Timestamp | None]:
        df = _find_first_with_data(sec, EXTENDED_TAGS.get(key, []), cik=cik)
        v, d, _ = _latest_with_form(df)
        freshness[key] = {"as_of": d, "tag": df.attrs.get("source_tag") if not df.empty else None}
        return v or 0.0, d

    cash, cash_date = _bs("cash_and_equivalents")
    restricted, _ = _bs("cash_and_equivalents")  # placeholder — restricted is a separate concept
    # Restricted cash via direct tag (it's not in EXTENDED_TAGS to keep that clean)
    rc_df = sec.get_fact("RestrictedCash", cik=cik)
    restricted = float(rc_df.iloc[-1]["value"]) if not rc_df.empty else 0.0

    lt_debt, _ = _bs("long_term_debt")
    cp_debt, _ = _bs("current_portion_lt_debt")

    st_df = sec.get_fact("ShortTermBorrowings", cik=cik)
    st_debt = float(st_df.iloc[-1]["value"]) if not st_df.empty else 0.0

    total_debt = lt_debt + cp_debt + st_debt

    ta_df = sec.get_fact("Assets", cik=cik)
    total_assets = float(ta_df.iloc[-1]["value"]) if not ta_df.empty else 0.0

    se_df = sec.get_fact("StockholdersEquity", cik=cik)
    stockholders_equity = float(se_df.iloc[-1]["value"]) if not se_df.empty else 0.0

    ol_df = _find_first_with_data(sec, EXTENDED_TAGS["operating_lease_liability"], cik=cik)
    operating_lease = float(ol_df.iloc[-1]["value"]) if not ol_df.empty else 0.0

    dr_df = _find_first_with_data(sec, EXTENDED_TAGS["deferred_revenue"], cik=cik)
    deferred_rev = float(dr_df.iloc[-1]["value"]) if not dr_df.empty else 0.0

    # ---- Income statement (LTM rollups) ----
    def _ltm(key: str) -> tuple[float, pd.Timestamp | None]:
        df = _find_first_with_data(sec, EXTENDED_TAGS.get(key, []), cik=cik)
        v, d = _ltm_rollup(df)
        freshness[key] = {"as_of": d, "tag": df.attrs.get("source_tag") if not df.empty else None, "ltm": True}
        return v, d

    ltm_revenue, _ = _ltm("revenue")
    ltm_op_income, _ = _ltm("operating_income")
    ltm_da, _ = _ltm("depreciation_amortization")
    ltm_interest, _ = _ltm("interest_expense")
    ltm_ni, _ = _ltm("net_income")
    ltm_cfo, _ = _ltm("cash_from_operations")
    ltm_capex, _ = _ltm("capex")

    ltm_ebitda = ltm_op_income + ltm_da
    ltm_ffo = ltm_ni + ltm_da  # simple FFO proxy
    ltm_fcf = ltm_cfo - ltm_capex

    return CompanyFinancials(
        company_name=company_name,
        as_of_date=cash_date or pd.Timestamp.now(),
        cash=cash,
        restricted_cash=restricted,
        total_assets=total_assets,
        long_term_debt=lt_debt,
        current_portion_lt_debt=cp_debt,
        short_term_borrowings=st_debt,
        total_debt=total_debt,
        stockholders_equity=stockholders_equity,
        operating_lease_liability=operating_lease,
        deferred_revenue=deferred_rev,
        ltm_revenue=ltm_revenue,
        ltm_operating_income=ltm_op_income,
        ltm_da=ltm_da,
        ltm_ebitda=ltm_ebitda,
        ltm_interest_expense=ltm_interest,
        ltm_net_income=ltm_ni,
        ltm_ffo=ltm_ffo,
        ltm_cfo=ltm_cfo,
        ltm_capex=ltm_capex,
        ltm_fcf=ltm_fcf,
        data_freshness=freshness,
    )


if __name__ == "__main__":
    print("=== Loading clean Carnival financials ===")
    fin = load_company_financials()
    print(f"\nCompany:        {fin.company_name}")
    print(f"As of:          {fin.as_of_date.date() if fin.as_of_date else 'N/A'}")
    print(f"\n--- Balance Sheet ---")
    print(f"  Cash:                  ${fin.cash/1e6:>10,.0f}M")
    print(f"  Restricted cash:       ${fin.restricted_cash/1e6:>10,.0f}M")
    print(f"  Total assets:          ${fin.total_assets/1e6:>10,.0f}M")
    print(f"  Long-term debt:        ${fin.long_term_debt/1e6:>10,.0f}M")
    print(f"  Current LT debt:       ${fin.current_portion_lt_debt/1e6:>10,.0f}M")
    print(f"  Total debt:            ${fin.total_debt/1e6:>10,.0f}M")
    print(f"  Stockholders equity:   ${fin.stockholders_equity/1e6:>10,.0f}M")
    print(f"  Operating lease liab:  ${fin.operating_lease_liability/1e6:>10,.0f}M")
    print(f"  Customer deposits:     ${fin.deferred_revenue/1e6:>10,.0f}M")
    print(f"\n--- LTM Income / Cash Flow ---")
    print(f"  LTM Revenue:           ${fin.ltm_revenue/1e6:>10,.0f}M")
    print(f"  LTM Operating Income:  ${fin.ltm_operating_income/1e6:>10,.0f}M")
    print(f"  LTM D&A:               ${fin.ltm_da/1e6:>10,.0f}M")
    print(f"  LTM EBITDA:            ${fin.ltm_ebitda/1e6:>10,.0f}M")
    print(f"  LTM Interest expense:  ${fin.ltm_interest_expense/1e6:>10,.0f}M")
    print(f"  LTM Net income:        ${fin.ltm_net_income/1e6:>10,.0f}M")
    print(f"  LTM FFO:               ${fin.ltm_ffo/1e6:>10,.0f}M")
    print(f"  LTM CFO:               ${fin.ltm_cfo/1e6:>10,.0f}M")
    print(f"  LTM Capex:             ${fin.ltm_capex/1e6:>10,.0f}M")
    print(f"  LTM Free Cash Flow:    ${fin.ltm_fcf/1e6:>10,.0f}M")
