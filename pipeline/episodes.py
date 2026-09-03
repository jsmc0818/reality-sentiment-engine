"""Prospective validation by distinct Candidate Dislocation episodes."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import config


HORIZONS = {21: "1m", 63: "3m", 126: "6m"}


def candidate_episodes(points: list[dict]) -> list[dict]:
    """Collapse autocorrelated daily flags into independent state entries."""
    hot = False
    active = None
    episodes = []
    for point in sorted(points, key=lambda item: item["date"]):
        hot = point["panic"] >= config.PANIC_HIGH or (
            hot and point["panic"] >= config.PANIC_HIGH_EXIT
        )
        candidate = hot and point["fundamentals"] >= config.FUNDAMENTALS_SPLIT
        if candidate and active is None:
            active = {
                "signal_date": point["date"],
                "signal_panic": point["panic"],
                "signal_fundamentals": point["fundamentals"],
            }
        elif not candidate and active is not None:
            active["state_exit_date"] = point["date"]
            episodes.append(active)
            active = None
    if active is not None:
        active["state_exit_date"] = None
        episodes.append(active)
    return episodes


def _normalize_prices(prices: pd.Series) -> pd.Series:
    clean = prices.dropna().copy()
    index = pd.DatetimeIndex(clean.index)
    if index.tz is not None:
        index = index.tz_convert(None)
    clean.index = index.normalize()
    return clean[~clean.index.duplicated(keep="last")].sort_index()


def _episode_outcomes(episode: dict, prices: pd.Series,
                      benchmark: pd.Series) -> dict:
    prices = _normalize_prices(prices)
    benchmark = _normalize_prices(benchmark)
    after_signal = prices[prices.index > pd.Timestamp(episode["signal_date"])]
    result = dict(episode)
    if after_signal.empty:
        result["status"] = "pending_entry"
        return result

    entry_date = after_signal.index[0]
    path = prices.loc[entry_date:]
    result["entry_date"] = entry_date.strftime("%Y-%m-%d")
    result["entry_price"] = round(float(path.iloc[0]), 4)
    drawdown = path.iloc[:127] / path.iloc[:127].cummax() - 1
    result["max_drawdown_to_date_pct"] = round(float(drawdown.min() * 100), 2)

    completed = 0
    for sessions, label in HORIZONS.items():
        if len(path) <= sessions:
            continue
        end_date = path.index[sessions]
        absolute = path.iloc[sessions] / path.iloc[0] - 1
        result[f"return_{label}_pct"] = round(float(absolute * 100), 2)
        benchmark_window = benchmark.reindex([entry_date, end_date], method="ffill")
        if benchmark_window.notna().all():
            benchmark_return = benchmark_window.iloc[1] / benchmark_window.iloc[0] - 1
            result[f"excess_vs_sp500_{label}_pct"] = round(
                float((absolute - benchmark_return) * 100), 2
            )
        completed = sessions
    result["status"] = "complete" if completed == max(HORIZONS) else "maturing"
    return result


def build_episode_report(timeline: dict, prices: dict[str, pd.Series],
                         benchmark: pd.Series, previous: dict | None = None) -> dict:
    scopes = {}
    for scope in config.SCOPES:
        episodes = candidate_episodes(timeline["scopes"][scope])
        scopes[scope] = {
            "episode_count": len(episodes),
            "episodes": [
                _episode_outcomes(episode, prices[scope], benchmark)
                for episode in episodes
            ],
        }
    methodology = {
        "methodology_start": timeline["methodology_start"],
        "scopes": scopes,
    }
    methodologies = dict((previous or {}).get("methodologies", {}))
    if previous and "scopes" in previous:
        methodologies["timeline_v1"] = {
            "methodology_start": previous["methodology_start"],
            "scopes": previous["scopes"],
        }
    methodologies[f"timeline_v{timeline['schema_version']}"] = methodology
    return {
        "schema_version": 2,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entry_rule": "first close after a Candidate Dislocation state begins",
        "horizons_sessions": list(HORIZONS),
        "methodologies": methodologies,
    }


def write_episode_report(path, report: dict) -> None:
    """Write atomically so a failed run cannot corrupt the research record."""
    destination = Path(path)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n",
                         encoding="utf-8")
    temporary.replace(destination)
