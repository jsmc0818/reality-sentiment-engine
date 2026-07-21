import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pandas as pd

from pipeline import fetchers
from pipeline.fetchers import _eps_trend_changes, _rank_market_cap_rows


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

    def test_partial_yahoo_download_preserves_missing_requested_names(self):
        raw = pd.concat(
            {"Close": pd.DataFrame(
                {"AAA": [10.0]}, index=pd.to_datetime(["2026-07-20"])
            )},
            axis=1,
        )
        with patch.object(fetchers.yf, "download", return_value=raw):
            prices = fetchers.yahoo_history(["AAA", "BBB"])
        self.assertEqual(prices.columns.tolist(), ["AAA", "BBB"])
        self.assertTrue(pd.isna(prices.loc[pd.Timestamp("2026-07-20"), "BBB"]))

    def test_eps_snapshot_blocks_a_mixed_market_date_before_fetching(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(fetchers.config, "DATA_DIR", directory), \
                patch.object(fetchers, "constituents") as constituents:
            snapshot = fetchers.forward_eps_snapshot(
                "sp500",
                market_asof="2026-07-20",
                now_utc=datetime(2026, 7, 21, 12, tzinfo=timezone.utc),
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
                    now_utc=datetime(2026, 7, 21, 12, tzinfo=timezone.utc),
                )
        self.assertEqual(snapshot["source_observation_date"], "2026-07-20")
        constituents.assert_not_called()

    def test_eps_trends_do_not_require_positive_forward_pe(self):
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
            snapshot = fetchers.forward_eps_snapshot("sp500")
        self.assertEqual(snapshot["n_analyst_trends"], 3)
        self.assertIsNone(snapshot["fwd_pe"])
        self.assertEqual(set(trends.call_args_list[0][0]), {"AAA"})
        self.assertEqual(trends.call_count, 3)


if __name__ == "__main__":
    unittest.main()
