# Telegram Crypto Scanner

Alert-only Binance USDT spot screener. It does not place orders. Signals are technical filters, not predictions or investment advice; no profit or probability is guaranteed.

## What it checks
- Tradable Binance USDT spot pairs, filtered by 24-hour quote volume; stablecoin-like bases, known tokenized-equity/index proxies, and leveraged-token suffixes are excluded consistently in live scanning and historical universe selection
- Closed 1h, 4h, and daily candles; confirmed candidates require full trend alignment plus the BTC 1h/4h/daily market-regime gate. A separate **EARLY WATCHLIST** tier uses looser momentum thresholds and requires a constructive 1h trend plus non-broken 4h structure; these are watch-only, not bullish alerts. When BTC fails or BTC history is insufficient, even fully confirmed individual candidates remain **WATCH ONLY**.
- RSI, breakout versus the prior 20 hourly highs, candle close-location quality, timestamp-aligned 24-hour relative strength versus BTC, and volume expansion
- Rejects candidates if the latest 55 hourly candles contain a timestamp gap
- Best bid/ask spread and nearby order-book depth; illustrative long entry/target levels use the ask-side price rather than last-traded price, and reject excessive ask-side drift
- Six-hour per-pair alert cooldown and a maximum of three alerts per scan
- If no candidate survives the relaxed technical filters, the scanner now ranks a broader discovery list from every symbol with valid synchronized candle history. Each discovery score is rule confluence across 1h/4h/daily trend, RSI range, breakout extension, volume, relative strength versus BTC, and candle-close quality. These ranks do not include confirmed order-book/risk checks and are explicitly watch-only.

It reports **NO TRADE** when no candidate passes either technical tier, while also showing a ranked discovery watchlist when enough valid market data exists. Discovery rankings are not qualified setups and may not have passed order-book/risk checks. Confirmed alerts still require every strict filter and a positive BTC regime. The early-watchlist tier can surface more developing setups without changing the confirmed-alert criteria; these candidates are never promoted to bullish alerts merely to increase alert frequency. If BTC fails, all candidates remain watch-only. Scan logs include rejection counts for trend, momentum/breakout/volume/relative strength, order-book spread/depth, stop-risk, cooldown, insufficient history, and API errors. It does not check news, token unlocks, exploits, regulatory developments, or fundamentals.

## Forward paper validation (new)
- The live scanner records each qualifying technical setup once per symbol and closed 1h candle, including BTC-gated watch-only candidates, to reduce selection bias from only evaluating alerts that were sent.
- It tracks 1h, 4h, 24h, and 72h follow-up quote marks using the observed bid as the hypothetical exit and the original ask as the hypothetical entry. It applies illustrative 0.10% fees and 0.05% slippage per side.
- Marks are recorded at the first scanner observation after each horizon, with the delay recorded. If the observation is more than one full horizon late—or no valid quote appears within that tolerance—it is flagged as missed and no return is fabricated. Temporary Binance failures use bounded retries and honor `Retry-After` when available; exchange limits still apply.
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

## GitHub-only persistence setup
- The scanner workflow declares `contents: write` so GitHub Actions can commit the state ledger to the dedicated `paper-state` branch. In repository **Settings → Actions → General → Workflow permissions**, allow workflows to read and write repository contents if organization/repository policy requires this setting. Never add a personal access token to the source code.
- The first successful workflow run creates the `paper-state` branch. Later runs restore its JSON state and update it. Check the workflow log for the `Persist state to paper-state branch` step; a failed push means persistence was not confirmed.
- The branch stores tracking/cooldown state only. On a public repository, this JSON is public; it should contain no credentials or private information.

## Important limitations and acceptance criteria
- This project is an experimental screener, not a proven profitable strategy. Earlier results were weak/negative, including a poor final holdout; no durable edge has been established. The expanded backtest must finish before its new results can be assessed.
- The validation report's statistical sub-gate is a screening rule, not a guarantee. Overall status remains NOT VALIDATED until survivorship bias and other data limitations are addressed and independent forward paper validation supports the result.
- Unit tests validate only tested software behavior. They do not prove live API reliability, Telegram delivery, or profitability.
- The workflow now restores `.paper_state.json` and `.state.json` from a dedicated `paper-state` branch and commits the latest state there after each run; Actions cache remains only a fallback. This is more durable than cache alone, but it is still a small JSON ledger, not a transactional database. It depends on the workflow having repository contents write permission, successful Git pushes, and non-overlapping runs. The state branch is force-updated and should contain only these state files; do not store secrets there. Back up the branch periodically. Scheduled jobs can be delayed or skipped, so a 30-minute cron is a target cadence, not a guaranteed execution SLA. Binance and Telegram availability, API quotas, GitHub Actions quotas, and network failures remain external limits.
- Stop and target levels are illustrative, not orders; live alerts use the current ask as a more conservative entry reference, but a snapshot order book is not a fill guarantee. Gaps, slippage, fees, spread changes, and liquidity can change outcomes.
- Keep the scanner alert-only and use paper tracking. Never interpret a signal as a guarantee or risk money based on a backtest alone.

## Run locally
```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scanner.py --test-telegram
python scanner.py
```

## Stock-market expansion — staged, paper-research-only

The stock extension is paper-research-only and does **not** place orders.
The initial module (`stock_research.py`) only evaluates supplied daily OHLCV bars;
it does not claim to scan the complete US or Philippine exchanges yet.

- A provider adapter must be selected and tested separately for US-listed stocks/ETFs and PSE-listed instruments. Do not assume a free endpoint covers both exchanges, offers complete history, or permits automated redistribution.
- Daily-bar screening now returns a transparent 0–100 rule-confluence score. All five checks passing is a `STRICT_RESEARCH_CANDIDATE`; 3–4 checks passing is a `WATCHLIST_CANDIDATE` with missing confirmations shown; fewer than 3 checks is not qualified. The checks are price above EMA20, EMA20 > EMA50, EMA50 > EMA200, breakout 0–2% above the prior 20-day high, and volume at least 1.2x the prior-19-day average. Scores are not win probabilities. The report ranks the top five valid candidates while keeping strict and watchlist tiers separate.
- Provider integration must validate split adjustments, timestamps, stale/missing bars, ticker mapping, delisted-symbol survivorship bias, exchange holidays, and rate limits. PSE liquidity needs separate handling for spread, turnover, board lots, and infrequent trading.
- The stock prototype now uses Yahoo Finance's public chart endpoint without an API key. This endpoint is unofficial, can change or throttle requests, and is not an exchange-licensed feed or guaranteed SLA. It does not guarantee complete PSE coverage; Yahoo-listed Philippine tickers commonly use the `.PS` suffix (for example, `AC.PS`), but each symbol must be verified.
- The stock workflow scans only its configured watchlist, not every US or Philippine listing. It can send a Telegram research summary when the existing Telegram secrets are configured. Do not interpret the report as full-market coverage.
- Keep all outputs observational and paper-only. Historical screening alone is not evidence of an edge; evaluate chronological holdouts and forward paper marks after provider integration.


## Free scheduled stock research prototype (separate from the crypto alert loop)

- Open **Actions → Free stock paper research scan → Run workflow** to scan a custom list of up to 50 comma-separated Yahoo Finance symbols and upload `stock_research_results.json` as an artifact. It also runs on weekday schedules, but scheduled execution may be delayed.
- It uses `stock_provider.py` and Yahoo Finance's public chart endpoint; no stock-data API key is required. The workflow runs on weekday schedules and can send a Telegram summary using the same `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` secrets as the crypto scanner. It produces an artifact even if Telegram is not configured. The default watchlist mixes US stocks/ETFs and selected Yahoo-listed Philippine tickers; it is not a full-market scan.
- The default symbol list is a starter watchlist of US stocks/ETFs and selected Philippine tickers, not a complete NYSE/Nasdaq/PSE universe. Each symbol is requested separately, so 30 symbols means around 30 requests. Yahoo's unofficial endpoint may throttle, block, or omit some symbols.
- This prototype is **US only**. It does not scan the Philippine Stock Exchange. PSE data requires a verified, appropriately licensed data source and coverage testing; do not treat a missing PSE integration as a scan with zero candidates.
- The provider adapter fails closed on missing keys, rate-limit/entitlement messages, malformed data, and fewer than 220 valid daily bars. Price adjustment and volume conventions still need independent validation before interpreting performance.
- The stock workflow is scheduled on weekdays (twice daily), but GitHub may delay scheduled jobs. It has no persistent forward stock paper ledger yet; the artifact and Telegram summary are scan snapshots, not tracked outcomes. The existing Binance workflow remains separate and unchanged.
