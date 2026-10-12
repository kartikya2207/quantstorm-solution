# Name: Kartikya
# College: IIT Bombay
# Roll Number: 24B4519

"""
shift_camper.py — test opponent (not a submission).

Mimics a "shift camper": bids hard (6 TE) on TRICK_ROOM / STEALTH_ROCK and
rides negotiations to the forced midpoint fill to cash the shift. As Taker it
always counters through turn 6; as Maker it counters unless it sees more than
3 ticks of edge. Quotes honestly at maximum width to keep room to ride.
"""

import random


class Bot:
    name = "ShiftCamper"

    def reset(self, seat, config, seed):
        self.seat = seat
        self.config = config
        self.rng = random.Random(seed)

    def bid(self, obs, offered):
        out = {}
        te = obs.te_mine
        for name in offered:
            if name in ("TRICK_ROOM", "STEALTH_ROCK") and te > 0:
                amount = min(6, te)
                out[name] = amount
                te -= amount
        return out

    def quote(self, obs):
        v = round(obs.k_mine + sum(obs.foresight))
        cap = obs.spread_cap
        lo = v - cap // 2
        return (lo, lo + cap)

    def respond(self, obs, quote, turn):
        bid, ask = quote
        v = obs.k_mine + sum(obs.foresight)

        if obs.is_maker:
            if v - ask > 3:
                return "ACCEPT_BUY"
            if bid - v > 3:
                return "ACCEPT_SELL"

        # Otherwise: counter toward v with the minimum shrink (rides to fill)
        w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
        center = max(bid, min(round(v), ask - w))
        return ("COUNTER", center, center + w)

    def use_transform(self, obs):
        return abs(obs.k_mine) <= 1
