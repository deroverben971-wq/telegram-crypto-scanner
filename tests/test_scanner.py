import unittest
import scanner

class IndicatorTests(unittest.TestCase):
    def test_ema_short_input(self):
        self.assertIsNone(scanner.ema([1, 2], 3))
    def test_ema_constant(self):
        self.assertAlmostEqual(scanner.ema([5] * 25, 20), 5)
    def test_ema_rising(self):
        self.assertGreater(scanner.ema(list(range(1, 31)), 10), scanner.ema(list(range(1, 31)), 20))
    def test_rsi_rising(self):
        self.assertEqual(scanner.rsi(list(range(1, 30))), 100)
    def test_rsi_flat(self):
        self.assertEqual(scanner.rsi([10] * 20), 50)
    def test_rsi_short(self):
        self.assertIsNone(scanner.rsi([1, 2], 14))


class CooldownStateTests(unittest.TestCase):
    def test_valid_timestamp(self):
        self.assertEqual(scanner.safe_timestamp("123.5"), 123.5)
    def test_malformed_timestamp_defaults_to_zero(self):
        self.assertEqual(scanner.safe_timestamp("not-a-number"), 0.0)
    def test_negative_or_infinite_timestamp_defaults_to_zero(self):
        self.assertEqual(scanner.safe_timestamp(-1), 0.0)
        self.assertEqual(scanner.safe_timestamp(float("inf")), 0.0)


class RelativeStrengthTests(unittest.TestCase):
    def rows(self, closes, times):
        return [{"time": t, "close": p} for t,p in zip(times,closes)]

    def test_uses_matching_24_hour_timestamps(self):
        hour=3_600_000
        asset=self.rows([100,110],[0,24*hour])
        btc=self.rows([100,105],[0,24*hour])
        self.assertAlmostEqual(scanner.relative_strength(asset,btc),5.0)

    def test_missing_exact_timestamp_fails_closed(self):
        hour=3_600_000
        asset=self.rows([100,110],[0,24*hour])
        btc=self.rows([100,105],[0,23*hour])
        self.assertIsNone(scanner.relative_strength(asset,btc))

    def test_invalid_price_fails_closed(self):
        hour=3_600_000
        asset=self.rows([0,110],[0,24*hour])
        btc=self.rows([100,105],[0,24*hour])
        self.assertIsNone(scanner.relative_strength(asset,btc))

    def test_stale_benchmark_latest_candle_fails_closed(self):
        hour=3_600_000
        asset=self.rows([100,110],[0,24*hour])
        btc=self.rows([100,105],[0,23*hour])
        self.assertIsNone(scanner.relative_strength(asset,btc))

    def test_contiguous_recent_accepts_even_spacing(self):
        hour=3_600_000
        rows=[{"time":i*hour} for i in range(55)]
        self.assertTrue(scanner.contiguous_recent(rows,hour))

    def test_contiguous_recent_rejects_gap(self):
        hour=3_600_000
        rows=[{"time":i*hour} for i in range(55)]
        rows[-1]["time"] += hour
        self.assertFalse(scanner.contiguous_recent(rows,hour))

    def test_contiguous_recent_rejects_insufficient_history(self):
        hour=3_600_000
        rows=[{"time":i*hour} for i in range(54)]
        self.assertFalse(scanner.contiguous_recent(rows,hour))

    def test_recent_and_contiguous_rejects_stale_data(self):
        hour=3_600_000
        rows=[{"time":i*hour} for i in range(55)]
        self.assertFalse(scanner.recent_and_contiguous(rows,hour,now_ms=100*hour))

    def test_recent_and_contiguous_accepts_recent_data(self):
        hour=3_600_000
        rows=[{"time":i*hour} for i in range(55)]
        self.assertTrue(scanner.recent_and_contiguous(rows,hour,now_ms=55*hour))

    def test_orderbook_metrics_valid_book(self):
        book=scanner.orderbook_metrics({"bids":[["99.95","200"]],"asks":[["100.05","200"]]})
        self.assertIsNotNone(book)
        self.assertAlmostEqual(book["spread_pct"],0.1,places=5)
        self.assertGreater(book["bid_depth"],0)

    def test_orderbook_metrics_rejects_crossed_or_empty_book(self):
        self.assertIsNone(scanner.orderbook_metrics({"bids":[["101","2"]],"asks":[["100","2"]]}))
        self.assertIsNone(scanner.orderbook_metrics({"bids":[],"asks":[]}))

    def test_orderbook_metrics_ignores_nonfinite_levels(self):
        self.assertIsNone(scanner.orderbook_metrics({"bids":[["NaN","2"]],"asks":[["100","2"]]}))

if __name__ == "__main__":
    unittest.main()
