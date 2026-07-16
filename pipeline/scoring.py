"""Percentile engine + Panic/Fundamentals scoring + verdict.

Panic components are oriented so higher percentiles mean more panic."""

import numpy as np
import pandas as pd

import config

# component -> +1 (raw high = high score) / -1 (raw high = low score)
ORIENT_PANIC = {"term_structure": +1, "credit_velocity": +1, "vvix": +1,
                "breadth": -1, "put_call": +1, "vxn_ratio": +1,
                "vxn_level": +1, "pairwise_corr": +1}
# A +/-5% weighted EPS revision maps to the ends of the 0-100 scale.
REVISION_HORIZON_WEIGHTS = {30: .5, 60: .3, 90: .2}


def rolling_percentile(s: pd.Series,
                       window: int = config.PCTL_WINDOW_DAYS) -> pd.Series:
    """Percentile versus up to five years, after one full year of evidence."""
    def pct(x):
        return (x[:-1] <= x[-1]).mean() * 100
    minimum = min(window, config.MIN_PCTL_OBSERVATIONS)
    return s.dropna().rolling(window, min_periods=minimum).apply(pct, raw=True)


def score_components(raw: dict[str, pd.Series], orient: dict) -> pd.DataFrame:
    cols = {}
    for name, series in raw.items():
        if series is None or series.empty:
            continue
        p = rolling_percentile(series)
        cols[name] = p if orient.get(name, +1) > 0 else 100 - p
    return pd.DataFrame(cols)


def weighted_meter(pctls: pd.DataFrame, weights: dict,
                   minimum_coverage: float = config.MIN_PANIC_COMPONENT_COVERAGE
                   ) -> pd.Series:
    """Fixed-weight research series; incomplete rows are unavailable, not rescaled."""
    if pctls.empty or not weights:
        return pd.Series(dtype=float)
    w = pd.Series(weights, dtype=float)
    w = w / w.sum()
    values = pd.DataFrame(index=pctls.index)
    for name in w.index:
        values[name] = pctls[name] if name in pctls else np.nan
    values = values.ffill(limit=config.MAX_PANIC_STALE_BUSINESS_DAYS)
    coverage = values.notna().mul(w).sum(axis=1)
    score = values.fillna(0).mul(w).sum(axis=1)
    return score.where(coverage >= minimum_coverage - 1e-12)


def current_weighted_meter(pctls: pd.DataFrame, weights: dict,
                           provenance: dict | None = None) -> dict:
    """Latest fixed-weight reading at one as-of, with explicit freshness evidence."""
    provenance = provenance or {}
    w = pd.Series(weights, dtype=float)
    if pctls.empty or w.empty:
        return {"score": None, "asof": None, "coverage_pct": 0,
                "ready": False, "components": {}}
    w = w / w.sum()
    latest = {}
    for name in w.index:
        if name in pctls and not pctls[name].dropna().empty:
            latest[name] = pd.Timestamp(pctls[name].dropna().index[-1]).tz_localize(None)
    if not latest:
        return {"score": None, "asof": None, "coverage_pct": 0,
                "ready": False, "components": {}}

    asof = max(latest.values()).normalize()
    coverage = 0.0
    score = 0.0
    statuses = {}
    for name, weight in w.items():
        points = (pctls[name].dropna() if name in pctls
                  else pd.Series(dtype=float))
        observation = (pd.Timestamp(points.index[-1]).tz_localize(None).normalize()
                       if not points.empty else None)
        age = (int(np.busday_count(observation.date(), asof.date()))
               if observation is not None else None)
        fresh = age is not None and 0 <= age <= config.MAX_PANIC_STALE_BUSINESS_DAYS
        value = float(points.iloc[-1]) if fresh else None
        if fresh:
            coverage += float(weight)
            score += value * float(weight)
        statuses[name] = {
            "source": provenance.get(name, "unspecified"),
            "observation_date": observation.strftime("%Y-%m-%d")
            if observation is not None else None,
            "stale_business_days": age,
            "fresh": fresh,
            "weight_pct": round(float(weight) * 100, 1),
            "score": value,
        }

    ready = coverage >= config.MIN_PANIC_COMPONENT_COVERAGE - 1e-12
    return {
        "score": score if ready else None,
        "asof": asof.strftime("%Y-%m-%d"),
        "coverage_pct": coverage * 100,
        "ready": ready,
        "components": statuses,
    }


def fundamental_health(snapshot: dict) -> dict | None:
    """Consensus Earnings Health score, independent of price and valuation.

    Revision magnitude contributes 60% and upward-revision breadth 40%.
    Zero revision is neutral (50); +/-5% maps to 0/100. All horizons must use
    one sufficiently covered market-cap-proxy cohort.
    """
    breadth = snapshot.get("analyst_eps_revision_breadth_30d_pct")
    n = snapshot.get("n_analyst_trends", 0)
    common_coverage = snapshot.get("analyst_eps_common_coverage_pct", 0)
    common_cohort = snapshot.get("analyst_eps_common_cohort_pct", 0)
    revisions = {
        days: snapshot.get(f"analyst_eps_revision_{days}d_pct")
        for days in REVISION_HORIZON_WEIGHTS
    }
    if (breadth is None or any(value is None for value in revisions.values())
            or n < config.MIN_ANALYST_TRENDS
            or common_coverage < config.MIN_ANALYST_MARKET_CAP_COVERAGE * 100
            or common_cohort < config.MIN_ANALYST_TREND_COVERAGE * 100):
        return None

    revision_trend = sum(
        value * REVISION_HORIZON_WEIGHTS[days] for days, value in revisions.items()
    )
    revision_score = float(np.clip(50 + 10 * revision_trend, 0, 100))
    breadth_score = float(np.clip(breadth, 0, 100))
    score = .60 * revision_score + .40 * breadth_score
    return {
        "score": score,
        "revision_score": revision_score,
        "breadth_score": breadth_score,
        "revision_trend_pct": revision_trend,
        "coverage_pct": float(common_coverage),
        "common_cohort_pct": float(common_cohort),
    }


def fundamental_discrepancy(panic: float, fundamentals: float) -> float:
    """Positive when market stress exceeds the damage visible in EPS trends."""
    return fundamentals + panic - 100


def quadrant(panic: float, fundamentals: float) -> dict:
    hot = panic >= config.PANIC_HIGH
    healthy = fundamentals >= config.FUNDAMENTALS_HEALTHY
    broken = fundamentals <= config.FUNDAMENTALS_BROKEN
    if hot and healthy:
        code, label = "golden", "CANDIDATE DISLOCATION: fear exceeds earnings damage"
    elif hot and broken:
        code, label = "fire", "REAL FIRE: fundamentals breaking, respect it"
    elif hot:
        code, label = "watch", "WATCH: panic is high, fundamentals are mixed"
    elif not hot and broken:
        code, label = "trap", "COMPLACENCY TRAP: calm surface, deteriorating floor"
    else:
        code, label = "normal", "NORMAL: no edge from sentiment, do bottom-up work"
    return {"code": code, "label": label}


def verdict(panic: float, fundamentals: float, discrepancy: float) -> str:
    q = quadrant(panic, fundamentals)["code"]
    if q == "golden":
        return (f"Panic {panic:.0f} / Consensus Earnings Health "
                f"{fundamentals:.0f}, Discrepancy {discrepancy:+.1f}pts. "
                "Candidate dislocation for valuation and risk review, not an "
                "automatic deployment signal.")
    if q == "fire":
        return (f"Panic {panic:.0f} / Consensus Earnings Health "
                f"{fundamentals:.0f}. EPS revisions and breadth are "
                "deteriorating; treat this as a research warning.")
    if q == "watch":
        return (f"Panic {panic:.0f} / Consensus Earnings Health {fundamentals:.0f}. "
                "Stress is elevated, but earnings evidence is mixed. Wait for "
                "revision direction and breadth to agree.")
    if q == "trap":
        return (f"Panic {panic:.0f} / Consensus Earnings Health "
                f"{fundamentals:.0f}. Calm prices and weak revisions warrant "
                "deeper risk review, not an automatic exposure change.")
    return (f"Panic {panic:.0f} / Consensus Earnings Health {fundamentals:.0f}, "
            f"Discrepancy {discrepancy:+.1f}pts. Sentiment offers no "
            f"edge; decisions belong to stock selection.")
