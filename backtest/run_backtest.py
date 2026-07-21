"""Exploratory historical weight diagnostic.

Run: python -m backtest.run_backtest

The report deliberately separates three questions:

1. Which individual components have useful rank IC?
2. Which joint weights look best using training data only?
3. Does that candidate still win when 2022-present is untouched and repeated
   days from one panic are counted as one independent 3-month research signal?

This script can show whether a candidate clears a statistical comparison
screen. It cannot promote weights from the current dataset because constituent
history backfills today's members and Shiller earnings are current-vintage.
This legacy proxy study does not validate the live Consensus Earnings Health
metric, forecast the market, or authorize an allocation action.
"""

import json
import os

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

import config
from backtest.build_history import next_close_forward_return
from pipeline import scoring as S

PANIC_COLS = {
    "term_structure": +1,
    "credit_velocity": +1,
    "vvix": +1,
    "breadth_sp500": -1,
    "put_call": +1,
}
REALITY_COLS = {
    "divergence_proxy": +1,
    "erp_proxy": +1,
    "sector_correlation": +1,
    # Negative quality-minus-speculation returns mean indiscriminate selling.
    "quality_spread": -1,
}

EPISODES = {
    "Dec 2018": ("2018-12-01", "2018-12-31"),
    "Mar 2020": ("2020-03-01", "2020-03-31"),
    "2022 bear": ("2022-06-01", "2022-06-30"),
    "Oct 2023": ("2023-10-01", "2023-10-31"),
    "Aug 2024": ("2024-08-01", "2024-08-15"),
    "Apr 2025": ("2025-04-01", "2025-04-30"),
    "Low-vol trap": ("2026-04-01", "2026-04-30"),
}

OPTIMIZER_SEED = 901
OPTIMIZER_DRAWS = 300_000
OPTIMIZER_TOP_N = 250
OPTIMIZER_BATCH = 1_000
BOOTSTRAP_DRAWS = 5_000
MIN_INDEPENDENT_ENTRIES = 10
PROMOTION_CONFIDENCE = .90
MIN_VALID_BOOTSTRAP_SHARE = .90


def purged_training_mask(index, split, horizon=63, execution_lag=1):
    """Keep signals whose full forward label ends before validation starts."""
    index = pd.DatetimeIndex(index)
    split_position = index.searchsorted(pd.Timestamp(split), side="left")
    label_end_positions = np.arange(len(index)) + execution_lag + horizon
    return pd.Series(label_end_positions < split_position, index=index)


def block_bootstrap_ic(x, y, block=63, n=2000, seed=7):
    idx = np.arange(len(x))
    ics = []
    rng = np.random.default_rng(seed)
    n_blocks = max(1, len(x) // block)
    for _ in range(n):
        starts = rng.integers(0, len(x) - block, size=n_blocks)
        take = np.concatenate([idx[s:s + block] for s in starts])
        ic, _ = spearmanr(x[take], y[take], nan_policy="omit")
        ics.append(ic)
    return np.percentile(ics, [2.5, 97.5])


def fit_ic_weights(pctls: pd.DataFrame, target: pd.Series, cols: list[str]):
    """Original IC method, retained as a diagnostic benchmark."""
    rows = []
    for c in cols:
        pair = pd.concat([pctls[c], target], axis=1).dropna()
        if len(pair) < 300:
            rows.append({"component": c, "ic": np.nan, "lo": np.nan, "hi": np.nan})
            continue
        ic, _ = spearmanr(pair.iloc[:, 0], pair.iloc[:, 1])
        lo, hi = block_bootstrap_ic(pair.iloc[:, 0].values, pair.iloc[:, 1].values)
        rows.append({"component": c, "ic": ic, "lo": lo, "hi": hi})
    table = pd.DataFrame(rows).set_index("component")
    raw = table["ic"].clip(lower=0).fillna(0)
    raw = raw / raw.sum() if raw.sum() else pd.Series(1 / len(cols), index=cols)
    equal = pd.Series(1 / len(cols), index=raw.index)
    table["weight_ic"] = (1 - config.SHRINKAGE) * raw + config.SHRINKAGE * equal
    table["weight_ic"] /= table["weight_ic"].sum()
    return table


def composite(pctls, weights: pd.Series):
    return S.weighted_meter(pctls, weights.to_dict())


def _candidate_metrics(panic, reality, target, mask):
    p = panic[mask]
    r = reality[mask]
    y = target[mask]
    signal = (p >= config.PANIC_HIGH) & (r > config.LEGACY_REALITY_BROKEN)
    n = signal.sum(axis=0)
    rest_n = (~signal).sum(axis=0)
    avg = (signal * y[:, None]).sum(axis=0) / np.maximum(n, 1)
    hit = (signal * (y[:, None] > 0)).sum(axis=0) / np.maximum(n, 1)
    rest_avg = ((~signal) * y[:, None]).sum(axis=0) / np.maximum(rest_n, 1)
    rest_hit = ((~signal) * (y[:, None] > 0)).sum(axis=0) / np.maximum(rest_n, 1)
    return {"n": n, "avg": avg, "hit": hit,
            "uplift": avg - rest_avg, "hit_uplift": hit - rest_hit}


def _round_to_five_points(weights):
    units = weights * 20
    rounded = np.floor(units).astype(int)
    remainder = 20 - rounded.sum()
    order = np.argsort(-(units - rounded))
    rounded[order[:remainder]] += 1
    return rounded / 20


def optimize_joint_weights(pctls: pd.DataFrame, target: pd.Series):
    """Select a stable joint candidate without looking at 2022-present.

    Candidates are constrained so no component can be deleted or dominate:
    panic weights are 5%-40%, proxy-overlay weights are 7.5%-50%. We rank candidates
    on two chronological training regimes, take the median of the top 250, then
    round to five percentage points. The median and rounding are intentional
    defenses against a lucky, one-decimal optimum.
    """
    pcols = list(PANIC_COLS)
    rcols = list(REALITY_COLS)
    complete = pd.concat([pctls[pcols + rcols], target.rename("target")], axis=1).dropna()
    p_values = complete[pcols].to_numpy()
    r_values = complete[rcols].to_numpy()
    y = complete["target"].to_numpy()
    dates = complete.index

    regimes = {
        "2016-2018": (dates >= "2016-01-01") & (dates <= "2018-12-31"),
        "2019-2021": (dates >= "2019-01-01") & (dates <= "2021-12-31"),
        "train": (dates >= "2016-01-01") & (dates <= "2021-12-31"),
    }

    rng = np.random.default_rng(OPTIMIZER_SEED)
    panic_draws = rng.dirichlet(np.ones(len(pcols)) * 1.5, OPTIMIZER_DRAWS)
    reality_draws = rng.dirichlet(np.ones(len(rcols)) * 1.5, OPTIMIZER_DRAWS)
    keep = ((panic_draws.max(axis=1) <= .40) & (panic_draws.min(axis=1) >= .05)
            & (reality_draws.max(axis=1) <= .50) & (reality_draws.min(axis=1) >= .075))
    panic_draws = panic_draws[keep]
    reality_draws = reality_draws[keep]
    n_candidates = len(panic_draws)

    metrics = {
        name: {key: np.zeros(n_candidates)
               for key in ("n", "avg", "hit", "uplift", "hit_uplift")}
        for name in regimes
    }
    for start in range(0, n_candidates, OPTIMIZER_BATCH):
        end = min(n_candidates, start + OPTIMIZER_BATCH)
        panic = p_values @ panic_draws[start:end].T
        reality = r_values @ reality_draws[start:end].T
        for name, mask in regimes.items():
            result = _candidate_metrics(panic, reality, y, mask)
            for key, values in result.items():
                metrics[name][key][start:end] = values

    def regime_score(name):
        m = metrics[name]
        return (2.0 * m["avg"] + .10 * m["hit"] + 1.5 * m["uplift"]
                + .05 * m["hit_uplift"])

    valid = ((metrics["2016-2018"]["n"] >= 3)
             & (metrics["2019-2021"]["n"] >= 25)
             & (metrics["train"]["n"] >= 35)
             & (metrics["train"]["n"] <= 150))
    score = (.30 * regime_score("2016-2018")
             + .50 * regime_score("2019-2021")
             + .20 * regime_score("train")
             - .02 * ((panic_draws - .20) ** 2).sum(axis=1)
             - .02 * ((reality_draws - .25) ** 2).sum(axis=1))
    score[~valid] = -np.inf

    top = np.argsort(score)[-OPTIMIZER_TOP_N:]
    panic = np.median(panic_draws[top], axis=0)
    reality = np.median(reality_draws[top], axis=0)
    panic = _round_to_five_points(panic / panic.sum())
    reality = _round_to_five_points(reality / reality.sum())
    return pd.Series(panic, index=pcols), pd.Series(reality, index=rcols)


def legacy_signal_stats(panic, reality, target, start):
    df = pd.concat([panic, reality, target], axis=1, keys=["p", "r", "fwd"]).dropna().loc[start:]
    signal = df[(df.p >= config.PANIC_HIGH) & (df.r > config.LEGACY_REALITY_BROKEN)]
    rest = df.drop(signal.index)
    return {
        "days": len(signal),
        "avg": signal.fwd.mean(),
        "hit": (signal.fwd > 0).mean(),
        "rest_avg": rest.fwd.mean(),
        "rest_hit": (rest.fwd > 0).mean(),
    }


def independent_entry_stats(panic, reality, target, start, cooldown=63):
    """Count at most one research entry per forward-return horizon."""
    df = pd.concat([panic, reality, target], axis=1, keys=["p", "r", "fwd"]).dropna().loc[start:]
    signal = (df.p >= config.PANIC_HIGH) & (df.r > config.LEGACY_REALITY_BROKEN)
    picks = []
    last = -cooldown
    for i, (_, row) in enumerate(df.iterrows()):
        if signal.iloc[i] and i - last >= cooldown:
            picks.append(row.fwd)
            last = i
    values = pd.Series(picks, dtype=float)
    return {"entries": len(values), "avg": values.mean(), "hit": (values > 0).mean()}


def bootstrap_compare(panic_a, reality_a, panic_b, reality_b, target,
                      start="2022-01-01", block=63, n=BOOTSTRAP_DRAWS, seed=31):
    frames = []
    for panic, reality in ((panic_a, reality_a), (panic_b, reality_b)):
        frames.append(pd.concat([panic, reality, target], axis=1,
                                keys=["p", "r", "fwd"]).dropna().loc[start:])
    common = frames[0].index.intersection(frames[1].index)
    frames = [frame.loc[common] for frame in frames]
    idx = np.arange(len(common))
    empty = {
        "hit_probability": 0.0,
        "return_probability": 0.0,
        "hit_ci": None,
        "return_ci": None,
        "valid_draws": 0,
        "requested_draws": int(n),
    }
    if len(idx) < block:
        return empty
    rng = np.random.default_rng(seed)
    diffs = []
    for _ in range(n):
        starts = rng.integers(0, len(idx) - block + 1,
                              size=max(1, len(idx) // block))
        take = np.concatenate([idx[s:s + block] for s in starts])
        values = []
        for frame in frames:
            sample = frame.iloc[take]
            signal = sample[(sample.p >= config.PANIC_HIGH)
                            & (sample.r > config.LEGACY_REALITY_BROKEN)]
            values.append(((signal.fwd > 0).mean(), signal.fwd.mean()))
        difference = (values[0][0] - values[1][0], values[0][1] - values[1][1])
        if np.isfinite(difference).all():
            diffs.append(difference)
    if not diffs:
        return empty
    diffs = np.asarray(diffs)
    return {
        "hit_probability": float((diffs[:, 0] > 0).mean()),
        "return_probability": float((diffs[:, 1] > 0).mean()),
        "hit_ci": np.percentile(diffs[:, 0] * 100, [2.5, 97.5]),
        "return_ci": np.percentile(diffs[:, 1] * 100, [2.5, 97.5]),
        "valid_draws": int(len(diffs)),
        "requested_draws": int(n),
    }


def _stats_row(name, stats, count_key):
    return (f"| {name} | {stats[count_key]} | {stats['avg'] * 100:+.1f}% | "
            f"{stats['hit'] * 100:.0f}% |")


def _bootstrap_row(name, comparison):
    if not comparison["valid_draws"]:
        return (f"| {name} | n/a | n/a | n/a | n/a | "
                f"0 / {comparison['requested_draws']} |")
    return (
        f"| {name} | {comparison['hit_probability'] * 100:.0f}% | "
        f"{comparison['return_probability'] * 100:.0f}% | "
        f"[{comparison['hit_ci'][0]:+.1f}, {comparison['hit_ci'][1]:+.1f}] pts | "
        f"[{comparison['return_ci'][0]:+.2f}, {comparison['return_ci'][1]:+.2f}] pts | "
        f"{comparison['valid_draws']} / {comparison['requested_draws']} |"
    )


def passes_promotion_gate(daily, entries, comparison_equal, comparison_production,
                          minimum_entries=MIN_INDEPENDENT_ENTRIES):
    """Statistical screen only; evidence quality is checked separately."""
    candidate_daily = daily["train-only candidate"]
    candidate_entries = entries["train-only candidate"]
    benchmarks = ("equal weight", "current production")
    return (
        candidate_entries["entries"] >= minimum_entries
        and candidate_daily["hit"] > max(daily[name]["hit"] for name in benchmarks)
        and candidate_daily["avg"] > max(daily[name]["avg"] for name in benchmarks)
        and candidate_entries["hit"] >= max(entries[name]["hit"] for name in benchmarks)
        and candidate_entries["avg"] >= max(entries[name]["avg"] for name in benchmarks)
        and comparison_equal["hit_probability"] >= PROMOTION_CONFIDENCE
        and comparison_equal["return_probability"] >= PROMOTION_CONFIDENCE
        and comparison_production["hit_probability"] >= PROMOTION_CONFIDENCE
        and comparison_production["return_probability"] >= PROMOTION_CONFIDENCE
        and comparison_equal["valid_draws"]
        >= comparison_equal["requested_draws"] * MIN_VALID_BOOTSTRAP_SHARE
        and comparison_production["valid_draws"]
        >= comparison_production["requested_draws"] * MIN_VALID_BOOTSTRAP_SHARE
    )


def promotion_decision(statistical_pass, metadata):
    """Block promotion unless both membership and fundamentals are point-in-time."""
    blockers = []
    if metadata.get("constituent_history") != "point_in_time":
        blockers.append("constituent history uses current-membership backfill")
    if metadata.get("shiller_vintage") != "point_in_time":
        blockers.append("Shiller earnings are current-vintage and revision-prone")
    return bool(statistical_pass and not blockers), blockers


def main():
    hist = pd.read_parquet(os.path.join(config.DATA_DIR, "history.parquet"))
    metadata_path = os.path.join(config.DATA_DIR, "history_metadata.json")
    metadata = json.load(open(metadata_path)) if os.path.exists(metadata_path) else {}

    pctl = pd.DataFrame(index=hist.index)
    for component, orientation in {**PANIC_COLS, **REALITY_COLS}.items():
        if component not in hist or hist[component].dropna().empty:
            continue
        percentile = S.rolling_percentile(hist[component])
        pctl[component] = percentile if orientation > 0 else 100 - percentile

    target = next_close_forward_return(hist["spx"], config.FWD_RETURN_DAYS)
    trading_dates = hist["spx"].dropna().index
    train = purged_training_mask(trading_dates, config.WALK_FORWARD_SPLIT,
                                 config.FWD_RETURN_DAYS).reindex(
                                     hist.index, fill_value=False)
    training_target = target.where(train)
    panic_ic = fit_ic_weights(pctl[train], target[train], list(PANIC_COLS))
    reality_ic = fit_ic_weights(pctl[train], target[train], list(REALITY_COLS))
    panic_candidate, reality_candidate = optimize_joint_weights(pctl, training_target)

    panic_equal = pd.Series(1 / len(PANIC_COLS), index=PANIC_COLS)
    reality_equal = pd.Series(1 / len(REALITY_COLS), index=REALITY_COLS)
    panic_production = pd.Series(config.PANIC_WEIGHTS["sp500"]).rename(
        index={"breadth": "breadth_sp500"})
    reality_production = pd.Series(config.LEGACY_REALITY_WEIGHTS["sp500"]).rename(
        index={"divergence": "divergence_proxy", "valuation_anchor": "erp_proxy"})

    panic_table = panic_ic.copy()
    panic_table["weight_candidate"] = panic_candidate
    panic_table["weight_production"] = panic_production
    reality_table = reality_ic.copy()
    reality_table["weight_candidate"] = reality_candidate
    reality_table["weight_production"] = reality_production

    models = {
        "train-only candidate": (panic_candidate, reality_candidate),
        "equal weight": (panic_equal, reality_equal),
        "current production": (panic_production, reality_production),
        "old IC method": (panic_ic["weight_ic"], reality_ic["weight_ic"]),
    }
    scored = {name: (composite(pctl, wp), composite(pctl, wr))
              for name, (wp, wr) in models.items()}
    daily = {name: legacy_signal_stats(p, r, target, config.WALK_FORWARD_SPLIT)
             for name, (p, r) in scored.items()}
    entries = {name: independent_entry_stats(p, r, target, config.WALK_FORWARD_SPLIT)
               for name, (p, r) in scored.items()}

    comparison_equal = bootstrap_compare(*scored["train-only candidate"],
                                          *scored["equal weight"], target)
    comparison_production = bootstrap_compare(*scored["train-only candidate"],
                                               *scored["current production"], target)

    statistical_pass = passes_promotion_gate(daily, entries, comparison_equal,
                                             comparison_production)
    promote, promotion_blockers = promotion_decision(statistical_pass, metadata)
    blocker_text = "; ".join(promotion_blockers)
    shiller_lag = metadata.get("shiller_publication_lag_months", "unknown")

    lines = [
        "# Exploratory historical diagnostic: candidate-weight stress test\n",
        ("Purpose: compare candidate behavior under historical proxies. This is not "
         "a validated forecast, a live-model backtest, or a production-weight approval.\n"),
        ("Training signals: 2016 through the last date whose 63-session, next-close "
         "forward return ends before 2022. Validation: 2022-present, untouched by "
         "the optimizer."),
        "Legacy thresholds remain fixed at Panic >= 75 and proxy overlay > 35.\n",
        "## Status\n",
        "**EXPLORATORY ONLY. Production weights remain unchanged.**",
        "",
        (f"Statistical comparison screen: **{'passed' if statistical_pass else 'failed'}**. "
         f"Production promotion is blocked because {blocker_text}.\n"),
        "## Statistical comparison rule\n",
        (f"The screen requires at least {MIN_INDEPENDENT_ENTRIES} independent entries, "
         "superiority on daily and independent-entry observations, and 90% "
         "block-bootstrap confidence versus both equal weight and current production. "
         "Passing it is diagnostic evidence, not deployment authority.\n"),
        "## Panic diagnostics and weights\n",
        panic_table.round(3).to_markdown(),
        "\n## Legacy proxy-overlay diagnostics and weights\n",
        reality_table.round(3).to_markdown(),
        "\n## Out-of-sample legacy proxy signal, daily observations\n",
        "| model | days | average forward 3M return | hit rate |",
        "|---|---:|---:|---:|",
    ]
    for name, stats in daily.items():
        lines.append(_stats_row(name, stats, "days"))

    lines.extend([
        "\n## Out-of-sample legacy proxy signal, independent entries\n",
        "A 63-trading-day cooldown prevents one long panic from being counted repeatedly.\n",
        "| model | entries | average forward 3M return | hit rate |",
        "|---|---:|---:|---:|",
    ])
    for name, stats in entries.items():
        lines.append(_stats_row(name, stats, "entries"))

    lines.extend([
        "\n## Block-bootstrap comparison\n",
        "| candidate versus | P(hit rate is higher) | P(avg return is higher) | hit difference 95% CI | return difference 95% CI | valid / requested draws |",
        "|---|---:|---:|---:|---:|---:|",
        _bootstrap_row("equal weight", comparison_equal),
        _bootstrap_row("current production", comparison_production),
        "\n## Episode readings, train-only candidate\n",
        "| episode | panic | proxy overlay |",
        "|---|---:|---:|",
    ])
    candidate_panic, candidate_reality = scored["train-only candidate"]
    for name, (start, end) in EPISODES.items():
        p = candidate_panic.loc[start:end]
        r = candidate_reality.loc[start:end]
        if p.empty:
            lines.append(f"| {name} | n/a | n/a |")
        else:
            lines.append(f"| {name} | {p.max():.0f} | {r.mean():.0f} |")

    credit_note = metadata.get("credit_velocity_series", config.FRED_SERIES["hy_oas"])
    lines.extend([
        "\n## What is still missing for final optimization\n",
        "1. Point-in-time index membership, not today's constituents backfilled through history.",
        "2. Point-in-time historical forward EPS estimates and analyst revisions, not current-vintage Shiller realized earnings.",
        "3. A consistent historical HY OAS series matching the live signal, not the BAA10Y proxy.",
        "4. More independent stress episodes. The current diagnostic contains too few separate 3-month decisions.",
        "5. A longer live forward-EPS snapshot history for every index scope.",
        "",
        ("Notes: IC confidence intervals use a 63-day block bootstrap. The joint optimizer "
         "uses training data only, constrained weights, top-candidate ensembling, and five-point "
         f"rounding. Shiller observations use a conservative {shiller_lag}-month publication "
         "lag, but the downloaded series remains revised current-vintage data. "
         f"Backtest credit velocity uses FRED {credit_note}; live scoring uses "
         f"{config.FRED_SERIES['hy_oas']}. This report is research-only and never an "
         "allocation instruction.")
    ])

    report = os.path.join(config.DATA_DIR, "weight_report.md")
    with open(report, "w") as handle:
        handle.write("\n".join(lines) + "\n")
    output = {
        "promote": bool(promote),
        "status": "exploratory_only",
        "statistical_screen_passed": bool(statistical_pass),
        "promotion_blockers": promotion_blockers,
        "method": "train-only constrained top-250 median, rounded to 5pts",
        "panic": panic_candidate.round(4).to_dict(),
        "reality": reality_candidate.round(4).to_dict(),
    }
    candidate_path = os.path.join(config.DATA_DIR, "weights_candidate.json")
    with open(candidate_path, "w") as handle:
        json.dump(output, handle, indent=2)
        handle.write("\n")
    print(f"wrote {report}")
    print(json.dumps(output, indent=2))
    print("production weights unchanged; candidate is exploratory only")


if __name__ == "__main__":
    main()
