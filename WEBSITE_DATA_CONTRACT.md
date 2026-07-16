# Website Data and Refresh Contract

The website is a read-only market-data product. It must never expose creator
information, environment variables, credentials, filesystem details, upstream
error bodies, or a general-purpose proxy to Yahoo, FRED, CBOE, GitHub, or any
other API.

## Public data

The only public market-data files are the validated contents of
`data/scores.json` and `data/timeline.json`. They contain three fixed market
scopes: `sp500`, `ndx100`, and `mag7`. The allowed fields are enforced by
`pipeline/public_output.py`. A new, missing, or unknown field causes the update
to fail while the prior valid file remains available.

Each scope publishes `panic`, `fundamentals`, and `fundamental_discrepancy`.
The schema name `fundamentals` means Consensus Earnings Health and is retained
for compatibility. It contains only direct EPS revision magnitude and revision breadth.
Valuation and EPS-price divergence are optional entry diagnostics under
`components.entry`; they never affect Consensus Earnings Health.

A Candidate Dislocation is a research flag only. No public score, quadrant,
verdict, discrepancy, or timeline point is a buy, sell, sizing, timing, or
allocation instruction.

## Data Timeline

`data/timeline.json` uses schema version 1:

```json
{
  "schema_version": 1,
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
  "stale_after_business_days": 2,
  "schedule": "weekdays_after_us_close"
}
```

The fixed daily workflow publishes after the US close on weekdays. Page loads
display the last validated static files. If data exceeds the stated business-day
staleness limit, the website may warn that it is stale, but it must not silently
substitute partial or newly reweighted data.

There is no endpoint that accepts arbitrary tickers, FRED series, URLs, Python,
shell commands, prompts, or personal questions.

## Privacy and logging

No creator profile is part of the application data model. Do not add creator
names, biographies, email addresses, usernames, analytics identifiers, cookies,
or IP-based profiles. Operational logs may record only timestamps, status codes,
duration, and fixed workflow status. Credentials and upstream response bodies
must be redacted or omitted.
