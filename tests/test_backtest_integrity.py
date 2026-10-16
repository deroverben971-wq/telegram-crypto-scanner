import unittest

from backtest import aggregate, latest_closed_bar_index


class BacktestDataIntegrityTests(unittest.TestCase):
    def test_aggregate_ignores_incomplete_hour_bucket(self):
        rows = [
            {"time": i * 3600000, "open": 10+i, "high": 12+i,
             "low": 9+i, "close": 11+i, "volume": 1.0}
            for i in range(5)
        ]
        result = aggregate(rows, 4)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["time"], 4 * 3600000)
        self.assertEqual(result[0]["open"], 10)
        self.assertEqual(result[0]["close"], 14)
        self.assertEqual(result[0]["volume"], 4.0)

    def test_aggregate_rejects_missing_hour(self):
        times = [0, 3600000, 7200000, 4 * 3600000]
        rows = [{"time": t, "open": 1, "high": 2, "low": 0.5,
                 "close": 1.5, "volume": 1.0} for t in times]
        self.assertEqual(aggregate(rows, 4), [])

    def test_latest_closed_bar_uses_close_time_not_future_bar(self):
        # Aggregated higher-timeframe timestamps represent candle close times.
        bar_close_times = [4*3600000, 8*3600000, 12*3600000]
        self.assertEqual(latest_closed_bar_index(bar_close_times, 8*3600000), 1)
        self.assertEqual(latest_closed_bar_index(bar_close_times, 8*3600000-1), 0)


if __name__ == "__main__":
    unittest.main()
