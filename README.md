# Telegram Crypto Scanner

Alert-only Binance USDT spot screener. It does not place orders. Signals are technical filters, not predictions or investment advice; no profit or probability is guaranteed.

## What it checks
- Tradable Binance USDT spot pairs, filtered by 24-hour quote volume
- Closed 1h, 4h, and daily candles; EMA trend alignment
- RSI, recent breakout, relative strength versus BTC, and volume expansion
- Best bid/ask spread and nearby order-book depth
- Six-hour per-pair alert cooldown and a maximum of three alerts per scan

It intentionally reports **NO TRADE** when no candidate passes all filters. It does not check news, token unlocks, exploits, regulatory developments, or fundamentals.

## Setup
1. In GitHub, open **Settings → Secrets and variables → Actions**.
2. Add repository secrets named `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Never paste secrets into source code or commit them.
3. Open **Actions → Binance spot scanner → Run workflow**.
4. Select `test_telegram=true) to send a test message first. If successful, run again with `false` to scan.
5. Review the workflow logs for errors. Scheduled runs target every five minutes, but GitHub Actions may delay scheduled jobs, and public-repository usage limits/availability may apply.

## Important limitations
- This project is an experimental screener, not a proven profitable strategy. It has **not** been validated by a historical backtest or forward paper-trading study.
- A passing test suite validates only the tested software behavior. It does not prove live API reliability, delivery on your Telegram account, or profitability.
- The GitHub Actions runner is temporary. The local JSON cooldown state may not persist reliably between runs, so repeated alerts can occur if state is lost.
- Stop and target levels are illustrative, not orders; gaps, slippage, fees, and liquidity can change outcomes.
- Keep trading decisions cautious and discuss financial risk with a trusted adult. Never risk money you cannot afford to lose.

## Run locally
```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scanner.py --test-telegram
python scanner.py
```
