import unittest
from stock_scan import rank_results


class StockRankingTests(unittest.TestCase):
    def test_failed_setups_never_appear_in_ranked_candidates(self):
        rows = [
            {"symbol": "A", "status": "NO_QUALIFIED_SETUP", "checks_passed": 8},
            {"symbol": "B", "status": "DATA_UNAVAILABLE", "checks_passed": 9},
            {"symbol": "C", "status": "WATCHLIST_CANDIDATE", "checks_passed": 5},
            {"symbol": "D", "status": "STRICT_RESEARCH_CANDIDATE", "checks_passed": 4},
        ]
        self.assertEqual([x["symbol"] for x in rank_results(rows)], ["C", "D"])

    def test_empty_or_unqualified_results_yield_empty_rank(self):
        self.assertEqual(rank_results([{"status": "NO_QUALIFIED_SETUP"}]), [])
        self.assertEqual(rank_results([]), [])


if __name__ == "__main__":
    unittest.main()
