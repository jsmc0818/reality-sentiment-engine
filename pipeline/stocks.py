"""Fixed-universe, dated stock evidence. No provider response is published verbatim.

Prices describe market behavior, not investor motives. Financial statements and
analyst expectations remain separate. Valuation is calculated in model.js from
explicit, user-adjustable research assumptions, never from an analyst price target.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

import config
from pipeline import fetchers as F

CATALOG = {
    "MSFT": {"name": "Microsoft", "sector": "Cloud & software", "ir": "https://www.microsoft.com/en-us/Investor/",
        "drivers": ["Azure demand and cloud capacity", "AI monetization versus infrastructure spending", "Recurring software margins and cash conversion"],
        "question": "Can cloud and AI demand earn an adequate return on the infrastructure required to serve it?",
        "countercase": "Strong revenue growth can coexist with weaker owner cash flow when capital spending and depreciation rise.",
        "invalidation": "Reassess if cloud growth weakens while infrastructure commitments and cash outflows keep rising."},
    "NVDA": {"name": "NVIDIA", "sector": "AI compute", "ir": "https://investor.nvidia.com/",
        "drivers": ["Data-center demand and customer concentration", "Product transitions, supply and gross margins", "Export access and competing compute architectures"],
        "question": "How much durable demand remains after the current infrastructure buildout?",
        "countercase": "Exceptional current margins and growth may normalize as customers improve utilization or deploy alternative chips.",
        "invalidation": "Reassess if customer spending slows, inventory builds, or pricing power deteriorates across product cycles."},
    "GOOGL": {"name": "Alphabet", "sector": "Search & cloud", "ir": "https://abc.xyz/investor/",
        "drivers": ["Search usage, monetization and traffic costs", "Cloud growth and operating profitability", "AI infrastructure spending and regulatory remedies"],
        "question": "Can AI investment defend search economics while expanding cloud profit?",
        "countercase": "Cheap-looking earnings can be misleading if AI changes search monetization or materially increases the cost per query.",
        "invalidation": "Reassess if search economics weaken persistently or capital intensity rises without corresponding cash generation."},
    "AMZN": {"name": "Amazon", "sector": "Commerce & cloud", "ir": "https://ir.aboutamazon.com/",
        "drivers": ["AWS growth, margins and capacity investment", "Retail fulfillment productivity", "Advertising contribution and free cash flow"],
        "question": "Can cloud and advertising profits fund growth while retail efficiency improves?",
        "countercase": "Consolidated margins can conceal very different businesses; lease obligations and capital spending can absorb operating gains.",
        "invalidation": "Reassess if AWS returns weaken and retail cash generation fails to offset investment requirements."},
    "META": {"name": "Meta", "sector": "Digital advertising", "ir": "https://investor.atmeta.com/",
        "drivers": ["Advertising demand and monetization", "AI spending versus engagement and advertiser returns", "Operating costs and long-duration investments"],
        "question": "Will AI-driven monetization justify the growing investment base?",
        "countercase": "Better ad performance may already be priced in while infrastructure spending and speculative projects reduce cash available to owners.",
        "invalidation": "Reassess if ad growth and monetization weaken while investment commitments continue to expand."},
    "AAPL": {"name": "Apple", "sector": "Devices & services", "ir": "https://investor.apple.com/",
        "drivers": ["Device replacement demand and installed base", "Services growth and ecosystem economics", "Regional demand, regulation and capital returns"],
        "question": "Can ecosystem cash generation support the growth expectations embedded in the share price?",
        "countercase": "Buybacks can support EPS while underlying demand slows; services economics may face regulatory pressure.",
        "invalidation": "Reassess if installed-base monetization weakens alongside sustained device demand deterioration."},
    "TSLA": {"name": "Tesla", "sector": "Vehicles & energy", "ir": "https://ir.tesla.com/",
        "drivers": ["Vehicle demand, pricing and margins", "Energy deployment and cash generation", "Autonomy commercialization and required investment"],
        "question": "How much of today's valuation depends on businesses that have yet to demonstrate durable cash flows?",
        "countercase": "A model anchored to current operations may miss successful autonomy or robotics commercialization. Those outcomes need separate evidence and scenarios.",
        "invalidation": "Reassess if core cash generation deteriorates while future-business assumptions become harder to substantiate."},
}
ROOT = Path(config.DATA_DIR)
VERSION = "expectations-v1"


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def row(frame, key, cols):
    if key not in frame.index:
        return None
    values = [number(frame.at[key, col]) for col in cols]
    return values if all(v is not None for v in values) else None


def financials(income, cashflow, balance):
    """Four actual discrete quarters; missing quarters never become zero."""
    income = income.sort_index(axis=1, ascending=False)
    cols = list(income.columns[:4])
    if len(cols) != 4 or any(not 70 <= (cols[i] - cols[i + 1]).days <= 110 for i in range(3)):
        raise ValueError("four comparable income quarters required")
    if any(c not in cashflow.columns for c in cols):
        raise ValueError("cash-flow quarters must align with income")
    revenue, operating = row(income, "Total Revenue", cols), row(income, "Operating Income", cols)
    cfo, capex = row(cashflow, "Operating Cash Flow", cols), row(cashflow, "Capital Expenditure", cols)
    if revenue is None or operating is None or cfo is None or capex is None or sum(revenue) <= 0:
        raise ValueError("required statement fields missing")
    if any(c > 0 for c in capex):
        raise ValueError("unexpected capital expenditure sign")
    latest = cols[0]
    prior_dates = [c for c in income.columns if 350 <= (latest - c).days <= 380]
    prior_revenue = row(income, "Total Revenue", prior_dates[:1]) if prior_dates else None
    prior_operating = row(income, "Operating Income", prior_dates[:1]) if prior_dates else None
    growth = ((revenue[0] / prior_revenue[0] - 1) * 100
              if prior_revenue and prior_revenue[0] > 0 else None)
    margin_change = ((operating[0] / revenue[0] - prior_operating[0] / prior_revenue[0]) * 100
                     if prior_operating and prior_revenue and prior_revenue[0] > 0 and revenue[0] > 0 else None)
    sbc = row(cashflow, "Stock Based Compensation", cols)
    balance = balance.sort_index(axis=1, ascending=False)
    if balance.empty:
        raise ValueError("balance sheet missing")
    bd = balance.columns[0]
    cash = row(balance, "Cash Cash Equivalents And Short Term Investments", [bd])
    debt = row(balance, "Total Debt", [bd])
    if cash is None or debt is None or min(cash[0], debt[0]) < 0:
        raise ValueError("cash and debt required")
    total = sum(revenue)
    return {
        "period_end": str(latest.date()), "balance_date": str(bd.date()),
        "revenue": total, "operating_income": sum(operating),
        "operating_margin_pct": sum(operating) / total * 100,
        "revenue_growth_yoy_pct": growth, "margin_change_yoy_pts": margin_change,
        "operating_cash_flow": sum(cfo), "capex": -sum(capex),
        "free_cash_flow": sum(cfo) + sum(capex),
        "sbc": sum(sbc) if sbc is not None else None,
        "cash": cash[0], "debt": debt[0],
        "quarters": [{"end": str(c.date()), "revenue": revenue[i],
                      "operating_income": operating[i], "cfo": cfo[i], "capex": -capex[i]}
                     for i, c in enumerate(cols)],
    }


def market_evidence(history, benchmark):
    """Signed price-pressure proxy; no claim to observe emotion or causal fear."""
    close = history["Close"].dropna()
    adjusted = history.get("Adj Close", history["Close"]).reindex(close.index)
    aligned = pd.concat([adjusted.rename("stock"), benchmark.rename("benchmark")], axis=1).dropna()
    if len(close) < 252 or len(aligned) < 64 or aligned.index[-1] != close.index[-1]:
        raise ValueError("insufficient comparable market history")
    ret63 = (adjusted.iloc[-1] / adjusted.iloc[-64] - 1) * 100
    excess = ((aligned.stock.iloc[-1] / aligned.stock.iloc[-64])
              - (aligned.benchmark.iloc[-1] / aligned.benchmark.iloc[-64])) * 100
    trend = (adjusted.iloc[-1] / adjusted.iloc[-200:].mean() - 1) * 100
    volume = history.Volume.reindex(close.index)
    signed_volume = np.sign(adjusted.diff()).mul(volume).iloc[-20:].sum() / volume.iloc[-20:].sum()
    if not math.isfinite(signed_volume):
        raise ValueError("volume history unavailable")
    # Fixed transparent scales. These heuristics are unvalidated, not percentiles.
    parts = {"return_3m": float(np.clip(ret63 / 25, -1, 1)),
             "relative_return": float(np.clip(excess / 15, -1, 1)),
             "trend": float(np.clip(trend / 25, -1, 1)),
             "volume_balance": float(signed_volume)}
    mood = 50 + 50 * (.30 * parts["return_3m"] + .25 * parts["relative_return"]
                      + .25 * parts["trend"] + .20 * parts["volume_balance"])
    return {"price": float(close.iloc[-1]), "price_date": str(close.index[-1].date()),
            "change_1d_pct": (close.iloc[-1] / close.iloc[-2] - 1) * 100,
            "return_1w_pct": (adjusted.iloc[-1] / adjusted.iloc[-6] - 1) * 100,
            "return_3m_pct": ret63, "relative_return_3m_pts": excess,
            "distance_200d_pct": trend,
            "drawdown_1y_pct": (adjusted.iloc[-1] / adjusted.iloc[-252:].max() - 1) * 100,
            "volume_balance": float(signed_volume), "mood": round(mood, 2),
            "history": [{"date": str(d.date()), "close": float(v)}
                        for d, v in close.iloc[-126:].items()]}


def fetch_stock(symbol, benchmark, cutoff, collected):
    result = {"symbol": symbol, **CATALOG[symbol], "collected_at": collected,
              "status": "unavailable", "market": None, "financials": None, "estimates": None,
              "previous_observation": None}
    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="2y", auto_adjust=False)
        history.index = history.index.tz_localize(None).normalize()
        history = history.loc[:cutoff]
        result["market"] = market_evidence(history, benchmark)
        info = ticker.info
        if info.get("currency") != "USD" or info.get("financialCurrency") != "USD":
            raise ValueError("USD market and financial statements required")
        market_cap, quote = number(info.get("marketCap")), number(info.get("regularMarketPrice"))
        if not market_cap or not quote or min(market_cap, quote) <= 0:
            raise ValueError("aggregate equity capitalization unavailable")
        # Aggregate issuer cap / provider quote handles Alphabet and Meta's share classes.
        result["market"]["market_cap"] = market_cap / quote * result["market"]["price"]
        result["financials"] = financials(ticker.quarterly_income_stmt,
                                         ticker.quarterly_cashflow, ticker.quarterly_balance_sheet)
        trend = F._ticker_eps_trend(symbol)
        if trend.get("analyst_target_end_date") and trend.get("analyst_eps_current") is not None:
            result["estimates"] = {"target_end": trend["analyst_target_end_date"],
                "current_eps": trend["analyst_eps_current"],
                "revision_30d_pct": trend.get("analyst_eps_revision_30d_pct"),
                "revision_60d_pct": trend.get("analyst_eps_revision_60d_pct"),
                "revision_90d_pct": trend.get("analyst_eps_revision_90d_pct")}
        result["status"] = "available"
    except Exception:
        # No credentials, arbitrary upstream messages, or scraped prose in public files.
        result["status"] = "limited" if result["market"] else "unavailable"
    return result


def validate(payload):
    from pipeline.public_output import _keys, _number
    _keys(payload, {"schema_version", "methodology", "generated_at", "stocks"}, "stocks root")
    if payload["schema_version"] != 1 or payload["methodology"] != VERSION:
        raise ValueError("unsupported stock methodology")
    stamp = datetime.fromisoformat(payload["generated_at"])
    if stamp.tzinfo is None:
        raise ValueError("publication timezone required")
    if not isinstance(payload["stocks"], list) or [r["symbol"] for r in payload["stocks"]] != list(CATALOG):
        raise ValueError("fixed stock universe required")
    for r in payload["stocks"]:
        _keys(r, {"symbol", *CATALOG[r["symbol"]], "collected_at", "status", "market", "financials", "estimates", "previous_observation"}, "stock")
        for key, value in CATALOG[r["symbol"]].items():
            if r[key] != value:
                raise ValueError("unapproved stock description")
        if r["status"] not in {"available", "limited", "unavailable"}:
            raise ValueError("unsupported evidence status")
        if r["collected_at"] != payload["generated_at"]:
            raise ValueError("collection timestamps disagree")
        m, f, e = r["market"], r["financials"], r["estimates"]
        if r["status"] == "available" and (m is None or f is None or "market_cap" not in m):
            raise ValueError("available stock lacks evidence")
        if m is not None:
            required = {"price", "price_date", "change_1d_pct", "return_1w_pct", "return_3m_pct", "relative_return_3m_pts", "distance_200d_pct", "drawdown_1y_pct", "volume_balance", "mood", "history"}
            _keys(m, required | {"market_cap"}, "market", exact=False)
            if not required <= m.keys():
                raise ValueError("missing market fields")
            date = datetime.strptime(m["price_date"], "%Y-%m-%d").date()
            if date > stamp.date():
                raise ValueError("future quote")
            for key in required - {"price_date", "history"}:
                _number(m[key], key, -1e8, 1e8)
            _number(m["price"], "price", .001, 1e7)
            _number(m["mood"], "mood", 0, 100)
            if "market_cap" in m:
                _number(m["market_cap"], "market cap", 1, 1e15)
            if not 2 <= len(m["history"]) <= 126:
                raise ValueError("invalid price history length")
            prior = ""
            for point in m["history"]:
                _keys(point, {"date", "close"}, "price history")
                datetime.strptime(point["date"], "%Y-%m-%d")
                if not prior < point["date"] <= m["price_date"]:
                    raise ValueError("unordered price history")
                prior = point["date"]
                _number(point["close"], "historical close", .001, 1e7)
            if m["history"][-1] != {"date": m["price_date"], "close": m["price"]}:
                raise ValueError("price endpoints disagree")
        if f is not None:
            _keys(f, {"period_end", "balance_date", "revenue", "operating_income", "operating_margin_pct", "revenue_growth_yoy_pct", "margin_change_yoy_pts", "operating_cash_flow", "capex", "free_cash_flow", "sbc", "cash", "debt", "quarters"}, "financials")
            for key in ("period_end", "balance_date"):
                if datetime.strptime(f[key], "%Y-%m-%d").date() > stamp.date():
                    raise ValueError("future financial period")
            for key, value in f.items():
                if key in {"period_end", "balance_date", "quarters"}:
                    continue
                if value is None and key in {"sbc", "revenue_growth_yoy_pct", "margin_change_yoy_pts"}:
                    continue
                _number(value, key, -1e14, 1e14)
            if f["revenue"] <= 0 or min(f["capex"], f["cash"], f["debt"]) < 0:
                raise ValueError("invalid financial sign")
            if abs(f["free_cash_flow"] - (f["operating_cash_flow"] - f["capex"])) > 1:
                raise ValueError("cash flow bridge does not reconcile")
            if len(f["quarters"]) != 4:
                raise ValueError("four quarters required")
            for q in f["quarters"]:
                _keys(q, {"end", "revenue", "operating_income", "cfo", "capex"}, "quarter")
                datetime.strptime(q["end"], "%Y-%m-%d")
                for k in ("revenue", "operating_income", "cfo", "capex"):
                    _number(q[k], k, -1e14, 1e14)
            dates = [datetime.strptime(q["end"], "%Y-%m-%d") for q in f["quarters"]]
            if f["quarters"][0]["end"] != f["period_end"] or any(
                not 70 <= (dates[i] - dates[i + 1]).days <= 110 for i in range(3)
            ):
                raise ValueError("quarter dates must be consecutive and match period end")
            for total_key, quarter_key in (("revenue", "revenue"), ("operating_income", "operating_income"),
                                           ("operating_cash_flow", "cfo"), ("capex", "capex")):
                if abs(f[total_key] - sum(q[quarter_key] for q in f["quarters"])) > 1:
                    raise ValueError("quarter observations do not reconcile to TTM totals")
            if abs(f["operating_margin_pct"] - f["operating_income"] / f["revenue"] * 100) > .001:
                raise ValueError("operating margin does not reconcile")
        if e is not None:
            _keys(e, {"target_end", "current_eps", "revision_30d_pct", "revision_60d_pct", "revision_90d_pct"}, "estimates")
            datetime.strptime(e["target_end"], "%Y-%m-%d")
            for key, value in e.items():
                if key != "target_end" and value is not None:
                    _number(value, key, -1e5, 1e5)
        previous = r["previous_observation"]
        if previous is not None:
            _keys(previous, {"date", "period_end", "revenue", "operating_margin_pct", "mood"}, "previous stock observation")
            if not 7 <= (stamp.date() - datetime.strptime(previous["date"], "%Y-%m-%d").date()).days <= 14:
                raise ValueError("comparison must be a 7–14 day old observation")
            datetime.strptime(previous["period_end"], "%Y-%m-%d")
            for key in ("revenue", "operating_margin_pct", "mood"):
                _number(previous[key], key, -1e14, 1e14)
    json.dumps(payload, allow_nan=False)


def publish(payload):
    validate(payload)
    # Preserve underlying observations prospectively. Same-day reruns replace that day's snapshot.
    date = payload["generated_at"][:10]
    targets = [ROOT / "stocks.json", ROOT / "stock_observations" / f"{date}.json"]
    for target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
        temporary.replace(target)


def attach_previous(stocks, now):
    """Use an actually archived vintage, never reconstruct historical financials."""
    earliest, latest = (now.date() - timedelta(days=d) for d in (14, 7))
    candidates = sorted((ROOT / "stock_observations").glob("????-??-??.json"), reverse=True)
    for file in candidates:
        if not str(earliest) <= file.stem <= str(latest):
            continue
        prior = json.loads(file.read_text())
        if prior.get("methodology") != VERSION:
            continue
        by_symbol = {s["symbol"]: s for s in prior["stocks"]}
        for s in stocks:
            old = by_symbol.get(s["symbol"], {})
            f, m = old.get("financials"), old.get("market")
            if s["previous_observation"] is None and f and m:
                s["previous_observation"] = {"date": file.stem, "period_end": f["period_end"],
                    "revenue": f["revenue"], "operating_margin_pct": f["operating_margin_pct"], "mood": m["mood"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    if args.validate:
        validate(json.loads((ROOT / "stocks.json").read_text()))
        print("validated stock evidence")
        return
    now = datetime.now(timezone.utc)
    collected = now.isoformat(timespec="seconds")
    cutoff = F.completed_market_cutoff(now)
    benchmark = yf.Ticker("SPY").history(period="2y", auto_adjust=True)["Close"]
    benchmark.index = benchmark.index.tz_localize(None).normalize()
    benchmark = benchmark.loc[:cutoff]
    if benchmark.empty:
        raise RuntimeError("benchmark unavailable; previous stock publication retained")
    with ThreadPoolExecutor(max_workers=3) as pool:
        stocks = list(pool.map(lambda s: fetch_stock(s, benchmark, cutoff, collected), CATALOG))
    if not any(s["status"] == "available" for s in stocks):
        raise RuntimeError("all stock evidence unavailable; previous publication retained")
    attach_previous(stocks, now)
    publish({"schema_version": 1, "methodology": VERSION, "generated_at": collected, "stocks": stocks})
    print(f"published stock evidence: {sum(s['status'] == 'available' for s in stocks)} of {len(stocks)} complete")


if __name__ == "__main__":
    main()
