# Name: Kartikya
# College: IIT Bombay
# Roll Number: 24B4519
# STUDENT PROMPT: "powers seem really strong, make sure we win the auctions"
# -> bids 1.2x the table (above fair value), naive pricing otherwise.

import random

POWER_VALUES = {
    "FORESIGHT":    {1: 0.76, 2: 1.16, 3: 1.48, 4: 1.97, 5: 2.02},
    "TRICK_ROOM":   {1: 1.14, 2: 0.00, 3: 0.00, 4: 0.60, 5: 0.52},
    "SUBSTITUTE":   {1: 1.46, 2: 1.15, 3: 0.95, 4: 0.57, 5: 0.29},
    "STEALTH_ROCK": {1: 1.51, 2: 0.75, 3: 0.75, 4: 0.75, 5: 0.00},
    "TRANSFORM":    {1: 1.58, 2: 1.24, 3: 1.31, 4: 0.00, 5: 0.00},
}
SHADE = 1.20


class Bot:
    name = "F07Overbid"

    def reset(self, seat, config, seed):
        self.seat = seat
        self.config = config
        self.rng = random.Random(seed)

    def bid(self, obs, offered):
        if not offered or obs.te_mine <= 0:
            return {}
        out = {}
        for name in offered:
            v = POWER_VALUES.get(name, {}).get(obs.round, 0.5)
            if v <= 0:
                continue
            out[name] = max(0, min(int(v / self.config.TE_SALVAGE * SHADE), obs.te_mine))
        return out

    def quote(self, obs):
        v = round(obs.k_mine + sum(obs.foresight))
        cap = obs.spread_cap
        lo = v - cap // 2
        return (lo, lo + cap)

    def respond(self, obs, quote, turn):
        bid, ask = quote
        v = obs.k_mine + sum(obs.foresight)
        if v > ask:
            return "ACCEPT_BUY"
        if v < bid:
            return "ACCEPT_SELL"
        w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
        center = max(bid, min(round(v), ask - w))
        return ("COUNTER", center, center + w)

    def use_transform(self, obs):
        return abs(obs.k_mine) <= 1
