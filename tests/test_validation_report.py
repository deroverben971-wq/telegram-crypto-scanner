import unittest

from validation_report import bootstrap_mean_interval, wilson_interval


class ValidationStatisticsTests(unittest.TestCase):
    def test_wilson_interval_contains_observed_rate(self):
        low, high = wilson_interval(7, 10)
        self.assertLessEqual(low, 0.7)
        self.assertGreaterEqual(high, 0.7)

    def test_wilson_empty_sample_is_zero_interval(self):
        self.assertEqual(wilson_interval(0, 0), (0.0, 0.0))

    def test_bootstrap_is_deterministic(self):
        values = [-1.0, 0.5, 1.0, -0.25, 2.0]
        self.assertEqual(bootstrap_mean_interval(values, iterations=500),
                         bootstrap_mean_interval(values, iterations=500))

    def test_bootstrap_empty_sample(self):
        self.assertIsNone(bootstrap_mean_interval([], iterations=500))


if __name__ == "__main__":
    unittest.main()
