# Exploratory historical diagnostic: candidate-weight stress test

Purpose: compare candidate behavior under historical proxies. This is not a validated forecast, a live-model backtest, or a production-weight approval.

Training signals: 2016 through the last date whose 63-session, next-close forward return ends before 2022. Validation: 2022-present, untouched by the optimizer.
Legacy thresholds remain fixed at Panic >= 75 and proxy overlay > 35.

## Status

**EXPLORATORY ONLY. Production weights remain unchanged.**

Statistical comparison screen: **failed**. Production promotion is blocked because constituent history uses current-membership backfill; Shiller earnings are current-vintage and revision-prone.

## Statistical comparison rule

The screen requires at least 10 independent entries, superiority on daily and independent-entry observations, and 90% block-bootstrap confidence versus both equal weight and current production. Passing it is diagnostic evidence, not deployment authority.

## Panic diagnostics and weights

| component       |     ic |     lo |    hi |   weight_ic |   weight_candidate |   weight_production |
|:----------------|-------:|-------:|------:|------------:|-------------------:|--------------------:|
| term_structure  |  0.207 |  0.011 | 0.379 |       0.231 |               0.15 |                0.25 |
| credit_velocity |  0.013 | -0.138 | 0.17  |       0.108 |               0.15 |                0.22 |
| vvix            |  0.332 |  0.095 | 0.551 |       0.31  |               0.15 |                0.2  |
| breadth_sp500   |  0.237 | -0.094 | 0.541 |       0.25  |               0.35 |                0.18 |
| put_call        | -0.065 | -0.258 | 0.174 |       0.1   |               0.2  |                0.15 |

## Legacy proxy-overlay diagnostics and weights

| component          |    ic |     lo |    hi |   weight_ic |   weight_candidate |   weight_production |
|:-------------------|------:|-------:|------:|------------:|-------------------:|--------------------:|
| divergence_proxy   | 0.088 | -0.209 | 0.409 |       0.188 |                0.1 |                0.35 |
| erp_proxy          | 0.246 | -0.081 | 0.514 |       0.299 |                0.4 |                0.25 |
| sector_correlation | 0.342 |  0.106 | 0.577 |       0.367 |                0.1 |                0.22 |
| quality_spread     | 0.03  | -0.302 | 0.34  |       0.146 |                0.4 |                0.18 |

## Out-of-sample legacy proxy signal, daily observations

| model | days | average forward 3M return | hit rate |
|---|---:|---:|---:|
| train-only candidate | 93 | +0.8% | 51% |
| equal weight | 93 | +3.3% | 57% |
| current production | 119 | +4.5% | 66% |
| old IC method | 106 | +3.3% | 57% |

## Out-of-sample legacy proxy signal, independent entries

A 63-trading-day cooldown prevents one long panic from being counted repeatedly.

| model | entries | average forward 3M return | hit rate |
|---|---:|---:|---:|
| train-only candidate | 6 | +3.6% | 50% |
| equal weight | 8 | +5.7% | 75% |
| current production | 9 | +4.6% | 67% |
| old IC method | 9 | +4.8% | 67% |

## Block-bootstrap comparison

| candidate versus | P(hit rate is higher) | P(avg return is higher) | hit difference 95% CI | return difference 95% CI | valid / requested draws |
|---|---:|---:|---:|---:|---:|
| equal weight | 12% | 10% | [-31.1, +5.1] pts | [-9.63, +0.58] pts | 4997 / 5000 |
| current production | 7% | 2% | [-34.8, +2.8] pts | [-8.29, -0.19] pts | 4997 / 5000 |

## Episode readings, train-only candidate

| episode | panic | proxy overlay |
|---|---:|---:|
| Dec 2018 | 91 | 50 |
| Mar 2020 | 100 | 65 |
| 2022 bear | 88 | 40 |
| Oct 2023 | 81 | 15 |
| Aug 2024 | 82 | 22 |
| Apr 2025 | 97 | 28 |
| Low-vol trap | 74 | 42 |

## What is still missing for final optimization

1. Point-in-time index membership, not today's constituents backfilled through history.
2. Point-in-time historical forward EPS estimates and analyst revisions, not current-vintage Shiller realized earnings.
3. A consistent historical HY OAS series matching the live signal, not the BAA10Y proxy.
4. More independent stress episodes. The current diagnostic contains too few separate 3-month decisions.
5. A longer live forward-EPS snapshot history for every index scope.

Notes: IC confidence intervals use a 63-day block bootstrap. The joint optimizer uses training data only, constrained weights, top-candidate ensembling, and five-point rounding. Shiller observations use a conservative 3-month publication lag, but the downloaded series remains revised current-vintage data. Backtest credit velocity uses FRED BAA10Y; live scoring uses BAMLH0A0HYM2. This report is research-only and never an allocation instruction.
