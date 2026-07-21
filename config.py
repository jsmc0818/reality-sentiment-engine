"""Central configuration for live research scores and legacy validation."""

import os

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")

# ---------------------------------------------------------------- scopes
SCOPES = ["sp500", "ndx100", "mag7"]

INDEX_TICKER = {          # price series per scope
    "sp500": "^GSPC",
    "ndx100": "^NDX",
}

BENCHMARK = "^GSPC"       # excess returns benchmarked vs S&P 500

# Equal-weight Magnificent Seven basket.
MAG7_TICKERS = ["NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA"]

SECTOR_ETFS = ["XLK", "XLF", "XLV", "XLY", "XLP", "XLE",
               "XLI", "XLB", "XLU", "XLRE", "XLC"]

VOL_TICKERS = ["^VIX", "^VVIX", "^VXN"]
QUALITY_PAIRS = [("QUAL", "SPHB"), ("RSP", "SPY")]
FRED_SERIES = {
    "hy_oas": "BAMLH0A0HYM2",
    # ICE restricted HY OAS history to three years in April 2026. BAA10Y is
    # the complete daily credit-spread proxy used only for historical fitting.
    "credit_history_proxy": "BAA10Y",
    "dgs10": "DGS10",
}

# ---------------------------------------------------------------- constants
PCTL_WINDOW_DAYS = 252 * 5     # 5y self-history for percentile ranks
MIN_PCTL_OBSERVATIONS = 252    # publish after 1y when an upstream history is shorter
VELOCITY_DAYS = 10             # z-score window for velocity components
Z_LOOKBACK_DAYS = 252          # 1y window to standardize velocity
CORR_WINDOW_DAYS = 20
BREADTH_MA_DAYS = 200
FWD_RETURN_DAYS = 63           # 3M forward window for IC
DIVERGENCE_LOOKBACK_DAYS = 63  # 3M window for the Divergence Score
SHRINKAGE = 0.50               # pull IC weights 50% toward equal weight
WALK_FORWARD_SPLIT = "2022-01-01"
TOP_N_FOR_INDEX_EPS = 100      # top market-cap-proxy names used for valuation
TOP_N_FOR_ANALYST_TRENDS = 30  # top market-cap-proxy names queried for EPS trends
MIN_FORWARD_EPS_SNAPSHOTS = 64 # endpoints required for one 63-day revision interval
MIN_ANALYST_TRENDS = 5         # minimum constituent trends for a fundamentals reading
MIN_ANALYST_TREND_COVERAGE = .70  # common cohort / targeted analyst cohort
MIN_ANALYST_MARKET_CAP_COVERAGE = .40  # common cohort / full scope proxy weight
MIN_MARKET_CAP_PROXY_NAME_COVERAGE = .90
MIN_CONSTITUENT_PRICE_COVERAGE = .90
MIN_MAG7_PRICE_COVERAGE = 1.0
EPS_REVISION_DEADBAND_PCT = .25
EPS_REVISION_CAP_PCT = 50.0
EPS_SCALE_FLOOR = .05
MAX_PANIC_STALE_BUSINESS_DAYS = 2
MAX_PUBLICATION_STALE_BUSINESS_DAYS = 1
MIN_PANIC_COMPONENT_COVERAGE = 1.0

PANIC_PROVENANCE = {
    "term_structure": "Cboe official daily closes (VIX9D / VIX3M)",
    "credit_velocity": "FRED BAMLH0A0HYM2",
    "vvix": "Yahoo Finance adjusted close (^VVIX)",
    "breadth": "Yahoo Finance constituent adjusted closes",
    "put_call": "Cboe Equity Put/Call Ratio",
    "vxn_ratio": "Yahoo Finance adjusted close (^VXN / ^VIX)",
    "vxn_level": "Yahoo Finance adjusted close (^VXN)",
    "pairwise_corr": "Yahoo Finance Magnificent Seven downside-return correlations",
}

# ---------------------------------------------------------------- launch weights
# Panic components use their stated level, ratio, breadth, correlation, or velocity.
PANIC_WEIGHTS = {
    "sp500":  {"term_structure": .25, "credit_velocity": .22, "vvix": .20,
               "breadth": .18, "put_call": .15},
    # no VXN9D/VXN3M exist -> vxn_ratio (VXN/VIX) replaces term structure
    "ndx100": {"vxn_ratio": .15, "vxn_level": .15, "credit_velocity": .25,
               "breadth": .25, "put_call": .20},
    # breadth is meaningless with seven names -> pairwise correlation
    "mag7":   {"vxn_ratio": .15, "vxn_level": .15, "credit_velocity": .25,
               "pairwise_corr": .25, "put_call": .20},
}

# Legacy historical-entry backtest only. These proxies are not Fundamentals.
LEGACY_REALITY_WEIGHTS = {
    scope: {"divergence": .35, "valuation_anchor": .25,
            "sector_correlation": .22, "quality_spread": .18}
    for scope in SCOPES
}

# Decision thresholds (0-100)
PANIC_HIGH = 75
PANIC_WATCH = 67
FUNDAMENTALS_HEALTHY = 60
FUNDAMENTALS_BROKEN = 40
LEGACY_REALITY_BROKEN = 35      # historical proxy-overlay backtest only

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
