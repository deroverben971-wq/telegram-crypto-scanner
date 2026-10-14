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

    def test_aggregation_rejects_missing_hour_inside_bucket(self):
        rows = self.make_rows(8)
        rows.pop(2)
        self.assertEqual(backtest.aggregate(rows, 4), [])

    def test_daily_aggregation_requires_24_hours(self):
        self.assertEqual(backtest.aggregate(self.make_rows(23), 24), [])
        result = backtest.aggregate(self.make_rows(24), 24)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["volume"], 240.0)
        self.assertEqual(result[0]["time"], 24 * 3_600_000)

    def test_empty_input(self):
        self.assertEqual(backtest.aggregate([], 4), [])

    def test_higher_timeframe_bar_must_be_closed_by_signal_time(self):
        closed_at = [4 * 3_600_000, 8 * 3_600_000]
        self.assertEqual(backtest.latest_closed_bar_index(closed_at, 3 * 3_600_000), -1)
        self.assertEqual(backtest.latest_closed_bar_index(closed_at, 4 * 3_600_000), 0)
        self.assertEqual(backtest.latest_closed_bar_index(closed_at, 7 * 3_600_000), 0)
        self.assertEqual(backtest.latest_closed_bar_index(closed_at, 8 * 3_600_000), 1)


class PortfolioTests(unittest.TestCase):
    def trade(self, entry, exit_, ret, risk=1.0):
        return {"entry_time": entry, "exit_time": exit_, "net_return_pct": ret,
                "risk_pct": risk}

    def test_position_cap_skips_overlapping_fourth_trade(self):
        trades = [
            self.trade("2024-01-01T00:00:00+00:00","2024-01-01T10:00:00+00:00",2),
            self.trade("2024-01-01T01:00:00+00:00","2024-01-01T11:00:00+00:00",2),
            self.trade("2024-01-01T02:00:00+00:00","2024-01-01T12:00:00+00:00",2),
            self.trade("2024-01-01T03:00:00+00:00","2024-01-01T13:00:00+00:00",2),
        ]
        result = backtest.simulate_portfolio(trades, starting_equity=1000, risk_fraction=.005, max_positions=3)
        self.assertEqual(result["trades_taken"], 3)
        self.assertEqual(result["trades_skipped"], 1)
        self.assertGreater(result["ending_equity"], 1000)

    def test_exits_free_slots_for_later_entries(self):
        trades = [
            self.trade("2024-01-01T00:00:00+00:00","2024-01-01T01:00:00+00:00",2),
            self.trade("2024-01-01T02:00:00+00:00","2024-01-01T03:00:00+00:00",-1),
        ]
        result = backtest.simulate_portfolio(trades, starting_equity=1000, risk_fraction=.005, max_positions=1)
        self.assertEqual(result["trades_taken"], 2)
        self.assertEqual(result["trades_skipped"], 0)

if __name__ == "__main__":
    unittest.main()
