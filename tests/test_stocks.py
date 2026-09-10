import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from pipeline import stocks


class StockEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads((Path(__file__).resolve().parents[1] / "data/stocks.json").read_text())

    def test_quarter_observations_must_reconcile(self):
        payload = copy.deepcopy(self.payload)
        next(s for s in payload["stocks"] if s["financials"])["financials"]["quarters"][0]["revenue"] += 1000
        with self.assertRaises(ValueError):
            stocks.validate(payload)

    def test_unknown_fields_and_nan_are_rejected(self):
        payload = copy.deepcopy(self.payload)
        payload["stocks"][0]["provider_response"] = {"private": "not permitted"}
        with self.assertRaises(ValueError):
            stocks.validate(payload)
        payload = copy.deepcopy(self.payload)
        payload["stocks"][0]["market"]["mood"] = float("nan")
        with self.assertRaises(ValueError):
            stocks.validate(payload)

    def test_incomplete_cash_flow_quarter_cannot_be_filled_with_zero(self):
        s = next(s for s in self.payload["stocks"] if s["financials"])["financials"]
        dates = pd.to_datetime([q["end"] for q in s["quarters"]])
        income = pd.DataFrame({d: {"Total Revenue": q["revenue"], "Operating Income": q["operating_income"]}
                               for d, q in zip(dates, s["quarters"])})
        cashflow = pd.DataFrame({d: {"Operating Cash Flow": q["cfo"], "Capital Expenditure": -q["capex"]}
                                for d, q in zip(dates, s["quarters"])})
        with self.assertRaisesRegex(ValueError, "align"):
            stocks.financials(income, cashflow.drop(columns=dates[0]), pd.DataFrame())

    def test_market_mood_has_direction_and_is_not_inverse_volatility(self):
        dates = pd.bdate_range("2025-01-01", periods=300)
        benchmark = pd.Series(100.0, index=dates)
        rising = pd.DataFrame({"Close": np.linspace(100, 200, 300), "Volume": 1000}, index=dates)
        falling = rising.copy()
        falling["Close"] = np.linspace(200, 100, 300)
        up = stocks.market_evidence(rising, benchmark)
        down = stocks.market_evidence(falling, benchmark)
        self.assertGreater(up["mood"], 70)
        self.assertLess(down["mood"], 30)
        self.assertEqual(up["history"][-1]["pressure"], up["mood"])
        self.assertTrue(all(0 <= point["pressure"] <= 100 for point in down["history"]))

    def test_invalid_update_preserves_last_good_publication(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(stocks, "ROOT", Path(directory)):
            stocks.publish(self.payload)
            prior = (Path(directory) / "stocks.json").read_bytes()
            bad = copy.deepcopy(self.payload)
            next(s for s in bad["stocks"] if s["financials"])["financials"]["capex"] = -1
            with self.assertRaises(ValueError):
                stocks.publish(bad)
            self.assertEqual((Path(directory) / "stocks.json").read_bytes(), prior)


if __name__ == "__main__":
    unittest.main()
