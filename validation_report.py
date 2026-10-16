"""Conservative statistical report for backtest_results.csv.

This script summarizes evidence; it does not prove a strategy will work live.
Bootstrap intervals are trade-level and do not correct for serial correlation,
survivorship bias, strategy selection, or inaccurate execution assumptions.
"""
import csv
import math
import random
import sys
from collections import defaultdict
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
    """Deterministic percentile interval; returns None for an empty sample."""
    if not values:
        return None
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(iterations):
        means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return means[int(0.025 * iterations)], means[min(iterations - 1, int(0.975 * iterations))]


def load_returns(path):
    returns = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                value = float(row["net_return_pct"])
                if math.isfinite(value):
                    returns.append((row.get("entry_time", ""), value))
            except (KeyError, TypeError, ValueError):
                continue
    return returns


def report(path):
    rows = load_returns(path)
    values = [v for _, v in rows]
    n = len(values)
    wins = sum(v > 0 for v in values)
    gains = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v < 0)
    pf = gains / losses if losses else (math.inf if gains else 0.0)
    avg = sum(values) / n if n else 0.0
    lo_win, hi_win = wilson_interval(wins, n)
    ci = bootstrap_mean_interval(values)
    print("=== INDEPENDENT EVIDENCE SUMMARY ===")
    print(f"Trades with valid net returns: {n}")
    print(f"Win rate: {wins / n:.2%}" if n else "Win rate: n/a")
    print(f"Win-rate Wilson 95% CI: [{lo_win:.2%}, {hi_win:.2%}]" if n else "Win-rate CI: n/a")
    print(f"Mean net trade return: {avg:.4f}%" if n else "Mean net trade return: n/a")
    print(f"Trade-level profit factor: {pf:.3f}" if math.isfinite(pf) else "Trade-level profit factor: infinity (no losses observed)")
    print(f"Bootstrap 95% CI for mean net trade return: [{ci[0]:.4f}%, {ci[1]:.4f}%]" if ci else "Bootstrap CI: n/a")

    by_year = defaultdict(list)
    for timestamp, value in rows:
        try:
            by_year[timestamp[:4]].append(value)
        except (TypeError, IndexError):
            continue
    print("Year-by-year descriptive results (not independent validation):")
    for year in sorted(by_year):
        vals = by_year[year]
        win_rate = sum(v > 0 for v in vals) / len(vals)
        print(f"  {year}: n={len(vals)}, win_rate={win_rate:.2%}, mean_net={sum(vals) / len(vals):.4f}%")

    # Strict minimum evidence gate. This is a screening rule, not a guarantee.
    passed = n >= 100 and pf > 1.0 and ci is not None and ci[0] > 0
    if passed:
        print("EVIDENCE GATE: preliminary historical pass only; forward paper validation is still required.")
    else:
        reasons = []
        if n < 100:
            reasons.append(f"sample too small ({n}/100 trades)")
        if pf <= 1.0:
            reasons.append(f"profit factor not above 1 ({pf:.3f})")
        if ci is None or ci[0] <= 0:
            reasons.append("95% bootstrap interval does not establish positive mean net return")
        print("EVIDENCE GATE: NOT VALIDATED — " + "; ".join(reasons))
    print("LIMITATIONS: intervals assume trades are exchangeable; overlapping/correlated trades,")
    print("survivorship bias, parameter selection, missing historical order books, and fill")
    print("uncertainty are not solved by this report. Do not treat this as a live-profit forecast.")
    return 0


if __name__ == "__main__":
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("backtest_results.csv")
    if not input_path.exists():
        print(f"Missing input file: {input_path}", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(report(input_path))
