import unittest
import backtest

class AggregateTests(unittest.TestCase):
    def make_rows(self, count):
        return [
            {"time": i * 3_600_000, "open": 100.0 + i, "high": 102.0 + i,
             "low": 99.0 + i, "close": 101.0 + i, "volume": 10.0}
            for i in range(count)
        ]

    def test_four_hour_aggregation_uses_only_complete_buckets(self):
        result = backtest.aggregate(self.make_rows(7), 4)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["open"], 100.0)
        self.assertEqual(result[0]["close"], 104.0)
        self.assertEqual(result[0]["high"], 105.0)
        self.assertEqual(result[0]["low"], 99.0)
        self.assertEqual(result[0]["volume"], 40.0)
        # The aggregate is timestamped when its final hourly candle has closed.
        self.assertEqual(result[0]["time"], 4 * 3_600_000)

    def test_daily_aggregation_requires_24_hours(self):
        self.assertEqual(backtest.aggregate(self.make_rows(23), 24), [])
        result = backtest.aggregate(self.make_rows(24), 24)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["volume"], 240.0)
        self.assertEqual(result[0]["time"], 24 * 3_600_000)

    def test_empty_input(self):
        self.assertEqual(backtest.aggregate([], 4), [])

if __name__ == "__main__":
    unittest.main()
