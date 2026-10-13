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

if __name__ == "__main__":
    unittest.main()
