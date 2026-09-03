import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pandas as pd

from pipeline import fetchers
from pipeline.fetchers import (
    _apply_owned_eps_revisions,
    _eps_trend_changes,
    _eps_trend_payload,
    _rank_market_cap_rows,
    _revision_breadth,
)


class FetcherTests(unittest.TestCase):
    def test_cboe_index_history_parses_closes_and_start_date(self):
        response = Mock()
        response.text = ("DATE,OPEN,HIGH,LOW,CLOSE\n"
                         "07/13/2026,13,16,12,15.1\n"
                         "07/14/2026,14,15,13,13.4\n")
        with patch.object(fetchers.requests, "get", return_value=response):
            series = fetchers.cboe_index_history("VIX9D", "2026-07-14")
        response.raise_for_status.assert_called_once()
        self.assertEqual(series.index.tolist(), [pd.Timestamp("2026-07-14")])
        self.assertEqual(series.iloc[0], 13.4)

    def test_full_universe_is_ranked_before_names_are_selected(self):
        tickers = ["AAA", "BBB", "CCC", "MSFT", "NVDA"]
        rows = [
            {"ticker": "AAA", "mc": 10},
            {"ticker": "BBB", "mc": 20},
            {"ticker": "CCC", "mc": 30},
            {"ticker": "MSFT", "mc": 900},
            {"ticker": "NVDA", "mc": 1000},
        ]
        ranked = _rank_market_cap_rows(tickers, rows)
        self.assertEqual([row["ticker"] for row in ranked[:2]], ["NVDA", "MSFT"])

    def test_positive_to_negative_eps_is_retained_as_deterioration(self):
        trend = pd.DataFrame({"current": [-1.0], "30daysAgo": [1.0]}, index=["+1y"])
        self.assertEqual(
            _eps_trend_changes(trend)["analyst_eps_revision_30d_pct"], -50
        )

    def test_less_negative_eps_is_an_improvement(self):
        trend = pd.DataFrame({"current": [-1.0], "30daysAgo": [-2.0]}, index=["+1y"])
        self.assertEqual(
            _eps_trend_changes(trend)["analyst_eps_revision_30d_pct"], 50
        )

    def test_more_negative_eps_is_a_deterioration(self):
        trend = pd.DataFrame({"current": [-2.0], "30daysAgo": [-1.0]}, index=["+1y"])
        self.assertEqual(
            _eps_trend_changes(trend)["analyst_eps_revision_30d_pct"], -50
        )

    def test_tiny_eps_sign_crossing_uses_the_denominator_floor(self):
        trend = pd.DataFrame(
            {"current": [0.001], "30daysAgo": [-0.001]}, index=["+1y"]
        )
        self.assertAlmostEqual(
            _eps_trend_changes(trend)["analyst_eps_revision_30d_pct"], 4.0
        )

    def test_raw_eps_payload_keeps_the_fiscal_target(self):
        row = {
            "period": "+1y",
            "endDate": "2027-09-30",
            "epsTrend": {
                "current": {"raw": 10.0},
                "30daysAgo": {"raw": 8.0},
                "epsTrendCurrency": "USD",
            },
        }
        result = _eps_trend_payload(row)
        self.assertEqual(result["analyst_target_end_date"], "2027-09-30")
        self.assertEqual(result["analyst_eps_current"], 10.0)
        self.assertEqual(result["analyst_eps_revision_30d_pct"], 20.0)

    def test_eps_trend_falls_back_when_target_payload_is_unavailable(self):
        fetchers._ticker_eps_trend.cache_clear()
        quote = Mock()
        quote._analysis._fetch.side_effect = RuntimeError("unavailable")
        quote.get_eps_trend.return_value = pd.DataFrame(
            {"current": [2.0], "30daysAgo": [1.0]}, index=["+1y"]
        )
        with patch.object(fetchers.yf, "Ticker", return_value=quote):
            result = fetchers._ticker_eps_trend("TEST")
        self.assertEqual(result["analyst_eps_revision_30d_pct"], 50.0)
        fetchers._ticker_eps_trend.cache_clear()

    def test_owned_eps_revision_requires_the_same_fiscal_target(self):
        target = pd.DataFrame([{
            "ticker": "AAA",
            "analyst_target_end_date": "2027-12-31",
            "analyst_eps_current": 12.0,
            "analyst_eps_revision_30d_pct": 50.0,
        }])
        history = pd.DataFrame([
            {"asof": "2026-06-20", "ticker": "AAA",
             "target_end_date": "2026-12-31", "eps_estimate": 1.0},
            {"asof": "2026-06-20", "ticker": "AAA",
             "target_end_date": "2027-12-31", "eps_estimate": 10.0},
        ])
        result = _apply_owned_eps_revisions(target, history, "2026-07-20")
        self.assertAlmostEqual(result.loc[0, "analyst_eps_revision_30d_pct"], 100 / 6)
        self.assertEqual(result.loc[0, "analyst_eps_revision_30d_basis"], "owned")
        self.assertTrue(pd.isna(result.loc[0, "analyst_eps_revision_60d_basis"]))

    def test_company_and_sector_breadth_resist_mega_cap_domination(self):
        common = pd.DataFrame({
            "analyst_eps_revision_30d_pct": [2.0, -2.0, -2.0, -2.0],
            "proxy_weight": [.85, .05, .05, .05],
            "sector": ["A", "A", "B", "B"],
        })
        result = _revision_breadth(common, "sp500")
        self.assertEqual(result["analyst_eps_cap_weighted_breadth_30d_pct"], 85.0)
        self.assertEqual(result["analyst_eps_name_breadth_30d_pct"], 25.0)
        self.assertEqual(result["analyst_eps_sector_breadth_30d_pct"], 25.0)
        self.assertEqual(result["analyst_eps_revision_breadth_30d_pct"], 25.0)

    def test_broad_index_breadth_fails_closed_without_sector_coverage(self):
        common = pd.DataFrame({
            "analyst_eps_revision_30d_pct": [2.0, -2.0],
            "proxy_weight": [.5, .5],
            "sector": ["A", None],
        })
        result = _revision_breadth(common, "sp500")
        self.assertEqual(result["analyst_eps_sector_coverage_pct"], 50.0)
        self.assertNotIn("analyst_eps_revision_breadth_30d_pct", result)

    def test_partial_yahoo_download_preserves_missing_requested_names(self):
        raw = pd.concat(
            {"Close": pd.DataFrame(
                {"AAA": [10.0]}, index=pd.to_datetime(["2026-07-20"])
            )},
            axis=1,
        )
        with patch.object(fetchers.yf, "download", return_value=raw) as download:
            prices = fetchers.yahoo_history(["AAA", "BBB"])
        self.assertEqual(prices.columns.tolist(), ["AAA", "BBB"])
        self.assertTrue(pd.isna(prices.loc[pd.Timestamp("2026-07-20"), "BBB"]))
        self.assertFalse(download.call_args.kwargs["threads"])

    def test_ndx_constituents_use_nasdaq_api(self):
        nasdaq = Mock()
        nasdaq.json.return_value = {
            "data": {"data": {"rows": [{"symbol": "AAPL"}, {"symbol": "MSFT"}]}}
        }
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(fetchers, "CACHE", directory), \
                patch.object(fetchers.requests, "get", return_value=nasdaq):
            tickers = fetchers.constituents("ndx100")
        self.assertEqual(tickers, ["AAPL", "MSFT"])
        nasdaq.raise_for_status.assert_called_once()

    def test_eps_snapshot_blocks_a_mixed_market_date_before_fetching(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(fetchers.config, "DATA_DIR", directory), \
                patch.object(fetchers, "constituents") as constituents:
            snapshot = fetchers.forward_eps_snapshot(
                "sp500",
                market_asof="2026-07-20",
                now_utc=datetime(2026, 7, 21, 22, tzinfo=timezone.utc),
            )
        self.assertEqual(snapshot, {})
        constituents.assert_not_called()

    def test_eps_snapshot_reuses_an_aligned_stored_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            pd.DataFrame([{
                "asof": "2026-07-20",
                "source_observation_date": "2026-07-20",
                "n_analyst_trends": 10,
            }]).to_csv(f"{directory}/eps_history_sp500.csv", index=False)
            with patch.object(fetchers.config, "DATA_DIR", directory), \
                    patch.object(fetchers, "constituents") as constituents:
                snapshot = fetchers.forward_eps_snapshot(
                    "sp500",
                    market_asof="2026-07-20",
                    now_utc=datetime(2026, 7, 21, 22, tzinfo=timezone.utc),
                )
        self.assertEqual(snapshot["source_observation_date"], "2026-07-20")
        constituents.assert_not_called()

    def test_post_midnight_eps_snapshot_uses_completed_session_without_pe(self):
        tickers = ["AAA", "MSFT", "NVDA"]
        ranked = [{"ticker": ticker, "mc": mc}
                  for ticker, mc in zip(tickers, (1, 2, 3))]
        trends = Mock(return_value={
            "analyst_eps_revision_30d_pct": 1,
            "analyst_eps_revision_60d_pct": 1,
            "analyst_eps_revision_90d_pct": 1,
        })
        no_valuation = lambda ticker: {
            "ticker": ticker, "mc": None, "fwd_pe": None, "trl_pe": None
        }
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(fetchers.config, "DATA_DIR", directory), \
                patch.object(fetchers, "constituents", return_value=tickers), \
                patch.object(fetchers, "_ranked_market_cap_proxy", return_value=ranked), \
                patch.object(fetchers, "_estimate_row", side_effect=no_valuation), \
                patch.object(fetchers, "_ticker_eps_trend", trends):
            snapshot = fetchers.forward_eps_snapshot(
                "sp500",
                market_asof="2026-07-20",
                now_utc=datetime(2026, 7, 21, 1, tzinfo=timezone.utc),
            )
        self.assertEqual(snapshot["n_analyst_trends"], 3)
        self.assertEqual(snapshot["source_observation_date"], "2026-07-20")
        self.assertIsNone(snapshot["fwd_pe"])
        self.assertEqual(set(trends.call_args_list[0][0]), {"AAA"})
        self.assertEqual(trends.call_count, 3)


if __name__ == "__main__":
    unittest.main()
