"""
Central configuration for the Treasury Intelligence Dashboard.
Edit COMPANY and S&P thresholds here to retarget the dashboard.
"""
from pathlib import Path

# --- Paths ---
ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "cache"
DATA_DIR = ROOT / "data"
CACHE_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# --- Company under analysis ---
COMPANY = {
    "name": "Carnival Corporation & plc",
    "ticker": "CCL",
    "cik": "0000815097",          # Carnival Corp CIK (10-digit, zero-padded)
    "industry": "Entertainment / Leisure",
    "reporting_currency": "USD",
    "fiscal_year_end_month": 11,  # Carnival's fiscal year ends in November
    "current_sp_rating": "BB+",
    "current_outlook": "Stable",
    "target_rating": "BBB-",      # Investment grade
}

# --- FRED series IDs (memorize these — they're the building blocks) ---
FRED_SERIES = {
    # Interest rates
    "SOFR": "SOFR",                          # Secured Overnight Financing Rate
    "FED_FUNDS": "DFF",                      # Federal Funds Effective Rate
    "TREASURY_2Y": "DGS2",
    "TREASURY_5Y": "DGS5",
    "TREASURY_10Y": "DGS10",
    "TREASURY_30Y": "DGS30",
    "PRIME_RATE": "DPRIME",

    # Credit spreads (BB index is closest to CCL)
    "HY_OAS": "BAMLH0A0HYM2",                # ICE BofA US High Yield OAS
    "BB_OAS": "BAMLH0A1HYBB",                # BB-rated OAS
    "B_OAS": "BAMLH0A2HYB",                  # B-rated OAS
    "IG_OAS": "BAMLC0A0CM",                  # Investment Grade OAS

    # FX (Carnival has EUR, GBP, CAD, AUD exposure from European/Australian ops)
    "EUR_USD": "DEXUSEU",
    "GBP_USD": "DEXUSUK",
    "CAD_USD": "DEXCAUS",                    # Note: this is CAD per USD (inverted)
    "AUD_USD": "DEXUSAL",

    # Macro / recession indicators
    "CPI": "CPIAUCSL",
    "UNEMPLOYMENT": "UNRATE",
    "CONSUMER_SENTIMENT": "UMCSENT",
    "RECESSION_PROB": "RECPROUSM156N",
    "YIELD_CURVE_10Y_2Y": "T10Y2Y",          # Inversion = recession signal

    # Volatility (for VaR calcs)
    "VIX": "VIXCLS",
    "MOVE": "ICE_BOFAML_MOVE_INDEX",         # Bond volatility
}

# --- S&P methodology: typical thresholds by rating notch ---
# Source: S&P Global Ratings — Corporate Methodology
# These are the credit metric ranges S&P typically associates with each rating.
SP_RATING_THRESHOLDS = {
    # Net Debt / EBITDA (lower is better)
    "net_debt_ebitda": {
        "AAA": (0, 1.0), "AA": (1.0, 1.5), "A": (1.5, 2.0),
        "BBB": (2.0, 3.0), "BB": (3.0, 4.5), "B": (4.5, 6.0), "CCC": (6.0, 99),
    },
    # FFO / Debt % (higher is better) — the key metric for CCL
    "ffo_debt": {
        "AAA": (60, 100), "AA": (45, 60), "A": (30, 45),
        "BBB": (20, 30), "BB": (12, 20), "B": (6, 12), "CCC": (0, 6),
    },
    # Fixed Charge Coverage (EBITDA / Fixed Charges, higher is better)
    "fixed_charge_coverage": {
        "AAA": (15, 99), "AA": (10, 15), "A": (6, 10),
        "BBB": (3, 6), "BB": (1.5, 3), "B": (1.0, 1.5), "CCC": (0, 1.0),
    },
}

# --- Cache TTLs ---
CACHE_TTL_HOURS = {
    "fred_rates": 24,       # Daily data — refresh once a day
    "fred_macro": 168,      # Weekly is fine for macro
    "sec_filings": 720,     # Filings don't change — 30 days
}
