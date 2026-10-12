"""Verify the post-patch clamp algebra against the real engine sanitiser.

Claim A: a zero-width counter at `ask` is clamped to [a-floor, a], so the
         forced fill is a - ceil(floor/2) + shift, not a + shift.
Claim B: at floor width, ANY sub-floor collapse (at ask OR at bid) returns
         the CURRENT range unchanged, so the fill is exactly the midpoint
         we already predict -- i.e. nothing to exploit at floor width.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "quantstorm-ps"
sys.path.insert(0, str(REPO))

from engine import BotWrapper          # noqa: E402
from game_config import GameConfig, Obs  # noqa: E402

cfg = GameConfig()
w = BotWrapper(object(), "probe", cfg)


def obs_for(r):
    return Obs(seat=0, round=r, my_revealed=tuple([1] * (4 * r)), te_mine=24,
               te_theirs=24, spread_cap=cfg.spread_cap(r),
               final_cap=cfg.final_cap(r), is_maker=True,
               powers_mine=frozenset(), powers_theirs=frozenset(),
               auction_log=(), contracts=(), foresight=(),
               n_unknown_both=cfg.unknown_to_both(r), n_turns=cfg.N_TURNS)


print(f"{'r':>2} {'floor':>5} {'W':>3} {'range':>10} "
      f"{'collapse@ask':>14} {'fill':>6} {'he thinks':>10} {'err':>4}"
      f"  {'collapse@bid':>14} {'fill':>6}  {'midpoint':>9}")
for r in range(1, 6):
    o = obs_for(r)
    floor = o.final_cap
    for extra in (0, 1, 2):
        W = floor + extra
        b, a = 0, W
        at_ask = w._sanitise_response(("COUNTER", a, a), (b, a), o, 6)
        at_bid = w._sanitise_response(("COUNTER", b, b), (b, a), o, 6)
        f_ask = (at_ask[1] + at_ask[2]) // 2
        f_bid = (at_bid[1] + at_bid[2]) // 2
        mid = (b + a) // 2
        err = a - f_ask                       # his overstatement
        print(f"{r:>2} {floor:>5} {W:>3} {str((b, a)):>10} "
              f"{str(at_ask[1:]):>14} {f_ask:>6} {a:>10} {err:>4}"
              f"  {str(at_bid[1:]):>14} {f_bid:>6}  {mid:>9}")
