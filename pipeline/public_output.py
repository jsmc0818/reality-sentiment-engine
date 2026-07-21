"""Validate and atomically publish website-safe market data."""

import json
import math
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config


REFRESH_POLICY = {
    "mode": "scheduled_static_publication",
    "stale_after_business_days": config.MAX_PUBLICATION_STALE_BUSINESS_DAYS,
    "schedule": "weekdays_after_us_close",
}
TIMELINE_SCHEMA_VERSION = 1
TIMELINE_ENTRY_KEYS = {
    "date", "panic", "fundamentals", "fundamental_discrepancy",
}
SCOPE_KEYS = {
    "panic", "fundamentals", "fundamental_discrepancy", "coverage",
    "quadrant", "verdict", "analyst_eps", "components", "data_quality",
}
COVERAGE_KEYS = {
    "panic_pct", "panic_ready", "panic_asof", "fundamentals_pct",
    "fundamentals_common_weight_pct", "fundamentals_common_cohort_pct",
    "fundamentals_ready",
    "entry_history_snapshot_count", "entry_history_snapshot_minimum",
}
ANALYST_KEYS = {
    "analyst_eps_revision_7d_pct", "analyst_eps_revision_30d_pct",
    "analyst_eps_revision_60d_pct", "analyst_eps_revision_90d_pct",
    "analyst_eps_revision_30d_coverage_pct", "analyst_eps_revision_60d_coverage_pct",
    "analyst_eps_revision_90d_coverage_pct", "analyst_eps_common_coverage_pct",
    "analyst_eps_common_cohort_pct", "analyst_eps_up_breadth_30d_pct",
    "analyst_eps_neutral_breadth_30d_pct", "analyst_eps_down_breadth_30d_pct",
    "analyst_eps_revision_breadth_30d_pct", "analyst_eps_target_weight_pct",
    "n_analyst_trends",
}
ANALYST_REQUIRED_KEYS = ANALYST_KEYS - {"analyst_eps_revision_7d_pct"}
COMPONENT_KEYS = {
    "panic": {
        "term_structure", "credit_velocity", "vvix", "breadth", "put_call",
        "vxn_ratio", "vxn_level", "pairwise_corr",
    },
    "fundamentals": {"revision_score", "revision_breadth"},
    "entry": {"forward_pe", "trailing_pe", "equity_risk_premium_pts",
              "divergence_pts"},
}
DATA_QUALITY_KEYS = {
    "constituent_hash", "constituent_count", "market_cap_proxy_count",
    "constituent_price_count", "constituent_price_coverage_pct",
    "eps_source", "eps_observation_date", "panic_components",
}
PANIC_QUALITY_KEYS = {
    "source", "observation_date", "stale_business_days", "fresh", "weight_pct",
}


def build_public_payload(scopes: dict, asof: str) -> dict:
    return {
        "asof": asof,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "refresh_policy": REFRESH_POLICY.copy(),
        "scopes": scopes,
    }


def build_timeline_payload(previous: dict | None, scopes: dict, asof: str) -> dict:
    """Append one real published reading per scope, replacing same-day reruns."""
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    history = ({scope: [] for scope in config.SCOPES} if not previous
               else {scope: list(previous["scopes"][scope]) for scope in config.SCOPES})
    for scope in config.SCOPES:
        reading = scopes[scope]
        point = {
            "date": asof,
            "panic": reading["panic"],
            "fundamentals": reading["fundamentals"],
            "fundamental_discrepancy": reading["fundamental_discrepancy"],
        }
        history[scope] = [item for item in history[scope] if item["date"] != asof]
        history[scope].append(point)
        history[scope].sort(key=lambda item: item["date"])
    first_date = min(item["date"] for points in history.values() for item in points)
    return {
        "schema_version": TIMELINE_SCHEMA_VERSION,
        "generated_at_utc": generated,
        "methodology_start": first_date,
        "scopes": history,
    }


def _keys(value, expected, location, exact=True):
    if not isinstance(value, dict):
        raise ValueError(f"{location} must be an object")
    actual = set(value)
    valid = actual == set(expected) if exact else actual <= set(expected)
    if not valid:
        raise ValueError(f"{location} contains missing or unsupported fields")


def _number(value, location, low=0, high=100):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not low <= value <= high):
        raise ValueError(f"{location} must be a finite number in [{low}, {high}]")


def _business_days_between(start, end) -> int:
    count = 0
    day = start
    while day < end:
        if day.weekday() < 5:
            count += 1
        day += timedelta(days=1)
    return count


def validate_public_payload(payload: dict) -> None:
    """Strict allowlists keep personal data and arbitrary API output out."""
    _keys(payload, {"asof", "generated_at_utc", "refresh_policy", "scopes"}, "root")
    asof_date = datetime.strptime(payload["asof"], "%Y-%m-%d").date()
    datetime.fromisoformat(payload["generated_at_utc"].replace("Z", "+00:00"))
    if payload["refresh_policy"] != REFRESH_POLICY:
        raise ValueError("refresh policy is not approved")
    _keys(payload["scopes"], config.SCOPES, "scopes")

    for scope, reading in payload["scopes"].items():
        _keys(reading, SCOPE_KEYS, scope)
        _number(reading["panic"], f"{scope}.panic")
        _number(reading["fundamentals"], f"{scope}.fundamentals")
        _number(reading["fundamental_discrepancy"],
                f"{scope}.fundamental_discrepancy", -100, 100)
        expected_gap = reading["panic"] + reading["fundamentals"] - 100
        if abs(reading["fundamental_discrepancy"] - expected_gap) > .11:
            raise ValueError(f"{scope}.fundamental_discrepancy is inconsistent")
        if not isinstance(reading["verdict"], str) or not reading["verdict"].strip():
            raise ValueError(f"{scope}.verdict must be market commentary")

        coverage = reading["coverage"]
        _keys(coverage, COVERAGE_KEYS, f"{scope}.coverage")
        _number(coverage["panic_pct"], f"{scope}.panic coverage")
        _number(coverage["fundamentals_pct"], f"{scope}.fundamentals coverage")
        _number(coverage["fundamentals_common_weight_pct"],
                f"{scope}.fundamentals common weight")
        _number(coverage["fundamentals_common_cohort_pct"],
                f"{scope}.fundamentals common cohort")
        for key in ("panic_ready", "fundamentals_ready"):
            if coverage[key] is not True:
                raise ValueError(f"{scope}.{key} must be true for publication")
        datetime.strptime(coverage["panic_asof"], "%Y-%m-%d")
        if coverage["panic_asof"] != payload["asof"]:
            raise ValueError(f"{scope}.panic_asof must match the public asof")
        if coverage["panic_pct"] < config.MIN_PANIC_COMPONENT_COVERAGE * 100:
            raise ValueError(f"{scope}.panic coverage is below the fixed-weight gate")
        if abs(coverage["fundamentals_pct"]
               - coverage["fundamentals_common_weight_pct"]) > .51:
            raise ValueError(f"{scope}.fundamentals coverage fields disagree")
        _number(coverage["entry_history_snapshot_count"],
                f"{scope}.entry history count", 0, 100000)
        _number(coverage["entry_history_snapshot_minimum"],
                f"{scope}.entry history minimum", 1, 100000)

        quadrant = reading["quadrant"]
        _keys(quadrant, {"code", "label"}, f"{scope}.quadrant")
        if quadrant["code"] not in {"golden", "fire", "watch", "trap", "normal"}:
            raise ValueError(f"{scope}.quadrant code is invalid")
        if not isinstance(quadrant["label"], str):
            raise ValueError(f"{scope}.quadrant label must be text")
        hot = reading["panic"] >= config.PANIC_HIGH
        near = reading["panic"] >= config.PANIC_WATCH
        healthy = reading["fundamentals"] >= config.FUNDAMENTALS_HEALTHY
        broken = reading["fundamentals"] <= config.FUNDAMENTALS_BROKEN
        expected_quadrant = ("golden" if hot and healthy else "fire" if hot and broken
                             else "watch" if hot or near
                             else "trap" if broken else "normal")
        if quadrant["code"] != expected_quadrant:
            raise ValueError(f"{scope}.quadrant is inconsistent with the scores")

        analyst = reading["analyst_eps"]
        _keys(analyst, ANALYST_KEYS, f"{scope}.analyst_eps", exact=False)
        if not ANALYST_REQUIRED_KEYS <= set(analyst):
            raise ValueError(f"{scope}.analyst_eps is missing required evidence")
        for key, value in analyst.items():
            low, high = ((0, config.TOP_N_FOR_ANALYST_TRENDS)
                         if key == "n_analyst_trends" else (-100, 100))
            if ("coverage_pct" in key or "cohort_pct" in key or "breadth" in key
                    or key == "analyst_eps_target_weight_pct"):
                low, high = 0, 100
            _number(value, f"{scope}.{key}", low, high)
        breadth_total = sum(analyst[key] for key in (
            "analyst_eps_up_breadth_30d_pct",
            "analyst_eps_neutral_breadth_30d_pct",
            "analyst_eps_down_breadth_30d_pct",
        ))
        if abs(breadth_total - 100) > .2:
            raise ValueError(f"{scope}.analyst breadth must sum to 100")
        expected_breadth = (analyst["analyst_eps_up_breadth_30d_pct"]
                            + .5 * analyst["analyst_eps_neutral_breadth_30d_pct"])
        if abs(analyst["analyst_eps_revision_breadth_30d_pct"]
               - expected_breadth) > .11:
            raise ValueError(f"{scope}.analyst revision breadth is inconsistent")
        if analyst["n_analyst_trends"] < config.MIN_ANALYST_TRENDS:
            raise ValueError(f"{scope}.analyst trend count is below the gate")
        if (analyst["analyst_eps_common_coverage_pct"]
                < config.MIN_ANALYST_MARKET_CAP_COVERAGE * 100):
            raise ValueError(f"{scope}.analyst market-cap coverage is below the gate")
        if (analyst["analyst_eps_common_cohort_pct"]
                < config.MIN_ANALYST_TREND_COVERAGE * 100):
            raise ValueError(f"{scope}.analyst cohort coverage is below the gate")

        components = reading["components"]
        _keys(components, COMPONENT_KEYS, f"{scope}.components")
        for group, allowed in COMPONENT_KEYS.items():
            exact = group != "entry"
            expected = config.PANIC_WEIGHTS[scope] if group == "panic" else allowed
            _keys(components[group], expected, f"{scope}.{group}", exact=exact)
            for key, value in components[group].items():
                if group == "entry":
                    low, high = ((0, 500) if key in {"forward_pe", "trailing_pe"}
                                 else (-200, 200))
                    _number(value, f"{scope}.{group}.{key}", low, high)
                else:
                    _number(value, f"{scope}.{group}.{key}")
        expected_panic = sum(
            components["panic"][name] * weight
            for name, weight in config.PANIC_WEIGHTS[scope].items()
        )
        if abs(reading["panic"] - expected_panic) > .11:
            raise ValueError(f"{scope}.panic is inconsistent with its components")
        expected_fundamentals = (
            .60 * components["fundamentals"]["revision_score"]
            + .40 * components["fundamentals"]["revision_breadth"]
        )
        if abs(reading["fundamentals"] - expected_fundamentals) > .11:
            raise ValueError(f"{scope}.fundamentals is inconsistent with its components")

        quality = reading["data_quality"]
        _keys(quality, DATA_QUALITY_KEYS, f"{scope}.data_quality")
        if not (isinstance(quality["constituent_hash"], str)
                and re.fullmatch(r"[0-9a-f]{64}", quality["constituent_hash"])):
            raise ValueError(f"{scope}.constituent_hash must be sha256 hex")
        _number(quality["constituent_count"], f"{scope}.constituent count", 1, 1000)
        _number(quality["market_cap_proxy_count"],
                f"{scope}.market cap proxy count", 1, quality["constituent_count"])
        if (quality["market_cap_proxy_count"] / quality["constituent_count"]
                < config.MIN_MARKET_CAP_PROXY_NAME_COVERAGE):
            raise ValueError(f"{scope}.market cap proxy coverage is below the gate")
        _number(quality["constituent_price_count"],
                f"{scope}.constituent price count", 1, quality["constituent_count"])
        _number(quality["constituent_price_coverage_pct"],
                f"{scope}.constituent price coverage")
        expected_price_coverage = (
            quality["constituent_price_count"] / quality["constituent_count"] * 100
        )
        if abs(quality["constituent_price_coverage_pct"]
               - expected_price_coverage) > .11:
            raise ValueError(f"{scope}.constituent price coverage is inconsistent")
        minimum_price_coverage = (
            config.MIN_MAG7_PRICE_COVERAGE if scope == "mag7"
            else config.MIN_CONSTITUENT_PRICE_COVERAGE
        )
        if quality["constituent_price_coverage_pct"] < minimum_price_coverage * 100:
            raise ValueError(f"{scope}.constituent price coverage is below the gate")
        if not isinstance(quality["eps_source"], str) or not quality["eps_source"].strip():
            raise ValueError(f"{scope}.eps_source must be text")
        expected_eps_source = (
            f"yfinance_market_cap_proxy_ranked_{quality['constituent_hash'][:12]}"
        )
        if quality["eps_source"] != expected_eps_source:
            raise ValueError(f"{scope}.eps_source does not match the constituent set")
        eps_date = datetime.strptime(quality["eps_observation_date"], "%Y-%m-%d").date()
        if eps_date != asof_date:
            raise ValueError(f"{scope}.eps_observation_date must match the public asof")
        _keys(quality["panic_components"], config.PANIC_WEIGHTS[scope],
              f"{scope}.panic quality")
        total_weight = 0.0
        for component, status in quality["panic_components"].items():
            location = f"{scope}.panic quality.{component}"
            _keys(status, PANIC_QUALITY_KEYS, location)
            if not isinstance(status["source"], str) or not status["source"].strip():
                raise ValueError(f"{location}.source must be text")
            observation_date = datetime.strptime(
                status["observation_date"], "%Y-%m-%d"
            ).date()
            if observation_date > asof_date:
                raise ValueError(f"{location}.observation_date is after the public asof")
            _number(status["stale_business_days"], f"{location}.staleness",
                    0, config.MAX_PANIC_STALE_BUSINESS_DAYS)
            expected_staleness = _business_days_between(observation_date, asof_date)
            if status["stale_business_days"] != expected_staleness:
                raise ValueError(f"{location}.staleness is inconsistent")
            if status["fresh"] is not True:
                raise ValueError(f"{location} must be fresh for publication")
            if status["source"] != config.PANIC_PROVENANCE[component]:
                raise ValueError(f"{location}.source is not approved")
            _number(status["weight_pct"], f"{location}.weight")
            expected_weight = config.PANIC_WEIGHTS[scope][component] * 100
            if abs(status["weight_pct"] - expected_weight) > .11:
                raise ValueError(f"{location}.weight does not match production")
            total_weight += status["weight_pct"]
        if abs(total_weight - 100) > .11:
            raise ValueError(f"{scope}.panic component weights must sum to 100")


def validate_timeline_payload(payload: dict) -> None:
    """Validate the small, prospective history consumed by the public chart."""
    _keys(payload, {"schema_version", "generated_at_utc", "methodology_start", "scopes"},
          "timeline root")
    if payload["schema_version"] != TIMELINE_SCHEMA_VERSION:
        raise ValueError("timeline schema version is unsupported")
    datetime.fromisoformat(payload["generated_at_utc"].replace("Z", "+00:00"))
    start = datetime.strptime(payload["methodology_start"], "%Y-%m-%d").date()
    _keys(payload["scopes"], config.SCOPES, "timeline scopes")
    for scope, points in payload["scopes"].items():
        if not isinstance(points, list) or not points:
            raise ValueError(f"timeline.{scope} must contain at least one real reading")
        dates = []
        for index, point in enumerate(points):
            location = f"timeline.{scope}[{index}]"
            _keys(point, TIMELINE_ENTRY_KEYS, location)
            date = datetime.strptime(point["date"], "%Y-%m-%d").date()
            if date < start:
                raise ValueError(f"{location}.date predates the methodology")
            dates.append(date)
            _number(point["panic"], f"{location}.panic")
            _number(point["fundamentals"], f"{location}.fundamentals")
            _number(point["fundamental_discrepancy"],
                    f"{location}.fundamental_discrepancy", -100, 100)
            expected = point["panic"] + point["fundamentals"] - 100
            if abs(point["fundamental_discrepancy"] - expected) > .11:
                raise ValueError(f"{location}.fundamental_discrepancy is inconsistent")
        if dates != sorted(set(dates)):
            raise ValueError(f"timeline.{scope} dates must be unique and ordered")


def validate_public_timeline_pair(public: dict, timeline: dict) -> None:
    """Require the chart history to end at the exact published reading."""
    validate_public_payload(public)
    validate_timeline_payload(timeline)
    for scope in config.SCOPES:
        latest = timeline["scopes"][scope][-1]
        reading = public["scopes"][scope]
        if latest["date"] != public["asof"]:
            raise ValueError(f"timeline.{scope} does not end at the public asof")
        for key in ("panic", "fundamentals", "fundamental_discrepancy"):
            if abs(latest[key] - reading[key]) > .11:
                raise ValueError(f"timeline.{scope}.{key} does not match public data")


def write_public_payload(path, payload) -> None:
    """A rejected or interrupted update leaves the prior file untouched."""
    validate_public_payload(payload)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n",
                             encoding="utf-8")
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def write_timeline_payload(path, payload) -> None:
    validate_timeline_payload(payload)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n",
                             encoding="utf-8")
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main() -> None:
    if len(sys.argv) not in {2, 3}:
        raise SystemExit(
            "usage: python -m pipeline.public_output data/scores.json [data/timeline.json]"
        )
    public = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if len(sys.argv) == 3:
        timeline = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        validate_public_timeline_pair(public, timeline)
    else:
        validate_public_payload(public)
    print(f"validated public market-data contract: {' '.join(sys.argv[1:])}")


if __name__ == "__main__":
    main()
