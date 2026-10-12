# Name: Kartikya
# College: IIT Bombay
# Roll Number: 24B4519

"""
my_bot.py — insurance submission (adaptive_bidder logic, verbatim)
==================================================================

Copied from quantstorm-ps/strategies/adaptive_bidder.py, which RULEBOOK §12
explicitly permits ("The code shipped in this repository ... is yours to copy
freely, constants included"). Only the metadata header and the display name
differ. Strategy notes below are from the original.

Core idea: Value each power based on the CURRENT game state, not
a fixed table. Shade bids at 0.60 of fair value (first-price auction).

Key mechanics:
  • Powers are bid at their calibrated tick value FOR THIS ROUND / te_salvage
  • Shading at 0.60 captures surplus in a first-price auction
  • Honest quoting at the tightest legal width, with full quote reading
  • TRANSFORM is bid from BOTH sides -- flat hand: win it and FIRE it;
    decisive hand: win it and DECLINE it (the power is consumed either way,
    so declining is a defence)
"""

import random
from math import sqrt


# Calibrated tick values per power AND PER ROUND (measured, not chosen).
# See adaptive_bidder.py for the measurement methodology: grant the power to
# one seat, in one round, free; both seats otherwise the same bot, so a
# mirrored match nets exactly zero and the residual IS the edge.
POWER_VALUES = {
    "FORESIGHT":    {1: 0.76, 2: 1.16, 3: 1.48, 4: 1.97, 5: 2.02},
    "TRICK_ROOM":   {1: 1.14, 2: 0.00, 3: 0.00, 4: 0.60, 5: 0.52},
    "SUBSTITUTE":   {1: 1.46, 2: 1.15, 3: 0.95, 4: 0.57, 5: 0.29},
    "STEALTH_ROCK": {1: 1.51, 2: 0.75, 3: 0.75, 4: 0.75, 5: 0.00},
    "TRANSFORM":    {1: 1.58, 2: 1.24, 3: 1.31, 4: 0.00, 5: 0.00},
}

#: Fraction of fair value to bid in a first-price auction.
SHADE = 0.60

#: How flat a revealed sum has to be before the hand is worth trading away.
FLAT_THRESHOLD = 1
#: How flat the OPPONENT has to look, by our read of their earlier quote,
#: before we will pay to keep our hand away from them.
OPP_FLAT_THRESHOLD = 2.0
#: What denial is worth when the read says the swap really is coming, as a
#: multiple of the swap's own value. Shipped at zero in the reference bot.
DENIAL_WEIGHT = 0.0


class Bot:
    name = "KartikyaBot"

    def reset(self, seat, config, seed):
        self.seat = seat
        self.config = config
        self.rng = random.Random(seed)
        self._anchor = {}
        self._opp_anchor = {}   # rounds where we read THEIR opening quote

    def _get_anchor(self, obs, quote):
        r = obs.round
        if r not in self._anchor:
            if not obs.is_maker and quote is not None:
                self._anchor[r] = (quote[0] + quote[1]) / 2
                self._opp_anchor[r] = self._anchor[r]
            else:
                self._anchor[r] = 0.0
        return self._anchor[r]

    def _opponent_k(self, obs):
        """Estimate the opponent's revealed sum from their earlier quote.

        An honest Maker centres its opening quote on its own revealed sum,
        so that midpoint IS the estimate. Only rounds where we were the
        Taker carry a reading; our own quotes tell us nothing new.
        """
        earlier = [k for k in self._opp_anchor if k < obs.round]
        if not earlier:
            return None
        return self._opp_anchor[max(earlier)]

    def _value(self, obs, quote=None):
        if obs.is_maker or quote is None:
            return float(obs.k_mine + sum(obs.foresight))
        anchor = self._get_anchor(obs, quote)
        if obs.foresight:
            anchor = 0.5 * anchor + 0.5 * sum(obs.foresight)
        return float(anchor + obs.k_mine)

    def _power_value(self, obs, name):
        """What `name` is worth in THIS round, in ticks.

        A power off the surface entirely falls back to 0.5 rather than to a
        confident number.
        """
        return POWER_VALUES.get(name, {}).get(obs.round, 0.5)

    def _transform_value(self, obs):
        """What winning TRANSFORM is worth to us right now, in ticks.

          flat hand           -> the swap itself, at full value
          decisive + no read  -> nothing
          decisive + they
          look flat too       -> denial, at DENIAL_WEIGHT x swap value
        """
        swap = self._power_value(obs, "TRANSFORM")
        if abs(obs.k_mine) <= FLAT_THRESHOLD:
            return swap

        opp_k = self._opponent_k(obs)
        if opp_k is not None and abs(opp_k) <= OPP_FLAT_THRESHOLD:
            return swap * DENIAL_WEIGHT
        return 0.0

    def bid(self, obs, offered):
        if not offered or obs.te_mine <= 0:
            return {}

        out = {}
        for name in offered:
            if name == "TRANSFORM":
                v = self._transform_value(obs)
            else:
                v = self._power_value(obs, name)

            if v <= 0:
                continue

            # Convert ticks to TE: fair_te = ticks / te_salvage
            fair_te = v / self.config.TE_SALVAGE
            bid_amount = max(0, min(int(fair_te * SHADE), obs.te_mine))
            out[name] = bid_amount

        return out

    def quote(self, obs):
        v = round(obs.k_mine + sum(obs.foresight))
        # Width stance: the FLOOR. Tightest legal opening -- pays no
        # width premium and collects the largest obligation payout when
        # it lands, at the cost of being crossable by someone who knows
        # more. Take-it-or-leave-it: there is nothing left to shrink.
        cap = obs.final_cap
        lo = v - cap // 2
        return (lo, lo + cap)

    def respond(self, obs, quote, turn):
        bid, ask = quote
        v = self._value(obs, quote)

        edge_buy = v - ask
        edge_sell = bid - v

        # SUBSTITUTE makes downside cheap — cross on thinner edge
        thresh = 0.0
        if "SUBSTITUTE" in obs.powers_mine:
            thresh -= 1.0

        if edge_buy > thresh and edge_buy >= edge_sell:
            return "ACCEPT_BUY"
        if edge_sell > thresh:
            return "ACCEPT_SELL"

        w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
        center = max(bid, min(round(v), ask - w))
        return ("COUNTER", center, center + w)

    def use_transform(self, obs):
        """Fire from a flat hand, decline from a decisive one."""
        return abs(obs.k_mine) <= FLAT_THRESHOLD
