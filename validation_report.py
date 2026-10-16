"""Conservative evidence report for approximate backtest trades.

Trade-level bootstrap is shown for comparison. The clustered bootstrap resamples
calendar days, keeping same-day signals together to reduce (not eliminate)
cross-asset/temporal dependence. This is still not a portfolio-equity simulator.
"""
import csv
import math
import random
import sys
from collections import defaultdict, Counter
from pathlib import Path

Z95 = 1.959963984540054
BOOTSTRAPS = 20000


def wilson_interval(wins, n, z=Z95):
    if n <= 0:
        return (0.0, 0.0)
    p = wins / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    margin = z * math.sqrt((p * (1 - p) / n) + z * z / (4 * n * n)) / den
    return max(0.0, center - margin), min(1.0, center + margin)


def bootstrap_mean_interval(values, iterations=BOOTSTRAPS, seed=20261016):
    """Deterministic trade-level percentile interval; not dependence-aware."""
    if not values:
        return None
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n
                   for _ in range(iterations))
    return means[int(0.025 * iterations)], means[min(iterations - 1, int(0.975 * iterations))]


def clustered_day_interval(rows, iterations=BOOTSTRAPS, seed=20261017):
    """Resample days, keeping all trades entered on each date in the same cluster."""
    by_day = defaultdict(list)
    for row in rows:
        day = row.get("entry_time", "")[:10]
        if day:
            by_day[day].append(float(row["net_return_pct"]))
    clusters = [values for _, values in sorted(by_day.items())]
    if not clusters:
        return None, 0
    # Each day contributes its mean trade return, so busy days don't dominate
    # merely because more symbols signaled together.
    daily_means = [sum(v) / len(v) for v in clusters]
    rng = random.Random(seed)
    n = len(daily_means)
    means = sorted(sum(daily_means[rng.randrange(n)] for _ in range(n)) / n
                   for _ in range(iterations))
    return (means[int(0.025 * iterations)],
            means[min(iterations - 1, int(0.975 * iterations))]), n


def load_rows(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                value = float(row["net_return_pct"])
                if math.isfinite(value):
                    row["net_return_pct"] = value
                    rows.append(row)
            except (KeyError, TypeError, ValueError):
                continue
    return rows


def report(path):
    rows = load_rows(path)
    values = [r["net_return_pct"] for r in rows]
    n = len(values)
    wins = sum(v > 0 for v in values)
    gains = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v < 0)
    pf = gains / losses if losses else (math.inf if gains else 0.0)
    avg = sum(values) / n if n else 0.0
    lo_win, hi_win = wilson_interval(wins, n)
    trade_ci = bootstrap_mean_interval(values)
    cluster_ci, day_count = clustered_day_interval(rows)
    print("=== HISTORICAL EVIDENCE SUMMARY ===")
    print(f"Trades with valid net returns: {n}")
    print(f"Win rate: {wins / n:.2%}" if n else "Win rate: n/a")
    print(f"Win-rate Wilson 95% CI: [{lo_win:.2%}, {hi_win:.2%}]" if n else "Win-rate CI: n/a")
    print(f"Mean net trade return: {avg:.4f}%" if n else "Mean net trade return: n/a")
    print(f"Trade-level profit factor: {pf:.3f}" if math.isfinite(pf) else "Trade-level profit factor: infinity (no losses observed)")
    print(f"Trade-level bootstrap 95% CI: [{trade_ci[0]:.4f}%, {trade_ci[1]:.4f}%]" if trade_ci else "Trade-level bootstrap CI: n/a")
    print(f"Day-cluster bootstrap 95% CI for mean daily-cluster trade return: [{cluster_ci[0]:.4f}%, {cluster_ci[1]:.4f}%] across {day_count} active days" if cluster_ci else "Day-cluster bootstrap CI: n/a")

    by_year = defaultdict(list)
    by_symbol = Counter()
    for row in rows:
        by_year[row.get("entry_time", "")[:4]].append(row["net_return_pct"])
        by_symbol[row.get("symbol", "UNKNOWN")] += 1
    print("Year-by-year descriptive results (not independent validation):")
    for year in sorted(by_year):
        vals = by_year[year]
        win_rate = sum(v > 0 for v in vals) / len(vals)
        print(f"  {year}: n={len(vals)}, win_rate={win_rate:.2%}, mean_net={sum(vals) / len(vals):.4f}%")
    print("Trade concentration by symbol (top 10):")
    for symbol, count in by_symbol.most_common(10):
        print(f"  {symbol}: {count} trades ({count / n:.1%})" if n else f"  {symbol}: {count} trades")

    # Conservative screening gate; not a guarantee and not independent proof.
    passed = (n >= 100 and day_count >= 60 and pf > 1.0
              and cluster_ci is not None and cluster_ci[0] > 0)
    if passed:
        print("STATISTICAL SUB-GATE: preliminary pass on these trade-level summaries only.")
        print("OVERALL EVIDENCE STATUS: NOT VALIDATED — current-liquid-pair selection has survivorship/selection bias,")
        print("and the dataset does not reconstruct delisted pairs, point-in-time listings, historical liquidity,")
        print("order-book conditions, or true fills. Independent forward paper validation remains mandatory.")
    else:
        reasons = []
        if n < 100:
            reasons.append(f"sample too small ({n}/100 trades)")
        if day_count < 60:
            reasons.append(f"too few active-day clusters ({day_count}/60)")
        if pf <= 1.0:
            reasons.append(f"profit factor not above 1 ({pf:.3f})")
        if cluster_ci is None or cluster_ci[0] <= 0:
            reasons.append("day-cluster 95% interval does not establish positive mean return")
        print("EVIDENCE GATE: NOT VALIDATED — " + "; ".join(reasons))
    print("LIMITATIONS THAT REMAIN: current-liquid-pair selection can omit delisted assets;")
    print("day clustering only partially addresses dependence; parameter selection may bias results;")
    print("historical spread/depth/news/token unlocks and exact fills are not reconstructed.")
    print("Use forward paper tracking and an independently sourced historical universe before claiming edge.")
    return 0


if __name__ == "__main__":
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("backtest_results.csv")
    if not input_path.exists():
        print(f"Missing input file: {input_path}", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(report(input_path))
