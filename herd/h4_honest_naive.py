# Name: Kartikya
# College: IIT Bombay
# Roll Number: 24B4519
# (herd bot h4: the "LLM derives the proper scoring rule" bot — honest centre,
#  floor width, naive posterior mean E[S|mine] = k_mine, never bids)

import random


class Bot:
    name = "H4HonestNaive"

    def reset(self, seat, config, seed):
        self.seat = seat
        self.config = config
        self.rng = random.Random(seed)

    def bid(self, obs, offered):
        return {}

    def quote(self, obs):
        v = round(obs.k_mine + sum(obs.foresight))
        cap = obs.final_cap
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
