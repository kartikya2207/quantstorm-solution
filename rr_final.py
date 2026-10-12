"""rr_final.py — final selection round robin.

Every candidate + every opponent, all pairs, the SAME paired seed set for
every pairing. Score = total PnL summed over all opponents, which is the
tournament's actual metric. Also prints each candidate's mean against the
12-bot independent field and against the 7-bot herd.

Usage: python rr_final.py [--seeds 40] [--start-seed 20000] [--jobs N]
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

CANDIDATES = [
    ("B4", WORK / "B4_width.py"),        # incumbent
    ("G1", WORK / "G1_shade.py"),
    ("D1", WORK / "D1_acceptev.py"),
    ("H1", WORK / "H1_g1d1.py"),
    ("H2", WORK / "H2_stack.py"),
    ("H3", WORK / "H3_tight.py"),
    ("H4", WORK / "H4_takerfix.py"),
    ("C7", WORK / "C7_adaptive.py"),     # control
    ("C9", WORK / "C9_shielded.py"),     # control
]

HERD = [(f"h{i}", p) for i, p in enumerate(sorted((WORK / "herd").glob("*.py")), 1)]
FIELD = [(f"f{i:02d}", p) for i, p in enumerate(sorted((WORK / "field").glob("*.py")), 1)]
EXTRA = [
    ("fD", WORK / "f13_defender.py"),
    ("f14", WORK / "f14_postpatch.py"),
    ("VED", WORK / "vedant_v1.py"),      # real competitor entry
    ("x1", WORK / "x1_sched12.py"),
    ("x2", WORK / "x2_randbid.py"),
]

OPPONENTS = HERD + FIELD + EXTRA
ALL = CANDIDATES + OPPONENTS


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=40)
    ap.add_argument("--start-seed", type=int, default=20000)
    ap.add_argument("--n_deals", type=int, default=10)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args()

    seeds = list(range(args.start_seed, args.start_seed + args.seeds))
    names = [n for n, _ in ALL]
    paths = {n: str(p) for n, p in ALL}
    pairs = [(a, b) for i, a in enumerate(names) for b in names[i + 1:]]

    t0 = time.perf_counter()
    print(f"  {len(names)} bots, {len(pairs)} pairings, {args.seeds} paired seeds "
          f"({seeds[0]}..{seeds[-1]}) = {len(pairs) * args.seeds} matches", flush=True)

    try:
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futs = {}
            for a, b in pairs:
                for s in seeds:
                    futs[(a, b, s)] = pool.submit(run_one, paths[a], paths[b],
                                                  s, args.n_deals, False)
            acc = {p: [] for p in pairs}
            for (a, b, s), fut in futs.items():
                acc[(a, b)].append(fut.result())
    except ParseError as e:
        import sys
        print(f"PARSE FAILURE: {e}", file=sys.stderr)
        print(e.raw, file=sys.stderr)
        raise SystemExit(2)

    mean_ab = {p: statistics.mean(v) for p, v in acc.items()}

    def cell(r, c):
        if r == c:
            return 0.0
        return mean_ab[(r, c)] if (r, c) in mean_ab else -mean_ab[(c, r)]

    cnames = [n for n, _ in CANDIDATES]
    onames = [n for n, _ in OPPONENTS]
    fnames = [n for n, _ in FIELD]
    hnames = [n for n, _ in HERD]

    print(f"\n  CANDIDATE x OPPONENT (mean PnL per match)\n")
    print("        " + "".join(f"{o:>8s}" for o in onames))
    for c in cnames:
        print(f"  {c:>4s}  " + "".join(f"{cell(c, o):+8.1f}" for o in onames))

    print(f"\n  CANDIDATE x CANDIDATE\n")
    print("        " + "".join(f"{c:>8s}" for c in cnames))
    for r in cnames:
        print(f"  {r:>4s}  " + "".join(f"{cell(r, c):+8.1f}" for c in cnames))

    print(f"\n  {'bot':>5s} {'RR TOTAL':>11s} {'field mean':>12s} {'herd mean':>11s} "
          f"{'worst opp':>12s}")
    rows = []
    for c in cnames:
        total = sum(cell(c, x) for x in names if x != c)
        fm = statistics.mean([cell(c, f) for f in fnames])
        hm = statistics.mean([cell(c, h) for h in hnames])
        worst_o = min(onames, key=lambda o: cell(c, o))
        rows.append((total, c, fm, hm, worst_o, cell(c, worst_o)))
    for total, c, fm, hm, wo, wv in sorted(rows, reverse=True):
        print(f"  {c:>5s} {total:+11.1f} {fm:+12.2f} {hm:+11.2f} "
              f"{wo:>7s} {wv:+5.1f}")

    print(f"\n  wall time: {time.perf_counter() - t0:.1f}s\n")


if __name__ == "__main__":
    main()
