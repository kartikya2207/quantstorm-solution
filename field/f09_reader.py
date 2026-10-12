# Name: Kartikya
# College: IIT Bombay
# Roll Number: 24B4519
# STUDENT PROMPT: "rational.py reads the opponent's quote — improve on that
# idea, weight the signals properly" (never touches the auction)
# -> 0.7/0.3 anchor-foresight blend, small positive accept threshold, floor
#    width quotes, never bids.

import random


class Bot:
    name = "F09Reader"

    def reset(self, seat, config, seed):
        self.seat = seat
        self.config = config
        self.rng = random.Random(seed)
        self._anchor = {}
        self._leak = None

    def _get_anchor(self, obs, quote):
        r = obs.round
        if r not in self._anchor:
            if not obs.is_maker and quote is not None:
                self._anchor[r] = (quote[0] + quote[1]) / 2
            else:
                self._anchor[r] = 0.0
        return self._anchor[r]

    def _value(self, obs, quote=None):
        if obs.foresight:
            self._leak = sum(obs.foresight)
        if obs.is_maker or quote is None:
            return float(obs.k_mine + (self._leak or 0))
        anchor = self._get_anchor(obs, quote)
        if self._leak is not None:
            anchor = 0.7 * anchor + 0.3 * self._leak
        return float(anchor + obs.k_mine)

    def bid(self, obs, offered):
        return {}

    def quote(self, obs):
        v = round(obs.k_mine + (self._leak or 0))
        w = obs.final_cap
        return (v - w // 2, v - w // 2 + w)

    def respond(self, obs, quote, turn):
        bid, ask = quote
        v = self._value(obs, quote)
        if (v - ask) > 0.5 and (v - ask) >= (bid - v):
            return "ACCEPT_BUY"
        if (bid - v) > 0.5:
            return "ACCEPT_SELL"
        w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
        center = max(bid, min(round(v), ask - w))
        return ("COUNTER", center, center + w)

    def use_transform(self, obs):
        return abs(obs.k_mine) <= 1
