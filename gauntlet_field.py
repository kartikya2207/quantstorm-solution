"""
gauntlet_field.py — score several candidates against the f01-f12 field
(equal weights), same paired seed set for every cell.

Usage:
  python gauntlet_field.py --bots v2_endgame.py C1_estimator.py C5_ai_beater.py
                           [--dir field] [--seeds 60] [--start-seed 7000]
                           [--n_deals 10] [--jobs N]

Prints: per-opponent × per-bot table, each bot's unweighted mean, and the
paired diff (with 95% CI) of every bot vs the FIRST bot listed.
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bots", nargs="+", required=True)
    ap.add_argument("--dir", default="field")
    ap.add_argument("--seeds", type=int, default=60)
    ap.add_argument("--start-seed", type=int, default=7000)
    ap.add_argument("--n_deals", type=int, default=10)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args()

    bots = [resolve_bot(b) for b in args.bots]
    names = [Path(b).stem for b in bots]
    opp_dir = WORK / args.dir
    opps = sorted(opp_dir.glob("*.py"))
    if not opps:
        sys.exit(f"no opponents in {opp_dir}")
    seeds = list(range(args.start_seed, args.start_seed + args.seeds))

    t0 = time.perf_counter()
    # grid[bot][opp][seed] = pnl
    grid = {n: {o.name: {} for o in opps} for n in names}
    try:
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futs = {}
            for b, n in zip(bots, names):
                for o in opps:
                    for s in seeds:
                        futs[(n, o.name, s)] = pool.submit(
                            run_one, b, str(o), s, args.n_deals, False)
            for (n, on, s), fut in futs.items():
                grid[n][on][s] = fut.result()
    except ParseError as e:
        print(f"PARSE FAILURE: {e}", file=sys.stderr)
        print(e.raw, file=sys.stderr)
        sys.exit(2)

    print(f"\n  FIELD GAUNTLET — {len(opps)} opponents, equal weight, "
          f"{args.seeds} paired seeds ({seeds[0]}..{seeds[-1]})")
    hdr = f"  {'opponent':24s}" + "".join(f"{n[:12]:>14s}" for n in names)
    print(hdr)
    print("  " + "-" * (24 + 14 * len(names)))
    for o in opps:
        row = f"  {o.name:24s}"
        for n in names:
            row += f"{statistics.mean(grid[n][o.name].values()):+14.2f}"
        print(row)
    print("  " + "-" * (24 + 14 * len(names)))
    row = f"  {'MEAN (unweighted)':24s}"
    means = {}
    for n in names:
        per_seed = [statistics.mean(grid[n][o.name][s] for o in opps) for s in seeds]
        means[n] = statistics.mean(per_seed)
        row += f"{means[n]:+14.2f}"
    print(row)

    base = names[0]
    print(f"\n  PAIRED DIFF vs {base} (population mean per seed, same seeds):")
    for n in names[1:]:
        diffs = []
        for s in seeds:
            a = statistics.mean(grid[n][o.name][s] for o in opps)
            b = statistics.mean(grid[base][o.name][s] for o in opps)
            diffs.append(a - b)
        dm = statistics.mean(diffs)
        ds = (statistics.stdev(diffs) / math.sqrt(len(diffs))) if len(diffs) > 1 else 0.0
        lo, hi = dm - 1.96 * ds, dm + 1.96 * ds
        sig = "SIGNIFICANT" if (lo > 0 or hi < 0) else "not significant"
        print(f"    {n:20s} {dm:+8.3f}  [{lo:+.3f}, {hi:+.3f}]  {sig}")

    print(f"\n  wall time: {time.perf_counter() - t0:.1f}s\n")


if __name__ == "__main__":
    main()
