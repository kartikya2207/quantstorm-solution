"""rr5.py — round robin among v2, C1, C5, C7, C8 (same paired seed set)."""

from __future__ import annotations

import argparse
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sweep import ParseError, run_one

WORK = Path(__file__).resolve().parent
BOTS = [
    ("v2", WORK / "v2_endgame.py"),
    ("C1", WORK / "C1_estimator.py"),
    ("C5", WORK / "C5_ai_beater.py"),
    ("C7", WORK / "C7_adaptive.py"),
    ("C8", WORK / "C8_portfolio.py"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=60)
    ap.add_argument("--start-seed", type=int, default=9000)
    ap.add_argument("--n_deals", type=int, default=10)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args()

    seeds = list(range(args.start_seed, args.start_seed + args.seeds))
    names = [n for n, _ in BOTS]
    paths = {n: str(p) for n, p in BOTS}
    pairs = [(a, b) for i, a in enumerate(names) for b in names[i + 1:]]

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futs = {}
        for a, b in pairs:
            for s in seeds:
                futs[(a, b, s)] = pool.submit(run_one, paths[a], paths[b], s,
                                              args.n_deals, False)
        acc = {p: [] for p in pairs}
        for (a, b, s), fut in futs.items():
            acc[(a, b)].append(fut.result())
    mean_ab = {p: statistics.mean(v) for p, v in acc.items()}

    def cell(r, c):
        if r == c:
            return 0.0
        return mean_ab[(r, c)] if (r, c) in mean_ab else -mean_ab[(c, r)]

    print(f"\n  ROUND ROBIN — {len(names)} bots, {args.seeds} paired seeds "
          f"({seeds[0]}..{seeds[-1]})")
    print("        " + "".join(f"{c:>9s}" for c in names) + f"{'TOTAL':>11s}")
    for r in names:
        row = [cell(r, c) for c in names]
        print(f"  {r:>4s}  " + "".join(f"{v:+9.1f}" for v in row)
              + f"{sum(row):+11.1f}")
    print(f"\n  wall time: {time.perf_counter() - t0:.1f}s\n")


if __name__ == "__main__":
    main()
