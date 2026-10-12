# Name: Kartikya
# College: IIT Bombay
# Roll Number: 24B4519
# (herd bot h6: my Step-0(c) prediction of the sharpest COMMON variant — the
#  clone plus persisted foresight plus a crude turn-6 fee check with NO shift
#  awareness. This is what "improve the endgame" gets a student.)

import random


POWER_VALUES = {
    "FORESIGHT":    {1: 0.76, 2: 1.16, 3: 1.48, 4: 1.97, 5: 2.02},
    "TRICK_ROOM":   {1: 1.14, 2: 0.00, 3: 0.00, 4: 0.60, 5: 0.52},
    "SUBSTITUTE":   {1: 1.46, 2: 1.15, 3: 0.95, 4: 0.57, 5: 0.29},
    "STEALTH_ROCK": {1: 1.51, 2: 0.75, 3: 0.75, 4: 0.75, 5: 0.00},
    "TRANSFORM":    {1: 1.58, 2: 1.24, 3: 1.31, 4: 0.00, 5: 0.00},
}

SHADE = 0.60


class Bot:
    name = "H6MyModal"

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
            anchor = 0.5 * anchor + 0.5 * self._leak
        return float(anchor + obs.k_mine)

    def bid(self, obs, offered):
        if not offered or obs.te_mine <= 0:
            return {}
        out = {}
        for name in offered:
            v = POWER_VALUES.get(name, {}).get(obs.round, 0.5)
            if name == "TRANSFORM" and abs(obs.k_mine) > 1:
                v = 0.0
            if v <= 0:
                continue
            out[name] = max(0, min(int(v / self.config.TE_SALVAGE * SHADE), obs.te_mine))
        return out

    def quote(self, obs):
        v = round(obs.k_mine + sum(obs.foresight))
        cap = obs.final_cap
        lo = v - cap // 2
        return (lo, lo + cap)

    def respond(self, obs, quote, turn):
        bid, ask = quote
        v = self._value(obs, quote)
        edge_buy = v - ask
        edge_sell = bid - v

        # Crude last-turn awareness: don't counter into the fee blindly.
        if turn == obs.n_turns and not obs.is_maker:
            mid = (bid + ask) // 2
            ev_force = (mid - v) - 2.0          # no shift awareness
            best = max(edge_buy, edge_sell, ev_force)
            if best == edge_buy:
                return "ACCEPT_BUY"
            if best == edge_sell:
                return "ACCEPT_SELL"
            w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
            return ("COUNTER", bid + ((ask - bid) - w), ask)

        if edge_buy > 0 and edge_buy >= edge_sell:
            return "ACCEPT_BUY"
        if edge_sell > 0:
            return "ACCEPT_SELL"
        w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
        center = max(bid, min(round(v), ask - w))
        return ("COUNTER", center, center + w)

    def use_transform(self, obs):
        return abs(obs.k_mine) <= 1
