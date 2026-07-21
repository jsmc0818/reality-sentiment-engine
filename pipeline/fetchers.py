"""Raw data pulls. Fetchers return explicit empty results on upstream failure;
the daily publisher decides whether evidence is complete enough to publish."""

import hashlib
import io
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import urljoin

import pandas as pd
import requests
import yfinance as yf

import config

log = logging.getLogger("fetchers")
logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")

CACHE = os.path.join(config.DATA_DIR, "cache")
os.makedirs(CACHE, exist_ok=True)

HTTP_HEADERS = {
    "User-Agent": "sentiment-engine/1.0 (public market-data research)",
}


def _safe_error(error: Exception) -> str:
    """Redact credentials from upstream error messages before they reach logs."""
    message = str(error)
    if config.FRED_API_KEY:
        message = message.replace(config.FRED_API_KEY, "[REDACTED]")
    return re.sub(r"(api_key=)[^&\s]+", r"\1[REDACTED]", message)


# ---------------------------------------------------------------- prices
def yahoo_history(tickers, start="2015-01-01", end=None) -> pd.DataFrame:
    """Adjusted close panel, columns = tickers."""
    try:
        requested = [tickers] if isinstance(tickers, str) else list(tickers)
        df = yf.download(tickers, start=start, end=end, auto_adjust=True,
                         progress=False)["Close"]
        if isinstance(df, pd.Series):
            df = df.to_frame(requested[0])
        # Preserve failed names as NaN columns so downstream universe-coverage
        # gates cannot mistake a partial Yahoo response for a complete panel.
        return df.reindex(columns=requested).dropna(how="all")
    except Exception as e:  # noqa: BLE001
        log.error("yahoo_history failed for %s: %s", tickers, e)
        return pd.DataFrame()


def cboe_index_history(symbol: str, start="2015-01-01") -> pd.Series:
    """Official daily close history for a Cboe volatility index."""
    url = ("https://cdn.cboe.com/api/global/us_indices/daily_prices/"
           f"{symbol}_History.csv")
    try:
        r = requests.get(url, headers=HTTP_HEADERS, timeout=30)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        dates = pd.to_datetime(df["DATE"], errors="coerce")
        closes = pd.to_numeric(df["CLOSE"], errors="coerce")
        series = pd.Series(closes.values, index=dates, name=symbol).dropna()
        series = series[~series.index.duplicated(keep="last")].sort_index()
        return series.loc[pd.Timestamp(start):]
    except Exception as e:  # noqa: BLE001
        log.error("cboe_index_history %s failed: %s", symbol, _safe_error(e))
        return pd.Series(dtype=float, name=symbol)


# ---------------------------------------------------------------- FRED
def fred_series(series_id: str, start="2015-01-01") -> pd.Series:
    if config.FRED_API_KEY:
        url = ("https://api.stlouisfed.org/fred/series/observations"
               f"?series_id={series_id}&api_key={config.FRED_API_KEY}"
               f"&file_type=json&observation_start={start}")
        try:
            r = requests.get(url, headers=HTTP_HEADERS, timeout=30)
            r.raise_for_status()
            obs = r.json()["observations"]
            s = pd.Series({o["date"]: o["value"] for o in obs})
            s.index = pd.to_datetime(s.index)
            return pd.to_numeric(s, errors="coerce").dropna().sort_index()
        except Exception as e:  # noqa: BLE001
            log.warning("FRED API failed for %s; trying public CSV: %s",
                        series_id, _safe_error(e))

    # The graph CSV is an official, no-key FRED endpoint. This keeps local runs
    # reproducible; GitHub Actions should still use the authenticated API above.
    url = ("https://fred.stlouisfed.org/graph/fredgraph.csv"
           f"?id={series_id}&cosd={start}")
    try:
        r = requests.get(url, headers=HTTP_HEADERS, timeout=120)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        date_col = "DATE" if "DATE" in df else "observation_date"
        s = pd.Series(pd.to_numeric(df[series_id], errors="coerce").values,
                      index=pd.to_datetime(df[date_col], errors="coerce"))
        return s.dropna().sort_index()
    except Exception as e:  # noqa: BLE001
        log.error("fred_series %s failed via API and public CSV: %s",
                  series_id, _safe_error(e))
        return pd.Series(dtype=float)


# ---------------------------------------------------------------- constituents
_WIKI = {
    "sp500": ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", 0, "Symbol"),
    "ndx100": ("https://en.wikipedia.org/wiki/Nasdaq-100", 4, "Ticker"),
}

_NASDAQ_100 = "https://www.nasdaq.com/solutions/nasdaq-100/companies"


def _tickers_from_tables(tables, columns) -> list[str]:
    """Find a ticker column without relying on a page's table position."""
    wanted = {c.casefold() for c in columns}
    for table in tables:
        by_name = {str(c).strip().casefold(): c for c in table.columns}
        match = next((by_name[c] for c in wanted if c in by_name), None)
        if match is not None:
            return table[match].astype(str).tolist()

        # Nasdaq's official page currently renders its header as the first row.
        if len(table) and str(table.iloc[0, 0]).strip().casefold() in wanted:
            return table.iloc[1:, 0].astype(str).tolist()
    return []


def constituents(scope: str, max_age_days=7) -> list[str]:
    """Constituent tickers, cached weekly. Mag7 comes from config."""
    if scope == "mag7":
        return config.MAG7_TICKERS
    path = os.path.join(CACHE, f"constituents_{scope}.json")
    if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < max_age_days * 86400:
        return json.load(open(path))
    url, table_ix, col = _WIKI[scope]
    try:
        html = requests.get(url, timeout=30,
                            headers=HTTP_HEADERS).text
        tables = pd.read_html(io.StringIO(html))
        # Table indices and, for Nasdaq-100, the entire table can disappear.
        tickers = _tickers_from_tables(tables, [col, "Ticker", "Ticker symbol",
                                                "Security Symbol"])
        if not tickers and scope == "ndx100":
            r = requests.get(_NASDAQ_100, timeout=30, headers=HTTP_HEADERS)
            r.raise_for_status()
            tickers = _tickers_from_tables(pd.read_html(io.StringIO(r.text)),
                                            ["Symbol", "Ticker"])
        if not tickers:
            raise ValueError(f"no table with column {col}")
        tickers = [t.strip().replace(".", "-") for t in tickers
                   if t and t.strip().casefold() not in {"symbol", "ticker", "nan"}]
        json.dump(tickers, open(path, "w"))
        return tickers
    except Exception as e:  # noqa: BLE001
        log.error("constituents(%s) failed: %s", scope, e)
        return json.load(open(path)) if os.path.exists(path) else []


def constituent_hash(tickers: list[str]) -> str:
    """Stable membership fingerprint, independent of source-list ordering."""
    members = "\n".join(sorted(set(tickers)))
    return hashlib.sha256(members.encode("utf-8")).hexdigest()


def _positive_number(value):
    value = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(value) if pd.notna(value) and value > 0 else None


@lru_cache(maxsize=None)
def _market_cap_row(ticker: str) -> dict | None:
    """Lightweight market-cap proxy used only to rank the current universe."""
    try:
        quote = yf.Ticker(ticker)
        market_cap = _positive_number(getattr(quote.fast_info, "market_cap", None))
        return {"ticker": ticker, "mc": market_cap} if market_cap else None
    except Exception as e:  # noqa: BLE001
        log.debug("Yahoo market-cap proxy failed for %s: %s", ticker, e)
        return None


def _rank_market_cap_rows(tickers: list[str], rows: list[dict]) -> list[dict]:
    """Rank all available proxies first; input list position never selects names."""
    universe = set(tickers)
    valid = [row for row in rows
             if row and row.get("ticker") in universe and _positive_number(row.get("mc"))]
    return sorted(valid, key=lambda row: (-float(row["mc"]), row["ticker"]))


def _ranked_market_cap_proxy(scope: str, tickers: list[str], max_age_hours=24) -> list[dict]:
    """Daily cached, full-universe market-cap-proxy ranking."""
    if not tickers:
        return []
    fingerprint = constituent_hash(tickers)
    path = os.path.join(CACHE, f"market_cap_proxy_{scope}.json")
    if (os.path.exists(path)
            and (time.time() - os.path.getmtime(path)) < max_age_hours * 3600):
        try:
            cached = json.load(open(path))
            if cached.get("constituent_hash") == fingerprint:
                ranked = _rank_market_cap_rows(tickers, cached.get("rows", []))
                if len(ranked) / len(tickers) >= config.MIN_MARKET_CAP_PROXY_NAME_COVERAGE:
                    return ranked
        except Exception as e:  # noqa: BLE001
            log.warning("market-cap proxy cache unreadable for %s: %s", scope, e)

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(_market_cap_row, tickers))
    ranked = _rank_market_cap_rows(tickers, rows)
    name_coverage = len(ranked) / len(tickers) if tickers else 0
    if name_coverage < config.MIN_MARKET_CAP_PROXY_NAME_COVERAGE:
        log.error("market-cap proxy coverage for %s is %.1f%%; need %.1f%%",
                  scope, name_coverage * 100,
                  config.MIN_MARKET_CAP_PROXY_NAME_COVERAGE * 100)
        return []
    json.dump({"constituent_hash": fingerprint, "rows": ranked}, open(path, "w"))
    return ranked


# ---------------------------------------------------------------- CBOE put/call
def cboe_put_call() -> pd.Series:
    """Daily CBOE equity put/call history, cached and incrementally refreshed.

    CBOE's consolidated CSV endpoints now return 403. Its official static archive
    ends in October 2019, so we seed from that file and fill subsequent exchange
    days from the official daily-statistics page. The tracked cache means normal
    daily runs fetch only new dates.
    """
    cache_path = os.path.join(config.DATA_DIR, "cboe_equity_put_call.csv")
    series = pd.Series(dtype=float)
    if os.path.exists(cache_path):
        try:
            cached = pd.read_csv(cache_path, parse_dates=["date"])
            series = pd.Series(cached["ratio"].values, index=cached["date"])
        except Exception as e:  # noqa: BLE001
            log.warning("CBOE cache unreadable; rebuilding: %s", e)

    if series.empty:
        archive = ("https://cdn.cboe.com/resources/options/"
                   "volume_and_call_put_ratios/equitypc.csv")
        try:
            r = requests.get(archive, headers=HTTP_HEADERS, timeout=30)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text), skiprows=2)
            series = pd.Series(pd.to_numeric(df["P/C Ratio"], errors="coerce").values,
                               index=pd.to_datetime(df["DATE"], errors="coerce"))
            series = series.dropna().sort_index()
        except Exception as e:  # noqa: BLE001
            log.warning("CBOE static archive failed: %s", e)

    start = (series.index.max() + pd.Timedelta(days=1)
             if not series.empty else pd.Timestamp("2015-01-01"))
    end = pd.Timestamp.today().normalize()
    dates = list(pd.bdate_range(start, end))

    def fetch_day(day):
        date = day.strftime("%Y-%m-%d")
        url = ("https://www.cboe.com/markets/us/options/market-statistics/"
               f"daily?dt={date}")
        try:
            r = requests.get(url, headers={**HTTP_HEADERS, "RSC": "1"}, timeout=30)
            r.raise_for_status()
            match = re.search(
                r'EQUITY PUT/CALL RATIO","value":"([0-9.]+)', r.text)
            return day, (float(match.group(1)) if match else None)
        except Exception as e:  # noqa: BLE001
            log.warning("CBOE daily fetch failed for %s: %s", date, e)
            return day, None

    if dates:
        log.info("CBOE backfill: checking %d business dates from %s", len(dates),
                 start.date())
        found = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(fetch_day, d) for d in dates]
            for future in as_completed(futures):
                day, value = future.result()
                if value is not None:
                    found[day] = value
        if found:
            series = pd.concat([series, pd.Series(found)]).sort_index()
            series = series[~series.index.duplicated(keep="last")]

    if series.empty:
        log.error("cboe_put_call: archive and daily page failed; component drops out")
        return series

    os.makedirs(config.DATA_DIR, exist_ok=True)
    series.rename_axis("date").rename("ratio").to_csv(cache_path)
    return series


# ---------------------------------------------------------------- forward EPS
def _signed_eps_change_pct(current: float, prior: float) -> float:
    """Directionally correct EPS change across zero and for negative EPS."""
    scale = max(abs(current), abs(prior), config.EPS_SCALE_FLOOR)
    change = (current - prior) / scale * 100
    return float(max(-config.EPS_REVISION_CAP_PCT,
                     min(config.EPS_REVISION_CAP_PCT, change)))


def _eps_trend_changes(trend: pd.DataFrame) -> dict:
    """Next-year analyst EPS change versus Yahoo's prior snapshots.

    The signed-safe denominator makes less-negative EPS an improvement and
    more-negative EPS a deterioration. Sign crossings are retained and capped.
    """
    if trend is None or trend.empty:
        return {}
    period = "+1y"
    if period not in trend.index or "current" not in trend:
        return {}
    current = pd.to_numeric(pd.Series([trend.at[period, "current"]]),
                            errors="coerce").iloc[0]
    if pd.isna(current):
        return {}

    out = {"analyst_period": period}
    for days in (7, 30, 60, 90):
        column = f"{days}daysAgo"
        if column not in trend:
            continue
        prior = pd.to_numeric(pd.Series([trend.at[period, column]]),
                              errors="coerce").iloc[0]
        if pd.isna(prior):
            continue
        out[f"analyst_eps_revision_{days}d_pct"] = _signed_eps_change_pct(
            float(current), float(prior)
        )
    return out


@lru_cache(maxsize=None)
def _estimate_row(ticker: str) -> dict | None:
    """Detailed valuation row; EPS-trend eligibility does not depend on it."""
    try:
        info = yf.Ticker(ticker).info
        return {"ticker": ticker,
                "mc": _positive_number(info.get("marketCap")),
                "fwd_pe": _positive_number(info.get("forwardPE")),
                "trl_pe": _positive_number(info.get("trailingPE"))}
    except Exception as e:  # noqa: BLE001
        log.debug("Yahoo estimate failed for %s: %s", ticker, e)
    return None


@lru_cache(maxsize=None)
def _ticker_eps_trend(ticker: str) -> dict:
    try:
        return _eps_trend_changes(yf.Ticker(ticker).get_eps_trend())
    except Exception as e:  # noqa: BLE001
        log.debug("Yahoo EPS trend failed for %s: %s", ticker, e)
        return {}


def _stored_eps_snapshot(scope: str, asof) -> dict:
    """Return an already-collected same-session snapshot for safe rebuilds."""
    path = os.path.join(config.DATA_DIR, f"eps_history_{scope}.csv")
    if not os.path.exists(path):
        return {}
    try:
        history = pd.read_csv(path)
        target = pd.Timestamp(asof).strftime("%Y-%m-%d")
        rows = history[history["asof"].astype(str) == target]
        if rows.empty:
            return {}
        snapshot = {
            key: (None if pd.isna(value) else value)
            for key, value in rows.iloc[-1].to_dict().items()
        }
        return snapshot if snapshot.get("source_observation_date") == target else {}
    except Exception as e:  # noqa: BLE001
        log.warning("stored EPS snapshot unreadable for %s: %s", scope, e)
        return {}


def forward_eps_snapshot(scope: str, market_asof=None, now_utc=None) -> dict:
    """Scope-weighted trailing and forward EPS inputs from constituent estimates.
    The broad indices are cap-weighted; Mag7 is equal-weighted to match its price basket.
    Returns a dict with valuation and analyst-revision diagnostics.
    Appends daily to data/eps_history_{scope}.csv so revision history self-accumulates."""
    observation_date = pd.Timestamp(
        (now_utc or datetime.now(timezone.utc)).date()
    ).normalize()
    if (market_asof is not None
            and observation_date != pd.Timestamp(market_asof).normalize()):
        stored = _stored_eps_snapshot(scope, market_asof)
        if stored:
            return stored
        log.error(
            "forward_eps_snapshot(%s): EPS observation date %s does not match "
            "the completed market session %s",
            scope, observation_date.date(), pd.Timestamp(market_asof).date(),
        )
        return {}

    tickers = constituents(scope)
    ranked_rows = _ranked_market_cap_proxy(scope, tickers)
    if not ranked_rows:
        log.error("forward_eps_snapshot(%s): no ranked market-cap proxies", scope)
        return {}

    ranked = pd.DataFrame(ranked_rows).reset_index(drop=True)
    ranked["proxy_weight"] = (1 / len(ranked) if scope == "mag7"
                              else ranked["mc"] / ranked["mc"].sum())
    sample = ranked.head(config.TOP_N_FOR_INDEX_EPS).copy()
    target = ranked.head(config.TOP_N_FOR_ANALYST_TRENDS).copy()

    with ThreadPoolExecutor(max_workers=8) as pool:
        details = list(pool.map(_estimate_row, sample["ticker"]))
    by_ticker = {row["ticker"]: row for row in details if row}
    for column in ("fwd_pe", "trl_pe"):
        sample[column] = [by_ticker.get(ticker, {}).get(column)
                          for ticker in sample["ticker"]]

    with ThreadPoolExecutor(max_workers=8) as pool:
        trends = pool.map(_ticker_eps_trend, target["ticker"])
        for row_ix, changes in zip(target.index, trends):
            for key, value in changes.items():
                target.at[row_ix, key] = value

    valuation = sample.dropna(subset=["fwd_pe"])
    valuation = valuation[valuation["fwd_pe"] > 0]
    valuation_w = (valuation["proxy_weight"] / valuation["proxy_weight"].sum()
                   if len(valuation) else pd.Series(dtype=float))
    fwd_pe = (1.0 / float((valuation_w / valuation["fwd_pe"]).sum())
              if len(valuation) else None)
    trailing = sample.dropna(subset=["trl_pe"])
    trailing = trailing[trailing["trl_pe"] > 0]
    trailing_w = (trailing["proxy_weight"] / trailing["proxy_weight"].sum()
                  if len(trailing) else pd.Series(dtype=float))
    trl_pe = (1.0 / float((trailing_w / trailing["trl_pe"]).sum())
              if len(trailing) else None)

    asof = observation_date.strftime("%Y-%m-%d")
    target_weight = float(target["proxy_weight"].sum())
    snap = {
        "asof": asof,
        "source_observation_date": asof,
        "fwd_pe": round(fwd_pe, 3) if fwd_pe else None,
        "trl_pe": round(trl_pe, 3) if trl_pe else None,
        "n_names": int(len(sample)),
        "n_constituents": int(len(tickers)),
        "n_market_cap_proxies": int(len(ranked)),
        "constituent_hash": constituent_hash(tickers),
        "valuation_market_cap_proxy_coverage_pct": round(
            float(valuation["proxy_weight"].sum()) * 100, 1),
        "analyst_eps_target_weight_pct": round(target_weight * 100, 1),
        "source": f"yfinance_market_cap_proxy_ranked_{constituent_hash(tickers)[:12]}",
    }

    revision_columns = []
    for days in (30, 60, 90):
        column = f"analyst_eps_revision_{days}d_pct"
        revision_columns.append(column)
        if column not in target:
            target[column] = float("nan")
        valid = target[column].notna()
        snap[f"analyst_eps_revision_{days}d_coverage_pct"] = round(
            float(target.loc[valid, "proxy_weight"].sum()) * 100, 1
        )

    common_mask = target[revision_columns].notna().all(axis=1)
    common = target.loc[common_mask].copy()
    common_weight = float(common["proxy_weight"].sum())
    snap["analyst_eps_common_coverage_pct"] = round(common_weight * 100, 1)
    snap["analyst_eps_common_cohort_pct"] = round(
        common_weight / target_weight * 100 if target_weight else 0, 1
    )
    snap["n_analyst_trends"] = int(len(common))

    if not common.empty:
        common_w = common["proxy_weight"] / common["proxy_weight"].sum()
        for days, column in zip((30, 60, 90), revision_columns):
            values = common[column].where(
                common[column].abs() > config.EPS_REVISION_DEADBAND_PCT, 0
            )
            snap[column] = round(float((values * common_w).sum()), 3)

        revision_30d = common["analyst_eps_revision_30d_pct"]
        up = revision_30d > config.EPS_REVISION_DEADBAND_PCT
        down = revision_30d < -config.EPS_REVISION_DEADBAND_PCT
        neutral = ~(up | down)
        up_pct = float((up * common_w).sum() * 100)
        neutral_pct = float((neutral * common_w).sum() * 100)
        down_pct = float((down * common_w).sum() * 100)
        snap["analyst_eps_up_breadth_30d_pct"] = round(up_pct, 1)
        snap["analyst_eps_neutral_breadth_30d_pct"] = round(neutral_pct, 1)
        snap["analyst_eps_down_breadth_30d_pct"] = round(down_pct, 1)
        snap["analyst_eps_revision_breadth_30d_pct"] = round(
            up_pct + .5 * neutral_pct, 1
        )

    column_7d = "analyst_eps_revision_7d_pct"
    if column_7d in target:
        seven = target.dropna(subset=[column_7d])
        if not seven.empty:
            seven_w = seven["proxy_weight"] / seven["proxy_weight"].sum()
            values = seven[column_7d].where(
                seven[column_7d].abs() > config.EPS_REVISION_DEADBAND_PCT, 0
            )
            snap[column_7d] = round(float((values * seven_w).sum()), 3)

    hist_path = os.path.join(config.DATA_DIR, f"eps_history_{scope}.csv")
    prior = pd.read_csv(hist_path) if os.path.exists(hist_path) else pd.DataFrame()
    updated = pd.concat([prior, pd.DataFrame([snap])], ignore_index=True)
    updated = updated.drop_duplicates("asof", keep="last")
    updated.to_csv(hist_path, index=False)
    return snap


def eps_history(scope: str) -> pd.DataFrame:
    path = os.path.join(config.DATA_DIR, f"eps_history_{scope}.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, parse_dates=["asof"]).drop_duplicates("asof", keep="last")
    return df.set_index("asof").sort_index()


# ---------------------------------------------------------------- Shiller (backtest proxy)
def shiller_earnings() -> pd.Series:
    """Monthly S&P realized 12m earnings (Shiller ie_data). Backtest proxy for
    EPS revisions; documented limitation in README."""
    urls = []
    try:
        home = requests.get("https://shillerdata.com/", headers=HTTP_HEADERS,
                            timeout=30)
        home.raise_for_status()
        match = re.search(r'href=["\']([^"\']*ie_data\.xls[^"\']*)', home.text,
                          flags=re.IGNORECASE)
        if match:
            urls.append(urljoin(home.url, match.group(1)))
    except Exception as e:  # noqa: BLE001
        log.warning("ShillerData workbook discovery failed: %s", e)
    urls.append("http://www.econ.yale.edu/~shiller/data/ie_data.xls")

    for url in urls:
        try:
            r = requests.get(url, headers=HTTP_HEADERS, timeout=45)
            r.raise_for_status()
            raw = pd.read_excel(io.BytesIO(r.content), sheet_name="Data", skiprows=7)
            raw = raw.rename(columns=lambda c: str(c).strip())
            numeric_dates = pd.to_numeric(raw["Date"], errors="coerce")
            years = numeric_dates.floordiv(1)
            months = ((numeric_dates - years) * 100).round()
            valid = numeric_dates.notna() & months.between(1, 12)
            dates = pd.Series(pd.NaT, index=raw.index, dtype="datetime64[ns]")
            dates.loc[valid] = pd.to_datetime({
                "year": years.loc[valid].astype(int),
                "month": months.loc[valid].astype(int),
                "day": 1,
            }).values
            s = pd.Series(pd.to_numeric(raw["E"], errors="coerce").values,
                          index=pd.DatetimeIndex(dates))
            s = s[~s.index.isna()].dropna().sort_index()
            if s.empty:
                raise ValueError("no earnings observations parsed")
            return s
        except Exception as e:  # noqa: BLE001
            log.warning("Shiller workbook failed (%s): %s", url, e)
    log.error("shiller_earnings: all sources failed; backtest drops divergence proxy")
    return pd.Series(dtype=float)
