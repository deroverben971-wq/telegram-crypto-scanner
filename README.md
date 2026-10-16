# Telegram Crypto Scanner

Alert-only Binance USDT spot screener. It does not place orders. Signals are technical filters, not predictions or investment advice; no profit or probability is guaranteed.

## What it checks
- Tradable Binance USDT spot pairs, filtered by 24-hour quote volume; stablecoin-like bases, known tokenized-equity/index proxies, and leveraged-token suffixes are excluded consistently in live scanning and historical universe selection
- Closed 1h, 4h, and daily candles; candidate trend alignment plus a BTC 1h/4h/daily market-regime gate. When BTC fails or BTC history is insufficient, the scanner still analyzes eligible altcoins but reports any qualifying technical candidates as **WATCH ONLY** and sends no bullish setup alerts.
- RSI, breakout versus the prior 20 hourly highs, candle close-location quality, timestamp-aligned 24-hour relative strength versus BTC, and volume expansion
- Rejects candidates if the latest 55 hourly candles contain a timestamp gap
- Best bid/ask spread and nearby order-book depth; illustrative long entry/target levels use the ask-side price rather than last-traded price, and reject excessive ask-side drift
- Six-hour per-pair alert cooldown and a maximum of three alerts per scan

It intentionally reports **NO TRADE** when no candidate passes all filters. If BTC fails and individual coins pass the technical filters, it reports up to three **WATCH ONLY** candidates instead of treating them as bullish alerts. Scan logs include rejection counts for trend, momentum/breakout/volume/relative strength, order-book spread/depth, stop-risk, cooldown, insufficient history, and API errors. It does not check news, token unlocks, exploits, regulatory developments, or fundamentals.

## Forward paper validation (new)
- The live scanner records each qualifying technical setup once per symbol and closed 1h candle, including BTC-gated watch-only candidates, to reduce selection bias from only evaluating alerts that were sent.
- It tracks 1h, 4h, 24h, and 72h follow-up quote marks using the observed bid as the hypothetical exit and the original ask as the hypothetical entry. It applies illustrative 0.10% fees and 0.05% slippage per side.
- Marks are recorded at the first scanner observation after each horizon, with the delay recorded. If the observation is more than one full horizon late, it is flagged as missed and no return is fabricated.
- The ledger is stored in \`.paper_state.json\` and carried between GitHub Actions runs using the Actions cache. **GitHub cache is best-effort and not a durable database**; cache loss can interrupt the record. Save/export the state regularly if you need an auditable long-term record.
- These are quote-based paper marks, not actual fills. A snapshot cannot establish queue position, market impact, exact stop/target path, or whether a price was continuously executable. Stop/target flags at a horizon are only snapshots, not proof the level was touched intraperiod.
- Do not treat the ledger as a profitability certificate. Review mark counts, missed observations, horizon-specific net returns, symbol concentration, and market regimes only after enough observations accumulate.

## Five-year historical backtest
1. Open **Actions → Five-year historical backtest → Run workflow** (or open a recent run).
2. Wait for the run to finish; downloading five years of hourly data for up to 50 currently liquid pairs can take a while.
3. Review the run log for portfolio simulation, trade count, win rate, profit factor, drawdown, chronological split results, and errors.
4. Download the **five-year-backtest-validation** artifact for `backtest_results.csv` and `validation_report.txt`.

The backtest uses up to 50 USDT spot pairs selected by their *current* 24-hour liquidity. It uses five years of hourly candles, builds 4h/daily bars from hourly data, filters known leveraged-token and tokenized-equity symbols from the research universe, enters at the next candle open, simulates a stop and 2R target, assumes the stop occurs first if stop and target are both touched in one candle, and subtracts illustrative fees/slippage. A statistical report adds year-by-year summaries and a day-clustered bootstrap interval. These are useful safeguards, not proof of a profitable edge.

**Important:** this is not a full replay of historical market conditions. Current-pair selection creates survivorship/selection bias; historical order-book spread/depth, token events, exact intrabar path, queue position, and real fills are not reconstructed. The portfolio model reports concurrent positions and maximum simultaneous planned stop-risk, but its drawdown is based on closed-trade realized equity and excludes unrealized losses while positions are open. It is not a full mark-to-market portfolio simulator. Chronological development/validation/holdout splits now purge trades that cross split boundaries and apply a 72-hour buffer. The evidence report can show a statistical sub-gate, but overall strategy status remains NOT VALIDATED while the historical universe has survivorship/selection bias. Do not tune parameters on the same period and then call that period independent validation.

## Setup
1. In GitHub, open **Settings → Secrets and variables → Actions**.
2. Add repository secrets named `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Never paste secrets into source code or commit them.
3. Open **Actions → Binance spot scanner → Run workflow**.
4. Select `test_telegram=true` to send a test message first. If successful, run again with `false` to scan.
5. Review workflow logs for errors. Scheduled runs target every 30 minutes, but GitHub Actions may delay scheduled jobs, and public-repository usage limits/availability may apply.

## Important limitations and acceptance criteria
- This project is an experimental screener, not a proven profitable strategy. Earlier results were weak/negative, including a poor final holdout; no durable edge has been established. The expanded backtest must finish before its new results can be assessed.
- The validation report's statistical sub-gate is a screening rule, not a guarantee. Overall status remains NOT VALIDATED until survivorship bias and other data limitations are addressed and independent forward paper validation supports the result.
- Unit tests validate only tested software behavior. They do not prove live API reliability, Telegram delivery, or profitability.
- The GitHub Actions runner is temporary. Cooldown state uses the Actions cache, which is best-effort rather than a durable database; state loss can allow repeated alerts. Scheduled jobs can be delayed or skipped, so a 30-minute cron is a target cadence, not a guaranteed execution SLA.
- Stop and target levels are illustrative, not orders; live alerts use the current ask as a more conservative entry reference, but a snapshot order book is not a fill guarantee. Gaps, slippage, fees, spread changes, and liquidity can change outcomes.
- Keep the scanner alert-only and use paper tracking. Never interpret a signal as a guarantee or risk money based on a backtest alone.

## Run locally
```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scanner.py --test-telegram
python scanner.py
```
