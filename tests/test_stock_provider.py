import unittest
from unittest.mock import Mock
from stock_provider import ProviderError, fetch_daily_bars


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
    def raise_for_status(self):
        return None
    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
    def get(self, *args, **kwargs):
        return FakeResponse(self.payload)


class StockProviderTests(unittest.TestCase):
    def test_missing_key_fails_closed(self):
        with self.assertRaisesRegex(ProviderError, "Missing ALPHAVANTAGE_API_KEY"):
            fetch_daily_bars("AAPL", api_key="", session=FakeSession({}))

    def test_rate_limit_or_premium_error_is_not_treated_as_data(self):
        with self.assertRaisesRegex(ProviderError, "did not return data"):
            fetch_daily_bars("AAPL", api_key="test", session=FakeSession({"Note": "API call frequency exceeded"}))

    def test_short_history_fails_closed(self):
        with self.assertRaisesRegex(ProviderError, "Only 1 valid daily bars"):
            fetch_daily_bars("AAPL", api_key="test", session=FakeSession({
                "Time Series (Daily)": {
                    "2026-01-02": {
                        "1. open": "10", "2. high": "11", "3. low": "9",
                        "4. close": "10", "5. adjusted close": "10", "6. volume": "100"
                    }
                }
            }))


if __name__ == "__main__":
    unittest.main()
