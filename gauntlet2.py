"""
gauntlet2.py — weighted-population gauntlet for Divided Oracle candidates.

Scores a candidate against the herd in ./work/herd/ with the field weights
from the day-3 plan, on paired seeds, and (optionally) reports the paired
diff vs a baseline bot run on the IDENTICAL seed set.

Usage:
  python gauntlet2.py --bot <candidate> [--baseline <bot>] [--seeds 40]
                      [--start-seed 2000] [--n_deals 10] [--jobs N]

Reuses sweep.run_one (subprocess per match, parses bot1 aggregate PnL from the
backtester MATCH SUMMARY; any parse failure prints raw output and aborts).
"""

from __future__ import annotations

import argparse
import math
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sweep import ParseError, run_one, resolve_bot

WORK = Path(__file__).resolve().parent
HERD = WORK / "herd"

#: Field-composition weights (day-3 plan Step 1).
WEIGHTS = {
    "h1_clone.py":         0.20,
    "h2_clone_tweaked.py": 0.15,
    "h3_clone_aggro.py":   0.10,
    "h4_honest_naive.py":  0.15,
    "h5_endgame_aware.py": 0.15,
    "h6_my_modal.py":      0.15,
    "h7_broken.py":        0.10,
}


def run_grid(bot: str, opponents: list[str], seeds: list[int],
             n_deals: int, jobs: int) -> dict[str, dict[int, float]]:
    """bot vs every opponent on every seed -> {opp_name: {seed: pnl}}."""
    results: dict[str, dict[int, float]] = {Path(o).name: {} for o in opponents}
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futs = {}
        for opp in opponents:
            for seed in seeds:
                futs[(Path(opp).name, seed)] = pool.submit(
                    run_one, bot, opp, seed, n_deals, False)
        for (opp_name, seed), fut in futs.items():
            results[opp_name][seed] = fut.result()
    return results


def weighted_stats(grid: dict[str, dict[int, float]]):
    """Per-seed weighted population score -> (per-opp means, weighted mean, stderr)."""
    seeds = sorted(next(iter(grid.values())).keys())
    per_opp = {o: statistics.mean(r.values()) for o, r in grid.items()}
    weighted_per_seed = [
        sum(WEIGHTS[o] * grid[o][s] for o in grid) for s in seeds
    ]
    n = len(seeds)
    mean = statistics.mean(weighted_per_seed)
    stderr = (statistics.stdev(weighted_per_seed) / math.sqrt(n)) if n > 1 else 0.0
    return per_opp, mean, stderr, weighted_per_seed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", required=True)
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--seeds", type=int, default=40)
    ap.add_argument("--start-seed", type=int, default=2000)
    ap.add_argument("--n_deals", type=int, default=10)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args()

    bot = resolve_bot(args.bot)
    opponents = [str(HERD / name) for name in WEIGHTS]
    for o in opponents:
        if not Path(o).exists():
            sys.exit(f"gauntlet2: missing herd bot {o}")
    seeds = list(range(args.start_seed, args.start_seed + args.seeds))

    t0 = time.perf_counter()
    try:
        grid = run_grid(bot, opponents, seeds, args.n_deals, args.jobs)
        per_opp, mean, stderr, wps = weighted_stats(grid)

        base_grid = None
        if args.baseline:
            base = resolve_bot(args.baseline)
            base_grid = run_grid(base, opponents, seeds, args.n_deals, args.jobs)
            bper_opp, bmean, _, bwps = weighted_stats(base_grid)
    except ParseError as e:
        print(f"\nPARSE FAILURE: {e}", file=sys.stderr)
        print(e.raw, file=sys.stderr)
        sys.exit(2)

    name = Path(bot).stem
    print(f"\n  WEIGHTED HERD GAUNTLET — {name}"
          f"  (seeds {seeds[0]}..{seeds[-1]}, n_deals={args.n_deals})")
    print(f"  {'-'*66}")
    header = f"  {'opponent':22s} {'w':>5s} {'mean PnL':>10s}"
    if base_grid:
        header += f" {'base':>10s} {'diff':>9s}"
    print(header)
    worst = None
    for o in WEIGHTS:
        line = f"  {o:22s} {WEIGHTS[o]:5.2f} {per_opp[o]:+10.2f}"
        if base_grid:
            d = per_opp[o] - bper_opp[o]
            line += f" {bper_opp[o]:+10.2f} {d:+9.2f}"
        print(line)
        if worst is None or per_opp[o] < per_opp[worst]:
            worst = o
    print(f"  {'-'*66}")
    print(f"  weighted mean: {mean:+8.3f}  (stderr {stderr:.3f})")
    print(f"  worst matchup: {worst}  ({per_opp[worst]:+.2f})")

    if base_grid:
        diffs = [w - b for w, b in zip(wps, bwps)]
        n = len(diffs)
        dm = statistics.mean(diffs)
        ds = (statistics.stdev(diffs) / math.sqrt(n)) if n > 1 else 0.0
        lo, hi = dm - 1.96 * ds, dm + 1.96 * ds
        print(f"\n  PAIRED WEIGHTED DIFF vs {Path(args.baseline).stem} (same seeds):")
        print(f"  mean {dm:+8.3f}   stderr {ds:.3f}   95% CI [{lo:+.3f}, {hi:+.3f}]"
              f"   {'SIGNIFICANT' if (lo > 0 or hi < 0) else 'not significant'}")

    print(f"\n  wall time: {time.perf_counter() - t0:.1f}s\n")


if __name__ == "__main__":
    main()
