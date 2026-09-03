import tempfile
import unittest
from pathlib import Path

import pandas as pd

from pipeline.episodes import (
    build_episode_report,
    candidate_episodes,
    write_episode_report,
)


class EpisodeTests(unittest.TestCase):
    def test_daily_candidate_streak_is_one_episode(self):
        points = [
            {"date": "2026-01-01", "panic": 60, "fundamentals": 80},
            {"date": "2026-01-02", "panic": 80, "fundamentals": 80},
            {"date": "2026-01-05", "panic": 76, "fundamentals": 75},
            {"date": "2026-01-06", "panic": 72, "fundamentals": 70},
            {"date": "2026-01-07", "panic": 69, "fundamentals": 70},
        ]
        episodes = candidate_episodes(points)
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["signal_date"], "2026-01-02")
        self.assertEqual(episodes[0]["state_exit_date"], "2026-01-07")

    def test_report_uses_the_close_after_the_signal(self):
        dates = pd.bdate_range("2026-01-01", periods=140)
        prices = pd.Series(range(100, 240), index=dates, dtype=float)
        points = [{
            "date": dates[0].strftime("%Y-%m-%d"),
            "panic": 80,
            "fundamentals": 80,
            "fundamental_discrepancy": 60,
        }]
        timeline = {
            "schema_version": 2,
            "methodology_start": points[0]["date"],
            "scopes": {scope: points for scope in ("sp500", "ndx100", "mag7")},
        }
        report = build_episode_report(
            timeline,
            {scope: prices for scope in ("sp500", "ndx100", "mag7")},
            prices,
        )
        episode = report["methodologies"]["timeline_v2"]["scopes"]["sp500"]["episodes"][0]
        self.assertEqual(episode["entry_date"], dates[1].strftime("%Y-%m-%d"))
        self.assertEqual(episode["status"], "complete")
        self.assertIn("return_6m_pct", episode)

    def test_report_write_is_valid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "episodes.json"
            write_episode_report(path, {"ok": True})
            self.assertEqual(path.read_text(), '{\n  "ok": true\n}\n')

    def test_new_methodology_preserves_prior_episode_results(self):
        dates = pd.bdate_range("2026-01-01", periods=3)
        prices = pd.Series([100.0, 101.0, 102.0], index=dates)
        timeline = {
            "schema_version": 2,
            "methodology_start": "2026-01-01",
            "scopes": {scope: [] for scope in ("sp500", "ndx100", "mag7")},
        }
        prior = {
            "methodology_start": "2025-01-01",
            "scopes": {scope: {"episode_count": 0, "episodes": []}
                       for scope in ("sp500", "ndx100", "mag7")},
        }
        report = build_episode_report(
            timeline,
            {scope: prices for scope in ("sp500", "ndx100", "mag7")},
            prices,
            prior,
        )
        self.assertEqual(set(report["methodologies"]), {"timeline_v1", "timeline_v2"})


if __name__ == "__main__":
    unittest.main()
