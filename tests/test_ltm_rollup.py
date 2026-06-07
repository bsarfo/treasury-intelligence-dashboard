"""
Test the LTM rollup logic against Carnival-shaped synthetic data.

The bug we're fixing: previous version summed last 4 rows regardless of period
type, causing 10-K (full-year) and 10-Q (single-quarter) rows to be combined,
inflating LTM totals by ~50-100%.

Ground truth for Carnival (from 8-K press release, March 2026):
  - Q1 2026 revenue = $6.2B
  - FY 2026 EBITDA guidance = ~$7B
  - LTM revenue (Q1 FY26 as anchor) ≈ $25-26B
"""
import sys
import pandas as pd
sys.path.insert(0, ".")

from src.data_loader import _ltm_rollup


def make_fact_row(end_date, value, form, fp, fy=None):
    return {
        "end_date": pd.Timestamp(end_date),
        "value": value,
        "form": form,
        "fp": fp,
        "fy": fy,
        "filed_date": pd.Timestamp(end_date) + pd.Timedelta(days=45),
    }


def test_carnival_revenue_ltm():
    """
    Simulate Carnival's actual quarterly revenue pattern.
    FY2024 = $25.0B annual, FY2025 = $25.0B annual, Q1 2026 = $6.2B
    LTM (as of Feb 28, 2026) should ≈ $25.4B
    (= FY25 $25.0B + Q1 26 $6.2B - Q1 25 $5.8B)
    """
    rows = [
        # FY2024 quarters (Carnival's fiscal year ends Nov 30)
        make_fact_row("2024-02-29", 5_400_000_000, "10-Q", "Q1", 2024),
        make_fact_row("2024-05-31", 5_800_000_000, "10-Q", "Q2", 2024),
        make_fact_row("2024-08-31", 7_900_000_000, "10-Q", "Q3", 2024),
        make_fact_row("2024-11-30", 25_000_000_000, "10-K", "FY", 2024),  # Annual!
        # FY2025 quarters
        make_fact_row("2025-02-28", 5_800_000_000, "10-Q", "Q1", 2025),
        make_fact_row("2025-05-31", 6_300_000_000, "10-Q", "Q2", 2025),
        make_fact_row("2025-08-31", 8_100_000_000, "10-Q", "Q3", 2025),
        make_fact_row("2025-11-30", 25_000_000_000, "10-K", "FY", 2025),  # Annual!
        # FY2026 Q1
        make_fact_row("2026-02-28", 6_200_000_000, "10-Q", "Q1", 2026),
    ]
    df = pd.DataFrame(rows)
    ltm, anchor = _ltm_rollup(df)

    print(f"  LTM Revenue: ${ltm/1e9:.2f}B  (expected ~$25.4B)")
    print(f"  Anchor date: {anchor.date() if anchor else 'None'}")

    # Should be FY25 + Q1 26 - Q1 25 = 25.0 + 6.2 - 5.8 = 25.4B
    assert 24_500_000_000 < ltm < 26_500_000_000, f"LTM revenue {ltm/1e9:.2f}B is wildly wrong"
    print("  ✓ PASS: LTM revenue is in correct range")


def test_carnival_ebitda_ltm():
    """
    Carnival LTM EBITDA should land near $6.5-7B (consistent with 2026 guidance of $7B).
    """
    # Operating income + D&A pattern
    op_income_rows = [
        make_fact_row("2024-02-29", 380_000_000, "10-Q", "Q1", 2024),
        make_fact_row("2024-05-31", 560_000_000, "10-Q", "Q2", 2024),
        make_fact_row("2024-08-31", 1_900_000_000, "10-Q", "Q3", 2024),
        make_fact_row("2024-11-30", 3_300_000_000, "10-K", "FY", 2024),
        make_fact_row("2025-02-28", 543_000_000, "10-Q", "Q1", 2025),
        make_fact_row("2025-05-31", 800_000_000, "10-Q", "Q2", 2025),
        make_fact_row("2025-08-31", 2_100_000_000, "10-Q", "Q3", 2025),
        make_fact_row("2025-11-30", 3_500_000_000, "10-K", "FY", 2025),
        make_fact_row("2026-02-28", 607_000_000, "10-Q", "Q1", 2026),
    ]
    op_ltm, _ = _ltm_rollup(pd.DataFrame(op_income_rows))
    print(f"  LTM Op Income: ${op_ltm/1e9:.2f}B  (expected ~$3.5B)")
    assert 3_000_000_000 < op_ltm < 4_500_000_000, f"LTM OI {op_ltm/1e9:.2f}B is wrong"

    # D&A: relatively stable ~$2.7B/year
    da_rows = [
        make_fact_row("2024-02-29", 600_000_000, "10-Q", "Q1", 2024),
        make_fact_row("2024-05-31", 650_000_000, "10-Q", "Q2", 2024),
        make_fact_row("2024-08-31", 700_000_000, "10-Q", "Q3", 2024),
        make_fact_row("2024-11-30", 2_650_000_000, "10-K", "FY", 2024),
        make_fact_row("2025-02-28", 660_000_000, "10-Q", "Q1", 2025),
        make_fact_row("2025-05-31", 670_000_000, "10-Q", "Q2", 2025),
        make_fact_row("2025-08-31", 680_000_000, "10-Q", "Q3", 2025),
        make_fact_row("2025-11-30", 2_700_000_000, "10-K", "FY", 2025),
        make_fact_row("2026-02-28", 696_000_000, "10-Q", "Q1", 2026),
    ]
    da_ltm, _ = _ltm_rollup(pd.DataFrame(da_rows))
    print(f"  LTM D&A:       ${da_ltm/1e9:.2f}B  (expected ~$2.7B)")

    ebitda = op_ltm + da_ltm
    print(f"  LTM EBITDA:    ${ebitda/1e9:.2f}B  (expected ~$6-7B)")
    assert 5_500_000_000 < ebitda < 7_500_000_000, f"LTM EBITDA {ebitda/1e9:.2f}B is wrong"
    print("  ✓ PASS: LTM EBITDA in correct range")


def test_interest_expense_ltm():
    """Carnival LTM interest expense should be ~$1.6-1.8B (down from peak)."""
    rows = [
        make_fact_row("2024-02-29", 540_000_000, "10-Q", "Q1", 2024),
        make_fact_row("2024-05-31", 520_000_000, "10-Q", "Q2", 2024),
        make_fact_row("2024-08-31", 500_000_000, "10-Q", "Q3", 2024),
        make_fact_row("2024-11-30", 2_000_000_000, "10-K", "FY", 2024),
        make_fact_row("2025-02-28", 471_000_000, "10-Q", "Q1", 2025),
        make_fact_row("2025-05-31", 450_000_000, "10-Q", "Q2", 2025),
        make_fact_row("2025-08-31", 430_000_000, "10-Q", "Q3", 2025),
        make_fact_row("2025-11-30", 1_750_000_000, "10-K", "FY", 2025),
        make_fact_row("2026-02-28", 400_000_000, "10-Q", "Q1", 2026),
    ]
    ltm, _ = _ltm_rollup(pd.DataFrame(rows))
    print(f"  LTM Interest:  ${ltm/1e9:.2f}B  (expected ~$1.7B)")
    assert 1_400_000_000 < ltm < 2_000_000_000, f"LTM interest {ltm/1e9:.2f}B is wrong"
    print("  ✓ PASS: LTM interest in correct range")


def test_only_quarters_no_annual():
    """Edge case: company hasn't filed an annual yet — only quarters."""
    rows = [
        make_fact_row("2025-02-28", 5_000_000_000, "10-Q", "Q1", 2025),
        make_fact_row("2025-05-31", 5_000_000_000, "10-Q", "Q2", 2025),
        make_fact_row("2025-08-31", 5_000_000_000, "10-Q", "Q3", 2025),
        make_fact_row("2025-11-30", 5_000_000_000, "10-Q", "Q4", 2025),
    ]
    ltm, _ = _ltm_rollup(pd.DataFrame(rows))
    print(f"  LTM (4 quarters, no FY): ${ltm/1e9:.2f}B (expected $20B)")
    assert ltm == 20_000_000_000, f"Should sum to exactly $20B, got {ltm/1e9}B"
    print("  ✓ PASS: 4-quarter sum works")


def test_only_annual_no_recent_quarters():
    """Edge case: only have a 10-K, no quarters after it."""
    rows = [
        make_fact_row("2025-11-30", 25_000_000_000, "10-K", "FY", 2025),
    ]
    ltm, _ = _ltm_rollup(pd.DataFrame(rows))
    print(f"  LTM (only FY): ${ltm/1e9:.2f}B (expected $25B)")
    assert ltm == 25_000_000_000
    print("  ✓ PASS: Annual-only fallback works")


if __name__ == "__main__":
    print("=" * 60)
    print("LTM Rollup Test Suite")
    print("=" * 60)
    print("\nTest 1: Carnival Revenue (Q1 26 + FY25 - Q1 25 method)")
    test_carnival_revenue_ltm()
    print("\nTest 2: Carnival EBITDA build-up")
    test_carnival_ebitda_ltm()
    print("\nTest 3: Carnival Interest Expense")
    test_interest_expense_ltm()
    print("\nTest 4: Edge case — only quarters, no annual")
    test_only_quarters_no_annual()
    print("\nTest 5: Edge case — only annual, no quarters")
    test_only_annual_no_recent_quarters()
    print("\n" + "=" * 60)
    print("✅ All LTM tests passed!")
    print("=" * 60)
