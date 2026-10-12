# Name: Kartikya
# College: IIT Bombay
# Roll Number: 24B4519
# (throwaway test opponent: a poisoning DEFENDER. Re-anchors on every quote
#  it sees, clamps the anchor to the plausible range of the maker's revealed
#  sum, and blends it with the prior — so an absurd bracket moves its
#  estimate only slightly, and it happily punishes inflated/deflated quotes
#  by trading against them.)

import random


class Bot:
    name = "F13Defender"

    def reset(self, seat, config, seed):
        self.seat = seat
        self.config = config
        self.rng = random.Random(seed)
        self.anchor = 0.0

    def _update_anchor(self, obs, quote):
        mid = (quote[0] + quote[1]) / 2.0
        bound = 4 * obs.round          # |their revealed sum| cannot exceed 4r
        clamped = max(-bound, min(mid, bound))
        # Blend with the zero prior: an implausible quote barely moves us.
        self.anchor = 0.6 * clamped if abs(mid) <= bound else 0.2 * clamped

    def _value(self, obs, quote=None):
        if quote is not None and not obs.is_maker:
            self._update_anchor(obs, quote)
        v = obs.k_mine + self.anchor
        if obs.foresight:
            v = obs.k_mine + 0.5 * self.anchor + 0.5 * sum(obs.foresight)
        return float(v)

    def bid(self, obs, offered):
        out = {}
        for name in offered:
            if name in ("FORESIGHT", "SUBSTITUTE") and obs.te_mine >= 5:
                out[name] = 5
                break
        return out

    def quote(self, obs):
        v = round(obs.k_mine + self.anchor)
        w = obs.final_cap
        return (v - w // 2, v - w // 2 + w)

    def respond(self, obs, quote, turn):
        bid, ask = quote
        v = self._value(obs, quote)
        edge_buy = v - ask
        edge_sell = bid - v

        if turn == obs.n_turns and not obs.is_maker:
            mid = (bid + ask) // 2
            ev_force = (mid - v) - 2.0
            best = max(edge_buy, edge_sell, ev_force)
            if best == edge_buy:
                return "ACCEPT_BUY"
            if best == edge_sell:
                return "ACCEPT_SELL"
            w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
            return ("COUNTER", bid + ((ask - bid) - w), ask)

        if edge_buy > 0.5 and edge_buy >= edge_sell:
            return "ACCEPT_BUY"
        if edge_sell > 0.5:
            return "ACCEPT_SELL"
        w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
        center = max(bid, min(round(v), ask - w))
        return ("COUNTER", center, center + w)

    def use_transform(self, obs):
        return abs(obs.k_mine) <= 1
