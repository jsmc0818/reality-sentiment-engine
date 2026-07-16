import unittest

import numpy as np
import pandas as pd

from pipeline.scoring import (
    current_weighted_meter,
    fundamental_discrepancy,
    fundamental_health,
    quadrant,
    rolling_percentile,
    weighted_meter,
)
from pipeline.components import breadth_pct_above_ma, equal_weight_index


class ScoringTests(unittest.TestCase):
    @staticmethod
    def healthy_snapshot(**overrides):
        snapshot = {
            "analyst_eps_revision_30d_pct": 1,
            "analyst_eps_revision_60d_pct": 2,
            "analyst_eps_revision_90d_pct": 3,
            "analyst_eps_revision_breadth_30d_pct": 80,
            "analyst_eps_common_coverage_pct": 50,
            "analyst_eps_common_cohort_pct": 90,
            "n_analyst_trends": 30,
        }
        snapshot.update(overrides)
        return snapshot

    def test_trailing_missing_quote_does_not_become_zero(self):
        values = pd.Series([*range(252), np.nan])
        scored = rolling_percentile(values, window=252)
        self.assertEqual(scored.index[-1], 251)
        self.assertGreater(scored.iloc[-1], 99)

    def test_percentile_waits_for_the_full_requested_window(self):
        scored = rolling_percentile(pd.Series(range(251)), window=252)
        self.assertTrue(scored.dropna().empty)

    def test_equal_weight_index_uses_each_stock_equally(self):
        prices = pd.DataFrame({"winner": [100, 110], "flat": [100, 100]})
        basket = equal_weight_index(prices)
        self.assertEqual(basket.iloc[0], 100)
        self.assertAlmostEqual(basket.iloc[-1], 105.0)

    def test_breadth_excludes_names_without_a_warmed_up_average(self):
        prices = pd.DataFrame({"ready": [1, 1, 1, 1, 2],
                               "late": [np.nan, np.nan, np.nan, np.nan, 5]})
        breadth = breadth_pct_above_ma(prices, ma_days=5)
        self.assertEqual(breadth.iloc[-1], 100)

    def test_positive_eps_revisions_produce_healthy_fundamentals(self):
        result = fundamental_health(self.healthy_snapshot())
        self.assertGreaterEqual(result["score"], 60)

    def test_price_and_valuation_do_not_enter_fundamentals(self):
        snapshot = self.healthy_snapshot()
        before = fundamental_health(snapshot)["score"]
        snapshot.update({"forward_pe": 100, "divergence_pts": -50})
        self.assertEqual(fundamental_health(snapshot)["score"], before)

    def test_discrepancy_is_positive_when_stress_exceeds_damage(self):
        self.assertEqual(fundamental_discrepancy(80, 90), 70)

    def test_thin_analyst_coverage_has_no_fundamentals_reading(self):
        self.assertIsNone(fundamental_health(self.healthy_snapshot(
            analyst_eps_common_coverage_pct=20
        )))

    def test_neutral_revisions_score_neutral(self):
        result = fundamental_health(self.healthy_snapshot(
            analyst_eps_revision_30d_pct=0,
            analyst_eps_revision_60d_pct=0,
            analyst_eps_revision_90d_pct=0,
            analyst_eps_revision_breadth_30d_pct=50,
        ))
        self.assertEqual(result["score"], 50)

    def test_missing_component_is_not_silently_renormalized(self):
        pctls = pd.DataFrame({"a": [80.0]})
        self.assertTrue(weighted_meter(pctls, {"a": .5, "b": .5}).isna().all())

    def test_stale_current_component_blocks_panic_reading(self):
        pctls = pd.DataFrame({
            "a": pd.Series([80.0], index=pd.to_datetime(["2026-07-15"])),
            "b": pd.Series([20.0], index=pd.to_datetime(["2026-07-10"])),
        })
        result = current_weighted_meter(pctls, {"a": .5, "b": .5})
        self.assertFalse(result["ready"])
        self.assertIsNone(result["score"])
        self.assertEqual(result["coverage_pct"], 50)

    def test_high_panic_with_mixed_fundamentals_is_watch_not_golden(self):
        self.assertEqual(quadrant(80, 50)["code"], "watch")


if __name__ == "__main__":
    unittest.main()
