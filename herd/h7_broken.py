# Name: Kartikya
# College: IIT Bombay
# Roll Number: 24B4519
# (herd bot h7: the broken tail — starter-bot-level logic that occasionally
#  returns garbage so the engine fallbacks fire: over-budget bids get zeroed,
#  bad respond strings become ACCEPT_BUY, bad quotes take the default.)

import random


class Bot:
    name = "H7Broken"

    def reset(self, seat, config, seed):
        self.seat = seat
        self.config = config
        self.rng = random.Random(seed)

    def bid(self, obs, offered):
        r = self.rng.random()
        if r < 0.20:
            # over-budget vector -> engine zeroes every bid
            return {name: obs.te_mine + 5 for name in offered}
        if r < 0.35:
            return {}
        return {name: 4 for name in offered}

    def quote(self, obs):
        if self.rng.random() < 0.10:
            return "oops"            # -> engine default quote
        v = obs.k_mine
        cap = obs.spread_cap
        return (v - cap // 2, v - cap // 2 + cap)

    def respond(self, obs, quote, turn):
        if self.rng.random() < 0.15:
            return "HOLD"            # -> engine falls back to ACCEPT_BUY
        bid, ask = quote
        v = obs.k_mine
        if v > ask:
            return "ACCEPT_BUY"
        if v < bid:
            return "ACCEPT_SELL"
        w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
        center = max(bid, min(round(v), ask - w))
        return ("COUNTER", center, center + w)

    def use_transform(self, obs):
        return self.rng.random() < 0.5
