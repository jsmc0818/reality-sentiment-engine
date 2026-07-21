"""Daily entrypoint: fetch -> compute -> score -> data/scores.json
Run: python -m pipeline.run_daily"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import config
from pipeline import components as C
from pipeline import fetchers as F
from pipeline import public_output as P
from pipeline import scoring as S


def completed_market_cutoff(now_utc=None) -> pd.Timestamp:
    """Latest date safe for daily bars; the workflow runs after 21:00 UTC."""
    now = now_utc or datetime.now(timezone.utc)
    cutoff = pd.Timestamp(now.date())
    return cutoff if now.hour >= 21 else cutoff - pd.offsets.BDay(1)


def through_cutoff(data, cutoff):
    """Drop partial or future daily bars without changing the input type."""
    if data.empty:
        return data
    index = pd.DatetimeIndex(data.index)
    if index.tz is not None:
        index = index.tz_convert(None)
    return data.loc[index.normalize() <= cutoff]


def canonical_market_asof(index_prices, mag7_prices, cutoff) -> pd.Timestamp:
    """Find one complete common session inside the public staleness limit."""
    panels = (
        (index_prices, list(config.INDEX_TICKER.values()), 1.0),
        (mag7_prices, config.MAG7_TICKERS, config.MIN_MAG7_PRICE_COVERAGE),
    )
    common_dates = None
    for panel, names, minimum in panels:
        aligned = panel.reindex(columns=names) if not panel.empty else panel
        coverage = C.price_coverage(aligned, len(names))
        complete = {
            pd.Timestamp(date).tz_localize(None).normalize()
            for date in coverage[coverage >= minimum].index
        }
        common_dates = complete if common_dates is None else common_dates & complete
    if not common_dates:
        raise RuntimeError("daily publication blocked: no complete common market session")
    asof = max(common_dates)
    cutoff = pd.Timestamp(cutoff).normalize()
    lag = len(pd.bdate_range(asof, cutoff, inclusive="left")) if asof < cutoff else 0
    if asof > cutoff or lag > config.MAX_PANIC_STALE_BUSINESS_DAYS:
        raise RuntimeError(
            f"daily publication blocked: latest complete market session {asof.date()} "
            f"is outside the cutoff window ending {cutoff.date()}"
        )
    return asof


def constituent_price_evidence(prices, tickers, asof) -> tuple[int, float]:
    """Usable names and expected-universe coverage on the publication date."""
    if prices.empty or not tickers:
        return 0, 0.0
    aligned = prices.reindex(columns=tickers)
    dates = pd.DatetimeIndex(aligned.index)
    if dates.tz is not None:
        dates = dates.tz_convert(None)
    rows = aligned.loc[dates.normalize() == pd.Timestamp(asof).normalize()]
    count = int(rows.iloc[-1].notna().sum()) if not rows.empty else 0
    return count, count / len(tickers) * 100


def keep_validated_previous_reading(scores_path, timeline_path, market_asof, cutoff):
    """No-session path: keep only a complete, internally aligned publication."""
    try:
        previous = json.loads(Path(scores_path).read_text(encoding="utf-8"))
        timeline = json.loads(Path(timeline_path).read_text(encoding="utf-8"))
        P.validate_public_timeline_pair(previous, timeline)
    except Exception as error:
        raise RuntimeError(
            "daily publication blocked: no new complete market session and "
            "the prior public reading is not valid"
        ) from error
    expected = pd.Timestamp(market_asof).strftime("%Y-%m-%d")
    if previous["asof"] != expected:
        raise RuntimeError(
            "daily publication blocked: the latest complete market session "
            "does not match the prior public reading"
        )
    print(
        f"no new complete market session through {pd.Timestamp(cutoff).date()}; "
        f"keeping validated {previous['asof']} reading"
    )


def build_entry_diagnostics(scope, idx_px, dgs10, snapshot):
    """Valuation and price/EPS divergence, kept outside Fundamentals."""
    eps_hist = F.eps_history(scope)
    source = snapshot.get("source")
    if source and "source" in eps_hist:
        eps_hist = eps_hist[eps_hist["source"] == source]
    snapshot_count = (int(eps_hist["fwd_pe"].notna().sum())
                      if "fwd_pe" in eps_hist else 0)

    entry = {}
    fwd_pe = snapshot.get("fwd_pe")
    trl_pe = snapshot.get("trl_pe")
    if fwd_pe:
        entry["forward_pe"] = float(fwd_pe)
        if not dgs10.dropna().empty:
            entry["equity_risk_premium_pts"] = 100 / fwd_pe - float(dgs10.dropna().iloc[-1])
    if trl_pe:
        entry["trailing_pe"] = float(trl_pe)

    if snapshot_count >= config.MIN_FORWARD_EPS_SNAPSHOTS:
        fwd_pe = eps_hist["fwd_pe"].reindex(idx_px.index, method="ffill")
        px_on_snapshot = idx_px.reindex(eps_hist.index, method="ffill")
        inferred_eps = px_on_snapshot / eps_hist["fwd_pe"]
        if "fwd_eps_index" in eps_hist:
            eps_snapshots = eps_hist["fwd_eps_index"].fillna(inferred_eps)
        else:
            eps_snapshots = inferred_eps
        fwd_eps = eps_snapshots.reindex(idx_px.index, method="ffill")
        divergence = C.divergence_score(idx_px, fwd_eps)
        if not divergence.dropna().empty:
            entry["divergence_pts"] = float(divergence.dropna().iloc[-1])
    return entry, snapshot_count


def main():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    today = pd.Timestamp(datetime.now(timezone.utc).date())
    market_cutoff = completed_market_cutoff()
    raw_lookback = (config.PCTL_WINDOW_DAYS
                    + max(config.BREADTH_MA_DAYS, config.Z_LOOKBACK_DAYS)
                    + config.VELOCITY_DAYS + 30)
    history_start = (today - pd.offsets.BDay(raw_lookback)).strftime("%Y-%m-%d")
    vols = through_cutoff(F.yahoo_history(config.VOL_TICKERS, start=history_start),
                          market_cutoff)
    vix9d = through_cutoff(F.cboe_index_history("VIX9D", history_start), market_cutoff)
    vix3m = through_cutoff(F.cboe_index_history("VIX3M", history_start), market_cutoff)
    hy = through_cutoff(F.fred_series(config.FRED_SERIES["hy_oas"],
                                      start=history_start), market_cutoff)
    dgs10 = through_cutoff(F.fred_series(config.FRED_SERIES["dgs10"],
                                         start=history_start), market_cutoff)
    pc = through_cutoff(F.cboe_put_call(), market_cutoff)
    index_px = through_cutoff(
        F.yahoo_history(list(config.INDEX_TICKER.values()), start=history_start),
        market_cutoff,
    )

    members = {scope: F.constituents(scope) for scope in config.SCOPES}
    member_px = {
        scope: through_cutoff(F.yahoo_history(members[scope], start=history_start),
                              market_cutoff)
        for scope in config.SCOPES
    }
    market_asof = canonical_market_asof(index_px, member_px["mag7"], market_cutoff)
    if market_asof != market_cutoff:
        scores_path = Path(config.DATA_DIR) / "scores.json"
        timeline_path = Path(config.DATA_DIR) / "timeline.json"
        keep_validated_previous_reading(
            scores_path, timeline_path, market_asof, market_cutoff
        )
        return

    credit_velocity = C.velocity_z(hy)
    panic_sp = {
        "credit_velocity": credit_velocity,
        "put_call": pc,
        "term_structure": C.term_structure(vix9d, vix3m),
        "vvix": vols["^VVIX"],
    }
    panic_ndx = {
        "credit_velocity": credit_velocity,
        "put_call": pc,
        "vxn_ratio": C.vxn_ratio(vols["^VXN"], vols["^VIX"]),
        "vxn_level": vols["^VXN"],
    }
    out = {"scopes": {}}
    failures = []
    market_dates = set()
    for scope in config.SCOPES:
        price_count, price_coverage = constituent_price_evidence(
            member_px[scope], members[scope], market_asof
        )
        minimum_price_coverage = (
            config.MIN_MAG7_PRICE_COVERAGE if scope == "mag7"
            else config.MIN_CONSTITUENT_PRICE_COVERAGE
        )
        if price_coverage < minimum_price_coverage * 100:
            failures.append(
                f"{scope}: constituent_price_coverage={price_coverage:.1f}% "
                f"minimum={minimum_price_coverage * 100:.1f}%"
            )
            continue
        eps_snapshot = F.forward_eps_snapshot(scope, market_asof)
        idx_px = (C.equal_weight_index(member_px[scope]) if scope == "mag7"
                  else index_px[config.INDEX_TICKER[scope]])
        raw_p = dict(panic_sp if scope == "sp500" else panic_ndx)
        if scope in ("sp500", "ndx100"):
            raw_p["breadth"] = C.breadth_pct_above_ma(
                member_px[scope], expected_count=len(members[scope])
            )
        else:
            raw_p["pairwise_corr"] = C.downside_pairwise_correlation(
                member_px[scope], expected_count=len(members[scope])
            )
        pctl_p = S.score_components(raw_p, S.ORIENT_PANIC)
        panic = S.current_weighted_meter(
            pctl_p, config.PANIC_WEIGHTS[scope], config.PANIC_PROVENANCE,
            expected_asof=market_asof,
        )
        fundamentals = S.fundamental_health(eps_snapshot)
        eps_aligned = (eps_snapshot.get("source_observation_date")
                       == market_asof.strftime("%Y-%m-%d"))
        constituents_aligned = (
            eps_snapshot.get("constituent_hash") == F.constituent_hash(members[scope])
            and eps_snapshot.get("n_constituents") == len(members[scope])
        )
        if (not panic["ready"] or fundamentals is None or not eps_aligned
                or not constituents_aligned):
            failures.append(
                f"{scope}: panic_ready={panic['ready']} "
                f"panic_coverage={panic['coverage_pct']:.1f}% "
                f"fundamentals_ready={fundamentals is not None} "
                f"eps_aligned={eps_aligned} "
                f"constituents_aligned={constituents_aligned}"
            )
            continue
        market_dates.add(panic["asof"])
        p = round(float(panic["score"]), 1)
        f = round(float(fundamentals["score"]), 1)
        discrepancy = round(S.fundamental_discrepancy(p, f), 1)
        entry, eps_snapshot_count = build_entry_diagnostics(
            scope, idx_px, dgs10, eps_snapshot
        )
        quadrant = S.quadrant(p, f)
        verdict = S.verdict(p, f, discrepancy)
        panic_components = {
            name: round(float(status["score"]), 1)
            for name, status in panic["components"].items()
            if status["score"] is not None
        }
        panic_quality = {
            name: {key: value for key, value in status.items() if key != "score"}
            for name, status in panic["components"].items()
        }

        out["scopes"][scope] = {
            "panic": p,
            "fundamentals": f,
            "fundamental_discrepancy": discrepancy,
            "coverage": {"panic_pct": round(panic["coverage_pct"], 1),
                         "panic_ready": panic["ready"],
                         "panic_asof": panic["asof"],
                         "fundamentals_pct": round(fundamentals["coverage_pct"]),
                         "fundamentals_common_weight_pct": round(
                             fundamentals["coverage_pct"], 1),
                         "fundamentals_common_cohort_pct": round(
                             fundamentals["common_cohort_pct"], 1),
                         "fundamentals_ready": True,
                         "entry_history_snapshot_count": eps_snapshot_count,
                         "entry_history_snapshot_minimum": config.MIN_FORWARD_EPS_SNAPSHOTS},
            "quadrant": quadrant,
            "verdict": verdict,
            "analyst_eps": {
                key: value for key, value in eps_snapshot.items()
                if key.startswith("analyst_eps_") or key in {
                    "analyst_eps_up_breadth_30d_pct", "n_analyst_trends"
                }
            },
            "components": {
                "panic": panic_components,
                "fundamentals": {
                    "revision_score": round(fundamentals["revision_score"], 1),
                    "revision_breadth": round(fundamentals["breadth_score"], 1),
                },
                "entry": {key: round(value, 2) for key, value in entry.items()},
            },
            "data_quality": {
                "constituent_hash": eps_snapshot["constituent_hash"],
                "constituent_count": eps_snapshot["n_constituents"],
                "market_cap_proxy_count": eps_snapshot["n_market_cap_proxies"],
                "constituent_price_count": price_count,
                "constituent_price_coverage_pct": round(price_coverage, 1),
                "eps_source": eps_snapshot["source"],
                "eps_observation_date": eps_snapshot["source_observation_date"],
                "panic_components": panic_quality,
            },
        }

    if failures:
        raise RuntimeError("daily publication blocked by data-quality gates: "
                           + "; ".join(failures))
    if len(market_dates) != 1:
        raise RuntimeError(f"daily publication blocked by mismatched market dates: "
                           f"{sorted(market_dates)}")
    asof = market_dates.pop()
    if pd.Timestamp(asof) != market_asof:
        raise RuntimeError("daily publication blocked by a non-canonical market asof")

    path = os.path.join(config.DATA_DIR, "scores.json")
    public_payload = P.build_public_payload(out["scopes"], asof)
    timeline_path = Path(config.DATA_DIR) / "timeline.json"
    previous_timeline = None
    if timeline_path.exists():
        previous_timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        P.validate_timeline_payload(previous_timeline)
    timeline_payload = P.build_timeline_payload(previous_timeline, out["scopes"], asof)
    P.validate_public_payload(public_payload)
    P.validate_timeline_payload(timeline_payload)
    P.validate_public_timeline_pair(public_payload, timeline_payload)
    P.write_public_payload(path, public_payload)
    P.write_timeline_payload(timeline_path, timeline_payload)
    print(f"wrote {path}")
    print(f"wrote {timeline_path}")
    for s, v in out["scopes"].items():
        print(f"{s:7s} panic={v['panic']:5.1f} fundamentals={v['fundamentals']:5.1f} "
              f"-> {v['quadrant']['label']}")


if __name__ == "__main__":
    main()
