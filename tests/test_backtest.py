import unittest

import numpy as np
import pandas as pd

from backtest.build_history import lag_monthly_publication, next_close_forward_return
from backtest.run_backtest import (
    REALITY_COLS,
    bootstrap_compare,
    passes_promotion_gate,
    promotion_decision,
    purged_training_mask,
)


class BacktestTests(unittest.TestCase):
    def test_forward_return_waits_for_next_close(self):
        prices = pd.Series(range(100, 170), dtype=float)

        result = next_close_forward_return(prices, 63)

        self.assertEqual(result.iloc[0], 164 / 101 - 1)
        self.assertTrue(result.iloc[6:].isna().all())

    def test_forward_return_skips_dates_without_a_close(self):
        prices = pd.Series([100, np.nan, 110, 121], dtype=float)

        result = next_close_forward_return(prices, 1)

        self.assertAlmostEqual(result.iloc[0], .10)
        self.assertTrue(pd.isna(result.iloc[1]))

    def test_training_mask_purges_labels_that_reach_validation(self):
        dates = pd.bdate_range("2021-09-01", periods=100)

        mask = purged_training_mask(dates, dates[70], horizon=5, execution_lag=1)

        self.assertTrue(mask.iloc[63])
        self.assertFalse(mask.iloc[64])

    def test_shiller_proxy_is_delayed_three_months(self):
        earnings = pd.Series([100.0], index=pd.to_datetime(["2020-01-01"]))

        delayed = lag_monthly_publication(earnings)

        self.assertEqual(delayed.index[0], pd.Timestamp("2020-04-01"))
        self.assertEqual(delayed.iloc[0], 100.0)
        self.assertTrue(lag_monthly_publication(pd.Series(dtype=float)).empty)

    def test_quality_selloff_scores_as_a_higher_proxy_signal(self):
        self.assertEqual(REALITY_COLS["quality_spread"], -1)

    def test_promotion_requires_enough_entries_and_production_bootstrap_support(self):
        daily = {
            "train-only candidate": {"hit": .70, "avg": .08},
            "equal weight": {"hit": .60, "avg": .06},
            "current production": {"hit": .65, "avg": .07},
        }
        entries = {
            "train-only candidate": {"entries": 10, "hit": .70, "avg": .08},
            "equal weight": {"entries": 10, "hit": .60, "avg": .06},
            "current production": {"entries": 10, "hit": .65, "avg": .07},
        }
        comparison_equal = {"hit_probability": .95, "return_probability": .95,
                            "valid_draws": 950, "requested_draws": 1000}
        comparison_production = {"hit_probability": .95, "return_probability": .95,
                                 "valid_draws": 950, "requested_draws": 1000}

        self.assertTrue(passes_promotion_gate(
            daily, entries, comparison_equal, comparison_production
        ))

        comparison_production["return_probability"] = .89
        self.assertFalse(passes_promotion_gate(
            daily, entries, comparison_equal, comparison_production
        ))

        comparison_production["return_probability"] = .95
        entries["train-only candidate"]["entries"] = 9
        self.assertFalse(passes_promotion_gate(
            daily, entries, comparison_equal, comparison_production
        ))

        entries["train-only candidate"]["entries"] = 10
        comparison_production["valid_draws"] = 899
        self.assertFalse(passes_promotion_gate(
            daily, entries, comparison_equal, comparison_production
        ))

    def test_current_membership_history_cannot_promote_weights(self):
        promote, blockers = promotion_decision(True, {
            "constituent_history": "current_membership_backfill",
            "shiller_vintage": "current_download",
        })

        self.assertFalse(promote)
        self.assertEqual(len(blockers), 2)

        promote, blockers = promotion_decision(True, {
            "constituent_history": "point_in_time",
            "shiller_vintage": "point_in_time",
        })
        self.assertTrue(promote)
        self.assertEqual(blockers, [])

    def test_sparse_bootstrap_reports_no_valid_draws_instead_of_nan(self):
        dates = pd.bdate_range("2022-01-03", periods=130)
        calm = pd.Series(0.0, index=dates)
        target = pd.Series(.01, index=dates)

        result = bootstrap_compare(calm, calm, calm, calm, target, n=20)

        self.assertEqual(result["valid_draws"], 0)
        self.assertIsNone(result["hit_ci"])
        self.assertEqual(result["hit_probability"], 0)


if __name__ == "__main__":
    unittest.main()
