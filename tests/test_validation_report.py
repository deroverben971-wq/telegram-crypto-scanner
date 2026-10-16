import unittest

from validation_report import (
    bootstrap_mean_interval, clustered_day_interval, wilson_interval,
)


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

    def test_day_cluster_bootstrap_keeps_same_day_as_cluster(self):
        rows = [
            {"entry_time": "2026-01-01T01:00:00+00:00", "net_return_pct": 1.0},
            {"entry_time": "2026-01-01T02:00:00+00:00", "net_return_pct": -1.0},
            {"entry_time": "2026-01-02T01:00:00+00:00", "net_return_pct": 2.0},
        ]
        interval, days = clustered_day_interval(rows, iterations=500)
        self.assertEqual(days, 2)
        self.assertIsNotNone(interval)
        self.assertEqual(interval, clustered_day_interval(rows, iterations=500)[0])

    def test_day_cluster_bootstrap_empty(self):
        self.assertEqual(clustered_day_interval([], iterations=500), (None, 0))


if __name__ == "__main__":
    unittest.main()
