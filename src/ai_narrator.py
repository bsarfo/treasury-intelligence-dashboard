"""
AI Narrator — wraps Anthropic Claude API for credit narrative generation.

Design principle: every function returns useful output even if the API is
unavailable, the key is missing, or the call fails. Fallback templates
produce decent-but-static text from the same metric inputs.

Cost note: Claude Haiku 4.5 at ~$1/MTok input, $5/MTok output.
A typical narrative call is ~600 input tokens + ~300 output tokens
= ~$0.002 per call. The dashboard caches via @st.cache_data so a session
runs ~5-10 calls total.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from src.secrets_loader import get_secret


# Sentinel — None means "AI disabled"
def _get_client():
    """Returns an Anthropic client if key is set and library available, else None."""
    key = get_secret("ANTHROPIC_API_KEY", "")
    if not key or key == "your_anthropic_key_here" or len(key) < 20:
        return None
    try:
        from anthropic import Anthropic
        return Anthropic(api_key=key)
    except ImportError:
        return None
    except Exception:
        return None


def is_ai_enabled() -> bool:
    """Quick check for UI badges / status indicators."""
    return _get_client() is not None


# ============================================================================
# Core generator
# ============================================================================
def _generate(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 400,
    model: str = "claude-haiku-4-5-20251001",
) -> Optional[str]:
    """
    Single-call helper. Returns the generated text, or None on any failure.
    Callers should always have a fallback path.
    """
    client = _get_client()
    if client is None:
        return None

    try:
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return msg.content[0].text.strip()
    except Exception:
        return None


# ============================================================================
# 1. Key Message generator (audience-aware)
# ============================================================================
SYSTEM_KEY_MESSAGE = """You are a senior treasury analyst writing concise executive narratives for a credit dashboard. Your output must be:
- One paragraph, 50-75 words maximum
- Specific, data-driven (cite the actual numbers given)
- Audience-aware: match tone and emphasis to who's reading
- Forward-looking where possible (catalyst, watch-item, or thesis)
- No hedging language ("we believe", "potentially")
- Use HTML <b> tags for key numbers, not markdown

Do NOT include greetings, headers, or sign-offs. Just the paragraph."""


AUDIENCE_FOCUS = {
    "C-Level": "strategic positioning, rating trajectory, key catalyst",
    "Board": "risk vs target ranges, governance-relevant trends, quarter-over-quarter movement",
    "Lenders": "liquidity coverage, refinancing wall, covenant headroom",
    "Rating Agencies": "metric movement vs S&P thresholds, peer positioning, upgrade catalysts",
}


def generate_key_message(
    company_name: str,
    audience: str,
    current_rating: str,
    target_rating: str,
    implied_rating: str,
    net_debt_ebitda: float,
    ffo_debt_pct: float,
    fixed_charge_coverage: float,
    liquidity_coverage_ratio: float,
    cash: float,
    total_debt: float,
    near_term_maturities: float,
    ltm_ebitda: float,
) -> str:
    """Generate the headline Key Message banner text."""
    focus = AUDIENCE_FOCUS.get(audience, AUDIENCE_FOCUS["C-Level"])

    user_prompt = f"""Write a Key Message for the {audience} view of {company_name}'s treasury dashboard.

Emphasize: {focus}

Current credit profile:
- S&P Rating: {current_rating} (target: {target_rating}, metrics imply: {implied_rating})
- Net Debt / EBITDA: {net_debt_ebitda:.2f}x (S&P BBB threshold: <3.0x)
- FFO / Debt: {ffo_debt_pct:.1f}% (S&P BBB threshold: >20%)
- Fixed Charge Coverage: {fixed_charge_coverage:.2f}x
- Liquidity Coverage Ratio: {liquidity_coverage_ratio:.2f}x
- Cash: ${cash/1e9:.2f}B
- Total Debt: ${total_debt/1e9:.2f}B
- LTM EBITDA: ${ltm_ebitda/1e9:.2f}B
- Near-term debt maturities (next 24m): ${near_term_maturities/1e9:.2f}B

Write the paragraph now."""

    ai_text = _generate(SYSTEM_KEY_MESSAGE, user_prompt, max_tokens=250)
    if ai_text:
        return ai_text

    # ---- Fallback ----
    return _fallback_key_message(
        audience, current_rating, target_rating, implied_rating,
        net_debt_ebitda, ffo_debt_pct, fixed_charge_coverage,
        liquidity_coverage_ratio, near_term_maturities,
    )


def _fallback_key_message(
    audience, current_rating, target_rating, implied_rating,
    net_debt_ebitda, ffo_debt_pct, fcc, liq_cov, near_term_mat,
) -> str:
    """Hardcoded-but-data-aware template if AI unavailable."""
    if audience == "C-Level":
        return (f"Composite metrics imply a <b>{implied_rating}</b> profile vs current <b>{current_rating}</b>. "
                f"Net Debt/EBITDA at <b>{net_debt_ebitda:.2f}x</b> is the gating metric for upgrade to {target_rating}; "
                f"FFO/Debt at <b>{ffo_debt_pct:.1f}%</b> has already crossed S&P's BBB threshold.")
    elif audience == "Board":
        return (f"Leverage at <b>{net_debt_ebitda:.2f}x</b> Net Debt/EBITDA tracks toward S&P's <3.0x BBB band. "
                f"Liquidity coverage of <b>{liq_cov:.2f}x</b> supports near-term flexibility. "
                f"Two of three core credit metrics already at investment-grade levels.")
    elif audience == "Lenders":
        return (f"Liquidity Coverage <b>{liq_cov:.2f}x</b> (target >1.25x). Fixed Charge Coverage <b>{fcc:.2f}x</b>. "
                f"Near-term refinancing wall: <b>${near_term_mat/1e9:.2f}B</b> over 24 months — primary watch item. "
                f"Covenant headroom adequate at current cash generation pace.")
    else:  # Rating Agencies
        return (f"Current <b>{current_rating}</b> with metrics implying composite <b>{implied_rating}</b>. "
                f"Upgrade catalysts: sustained FFO/Debt above 20% (achieved at <b>{ffo_debt_pct:.1f}%</b>) "
                f"and leverage path to 3.0x (currently <b>{net_debt_ebitda:.2f}x</b>).")


# ============================================================================
# 2. Path-to-Upgrade Actions generator
# ============================================================================
SYSTEM_ACTIONS = """You are a credit strategist. Generate 4-6 specific, prioritized actions to achieve the next rating upgrade. Each action must:
- Be concrete and quantified where possible (specific $ amounts, ratios, timeframes)
- Identify the metric it impacts
- Be ordered by priority (High first)
- Be 1 sentence each

Output format: return a JSON array of objects with keys: action, impact, priority. Priority must be exactly "High" or "Medium" or "Low". Return ONLY the JSON, no preamble, no markdown fences."""


def generate_actions(
    company_name: str,
    current_rating: str,
    target_rating: str,
    net_debt_ebitda: float,
    ffo_debt_pct: float,
    fixed_charge_coverage: float,
    total_debt: float,
    ltm_ebitda: float,
    near_term_maturities: float,
    cash: float,
    weighted_avg_rate: float,
) -> list[dict]:
    """Returns list of {action, impact, priority} dicts. Always returns at least the fallback list."""
    user_prompt = f"""Company: {company_name}
Current rating: {current_rating} → Target: {target_rating}

Current metrics vs S&P BBB thresholds:
- Net Debt/EBITDA: {net_debt_ebitda:.2f}x (threshold: <3.0x) — gap to close: {max(0, net_debt_ebitda - 3.0):.2f}x
- FFO/Debt: {ffo_debt_pct:.1f}% (threshold: >20%) — {"above" if ffo_debt_pct > 20 else "below"} threshold
- Fixed Charge Coverage: {fixed_charge_coverage:.2f}x (threshold: >3.0x) — {"above" if fixed_charge_coverage > 3 else "below"}

Financials:
- Total Debt: ${total_debt/1e9:.2f}B
- LTM EBITDA: ${ltm_ebitda/1e9:.2f}B
- Near-term maturities (24m): ${near_term_maturities/1e9:.2f}B
- Cash: ${cash/1e9:.2f}B
- Weighted avg rate: {weighted_avg_rate*100:.2f}%

Generate prioritized actions. Calculate specific $ amounts in your actions where helpful (e.g., "reduce debt by $XB to bring leverage to Y.Yx")."""

    import json
    ai_text = _generate(SYSTEM_ACTIONS, user_prompt, max_tokens=600)
    if ai_text:
        try:
            # Strip any code fences just in case
            clean = ai_text.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean)
            if isinstance(data, list) and all("action" in d for d in data):
                return data
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    return _fallback_actions(net_debt_ebitda, ffo_debt_pct, total_debt,
                              ltm_ebitda, near_term_maturities, weighted_avg_rate)


def _fallback_actions(leverage, ffo_debt, total_debt, ebitda, near_term_mat, wtd_rate) -> list[dict]:
    """Data-aware fallback action list."""
    debt_reduction_needed = max(0, (leverage - 3.0)) * ebitda
    actions = []

    if leverage > 3.0:
        actions.append({
            "action": f"Reduce gross debt by ~${debt_reduction_needed/1e9:.1f}B over 24 months",
            "impact": f"Brings Net Debt/EBITDA from {leverage:.2f}x toward S&P's 3.0x BBB threshold",
            "priority": "High",
        })

    if near_term_mat > 2e9:
        wtd_rate_pct = wtd_rate * 100
        actions.append({
            "action": f"Refinance ${near_term_mat/1e9:.1f}B of near-term maturities at improved coupons",
            "impact": f"Current weighted avg rate is {wtd_rate_pct:.2f}% — 100bp save = ${near_term_mat * 0.01 / 1e6:.0f}M/yr to FFO",
            "priority": "High",
        })

    actions.append({
        "action": "Extend weighted average debt maturity beyond 5 years",
        "impact": "Reduces refinancing-cliff risk; supports liquidity & maturity profile",
        "priority": "High",
    })

    if ffo_debt < 20:
        actions.append({
            "action": f"Drive FFO/Debt above 20% via EBITDA growth or debt paydown",
            "impact": f"Currently {ffo_debt:.1f}% — must clear S&P's 20% BB/BBB boundary",
            "priority": "High",
        })
    else:
        actions.append({
            "action": "Sustain FFO/Debt above 20% for four consecutive quarters",
            "impact": f"Currently {ffo_debt:.1f}% — S&P typically requires durability before upgrade",
            "priority": "Medium",
        })

    actions.append({
        "action": "Maintain unrestricted cash + revolver availability > $3.5B",
        "impact": "Strengthens liquidity assessment; counters cyclical revenue risk",
        "priority": "Medium",
    })

    actions.append({
        "action": "Demonstrate consistent access to capital markets on favorable terms",
        "impact": "Validates financial flexibility — qualitative input to rating action",
        "priority": "Medium",
    })

    return actions


# ============================================================================
# 3. Risk Commentary generator
# ============================================================================
SYSTEM_RISK = """You are a treasury risk commentator. Write a 2-3 sentence read-out of where the company's risk concentrates, given the data below. Be concrete: name the dominant exposure and quantify it. Output HTML-safe plain text (use <b> for emphasis). No preamble."""


def generate_risk_commentary(
    variable_debt: float,
    annual_sofr_vol_bps: float,
    annual_var_usd: float,
    dominant_fx_currency: str,
    dominant_fx_pct: float,
    aggregate_fx_var: float,
    near_term_maturities: float,
) -> str:
    """Generate the Risk Dashboard read-out paragraph."""
    user_prompt = f"""Risk profile data:
- Variable-rate debt: ${variable_debt/1e9:.2f}B
- Annualized SOFR volatility: {annual_sofr_vol_bps:.0f} bps
- Annual interest expense VaR (95%): ${annual_var_usd/1e6:.0f}M
- Dominant FX exposure: {dominant_fx_currency} at {dominant_fx_pct:.1f}% of total FX
- Aggregate 10-day FX VaR (95%): ${aggregate_fx_var/1e6:.1f}M
- Near-term refinancing wall: ${near_term_maturities/1e9:.2f}B

Write the commentary now."""

    ai_text = _generate(SYSTEM_RISK, user_prompt, max_tokens=200)
    if ai_text:
        return ai_text

    return (f"Risk concentrates in three areas: rate sensitivity on <b>${variable_debt/1e9:.1f}B</b> of variable debt "
            f"(annual <b>${annual_var_usd/1e6:.0f}M</b> VaR), translation exposure dominated by <b>{dominant_fx_currency}</b> "
            f"at <b>{dominant_fx_pct:.0f}%</b> of FX, and refinancing of <b>${near_term_maturities/1e9:.1f}B</b> over 24 months. "
            f"FX VaR contained at <b>${aggregate_fx_var/1e6:.0f}M</b> — modest vs balance sheet scale.")


# ============================================================================
# Quick test
# ============================================================================
if __name__ == "__main__":
    print(f"AI enabled: {is_ai_enabled()}")
    if is_ai_enabled():
        print("\nTesting Key Message generation...")
        msg = generate_key_message(
            company_name="Carnival Corporation",
            audience="C-Level",
            current_rating="BB+",
            target_rating="BBB-",
            implied_rating="BB",
            net_debt_ebitda=3.35,
            ffo_debt_pct=21.2,
            fixed_charge_coverage=3.23,
            liquidity_coverage_ratio=1.28,
            cash=1.42e9,
            total_debt=25.29e9,
            near_term_maturities=4.03e9,
            ltm_ebitda=7.1e9,
        )
        print(f"\n[KEY MESSAGE]\n{msg}\n")
    else:
        print("AI disabled (no API key) — fallback templates will be used.")
        msg = _fallback_key_message(
            "C-Level", "BB+", "BBB-", "BB",
            3.35, 21.2, 3.23, 1.28, 4.03e9,
        )
        print(f"\n[FALLBACK KEY MESSAGE]\n{msg}\n")
