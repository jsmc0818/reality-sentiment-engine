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
    return cutoff if now.hour >= 21 else cutoff - pd.Timedelta(days=1)


def through_cutoff(data, cutoff):
    """Drop partial or future daily bars without changing the input type."""
    if data.empty:
        return data
    index = pd.DatetimeIndex(data.index)
    if index.tz is not None:
        index = index.tz_convert(None)
    return data.loc[index.normalize() <= cutoff]


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
    today = pd.Timestamp.today().normalize()
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
        eps_snapshot = F.forward_eps_snapshot(scope)  # append today's estimates to history
        idx_px = (C.equal_weight_index(member_px[scope]) if scope == "mag7"
                  else index_px[config.INDEX_TICKER[scope]])
        raw_p = dict(panic_sp if scope == "sp500" else panic_ndx)
        if scope in ("sp500", "ndx100"):
            raw_p["breadth"] = C.breadth_pct_above_ma(member_px[scope])
        else:
            raw_p["pairwise_corr"] = C.pairwise_correlation(member_px[scope])
        pctl_p = S.score_components(raw_p, S.ORIENT_PANIC)
        panic = S.current_weighted_meter(
            pctl_p, config.PANIC_WEIGHTS[scope], config.PANIC_PROVENANCE
        )
        fundamentals = S.fundamental_health(eps_snapshot)
        if not panic["ready"] or fundamentals is None:
            failures.append(
                f"{scope}: panic_ready={panic['ready']} "
                f"panic_coverage={panic['coverage_pct']:.1f}% "
                f"fundamentals_ready={fundamentals is not None}"
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
    if pd.Timestamp(asof) > market_cutoff:
        raise RuntimeError("daily publication blocked before the US session is safely closed")

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
    P.write_public_payload(path, public_payload)
    P.write_timeline_payload(timeline_path, timeline_payload)
    print(f"wrote {path}")
    print(f"wrote {timeline_path}")
    for s, v in out["scopes"].items():
        print(f"{s:7s} panic={v['panic']:5.1f} fundamentals={v['fundamentals']:5.1f} "
              f"-> {v['quadrant']['label']}")


if __name__ == "__main__":
    main()
