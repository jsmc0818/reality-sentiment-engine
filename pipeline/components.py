"""Component math. Each function returns raw values for scoring or diagnostics."""

import numpy as np
import pandas as pd

import config


# ---------------------------------------------------------------- helpers
def velocity_z(series: pd.Series,
               change_days: int = config.VELOCITY_DAYS,
               lookback: int = config.Z_LOOKBACK_DAYS) -> pd.Series:
    """Z-score of an N-day change versus its own one-year distribution."""
    chg = series.diff(change_days)
    mu = chg.rolling(lookback, min_periods=60).mean()
    sd = chg.rolling(lookback, min_periods=60).std()
    return (chg - mu) / sd


# ---------------------------------------------------------------- panic
def term_structure(vix9d: pd.Series, vix3m: pd.Series) -> pd.Series:
    """VIX9D/VIX3M with persistence bonus: depth x sqrt(consecutive days > 1.0).
    Duration separates positioning shocks (days) from fundamental bears (weeks)."""
    ratio = (vix9d / vix3m).dropna()
    inverted = (ratio > 1.0).astype(int)
    streak = inverted.groupby((inverted != inverted.shift()).cumsum()).cumsum()
    return ratio * (1 + 0.15 * np.sqrt(streak.clip(upper=20)))


def vxn_ratio(vxn: pd.Series, vix: pd.Series) -> pd.Series:
    """Concentration-of-fear gauge; NDX substitute for term structure."""
    return (vxn / vix).dropna()


def breadth_pct_above_ma(prices: pd.DataFrame,
                         ma_days: int = config.BREADTH_MA_DAYS) -> pd.Series:
    ma = prices.rolling(ma_days, min_periods=int(ma_days * .8)).mean()
    eligible = prices.notna() & ma.notna()
    denominator = eligible.sum(axis=1).replace(0, np.nan)
    return ((prices.gt(ma) & eligible).sum(axis=1) / denominator * 100).dropna()


def pairwise_correlation(prices: pd.DataFrame,
                         window: int = config.CORR_WINDOW_DAYS) -> pd.Series:
    """Average pairwise correlation used as the Mag7 breadth substitute."""
    rets = prices.pct_change(fill_method=None)
    out = {}
    for end in range(window, len(rets)):
        c = rets.iloc[end - window + 1:end + 1].corr().values
        iu = np.triu_indices_from(c, k=1)
        out[rets.index[end]] = np.nanmean(c[iu])
    return pd.Series(out)


def equal_weight_index(prices: pd.DataFrame) -> pd.Series:
    """Daily-rebalanced equal-weight basket, rebased to 100."""
    returns = prices.pct_change(fill_method=None).mean(axis=1)
    if returns.empty:
        return returns
    returns.iloc[0] = 0
    return returns.add(1).cumprod().mul(100)


# ---------------------------------------------------------------- entry diagnostics and legacy backtest inputs
def divergence_score(price: pd.Series, fwd_eps: pd.Series) -> pd.Series:
    """3M forward-EPS revision minus the 3M index return.

    Use this when point-in-time EPS snapshots are available directly. Keeping
    EPS flat between snapshots is more honest than allowing a stale P/E ratio
    to make the implied EPS move mechanically with the index price.
    """
    lb = config.DIVERGENCE_LOOKBACK_DAYS
    eps = fwd_eps.reindex(price.index, method="ffill")
    eps_rev = eps.pct_change(lb) * 100
    px_ret = price.pct_change(lb) * 100
    return (eps_rev - px_ret).dropna()


def erp(price: pd.Series, fwd_pe: pd.Series, dgs10: pd.Series) -> pd.Series:
    """Equity risk premium: forward earnings yield minus 10y Treasury (pct pts)."""
    ey = (100.0 / fwd_pe).reindex(price.index).ffill()
    return (ey - dgs10.reindex(price.index).ffill()).dropna()


def growth_gap_gated(trl_pe: pd.Series, fwd_pe: pd.Series,
                     eps_revision_3m: pd.Series) -> pd.Series:
    """Danny's 32x->12x signal with the value-trap gate:
    gap = trl_pe / fwd_pe, but zeroed (set to 1.0 = neutral) whenever
    3M EPS revisions are falling. Cheapness only counts if estimates hold."""
    gap = (trl_pe / fwd_pe).dropna()
    gate = (eps_revision_3m.reindex(gap.index).ffill() >= 0)
    return gap.where(gate, 1.0)


def quality_spread_from_panel(prices: pd.DataFrame, days: int = 63) -> pd.Series:
    """Avg 3M relative return of quality vs junk pairs (QUAL-SPHB, RSP-SPY).
    Deeply negative = even good businesses being dumped; orientation in scoring.py."""
    rels = []
    for a, b in config.QUALITY_PAIRS:
        if a in prices and b in prices:
            rels.append(prices[a].pct_change(days) - prices[b].pct_change(days))
    return (sum(rels) / len(rels) * 100).dropna() if rels else pd.Series(dtype=float)


def eps_inflection(eps_revision_3m: pd.Series, smooth: int = 10) -> pd.Series:
    """Backup trigger for earnings recessions: 2nd derivative of revisions.
    Positive while Panic extreme = 'smoke stopped thickening'."""
    return eps_revision_3m.rolling(smooth).mean().diff(smooth)
