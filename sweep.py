"""
sweep.py — multi-seed sweep harness for the Divided Oracle backtester.

Runs quantstorm-ps/backtester.py as a subprocess once per seed and aggregates
bot1's match-level PnL across seeds. Plain stdlib only.

Usage:
    python sweep.py --bot1 <path> --bot2 <path> [--seeds 50] [--start-seed 1000]
                    [--isolate] [--n_deals 10] [--jobs N]

    python sweep.py --compare <botA> <botB> --vs <opponent> [--seeds N] ...
        Runs BOTH bots against the same opponent on the SAME seed set and
        reports the paired difference (A minus B). Paired on identical seeds.

Parsing contract (from backtester.print_summary, backtester.py:142-149):
    print(f"  {'':20s} {'Aggregate':>12s} {'Mean/deal':>12s} {'Std Dev':>12s}")
    print(f"  {'-' * 56}")
    print(f"  {bot_a_name:20s} {result.pnl[0]:+12.2f} ...")   # <- bot1 row
    print(f"  {bot_b_name:20s} {result.pnl[1]:+12.2f} ...")   # <- bot2 row
We locate the header line containing all three column titles and read bot1's
aggregate PnL from the first float on the line two below it. If that fails on
any run, the raw output is printed and the sweep stops.
"""

from __future__ import annotations

import argparse
import math
import os
import re
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "quantstorm-ps"
BACKTESTER = REPO / "backtester.py"

# First signed float on a summary data row, e.g. "  KartikyaBot   +23.04 ..."
_ROW_FLOAT = re.compile(r"([+-]\d+(?:\.\d+)?)")


class ParseError(Exception):
    def __init__(self, msg: str, raw: str):
        super().__init__(msg)
        self.raw = raw


def run_one(bot1: str, bot2: str, seed: int, n_deals: int, isolate: bool) -> float:
    """Run one match; return bot1's aggregate PnL."""
    cmd = [
        sys.executable, "-B", str(BACKTESTER),
        "--bot1", bot1, "--bot2", bot2,
        "--seed", str(seed), "--n_deals", str(n_deals),
        "--quiet",
    ]
    if isolate:
        cmd.append("--isolate")

    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"   # never write __pycache__ into the repo
    env["PYTHONIOENCODING"] = "utf-8"      # backtester prints unicode glyphs

    proc = subprocess.run(
        cmd, cwd=str(REPO), env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    out = proc.stdout + ("\n--- stderr ---\n" + proc.stderr if proc.stderr.strip() else "")
    if proc.returncode != 0:
        raise ParseError(f"backtester exited {proc.returncode} on seed {seed}", out)

    lines = proc.stdout.splitlines()
    header = None
    for i, line in enumerate(lines):
        if "Aggregate" in line and "Mean/deal" in line and "Std Dev" in line:
            header = i
            break
    if header is None or header + 2 >= len(lines):
        raise ParseError(f"could not find MATCH SUMMARY table on seed {seed}", out)

    row = lines[header + 2]                 # header, dashes, then bot1's row
    m = _ROW_FLOAT.search(row)
    if not m:
        raise ParseError(f"could not parse bot1 PnL from row {row!r} on seed {seed}", out)
    return float(m.group(1))


def run_seeds(bot1: str, bot2: str, seeds: list[int], n_deals: int,
              isolate: bool, jobs: int) -> dict[int, float]:
    """Run all seeds in parallel; return {seed: bot1_pnl}, in seed order."""
    results: dict[int, float] = {}
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {
            seed: pool.submit(run_one, bot1, bot2, seed, n_deals, isolate)
            for seed in seeds
        }
        for seed in seeds:
            results[seed] = futures[seed].result()   # re-raises ParseError
    return results


def summarize(label: str, results: dict[int, float]) -> None:
    vals = list(results.values())
    n = len(vals)
    mean = statistics.mean(vals)
    stdev = statistics.stdev(vals) if n > 1 else 0.0
    stderr = stdev / math.sqrt(n) if n > 1 else 0.0
    lo, hi = mean - 1.96 * stderr, mean + 1.96 * stderr
    wins = sum(1 for v in vals if v > 0)
    losses = sum(1 for v in vals if v < 0)
    draws = n - wins - losses
    min_seed = min(results, key=results.get)
    max_seed = max(results, key=results.get)

    print(f"\n  {label}")
    print(f"  {'-' * 58}")
    print(f"  matches (seeds):    {n}")
    print(f"  mean PnL / match:   {mean:+10.3f}")
    print(f"  sample stdev:       {stdev:10.3f}")
    print(f"  standard error:     {stderr:10.3f}")
    print(f"  95% CI:             [{lo:+.3f}, {hi:+.3f}]")
    print(f"  record (W/D/L):     {wins}W / {draws}D / {losses}L")
    print(f"  min:                {results[min_seed]:+10.2f}  (seed {min_seed})")
    print(f"  max:                {results[max_seed]:+10.2f}  (seed {max_seed})")


def paired_compare(res_a: dict[int, float], res_b: dict[int, float],
                   name_a: str, name_b: str) -> None:
    seeds = list(res_a)
    diffs = [res_a[s] - res_b[s] for s in seeds]
    n = len(diffs)
    mean = statistics.mean(diffs)
    stdev = statistics.stdev(diffs) if n > 1 else 0.0
    stderr = stdev / math.sqrt(n) if n > 1 else 0.0
    lo, hi = mean - 1.96 * stderr, mean + 1.96 * stderr
    a_better = sum(1 for d in diffs if d > 0)
    b_better = sum(1 for d in diffs if d < 0)

    print(f"\n  PAIRED DIFFERENCE  ({name_a} minus {name_b}, same seeds)")
    print(f"  {'-' * 58}")
    print(f"  mean diff / match:  {mean:+10.3f}")
    print(f"  stderr of diff:     {stderr:10.3f}")
    print(f"  95% CI:             [{lo:+.3f}, {hi:+.3f}]")
    print(f"  seeds favouring:    {name_a}: {a_better}   {name_b}: {b_better}   "
          f"ties: {n - a_better - b_better}")
    if lo > 0:
        print(f"  VERDICT: {name_a} is BETTER — 95% CI excludes zero.")
    elif hi < 0:
        print(f"  VERDICT: {name_a} is WORSE — 95% CI excludes zero.")
    else:
        print(f"  VERDICT: NOT significant at 95% — CI includes zero. "
              f"More seeds or a real effect needed.")


def resolve_bot(path_str: str) -> str:
    """Make a bot path absolute so it survives the cwd change to the repo.

    Bare 'strategies/...' paths are resolved against the repo, matching how
    you would type them for backtester.py; everything else resolves against
    the caller's cwd.
    """
    p = Path(path_str)
    if p.exists():
        return str(p.resolve())
    rp = REPO / path_str
    if rp.exists():
        return str(rp.resolve())
    sys.exit(f"sweep.py: bot file not found: {path_str}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Multi-seed sweep for the Divided Oracle backtester")
    ap.add_argument("--bot1", type=str, default=None)
    ap.add_argument("--bot2", type=str, default=None)
    ap.add_argument("--compare", nargs=2, metavar=("BOT_A", "BOT_B"), default=None,
                    help="run two bots against --vs on the same seeds, report paired diff")
    ap.add_argument("--vs", type=str, default=None, help="opponent for --compare mode")
    ap.add_argument("--seeds", type=int, default=50)
    ap.add_argument("--start-seed", type=int, default=1000)
    ap.add_argument("--isolate", action="store_true")
    ap.add_argument("--n_deals", type=int, default=10)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args()

    if not BACKTESTER.exists():
        sys.exit(f"sweep.py: backtester not found at {BACKTESTER}")

    seeds = list(range(args.start_seed, args.start_seed + args.seeds))
    t0 = time.perf_counter()

    try:
        if args.compare:
            if not args.vs:
                sys.exit("sweep.py: --compare requires --vs <opponent>")
            bot_a = resolve_bot(args.compare[0])
            bot_b = resolve_bot(args.compare[1])
            opp = resolve_bot(args.vs)
            name_a, name_b = Path(bot_a).stem, Path(bot_b).stem

            print(f"  Comparing {name_a} vs {name_b}, both against {Path(opp).stem}")
            print(f"  seeds {seeds[0]}..{seeds[-1]}  n_deals={args.n_deals}"
                  f"  isolate={args.isolate}  jobs={args.jobs}")
            res_a = run_seeds(bot_a, opp, seeds, args.n_deals, args.isolate, args.jobs)
            res_b = run_seeds(bot_b, opp, seeds, args.n_deals, args.isolate, args.jobs)
            summarize(f"{name_a} vs {Path(opp).stem}", res_a)
            summarize(f"{name_b} vs {Path(opp).stem}", res_b)
            paired_compare(res_a, res_b, name_a, name_b)
        else:
            if not (args.bot1 and args.bot2):
                sys.exit("sweep.py: need --bot1 and --bot2 (or --compare A B --vs OPP)")
            bot1 = resolve_bot(args.bot1)
            bot2 = resolve_bot(args.bot2)
            print(f"  Sweeping {Path(bot1).stem} vs {Path(bot2).stem}")
            print(f"  seeds {seeds[0]}..{seeds[-1]}  n_deals={args.n_deals}"
                  f"  isolate={args.isolate}  jobs={args.jobs}")
            results = run_seeds(bot1, bot2, seeds, args.n_deals, args.isolate, args.jobs)
            summarize(f"{Path(bot1).stem} vs {Path(bot2).stem} (bot1's PnL)", results)
    except ParseError as e:
        print(f"\n  PARSE FAILURE: {e}", file=sys.stderr)
        print("  --- raw backtester output ---", file=sys.stderr)
        print(e.raw, file=sys.stderr)
        sys.exit(2)

    print(f"\n  total wall time: {time.perf_counter() - t0:.1f}s\n")


if __name__ == "__main__":
    main()
