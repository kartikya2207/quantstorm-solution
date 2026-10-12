"""Measure the cost of the H3 Taker bug directly.

H3's Taker rule declines an acceptance whenever
    ev_force <= best_acc < ev_force + ACCEPT_MARGIN
(the "band"), because it treats the forced fill as a fallback it controls.
H4 accepts there instead. Since H4 differs from H3 in nothing else, the
realised PnL difference on identical seeds IS the realised cost of exactly
those decisions.

This harness counts band events by instrumenting H3's respond in-process,
and reports the per-match event rate alongside the paired PnL delta.
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "quantstorm-ps"
sys.path.insert(0, str(REPO))

from bot_loader import load_bot_class          # noqa: E402
from engine import play_match                  # noqa: E402
from game_config import GameConfig             # noqa: E402

WORK = Path(__file__).resolve().parent
EVENTS = []          # (best_acc, ev_force, round, is_maker)


def instrument(cls):
    """Wrap _respond_v2 so every band-hit is recorded, without changing play."""
    orig = cls._respond_v2

    def probed(self, obs, quote, turn):
        try:
            bid, ask = int(quote[0]), int(quote[1])
            v = self._value(obs, quote)
            ev_buy = v - ask
            ev_sell = bid - v
            best_acc = max(ev_buy, ev_sell)
            ev_force = self._forced_fill_ev(obs, bid, ask, v)
            margin = 0.5
            last = (turn == obs.n_turns)
            if (not obs.is_maker) and (not last):
                lo = max(ev_force, 0.0)
                if lo <= best_acc < lo + margin:
                    EVENTS.append((best_acc, ev_force, obs.round, turn))
        except Exception:
            pass
        return orig(self, obs, quote, turn)

    cls._respond_v2 = probed
    return cls


def main() -> None:
    opp_path = sys.argv[1] if len(sys.argv) > 1 else str(WORK / "vedant_v1.py")
    n_seeds = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    config = GameConfig()

    H3 = instrument(load_bot_class(WORK / "H3_tight.py", strict=False))
    OPP = load_bot_class(Path(opp_path), strict=False)

    h3_pnl = []
    for seed in range(40000, 40000 + n_seeds):
        r = play_match(H3, OPP, config, seed=seed, mirror=True,
                       n_deals=10, verbose=False)
        h3_pnl.append(r.pnl[0])

    matches = len(h3_pnl)
    print(f"\n  BAND PROBE — H3 vs {Path(opp_path).stem}, {matches} matches "
          f"({matches * 20} deals)")
    print(f"  {'-' * 60}")
    print(f"  band events (H3 declined a legal accept): {len(EVENTS)}")
    print(f"  per match: {len(EVENTS) / matches:.2f}   "
          f"per deal: {len(EVENTS) / (matches * 20):.3f}")
    if EVENTS:
        accs = [e[0] for e in EVENTS]
        print(f"  edge declined  mean {statistics.mean(accs):+.2f}   "
              f"max {max(accs):+.2f}   min {min(accs):+.2f}")
        big = [a for a in accs if a > 10]
        print(f"  events with edge > 10 ticks: {len(big)} "
              f"({100 * len(big) / len(EVENTS):.0f}%)")
        by_round = {}
        for _, _, rnd, _ in EVENTS:
            by_round[rnd] = by_round.get(rnd, 0) + 1
        print(f"  by round: {dict(sorted(by_round.items()))}")
    print(f"  H3 mean PnL/match: {statistics.mean(h3_pnl):+.2f}")
    print()


if __name__ == "__main__":
    main()
