import unittest
from datetime import datetime, timezone

import pandas as pd

from pipeline.run_daily import completed_market_cutoff, through_cutoff


class DailyCutoffTests(unittest.TestCase):
    def test_before_publication_time_uses_previous_date(self):
        now = datetime(2026, 7, 16, 12, tzinfo=timezone.utc)
        self.assertEqual(completed_market_cutoff(now), pd.Timestamp("2026-07-15"))

    def test_partial_bar_is_removed(self):
        series = pd.Series([1, 2], index=pd.to_datetime(["2026-07-15", "2026-07-16"]))
        result = through_cutoff(series, pd.Timestamp("2026-07-15"))
        self.assertEqual(result.index.tolist(), [pd.Timestamp("2026-07-15")])


if __name__ == "__main__":
    unittest.main()
