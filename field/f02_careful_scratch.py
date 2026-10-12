# Name: Kartikya
# College: IIT Bombay
# Roll Number: 24B4519
# STUDENT PROMPT: "I read the whole rulebook. Write a bot from scratch: quote
# honestly at the floor (the obligation is a proper scoring rule so honesty is
# free), don't pay the forcing fee on the last turn, and only buy FORESIGHT in
# the late rounds when it shows the most coins."
# -> careful reader, no reference-bot anchoring, flat late FORESIGHT bids,
#    crude last-turn fee avoidance without shift awareness.

import random


class Bot:
    name = "F02Careful"

    def reset(self, seat, config, seed):
        self.seat = seat
        self.config = config
        self.rng = random.Random(seed)
        self.opp_mid = None

    def bid(self, obs, offered):
        out = {}
        if "FORESIGHT" in offered and obs.round >= 3 and obs.te_mine >= 6:
            out["FORESIGHT"] = 6
        return out

    def quote(self, obs):
        v = round(obs.k_mine + sum(obs.foresight))
        w = obs.final_cap
        return (v - w // 2, v - w // 2 + w)

    def _estimate(self, obs, quote, turn):
        # First quote I see as Taker is the maker's honest centre.
        if not obs.is_maker and turn == 2:
            self.opp_mid = (quote[0] + quote[1]) / 2
        est = obs.k_mine + sum(obs.foresight)
        if self.opp_mid is not None:
            est += self.opp_mid
        return est

    def respond(self, obs, quote, turn):
        bid, ask = quote
        v = self._estimate(obs, quote, turn)

        if turn == obs.n_turns and not obs.is_maker:
            # Last turn: countering costs the 2-tick fee and makes me the
            # seller at the midpoint. Just take the better side.
            if (v - ask) >= (bid - v):
                return "ACCEPT_BUY"
            return "ACCEPT_SELL"

        if v > ask + 1:
            return "ACCEPT_BUY"
        if v < bid - 1:
            return "ACCEPT_SELL"
        w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
        center = max(bid, min(round(v), ask - w))
        return ("COUNTER", center, center + w)

    def use_transform(self, obs):
        # A decisive hand is valuable; only swap away a flat one.
        return abs(obs.k_mine) <= 1
