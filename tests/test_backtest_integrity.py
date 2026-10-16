import unittest

from backtest import aggregate, chronological_splits, eligible_backtest_symbol, latest_closed_bar_index, simulate_portfolio


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


    def test_chronological_splits_purge_boundary_crossing_trades(self):
        from datetime import datetime, timezone

        start = 0
        end = 1000 * 1000  # milliseconds; split at 600000 and 800000
        def iso(ms):
            return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()

        trades = [
            {"symbol": "A", "entry_time": iso(100000), "exit_time": iso(200000)},  # development
            {"symbol": "B", "entry_time": iso(590000), "exit_time": iso(610000)},  # crosses boundary
            {"symbol": "C", "entry_time": iso(700000), "exit_time": iso(750000)},  # validation
            {"symbol": "D", "entry_time": iso(810000), "exit_time": iso(820000)},  # holdout
        ]
        # Disable the extra time buffer so this test isolates crossing-trade purging.
        development, validation, holdout = chronological_splits(
            trades, start, end, purge_ms=0
        )
        self.assertEqual([t["symbol"] for t in development], ["A"])
        self.assertEqual([t["symbol"] for t in validation], ["C"])
        self.assertEqual([t["symbol"] for t in holdout], ["D"])

    def test_portfolio_reports_concurrent_exposure_and_realized_drawdown_scope(self):
        trades = [
            {"entry_time": "2026-01-01T00:00:00+00:00",
             "exit_time": "2026-01-01T02:00:00+00:00",
             "risk_pct": 1.0, "net_return_pct": 2.0},
            {"entry_time": "2026-01-01T01:00:00+00:00",
             "exit_time": "2026-01-01T03:00:00+00:00",
             "risk_pct": 1.0, "net_return_pct": -1.0},
        ]
        result = simulate_portfolio(trades, starting_equity=1000, risk_fraction=0.005,
                                    max_positions=3)
        self.assertEqual(result["trades_taken"], 2)
        self.assertEqual(result["max_concurrent_positions"], 2)
        self.assertGreater(result["max_open_risk_cash"], 0)
        self.assertIn("excludes unrealized", result["drawdown_method"])

    def test_portfolio_rejects_invalid_configuration(self):
        with self.assertRaises(ValueError):
            simulate_portfolio([], starting_equity=0)

    def test_backtest_universe_rejects_leveraged_and_tokenized_equity_pairs(self):
        valid = {"BTCUSDT", "ETHUSDT", "BTCUPUSDT", "NVDABUSDT", "XAUTUSDT"}
        excluded = {"USDC", "XAUT"}
        self.assertTrue(eligible_backtest_symbol("BTCUSDT", valid, excluded))
        self.assertFalse(eligible_backtest_symbol("BTCUPUSDT", valid, excluded))
        self.assertFalse(eligible_backtest_symbol("NVDABUSDT", valid, excluded))
        self.assertFalse(eligible_backtest_symbol("XAUTUSDT", valid, excluded))

    def test_backtest_universe_rejects_non_usdt_or_non_trading_pairs(self):
        valid = {"BTCUSDT", "ETHBTC"}
        self.assertFalse(eligible_backtest_symbol("ETHBTC", valid))
        self.assertFalse(eligible_backtest_symbol("SOLUSDT", valid))


if __name__ == "__main__":
    unittest.main()
