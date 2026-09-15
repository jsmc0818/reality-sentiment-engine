# Reality Sentiment Engine

**Does today’s price compensate you for today’s uncertainty?**

A public, mobile-friendly research dashboard for seven companies, with S&P 500,
Nasdaq-100 and equal-weight Mag7 index context.

[Open the dashboard](https://jsmc0818.github.io/reality-sentiment-engine/) · [Why I built it](ABOUT.md)

## The decision workflow

1. Observe signed market pressure. Selling and buying pressure are proxies for mood, not proof of investor motives.
2. Inspect business resilience using reported growth, margins, cash generation and leverage. Consensus revisions are separate expectations evidence.
3. Inspect reference valuation assumptions and solve for growth needed to justify the current price.
4. Stress growth, margins, reinvestment, tax and discount rate. Read the counterargument and thesis-break condition.

The opportunity map compares price pressure with reference-model upside. Dot color
represents financial resilience. Company research views expose financial periods,
sources, scenario assumptions and a cash-flow bridge. Selection links use
`#stock=MSFT` (or another covered symbol), so research pages can be bookmarked.

## What the model actually does

### Market behavior

Mood runs from 0 (selling pressure) to 100 (buying pressure), using:

- 30% three-month adjusted return, divided by 25 percentage points.
- 25% three-month return minus SPY return, divided by 15 points.
- 25% distance from the 200-day adjusted-price average, divided by 25 points.
- 20% signed daily volume balance over 20 sessions.

Each component is clipped to −1 through +1. The weighted result maps linearly to
0–100. These are fixed, unvalidated heuristics, not percentiles or emotional
measurements. Mood ≤30 is selling pressure and ≥70 is buying pressure. Broad
index panic is a separate methodology and is never relabeled as stock mood.

### Financial resilience

Resilient requires nonnegative latest-quarter year-over-year revenue growth,
margin compression no worse than 1 point, positive trailing free cash flow and
net debt no higher than 3 times operating cash flow (or net cash).

Growth below −5%, margin compression beyond 3 points, nonpositive operating profit,
or net debt with nonpositive operating cash flow / leverage beyond 4 times cash
flow flags weakening evidence. Otherwise the reading is mixed. Missing comparable
growth or margin evidence is unknown. This is not an independent moat assessment.

### Reference valuation

`model.js` runs the same five-year FCFF calculation in the browser and in CI:

- Starting revenue and operating margin come from four aligned reported quarters.
- Revenue grows at the selected five-year CAGR; margin transitions linearly to the selected year-five margin.
- Net reinvestment is positive incremental revenue divided by sales-to-capital. No cash release is assumed when revenue contracts.
- Operating income after normalized tax less net reinvestment gives FCFF.
- Terminal value uses year-five margin and perpetual growth below WACC.
- Discounted FCFF plus cash less debt gives equity value, floored at zero.
- Equity value divided by aggregate issuer market capitalization, multiplied by the quoted share price, expresses model value per quoted share. This handles multiple share classes without treating one class’s share count as the whole issuer.

**Default assumptions are mechanical research starting points.** Latest-quarter
revenue growth is clipped to 0–25%, TTM margin to 1–65%; both are rounded to half
percentage points. Other defaults: 10% WACC, 3% terminal growth, 21% tax, 2×
sales-to-capital. They are not company-specific forecasts or approved fair values.

Bear: growth −5 points, margin −3 points, WACC +2 points. Bull: growth +5 points,
margin +3 points, WACC −1 point, within displayed input limits. Scenarios are not
confidence intervals and need not be ordered when growth destroys value.

Reverse valuation scans growth from −10% to 60% and reports all detected crossings.
There may be no solution or multiple solutions. Other assumptions remain fixed.
A numerical solution is not the market’s uniquely identifiable growth forecast.

### Research classifications

A discount requires a 20% margin below reference value. A premium requires price
more than 15% above reference value. Fear discount candidates additionally require
selling pressure and resilient financial evidence. Optimism priced in requires
buying pressure and a premium. Other states retain uncertainty explicitly.

Classification requires sufficient dated evidence. Price age beyond one completed
weekday session, collection age beyond four calendar days, income period age
beyond 150 days or balance-sheet age beyond 200 days blocks classification.
Weekday rules are conservative around market holidays. Dated financial evidence
can remain inspectable after classification is withheld.

## Data and publication

Yahoo Finance supplies closing prices, financial statements and fiscal-targeted
EPS observations. `pipeline/stocks.py` publishes allowlisted fields only, validates
aligned quarters, and preserves dated observations in `data/stock_observations/`.
Provider collection time is not a claim that every estimate was updated that day.
Company concerns and counterarguments are standing research questions, not a
news feed or causal explanations of daily returns.

The website fetches only fixed static JSON files. Visitors cannot execute the
pipeline or submit arbitrary tickers to upstream services. Scenario edits stay
in browser memory. The About page contains intentionally published authorship;
market-data files contain no profile, credentials or general provider responses.

GitHub Actions attempt index scores at 22:30 UTC and stock evidence at 22:45 UTC,
Monday through Friday, then retry at 10:30/10:45 UTC Tuesday through Saturday
if providers lag. Each run targets the latest completed US trading weekday.
Both jobs retry once after a transient failure and
serialize market-data commits from the latest main checkout. Date and freshness
gates still block mismatched evidence; older scores are never relabeled as current.
Successful jobs trigger GitHub Pages publication. Upstream failures retain prior
files where the entire stock fetch fails; partial evidence is explicitly limited.
Freshness gates prevent prior data from being displayed as current conviction.

## Run locally

```bash
pip install -r requirements.txt
python -m pipeline.stocks
python -m pipeline.stocks --validate
python -m unittest discover -s tests -q
node app.js
node tests/test_model.js
python -m http.server 8765 --bind 127.0.0.1
```

The stock pipeline needs no FRED key. Index collection still uses the original
`python -m pipeline.run_daily` workflow. See [index methodology](INDEX_METHODOLOGY.md)
and the [public data contract](WEBSITE_DATA_CONTRACT.md).

## Validation boundaries

This research edition has **not demonstrated an investment edge**. All reference
assumptions and thresholds are unvalidated. Financial statement aggregates do not
replace segment research; option value, future dilution, acquisitions and detailed
lease/cash adjustments are not separately modeled.

The default model can miss economically important investment requirements or
future business lines. Terminal value may dominate outputs. The dashboard
therefore presents sensitivity, sources and counterarguments alongside results.

Prospective stock observations start with their first real collection under
`expectations-v1`. No reconstructed historical stock verdicts are presented. A
future evaluation should compare all qualifying episodes against price-pressure
alone and predefined accumulation policies, including drawdowns, estimate cuts,
missed opportunities and waiting in cash.

Existing index timelines and episode records remain intact. The legacy arithmetic
`fundamental_discrepancy` is retained for historical schema compatibility but is
removed from the dashboard and is not an economically calibrated valuation gap.
The historical proxy backtest and index episodes cannot validate this stock model.

## Files

- `index.html`, `styles.css`, `app.js`: dashboard and evidence views.
- `model.js`: valuation, reverse solver, freshness and classifications.
- `pipeline/stocks.py`: fixed-universe evidence collection, validation and archival.
- `about.html`, `ABOUT.md`: project mission and authorship.
- `data/stocks.json`: public dated company evidence.
- `data/stock_observations/`: prospective underlying observations, retained in source.
- `.github/workflows/stock-research.yml`: independent scheduled stock refresh.
- `.github/workflows/pages.yml`: allowlisted public artifact and deployment.
