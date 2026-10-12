# Name: Kartikya
# College: IIT Bombay
# Roll Number: 24B4519
# STUDENT PROMPT: "don't overthink the auction, just bid a constant on
# everything so we always have powers" (after asking for a basic bot)
# -> the classic flat-8 bidder with naive max-width quoting.

import random


class Bot:
    name = "F06Flat8"

    def reset(self, seat, config, seed):
        self.seat = seat
        self.config = config
        self.rng = random.Random(seed)

    def bid(self, obs, offered):
        out = {}
        te = obs.te_mine
        for name in offered:
            amt = min(8, te)
            if amt > 0:
                out[name] = amt
                te -= amt
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
