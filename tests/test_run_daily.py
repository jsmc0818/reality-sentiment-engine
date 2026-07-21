import unittest
from datetime import datetime, timezone
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from pipeline.run_daily import (
    canonical_market_asof,
    completed_market_cutoff,
    constituent_price_evidence,
    keep_validated_previous_reading,
    through_cutoff,
)


class DailyCutoffTests(unittest.TestCase):
    def test_before_publication_time_uses_previous_date(self):
        now = datetime(2026, 7, 16, 12, tzinfo=timezone.utc)
        self.assertEqual(completed_market_cutoff(now), pd.Timestamp("2026-07-15"))

    def test_partial_bar_is_removed(self):
        series = pd.Series([1, 2], index=pd.to_datetime(["2026-07-15", "2026-07-16"]))
        result = through_cutoff(series, pd.Timestamp("2026-07-15"))
        self.assertEqual(result.index.tolist(), [pd.Timestamp("2026-07-15")])

    def test_before_monday_close_uses_friday(self):
        now = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)
        self.assertEqual(completed_market_cutoff(now), pd.Timestamp("2026-07-17"))

    def test_canonical_market_asof_accepts_a_recent_common_session(self):
        dates = pd.to_datetime(["2026-07-17", "2026-07-20"])
        indices = pd.DataFrame({"^GSPC": [1, 2], "^NDX": [1, 2]}, index=dates)
        mag7 = pd.DataFrame(
            {name: [1, 2] for name in ("NVDA", "AAPL", "MSFT", "GOOGL",
                                       "AMZN", "META", "TSLA")},
            index=dates,
        )
        self.assertEqual(
            canonical_market_asof(indices, mag7, pd.Timestamp("2026-07-20")),
            pd.Timestamp("2026-07-20"),
        )
        self.assertEqual(
            canonical_market_asof(indices.iloc[:1], mag7.iloc[:1],
                                  pd.Timestamp("2026-07-20")),
            pd.Timestamp("2026-07-17"),
        )

    def test_canonical_market_asof_blocks_beyond_the_staleness_limit(self):
        dates = pd.to_datetime(["2026-07-16"])
        indices = pd.DataFrame({"^GSPC": [1], "^NDX": [1]}, index=dates)
        mag7 = pd.DataFrame(
            {name: [1] for name in ("NVDA", "AAPL", "MSFT", "GOOGL",
                                    "AMZN", "META", "TSLA")},
            index=dates,
        )
        with self.assertRaises(RuntimeError):
            canonical_market_asof(indices, mag7, pd.Timestamp("2026-07-21"))

    def test_constituent_price_evidence_uses_the_requested_denominator(self):
        prices = pd.DataFrame(
            {"AAA": [1.0], "BBB": [float("nan")]},
            index=pd.to_datetime(["2026-07-20"]),
        )
        count, coverage = constituent_price_evidence(
            prices, ["AAA", "BBB", "CCC"], pd.Timestamp("2026-07-20")
        )
        self.assertEqual(count, 1)
        self.assertAlmostEqual(coverage, 100 / 3)

    def test_no_session_requires_an_aligned_score_and_timeline(self):
        with tempfile.TemporaryDirectory() as directory:
            scores = Path(directory) / "scores.json"
            timeline = Path(directory) / "timeline.json"
            scores.write_text(json.dumps({"asof": "2026-07-17"}))
            timeline.write_text("{}")
            with patch("pipeline.run_daily.P.validate_public_timeline_pair") as validate:
                keep_validated_previous_reading(
                    scores, timeline, pd.Timestamp("2026-07-17"),
                    pd.Timestamp("2026-07-20"),
                )
                validate.assert_called_once()
            timeline.unlink()
            with self.assertRaises(RuntimeError):
                keep_validated_previous_reading(
                    scores, timeline, pd.Timestamp("2026-07-17"),
                    pd.Timestamp("2026-07-20"),
                )


if __name__ == "__main__":
    unittest.main()
