import unittest

import numpy as np
import pandas as pd

from backtest.build_history import next_close_forward_return
from backtest.run_backtest import passes_promotion_gate, purged_training_mask


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
        comparison_equal = {"hit_probability": .95, "return_probability": .95}
        comparison_production = {"hit_probability": .95, "return_probability": .95}

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


if __name__ == "__main__":
    unittest.main()
