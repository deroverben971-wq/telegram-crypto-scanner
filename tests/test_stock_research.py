import unittest
from stock_research import evaluate_daily_bars, ema


def make_bars(n=230, trend=1.0):
    bars = []
    for i in range(n):
        close = 20 + i * trend * 0.1
        bars.append({
            "date": f"2025-{(i // 28) % 12 + 1:02d}-{i % 28 + 1:02d}",
            "open": close - 0.1,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": 1000 + (500 if i == n - 1 else 0),
        })
    # Use stable sortable daily identifiers for validation.
    for i, bar in enumerate(bars):
        bar["date"] = f"{i:04d}"
    return bars


class StockResearchTests(unittest.TestCase):
    def test_ema_requires_enough_values(self):
        self.assertIsNone(ema([1, 2], 3))

    def test_short_history_fails_closed(self):
        self.assertEqual(evaluate_daily_bars(make_bars(100))["status"], "INSUFFICIENT_DATA")

    def test_invalid_data_fails_closed(self):
        bars = make_bars()
        bars[-1]["close"] = float("nan")
        self.assertEqual(evaluate_daily_bars(bars)["status"], "INVALID_DATA")

    def test_result_is_research_only(self):
        result = evaluate_daily_bars(make_bars())
        self.assertIn(result["status"], {"STRICT_RESEARCH_CANDIDATE", "NO_QUALIFIED_SETUP"})
        self.assertIn("checks", result)
        self.assertNotIn("order", result)
        self.assertNotIn("buy", result)


if __name__ == "__main__":
    unittest.main()
