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

if __name__ == "__main__":
    unittest.main()
