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

The two files are one publication unit. Every scope's final timeline date and
three headline values must equal the current score file. A valid but lagging or
conflicting timeline blocks publication.

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
