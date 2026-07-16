import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from pipeline import fetchers
from pipeline.fetchers import _safe_error
from pipeline.public_output import (
    build_timeline_payload,
    validate_public_payload,
    validate_timeline_payload,
    write_public_payload,
    write_timeline_payload,
)


class PublicOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads(Path("data/scores.json").read_text())

    def test_current_scores_follow_public_contract(self):
        validate_public_payload(self.payload)

    def test_missing_market_scope_is_rejected(self):
        invalid = copy.deepcopy(self.payload)
        invalid["scopes"].pop("sp500")
        with self.assertRaises(ValueError):
            validate_public_payload(invalid)

    def test_creator_or_secret_fields_are_rejected(self):
        for private_key in ("creator", "owner_email", "api_key", "access_token"):
            invalid = copy.deepcopy(self.payload)
            invalid[private_key] = "must-not-publish"
            with self.subTest(private_key=private_key), self.assertRaises(ValueError):
                validate_public_payload(invalid)

    def test_invalid_update_preserves_last_good_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scores.json"
            write_public_payload(path, self.payload)
            before = path.read_bytes()
            invalid = copy.deepcopy(self.payload)
            invalid["scopes"].pop("mag7")
            with self.assertRaises(ValueError):
                write_public_payload(path, invalid)
            self.assertEqual(before, path.read_bytes())

    def test_timeline_appends_real_readings_and_replaces_same_day(self):
        timeline = build_timeline_payload(None, self.payload["scopes"], self.payload["asof"])
        validate_timeline_payload(timeline)
        updated = build_timeline_payload(timeline, self.payload["scopes"], self.payload["asof"])
        self.assertTrue(all(len(points) == 1 for points in updated["scopes"].values()))

    def test_timeline_rejects_inconsistent_discrepancy(self):
        timeline = build_timeline_payload(None, self.payload["scopes"], self.payload["asof"])
        timeline["scopes"]["sp500"][0]["fundamental_discrepancy"] += 1
        with self.assertRaises(ValueError):
            validate_timeline_payload(timeline)

    def test_invalid_timeline_preserves_last_good_file(self):
        timeline = build_timeline_payload(None, self.payload["scopes"], self.payload["asof"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "timeline.json"
            write_timeline_payload(path, timeline)
            before = path.read_bytes()
            timeline["scopes"]["mag7"].clear()
            with self.assertRaises(ValueError):
                write_timeline_payload(path, timeline)
            self.assertEqual(before, path.read_bytes())

    def test_error_redaction_removes_api_credentials(self):
        error = RuntimeError("request failed?api_key=private-value&series_id=DGS10")
        redacted = _safe_error(error)
        self.assertNotIn("private-value", redacted)
        self.assertIn("api_key=[REDACTED]", redacted)

    def test_yahoo_estimate_is_cached_across_scopes(self):
        fetchers._estimate_row.cache_clear()
        ticker = Mock()
        ticker.info = {"marketCap": 100, "forwardPE": 20, "trailingPE": 25}
        with patch.object(fetchers.yf, "Ticker", return_value=ticker) as factory:
            self.assertEqual(fetchers._estimate_row("TEST"),
                             fetchers._estimate_row("TEST"))
            factory.assert_called_once_with("TEST")
        fetchers._estimate_row.cache_clear()

    def test_mag7_constituents_are_fixed(self):
        self.assertEqual(fetchers.constituents("mag7"),
                         ["NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA"])


if __name__ == "__main__":
    unittest.main()
