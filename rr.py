"""
rr.py — full round robin among candidates + v2_endgame + the herd.

Every pair plays the SAME seed set (paired), mirroring tournament scoring:
each bot's total = sum of its mean PnL across all opponents.

Usage: python rr.py [--seeds 40] [--start-seed 2000] [--n_deals 10] [--jobs N]
"""

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
    ("C1",   WORK / "C1_estimator.py"),
    ("C2",   WORK / "C2_endgame_exact.py"),
    ("C3",   WORK / "C3_full.py"),
    ("C4",   WORK / "C4_full_jitter.py"),
    ("C5",   WORK / "C5_ai_beater.py"),
    ("v2",   WORK / "v2_endgame.py"),
    ("h1",   WORK / "herd" / "h1_clone.py"),
    ("h2",   WORK / "herd" / "h2_clone_tweaked.py"),
    ("h3",   WORK / "herd" / "h3_clone_aggro.py"),
    ("h4",   WORK / "herd" / "h4_honest_naive.py"),
    ("h5",   WORK / "herd" / "h5_endgame_aware.py"),
    ("h6",   WORK / "herd" / "h6_my_modal.py"),
    ("h7",   WORK / "herd" / "h7_broken.py"),
]

HERD_WEIGHTS = {"h1": 0.20, "h2": 0.15, "h3": 0.10, "h4": 0.15,
                "h5": 0.15, "h6": 0.15, "h7": 0.10}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=40)
    ap.add_argument("--start-seed", type=int, default=2000)
    ap.add_argument("--n_deals", type=int, default=10)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args()

    seeds = list(range(args.start_seed, args.start_seed + args.seeds))
    names = [n for n, _ in BOTS]
    paths = {n: str(p) for n, p in BOTS}

    pairs = [(a, b) for i, a in enumerate(names) for b in names[i + 1:]]
    t0 = time.perf_counter()
    mean_ab: dict[tuple[str, str], float] = {}

    try:
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futs = {}
            for a, b in pairs:
                for s in seeds:
                    futs[(a, b, s)] = pool.submit(
                        run_one, paths[a], paths[b], s, args.n_deals, False)
            acc: dict[tuple[str, str], list[float]] = {p: [] for p in pairs}
            for (a, b, s), fut in futs.items():
                acc[(a, b)].append(fut.result())
        for p, vals in acc.items():
            mean_ab[p] = statistics.mean(vals)
    except ParseError as e:
        import sys
        print(f"PARSE FAILURE: {e}", file=sys.stderr)
        print(e.raw, file=sys.stderr)
        raise SystemExit(2)

    # Matrix: cell[r][c] = mean PnL of row bot vs column bot (antisymmetric).
    def cell(r, c):
        if r == c:
            return 0.0
        return mean_ab[(r, c)] if (r, c) in mean_ab else -mean_ab[(c, r)]

    print(f"\n  ROUND ROBIN — {len(names)} bots, {args.seeds} paired seeds "
          f"({seeds[0]}..{seeds[-1]}), n_deals={args.n_deals}")
    print("  (cell = row bot's mean PnL per match vs column bot)\n")
    hdr = "        " + "".join(f"{c:>8s}" for c in names)
    print(hdr)
    totals = {}
    for r in names:
        row = [cell(r, c) for c in names]
        totals[r] = sum(row)
        print(f"  {r:>5s} " + "".join(f"{v:+8.1f}" for v in row))

    print("\n  TOTALS (sum of mean PnL across all opponents — tournament scoring):")
    for rank, (n, t) in enumerate(sorted(totals.items(), key=lambda kv: -kv[1]), 1):
        print(f"   {rank:2d}. {n:>5s}  {t:+10.1f}")

    print("\n  WEIGHTED-HERD SCORE (candidates only, from the same matrix):")
    wh = {}
    for n in ("C1", "C2", "C3", "C4", "C5", "v2"):
        wh[n] = sum(HERD_WEIGHTS[h] * cell(n, h) for h in HERD_WEIGHTS)
    for rank, (n, t) in enumerate(sorted(wh.items(), key=lambda kv: -kv[1]), 1):
        print(f"   {rank:2d}. {n:>5s}  {t:+10.2f}")

    print(f"\n  wall time: {time.perf_counter() - t0:.1f}s\n")


if __name__ == "__main__":
    main()
