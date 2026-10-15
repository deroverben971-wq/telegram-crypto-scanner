# Telegram Crypto Scanner

Alert-only Binance USDT spot screener. It does not place orders. Signals are technical filters, not predictions or investment advice; no profit or probability is guaranteed.

## What it checks
- Tradable Binance USDT spot pairs, filtered by 24-hour quote volume
- Closed 1h, 4h, and daily candles; candidate trend alignment plus a BTC 1h/4h/daily market-regime gate. When BTC fails or BTC history is insufficient, the scanner still analyzes eligible altcoins but reports any qualifying technical candidates as **WATCH ONLY** and sends no bullish setup alerts.
- RSI, breakout versus the prior 20 hourly highs, candle close-location quality, timestamp-aligned 24-hour relative strength versus BTC, and volume expansion
- Rejects candidates if the latest 55 hourly candles contain a timestamp gap
- Best bid/ask spread and nearby order-book depth
- Six-hour per-pair alert cooldown and a maximum of three alerts per scan

It intentionally reports **NO TRADE** when no candidate passes all filters. If BTC fails and individual coins pass the technical filters, it reports up to three **WATCH ONLY** candidates instead of treating them as bullish alerts. Scan logs now include rejection counts for trend, momentum/breakout/volume/relative strength, order-book spread/depth, stop-risk, cooldown, insufficient history, and API errors. It does not check news, token unlocks, exploits, regulatory developments, or fundamentals.

## Five-year historical backtest (manual)
1. Open **Actions → Five-year historical backtest → Run workflow**.
2. Wait for the run to finish; downloading five years of hourly data may take a while.
3. Read the run log for trade count, win rate, net trade-return statistics, profit factor, and drawdown.
4. In the completed run, download the **five-year-backtest-results** artifact for individual simulated trades.

The backtest tests an approximation of the technical setup on up to 15 pairs that are liquid **today**. It uses five years of hourly candles, approximates 4h/daily candles from hourly data, enters at the next candle open, simulates a stop and 2R target, uses a conservative stop-first rule when both levels are touched in the same candle, and subtracts illustrative fees/slippage. It cannot reconstruct historical order-book spread/depth or actual fills and does not include delisted coins, so survivorship bias and execution-model limitations remain. Its results are exploratory, not proof of a durable edge. Do not optimize rules against the same period and then treat that result as independent validation.

## Setup
1. In GitHub, open **Settings → Secrets and variables → Actions**.
2. Add repository secrets named `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Never paste secrets into source code or commit them.
3. Open **Actions → Binance spot scanner → Run workflow**.
4. Select `test_telegram=true` to send a test message first. If successful, run again with `false` to scan.
5. Review the workflow logs for errors. Scheduled runs target every 30 minutes, but GitHub Actions may delay scheduled jobs, and public-repository usage limits/availability may apply.

## Important limitations
- This project is an experimental screener, not a proven profitable strategy. The five-year approximate backtest is exploratory, has a weak/negative final holdout, and has not established a durable edge. No sustained forward paper-trading study has been completed.
- A passing test suite validates only the tested software behavior. It does not prove live API reliability, delivery on your Telegram account, or profitability. The backtest's historical universe is selected from pairs liquid today; it cannot fully remove survivorship bias or recreate historical order books, point-in-time listings, exchange outages, token events, or actual queue position.
- The GitHub Actions runner is temporary. The workflow now restores/saves the local JSON cooldown state through the Actions cache, but cache availability is best-effort rather than a durable database; state loss can still allow repeated alerts. Scheduled jobs can be delayed or skipped by GitHub; a five-minute cron is a target cadence, not a guaranteed execution SLA.
- Stop and target levels are illustrative, not orders; gaps, slippage, fees, and liquidity can change outcomes.
- Keep trading decisions cautious and discuss financial risk with a trusted adult. Never risk money you cannot afford to lose.

## Run locally
```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scanner.py --test-telegram
python scanner.py
```
