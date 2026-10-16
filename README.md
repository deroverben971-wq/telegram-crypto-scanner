# Telegram Crypto Scanner

Alert-only Binance USDT spot screener. It does not place orders. Signals are technical filters, not predictions or investment advice; no profit or probability is guaranteed.

## What it checks
- Tradable Binance USDT spot pairs, filtered by 24-hour quote volume; stablecoin-like bases, known tokenized-equity/index proxies, and leveraged-token suffixes are excluded consistently in live scanning and historical universe selection
- Closed 1h, 4h, and daily candles; candidate trend alignment plus a BTC 1h/4h/daily market-regime gate. When BTC fails or BTC history is insufficient, the scanner still analyzes eligible altcoins but reports any qualifying technical candidates as **WATCH ONLY** and sends no bullish setup alerts.
- RSI, breakout versus the prior 20 hourly highs, candle close-location quality, timestamp-aligned 24-hour relative strength versus BTC, and volume expansion
- Rejects candidates if the latest 55 hourly candles contain a timestamp gap
- Best bid/ask spread and nearby order-book depth
- Six-hour per-pair alert cooldown and a maximum of three alerts per scan

It intentionally reports **NO TRADE** when no candidate passes all filters. If BTC fails and individual coins pass the technical filters, it reports up to three **WATCH ONLY** candidates instead of treating them as bullish alerts. Scan logs include rejection counts for trend, momentum/breakout/volume/relative strength, order-book spread/depth, stop-risk, cooldown, insufficient history, and API errors. It does not check news, token unlocks, exploits, regulatory developments, or fundamentals.

## Five-year historical backtest
1. Open **Actions → Five-year historical backtest → Run workflow** (or open a recent run).
2. Wait for the run to finish; downloading five years of hourly data for up to 50 currently liquid pairs can take a while.
3. Review the run log for portfolio simulation, trade count, win rate, profit factor, drawdown, chronological split results, and errors.
4. Download the **five-year-backtest-validation** artifact for `backtest_results.csv` and `validation_report.txt`.

The backtest uses up to 50 USDT spot pairs selected by their *current* 24-hour liquidity. It uses five years of hourly candles, builds 4h/daily bars from hourly data, filters known leveraged-token and tokenized-equity symbols from the research universe, enters at the next candle open, simulates a stop and 2R target, assumes the stop occurs first if stop and target are both touched in one candle, and subtracts illustrative fees/slippage. A statistical report adds year-by-year summaries and a day-clustered bootstrap interval. These are useful safeguards, not proof of a profitable edge.

**Important:** this is not a full replay of historical market conditions. Current-pair selection creates survivorship/selection bias; historical order-book spread/depth, token events, exact intrabar path, queue position, and real fills are not reconstructed. The portfolio model is still approximate. Do not tune parameters on the same period and then call that period independent validation.

## Setup
1. In GitHub, open **Settings → Secrets and variables → Actions**.
2. Add repository secrets named `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Never paste secrets into source code or commit them.
3. Open **Actions → Binance spot scanner → Run workflow**.
4. Select `test_telegram=true` to send a test message first. If successful, run again with `false` to scan.
5. Review workflow logs for errors. Scheduled runs target every 30 minutes, but GitHub Actions may delay scheduled jobs, and public-repository usage limits/availability may apply.

## Important limitations and acceptance criteria
- This project is an experimental screener, not a proven profitable strategy. Earlier results were weak/negative, including a poor final holdout; no durable edge has been established. The expanded backtest must finish before its new results can be assessed.
- The validation report's evidence gate is a screening rule, not a guarantee. Even a historical pass would require independent forward paper validation before any claim of edge.
- Unit tests validate only tested software behavior. They do not prove live API reliability, Telegram delivery, or profitability.
- The GitHub Actions runner is temporary. Cooldown state uses the Actions cache, which is best-effort rather than a durable database; state loss can allow repeated alerts. Scheduled jobs can be delayed or skipped, so a 30-minute cron is a target cadence, not a guaranteed execution SLA.
- Stop and target levels are illustrative, not orders; gaps, slippage, fees, and liquidity can change outcomes.
- Keep the scanner alert-only and use paper tracking. Never interpret a signal as a guarantee or risk money based on a backtest alone.

## Run locally
```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scanner.py --test-telegram
python scanner.py
```
