# Name: Kartikya
# College: IIT Bombay
# Roll Number: 24B4519
# STUDENT PROMPT: "add some randomness so opponents can't predict us"
# -> random bids 0-10, randomised accept threshold, clone-ish core.

import random


class Bot:
    name = "F08Random"

    def reset(self, seat, config, seed):
        self.seat = seat
        self.config = config
        self.rng = random.Random(seed)
        self._anchor = {}

    def _get_anchor(self, obs, quote):
        r = obs.round
        if r not in self._anchor:
            if not obs.is_maker and quote is not None:
                self._anchor[r] = (quote[0] + quote[1]) / 2
            else:
                self._anchor[r] = 0.0
        return self._anchor[r]

    def _value(self, obs, quote=None):
        if obs.is_maker or quote is None:
            return float(obs.k_mine + sum(obs.foresight))
        anchor = self._get_anchor(obs, quote)
        if obs.foresight:
            anchor = 0.5 * anchor + 0.5 * sum(obs.foresight)
        return float(anchor + obs.k_mine)

    def bid(self, obs, offered):
        out = {}
        te = obs.te_mine
        for name in offered:
            amt = min(self.rng.randint(0, 10), te)
            if amt > 0:
                out[name] = amt
                te -= amt
        return out

    def quote(self, obs):
        v = round(obs.k_mine + sum(obs.foresight))
        cap = obs.final_cap if self.rng.random() < 0.5 else obs.spread_cap
        lo = v - cap // 2
        return (lo, lo + cap)

    def respond(self, obs, quote, turn):
        bid, ask = quote
        v = self._value(obs, quote)
        t = self.rng.uniform(0.0, 2.0)
        if (v - ask) > t and (v - ask) >= (bid - v):
            return "ACCEPT_BUY"
        if (bid - v) > t:
            return "ACCEPT_SELL"
        w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
        center = max(bid, min(round(v), ask - w))
        return ("COUNTER", center, center + w)

    def use_transform(self, obs):
        return self.rng.random() < 0.4
