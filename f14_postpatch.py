# Name: Kartikya
# College: IIT Bombay
# Roll Number: 24B4519
# TRACK C — the POST-PATCH modal bot: what an AI writes for a student who
# pasted the PATCHED repo (README 8:55 PM, sanitisation fix) and asked for a
# good bot. Differences from the pre-patch modal bot, all of them things the
# new rulebook text now makes obvious:
#   * knows a floor-width range is immovable, so as Maker it opens AT the
#     floor deliberately ("take it or leave it")
#   * knows the Taker pays 2.0 on a forced fill, so as Taker it NEVER rides
#     to turn 6 — it takes the better side instead
#   * when it does not want to trade mid-negotiation it repeats the market
#     explicitly (the new legal no-op) instead of emitting a sub-floor width
#   * still latches the maker's opening midpoint as its estimate of their
#     revealed sum, and still bids the 0.60 schedule — the patch gave an AI
#     no reason to change either.

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
    name = "F14PostPatch"

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
            out[name] = max(0, min(int(v / self.config.TE_SALVAGE * SHADE),
                                   obs.te_mine))
        return out

    def quote(self, obs):
        # Floor width: post-patch this range cannot be moved by the Taker.
        v = round(obs.k_mine + (self._leak or 0))
        w = obs.final_cap
        lo = v - w // 2
        return (lo, lo + w)

    def respond(self, obs, quote, turn):
        bid, ask = quote
        v = self._value(obs, quote)
        edge_buy = v - ask
        edge_sell = bid - v

        if not obs.is_maker and turn == obs.n_turns:
            # Never ride: the forced fill costs the Taker 2.0 and puts it
            # short at the midpoint. Take the better side instead.
            return "ACCEPT_BUY" if edge_buy >= edge_sell else "ACCEPT_SELL"

        if edge_buy > 0 and edge_buy >= edge_sell:
            return "ACCEPT_BUY"
        if edge_sell > 0:
            return "ACCEPT_SELL"

        w = ask - bid
        if w <= obs.final_cap:
            return ("COUNTER", bid, ask)      # explicit legal repeat
        nw = w - self.config.MIN_REDUCTION
        centre = max(bid, min(round(v) - nw // 2, ask - nw))
        return ("COUNTER", centre, centre + nw)

    def use_transform(self, obs):
        return abs(obs.k_mine) <= 1
