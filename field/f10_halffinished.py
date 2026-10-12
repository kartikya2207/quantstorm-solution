# Name: Kartikya
# College: IIT Bombay
# Roll Number: 24B4519
# STUDENT PROMPT: "help me get started with the template" — and then the
# student ran out of time and submitted the barely-modified starter bot:
# bid() still returns {}, respond() is the docstring example.

import random


class Bot:
    name = "F10HalfDone"

    def reset(self, seat, config, seed):
        self.seat = seat
        self.config = config
        self.rng = random.Random(seed)

    def bid(self, obs, offered):
        # TODO: implement bidding strategy
        return {}

    def quote(self, obs):
        v = obs.k_mine
        cap = obs.spread_cap
        return (v - cap // 2, v + (cap - cap // 2))

    def respond(self, obs, quote, turn):
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
        return abs(obs.k_mine) <= 1
