"""Build raw history for an exploratory diagnostic -> data/history.parquet
Run once: python -m backtest.build_history  (~10-20 min, mostly breadth prices)

Backtest proxies (see README limitations):
- Divergence: lagged, current-vintage Shiller realized 12m earnings trend
- Valuation: index trailing PE from Shiller E; ERP uses earnings yield - DGS10
- put/call from CBOE history where available
- Forward returns: next available close through 63 trading sessions later

Constituent histories use today's membership backfilled through time. This is
survivorship-biased evidence and cannot approve production-weight changes.
"""

import json
import os

import pandas as pd

import config
from pipeline import components as C
from pipeline import fetchers as F

START = "2015-01-01"
SHILLER_PUBLICATION_LAG_MONTHS = 3


def next_close_forward_return(series: pd.Series, sessions: int) -> pd.Series:
    """Return from the next available close through ``sessions`` later."""
    closes = series.dropna()
    result = closes.shift(-(sessions + 1)).div(closes.shift(-1)).sub(1)
    return result.reindex(series.index)


def lag_monthly_publication(series: pd.Series,
                            months: int = SHILLER_PUBLICATION_LAG_MONTHS) -> pd.Series:
    """Move current-vintage monthly observations to a conservative availability date."""
    return series.shift(months, freq="MS") if not series.empty else series


def main():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    print("volatility complex...")
    vols = F.yahoo_history(config.VOL_TICKERS, start=START)
    vix9d = F.cboe_index_history("VIX9D", start=START)
    vix3m = F.cboe_index_history("VIX3M", start=START)
    print("FRED...")
    hy = F.fred_series(config.FRED_SERIES["hy_oas"], start=START)
    credit_series = config.FRED_SERIES["hy_oas"]
    # Starting in April 2026, FRED/ICE limits HY OAS to three years. That is
    # insufficient for the 2016-2021 fit, so use a complete daily spread proxy.
    if hy.empty or hy.index.min() > pd.Timestamp(START) + pd.Timedelta(days=365):
        proxy_id = config.FRED_SERIES["credit_history_proxy"]
        proxy = F.fred_series(proxy_id, start=START)
        if not proxy.empty:
            print(f"HY OAS history is truncated; using {proxy_id} for backtest credit velocity")
            hy = proxy
            credit_series = proxy_id
    dgs10 = F.fred_series(config.FRED_SERIES["dgs10"], start=START)
    print("index + ETFs...")
    idx = F.yahoo_history(["^GSPC", "^NDX"], start=START)
    sectors = F.yahoo_history(config.SECTOR_ETFS, start=START)
    qual = F.yahoo_history(sorted({t for p in config.QUALITY_PAIRS for t in p}), start=START)
    print("breadth constituents (slow)...")
    sp500_px = F.yahoo_history(F.constituents("sp500"), start=START)
    ndx_px = F.yahoo_history(F.constituents("ndx100"), start=START)
    mag7_px = F.yahoo_history(config.MAG7_TICKERS, start=START)
    print("CBOE put/call...")
    pc = F.cboe_put_call()
    print("Shiller earnings (divergence proxy)...")
    shiller_e = lag_monthly_publication(F.shiller_earnings())

    spx = idx["^GSPC"]
    eps_daily = shiller_e.reindex(spx.index, method="ffill") if not shiller_e.empty else pd.Series(dtype=float)

    df = pd.DataFrame({
        # ---- panic raw
        "term_structure": C.term_structure(vix9d, vix3m),
        "credit_velocity": C.velocity_z(hy),
        "vvix": vols["^VVIX"],
        "breadth_sp500": C.breadth_pct_above_ma(sp500_px),
        "breadth_ndx": C.breadth_pct_above_ma(ndx_px),
        "put_call": pc,
        "vxn_ratio": C.vxn_ratio(vols["^VXN"], vols["^VIX"]),
        "vxn_level": vols["^VXN"],
        "pairwise_corr_mag7": C.pairwise_correlation(mag7_px),
        # ---- legacy proxy-overlay inputs
        "divergence_proxy": ((eps_daily.pct_change(config.DIVERGENCE_LOOKBACK_DAYS)
                              - spx.pct_change(config.DIVERGENCE_LOOKBACK_DAYS)) * 100
                             if not eps_daily.empty else pd.Series(dtype=float)),
        "erp_proxy": ((eps_daily / spx * 100) - dgs10.reindex(spx.index).ffill()
                      if not eps_daily.empty else pd.Series(dtype=float)),
        "sector_correlation": C.pairwise_correlation(sectors),
        "quality_spread": C.quality_spread_from_panel(qual),
        # ---- forward return targets
        "spx": spx, "ndx": idx["^NDX"], "mag7": C.equal_weight_index(mag7_px),
    })
    df["fwd3m_spx"] = next_close_forward_return(spx, config.FWD_RETURN_DAYS)
    df["fwd3m_ndx_excess"] = (
        next_close_forward_return(idx["^NDX"], config.FWD_RETURN_DAYS)
        - df["fwd3m_spx"]
    )
    df["fwd3m_mag7_excess"] = (
        next_close_forward_return(df["mag7"], config.FWD_RETURN_DAYS)
        - df["fwd3m_spx"]
    )

    path = os.path.join(config.DATA_DIR, "history.parquet")
    df.to_parquet(path)
    metadata = {
        "credit_velocity_series": credit_series,
        "forward_return_execution": "next_available_close",
        "shiller_publication_lag_months": SHILLER_PUBLICATION_LAG_MONTHS,
        "shiller_vintage": "current_download",
        "constituent_history": "current_membership_backfill",
        "evidence_use": "exploratory_only",
    }
    with open(os.path.join(config.DATA_DIR, "history_metadata.json"), "w") as handle:
        json.dump(metadata, handle, indent=2)
        handle.write("\n")
    print(f"wrote {path}: {df.shape[0]} rows, {df.shape[1]} cols, "
          f"{df.index.min().date()} -> {df.index.max().date()}")


if __name__ == "__main__":
    main()
