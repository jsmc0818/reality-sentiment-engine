# Expectations research edition: public contract

This section supersedes the legacy dashboard restrictions below where they conflict.

The intentionally public site consists of `index.html`, `about.html`, `styles.css`,
`app.js`, `model.js`, `assets/favicon.svg`, and the fixed JSON publications
`data/scores.json`, `data/timeline.json`, `data/stocks.json`. The About page may
contain the user-authorized author name and project story. Market-data records
never contain creator profiles, credentials, arbitrary upstream bodies or errors.

Seven fixed stock symbols may be selected. Visitors may change bounded valuation
assumptions in memory. No data or scenario changes are submitted to a server;
there is no arbitrary ticker proxy, public refresh, authentication or tracking.

`stocks.json` schema 1 contains methodology `expectations-v1`, generation timestamp
and seven fixed stock records. `pipeline.stocks.validate` checks exact allowlists,
financial signs, quarter alignment, quote endpoints, finite values and approved
company descriptions. Raw quarter observations, target EPS periods and retrieval
times are retained. Source descriptions are fixed research prompts, not news.

Stock and index publications are independent units, with independent timestamps.
Failure of one collection does not authorize substituting it into the other.
Stale quotes and incomplete financial evidence withhold stock classifications.
Dated financial observations remain inspectable. No old dataset is relabeled as
new, and no historical stock verdict is backfilled. Stock observations are
archived prospectively in the repository; the website does not serve the archive
as a general API.

Model assumptions are explicit, mechanically initialized and unreviewed. Scenario
values, research categories and growth solutions are not financial forecasts,
validated probabilities or investment instructions. The model never interprets
the sum of unlike score scales as an economic valuation gap.

---

## Retained legacy index publication contract

The following rules continue to govern the older paired index JSON files, not
the new stock publication or the authorized About page.

# Website Data and Refresh Contract

The website is a read-only market-data product. It must never expose creator
information, environment variables, credentials, filesystem details, upstream
error bodies, or a general-purpose proxy to Yahoo, FRED, CBOE, GitHub, or any
other API.

## Public data

The browser reads only the validated contents of `data/scores.json` and
`data/timeline.json`. They contain three fixed market
scopes: `sp500`, `ndx100`, and `mag7`. The allowed fields are enforced by
`pipeline/public_output.py`. A new, missing, or unknown field causes the update
to fail while the prior valid file remains available.

The two files are one publication unit. Every scope's final timeline date and
three headline values must equal the current score file. A valid but lagging or
conflicting timeline blocks publication.

Each scope publishes `panic`, `fundamentals`, and `fundamental_discrepancy`.
The schema name `fundamentals` means Consensus Earnings Health and is retained
for compatibility. It contains only direct EPS revision magnitude and revision breadth.
Valuation and EPS-price divergence are optional entry diagnostics under
`components.entry`; they never affect Consensus Earnings Health.

Raw EPS observations are stored by ticker, retrieval date, and fiscal target date.
The public quality record labels revision inputs as `vendor`, `mixed`, or `owned`.
Broad-index revision breadth gives equal weight to company participation and sector
participation. Panic enters its high regime at 75 and exits below 70.

A Candidate Dislocation is a research flag only. No public score, quadrant,
verdict, discrepancy, or timeline point is a buy, sell, sizing, timing, or
allocation instruction.

## Data Timeline

`data/timeline.json` uses schema version 2. A methodology change starts a new
timeline rather than splicing unlike scores together:

```json
{
  "schema_version": 2,
  "generated_at_utc": "ISO-8601 timestamp",
  "methodology_start": "YYYY-MM-DD",
  "scopes": {
    "sp500": [
      {
        "date": "YYYY-MM-DD",
        "panic": 50,
        "fundamentals": 50,
        "fundamental_discrepancy": 0
      }
    ],
    "ndx100": [
      {
        "date": "YYYY-MM-DD",
        "panic": 50,
        "fundamentals": 50,
        "fundamental_discrepancy": 0
      }
    ],
    "mag7": [
      {
        "date": "YYYY-MM-DD",
        "panic": 50,
        "fundamentals": 50,
        "fundamental_discrepancy": 0
      }
    ]
  }
}
```

Each scope receives at most one point per market date. A same-day rerun replaces
that date rather than creating a duplicate. Dates are ordered, values are finite,
and `fundamental_discrepancy` must equal `panic + fundamentals - 100` within the
published rounding tolerance.

The timeline is prospective hardened-methodology history. `methodology_start`
is the first real score produced under that methodology. Never backfill, splice,
or label legacy Shiller earnings, proxy-overlay backtests, reconstructed analyst
estimates, or interpolated values as historical Consensus Earnings Health. Missing
dates remain missing. Any future visualization must disclose the methodology
start instead of implying that the series existed earlier.

## Static publication and refresh

The browser may read only the two fixed static market-data files. It must not
trigger pipeline execution or accept a user-selected ticker, series, source, or
date range. There is no public refresh endpoint and no update-button workflow.

`scores.json` publishes this fixed refresh policy:

```json
{
  "mode": "scheduled_static_publication",
  "stale_after_business_days": 1,
  "schedule": "weekdays_after_us_close"
}
```

The fixed daily workflow publishes after the US close on weekdays. Page loads
display the last validated static files. Freshness is measured against the latest
completed session, using 21:00 UTC as the conservative close cutoff. If data exceeds
one completed business session, the website must withhold the live readings. It must
not silently substitute partial or newly reweighted data.

On a market holiday or another recent no-session date, the workflow may keep the
previous files only when both files validate, agree with each other, and match the
latest complete common index and Mag7 session. Otherwise it fails closed.

Each published scope also carries fixed data-quality evidence. Broad constituent
prices and market-cap proxies require at least 90% expected-name coverage, Mag7
prices require 100%, Panic components must remain inside their approved source-age
limits, and the EPS observation date plus constituent hash must match the market
session and current membership used by the price panel.

There is no endpoint that accepts arbitrary tickers, FRED series, URLs, Python,
shell commands, prompts, or personal questions.

## Privacy and logging

No creator profile is part of the application data model. Do not add creator
names, biographies, email addresses, usernames, analytics identifiers, cookies,
or IP-based profiles. Operational logs may record only timestamps, status codes,
duration, and fixed workflow status. Credentials and upstream response bodies
must be redacted or omitted.
