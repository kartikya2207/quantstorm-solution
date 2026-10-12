"""How often do rounds actually reach a forced fill against a given opponent,
and how often are we the Maker (long, fee-receiving) when they do?"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "quantstorm-ps"
sys.path.insert(0, str(REPO))

from bot_loader import load_bot_class      # noqa: E402
from engine import play_match              # noqa: E402
from game_config import GameConfig         # noqa: E402

WORK = Path(__file__).resolve().parent
cfg = GameConfig()

ours = load_bot_class(WORK / "FINAL_SUBMISSION.py", strict=False)
for opp_name in sys.argv[1:]:
    opp = load_bot_class(Path(opp_name) if Path(opp_name).exists()
                         else WORK / opp_name, strict=False)
    tot = forced = we_long = late = 0
    for seed in range(40000, 40020):
        res = play_match(ours, opp, cfg, seed=seed, mirror=True,
                         n_deals=10, verbose=False)
        for deal in res.deals:
            for c in deal.contracts:
                tot += 1
                if c.forced:
                    forced += 1
                    if c.long_seat == 0:
                        we_long += 1
                    if c.round >= 3:
                        late += 1
    print(f"\n  {Path(opp_name).stem}: {tot} contracts over 20 matches")
    print(f"    forced fills      : {forced} ({100*forced/tot:.1f}%)")
    print(f"    ...we were long   : {we_long}")
    print(f"    ...in rounds 3-5  : {late}   (the only rounds worth +1 to us)")
    print(f"    upper-bound gain  : {late} ticks over 20 matches = "
          f"{late/20:.2f} PnL/match")
