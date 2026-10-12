# Name: Kartikya
# College: IIT Bombay
# Roll Number: 24B4519
# STUDENT PROMPT: "be sneaky — quote a bit high so we sell above fair value,
# and lowball the auction"
# -> centres quotes +2 above its estimate (ignoring the maker obligation),
#    bids 0.4x the table, loose accepts.

import random

POWER_VALUES = {
    "FORESIGHT":    {1: 0.76, 2: 1.16, 3: 1.48, 4: 1.97, 5: 2.02},
    "TRICK_ROOM":   {1: 1.14, 2: 0.00, 3: 0.00, 4: 0.60, 5: 0.52},
    "SUBSTITUTE":   {1: 1.46, 2: 1.15, 3: 0.95, 4: 0.57, 5: 0.29},
    "STEALTH_ROCK": {1: 1.51, 2: 0.75, 3: 0.75, 4: 0.75, 5: 0.00},
    "TRANSFORM":    {1: 1.58, 2: 1.24, 3: 1.31, 4: 0.00, 5: 0.00},
}
SHADE = 0.40


class Bot:
    name = "F12Tricky"

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
        if not offered or obs.te_mine <= 0:
            return {}
        out = {}
        for name in offered:
            v = POWER_VALUES.get(name, {}).get(obs.round, 0.5)
            if v <= 0:
                continue
            amt = int(v / self.config.TE_SALVAGE * SHADE)
            if amt > 0:
                out[name] = min(amt, obs.te_mine)
        return out

    def quote(self, obs):
        v = round(obs.k_mine + sum(obs.foresight)) + 2   # "sell high"
        cap = obs.final_cap
        lo = v - cap // 2
        return (lo, lo + cap)

    def respond(self, obs, quote, turn):
        bid, ask = quote
        v = self._value(obs, quote)
        if (v - ask) > -0.5 and (v - ask) >= (bid - v):
            return "ACCEPT_BUY"
        if (bid - v) > -0.5:
            return "ACCEPT_SELL"
        w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
        center = max(bid, min(round(v), ask - w))
        return ("COUNTER", center, center + w)

    def use_transform(self, obs):
        return abs(obs.k_mine) <= 2
