import unittest
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
        self.calls = []
    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return FakeResponse(self.payload)


def make_payload(n=230, dividend_adjustment=False):
    import datetime
    start = datetime.datetime.now(datetime.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - datetime.timedelta(days=n + 2)
    timestamps = [int((start + datetime.timedelta(days=i)).timestamp()) for i in range(n)]
    closes = [20.0 + i * 0.1 for i in range(n)]
    adj = [x * 0.9 for x in closes] if dividend_adjustment else closes
    return {"chart": {"result": [{
        "timestamp": timestamps,
        "indicators": {
            "quote": [{"open": [x-0.1 for x in closes], "high": [x+0.2 for x in closes],
                       "low": [x-0.2 for x in closes], "close": closes, "volume": [1000]*n}],
            "adjclose": [{"adjclose": adj}],
        },
    }], "error": None}}


class StockProviderTests(unittest.TestCase):
    def test_no_api_key_needed_and_bars_parsed(self):
        session = FakeSession(make_payload())
        bars = fetch_daily_bars("AAPL", session=session)
        self.assertGreaterEqual(len(bars), 220)
        self.assertEqual(set(("date", "open", "high", "low", "close", "volume")), set(bars[0]))
        self.assertIn("period1", session.calls[0][1]["params"])

    def test_adjusted_close_does_not_rescale_ohlc(self):
        bars = fetch_daily_bars("AAPL", session=FakeSession(make_payload(dividend_adjustment=True)))
        self.assertAlmostEqual(bars[0]["open"], 19.9)
        self.assertAlmostEqual(bars[0]["close"], 20.0)
        self.assertAlmostEqual(bars[0]["high"], 20.2)

    def test_philippine_suffix_accepted(self):
        bars = fetch_daily_bars("AC.PS", session=FakeSession(make_payload()))
        self.assertGreaterEqual(len(bars), 220)

    def test_provider_error_fails_closed(self):
        payload = {"chart": {"error": {"description": "No data found"}, "result": None}}
        with self.assertRaisesRegex(ProviderError, "unavailable"):
            fetch_daily_bars("NOTREAL", session=FakeSession(payload))

    def test_short_history_fails_closed(self):
        with self.assertRaisesRegex(ProviderError, "need at least 220"):
            fetch_daily_bars("AAPL", session=FakeSession(make_payload(10)))

    def test_invalid_symbol_fails_closed(self):
        with self.assertRaisesRegex(ProviderError, "Invalid symbol"):
            fetch_daily_bars("bad symbol", session=FakeSession(make_payload()))


if __name__ == "__main__":
    unittest.main()
