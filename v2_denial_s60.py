# Name: Kartikya
# College: IIT Bombay
# Roll Number: 24B4519

"""
v2_endgame.py — candidate v2, stage 1: forced-fill-aware negotiation.

Base: work/my_bot.py (adaptive_bidder verbatim). Changes:
  * respond() replaced with backward-induction logic against the forced fill
    (engine facts: MIDPOINT_SIDE_RULE="last_quoter_sells"; with 6 turns the
    Taker speaks on turns 2/4/6, so on every forced fill the Taker is the
    short and pays FORCED_FILL_FEE=2.0, the Maker is long and receives it;
    fill_price = (bid+ask)//2 + shift, shift = +mag for the short's
    TRICK_ROOM/STEALTH_ROCK, -mag for the long's — engine.py:670-686, 806).
  * reset() additionally initialises persisted-foresight state; _value() reads
    the persisted leak instead of only the current-round obs.foresight.
bid(), quote(), use_transform() are untouched from my_bot.py.
"""

import random
from math import sqrt


POWER_VALUES = {
    "FORESIGHT":    {1: 0.76, 2: 1.16, 3: 1.48, 4: 1.97, 5: 2.02},
    "TRICK_ROOM":   {1: 1.14, 2: 0.00, 3: 0.00, 4: 0.60, 5: 0.52},
    "SUBSTITUTE":   {1: 1.46, 2: 1.15, 3: 0.95, 4: 0.57, 5: 0.29},
    "STEALTH_ROCK": {1: 1.51, 2: 0.75, 3: 0.75, 4: 0.75, 5: 0.00},
    "TRANSFORM":    {1: 1.58, 2: 1.24, 3: 1.31, 4: 0.00, 5: 0.00},
}

SHADE = 0.60

#: Stage-2 denial shading: fraction of (my use value + opponent's denial
#: value) to bid. Denial roughly doubles values, so the shade comes down.
SHADE_D = 0.60

FLAT_THRESHOLD = 1
OPP_FLAT_THRESHOLD = 2.0
DENIAL_WEIGHT = 0.0

#: Extra edge an acceptance must clear over the forced-fill EV before we take
#: it mid-negotiation (option value of staying in the round).
ACCEPT_MARGIN = 0.5

#: The two fill-shifting powers (magnitudes read from config at runtime).
_SHIFT_POWERS = ("TRICK_ROOM", "STEALTH_ROCK")


class Bot:
    name = "KartikyaV2D60"

    def reset(self, seat, config, seed):
        self.seat = seat
        self.config = config
        self.rng = random.Random(seed)
        self._anchor = {}
        self._opp_anchor = {}   # rounds where we read THEIR opening quote
        self._leak_sum = None   # persisted FORESIGHT leak (sum of shown coins)

    # ── pricing (as my_bot.py, plus persisted foresight) ────────────

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
        earlier = [k for k in self._opp_anchor if k < obs.round]
        if not earlier:
            return None
        return self._opp_anchor[max(earlier)]

    def _note_foresight(self, obs):
        """Persist a FORESIGHT leak: obs.foresight is only populated in the
        round the power was held, but the information does not expire."""
        if obs.foresight:
            self._leak_sum = sum(obs.foresight)

    def _value(self, obs, quote=None):
        self._note_foresight(obs)
        leak = self._leak_sum
        if obs.is_maker or quote is None:
            return float(obs.k_mine + (leak if leak is not None else 0))
        anchor = self._get_anchor(obs, quote)
        if leak is not None:
            anchor = 0.5 * anchor + 0.5 * leak
        return float(anchor + obs.k_mine)

    def _power_value(self, obs, name):
        return POWER_VALUES.get(name, {}).get(obs.round, 0.5)

    def _transform_value(self, obs):
        swap = self._power_value(obs, "TRANSFORM")
        if abs(obs.k_mine) <= FLAT_THRESHOLD:
            return swap
        opp_k = self._opponent_k(obs)
        if opp_k is not None and abs(opp_k) <= OPP_FLAT_THRESHOLD:
            return swap * DENIAL_WEIGHT
        return 0.0

    # ── auction (stage-2 change: zero-sum denial bidding) ──────────

    def _bid_denial(self, obs, offered):
        """Bid on my use value PLUS the opponent's denial value.

        The game is zero-sum: a power the opponent would use against me is
        worth denying, so the contested value of a slot is (what it does for
        me) + (what it would do for them). Their use value is proxied by the
        same POWER_VALUES table entry (symmetric prior) — including for
        TRANSFORM, where their true gain depends on hand flatness we cannot
        see. My own TRANSFORM side stays state-dependent.

        Reserve: keep 2 TE in hand through round 4 so we are never priced
        out of a late slot — waived for FORESIGHT in rounds 4-5, the most
        valuable late power.
        """
        if not offered or obs.te_mine <= 0:
            return {}

        out = {}
        for name in offered:
            table = self._power_value(obs, name)
            if name == "TRANSFORM":
                mine = self._transform_value(obs)
            else:
                mine = table
            eff = mine + table
            if eff <= 0:
                continue

            fair_te = eff / self.config.TE_SALVAGE
            amount = int(fair_te * SHADE_D)

            reserve = 0
            if obs.round <= 4 and not (name == "FORESIGHT" and obs.round >= 4):
                reserve = 2
            cap = max(0, obs.te_mine - reserve)
            amount = max(0, min(amount, cap))
            if amount > 0:
                out[name] = amount

        return out

    def _bid_legacy(self, obs, offered):
        """v2_endgame / my_bot bidding — the safe fallback."""
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

            fair_te = v / self.config.TE_SALVAGE
            bid_amount = max(0, min(int(fair_te * SHADE), obs.te_mine))
            out[name] = bid_amount

        return out

    def bid(self, obs, offered):
        try:
            return self._bid_denial(obs, offered)
        except Exception:
            try:
                return self._bid_legacy(obs, offered)
            except Exception:
                return {}

    # ── quoting (unchanged from my_bot.py) ──────────────────────────

    def quote(self, obs):
        v = round(obs.k_mine + sum(obs.foresight))
        cap = obs.final_cap
        lo = v - cap // 2
        return (lo, lo + cap)

    # ── negotiation (stage-1 change) ────────────────────────────────

    def _shift_mag(self, powers):
        """Total fill-shift magnitude a seat controls this round.

        obs.powers_mine/theirs already carry engine semantics: TRICK_ROOM
        appears only in the round it was won, STEALTH_ROCK persists.
        """
        total = 0
        for name in _SHIFT_POWERS:
            if name in powers and name in self.config.POWERS:
                total += int(self.config.POWERS[name]["magnitude"])
        return total

    def _forced_fill_ev(self, obs, bid, ask, v):
        """My EV, in ticks, if this round runs to the forced midpoint fill.

        Engine: fill = (bid+ask)//2 + shift, where shift adds the SHORT's
        shift magnitudes and subtracts the LONG's. Under last_quoter_sells
        with 6 turns the Taker is always the short and pays the 2.0 fee.
        """
        mid = (bid + ask) // 2
        fee = float(self.config.FORCED_FILL_FEE)
        mine = self._shift_mag(obs.powers_mine)
        theirs = self._shift_mag(obs.powers_theirs)
        if obs.is_maker:
            fill = mid + (theirs - mine)      # opponent (Taker) is the short
            return (v - fill) + fee           # I am long and receive the fee
        fill = mid + (mine - theirs)          # I (Taker) am the short
        return (fill - v) - fee               # short at fill, pay the fee

    def _counter_toward(self, target, bid, ask, floor):
        """Largest legal width (minimal shrink), centred toward `target`,
        constructed so _sanitise_response never fires: inside [bid, ask],
        width == min(w, max(floor, w-1))."""
        w = ask - bid
        max_w = min(w, max(floor, w - self.config.MIN_REDUCTION))
        nb = max(bid, min(int(round(target)) - max_w // 2, ask - max_w))
        return ("COUNTER", nb, nb + max_w)

    def _respond_v2(self, obs, quote, turn):
        bid, ask = int(quote[0]), int(quote[1])
        v = self._value(obs, quote)
        floor = obs.final_cap

        ev_buy = v - ask
        ev_sell = bid - v
        best_acc = max(ev_buy, ev_sell)
        accept = "ACCEPT_BUY" if ev_buy >= ev_sell else "ACCEPT_SELL"
        ev_force = self._forced_fill_ev(obs, bid, ask, v)

        last = (turn == obs.n_turns)

        if last and not obs.is_maker:
            # Turn 6, Taker: terminal choice between the three exits.
            if best_acc >= ev_force:
                return accept
            # Ride to the fill: minimal legal change. Shrink from the bid
            # side — I am the short, and my counter IS the final range, so
            # raising the bottom raises the midpoint I sell at.
            w = ask - bid
            max_w = min(w, max(floor, w - self.config.MIN_REDUCTION))
            return ("COUNTER", bid + (w - max_w), ask)

        if obs.is_maker:
            # Turns 3/5: riding to the fill pays me the fee, so an accept
            # must beat that by a margin.
            if best_acc > ev_force + ACCEPT_MARGIN:
                return accept
        else:
            # Turns 2/4: keep the option unless the accept clearly beats
            # both the fill EV and doing nothing.
            if best_acc >= max(ev_force, 0.0) + ACCEPT_MARGIN:
                return accept

        return self._counter_toward(v, bid, ask, floor)

    def _respond_legacy(self, obs, quote, turn):
        """Original adaptive_bidder respond — the safe fallback."""
        bid, ask = quote
        v = self._value(obs, quote)

        edge_buy = v - ask
        edge_sell = bid - v

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

    def respond(self, obs, quote, turn):
        try:
            return self._respond_v2(obs, quote, turn)
        except Exception:
            try:
                return self._respond_legacy(obs, quote, turn)
            except Exception:
                # Last-ditch legal action; sanitiser will keep it in range.
                # Anything is better than the engine fallback (buy at ask).
                return ("COUNTER", quote[0], quote[1])

    # ── transform (unchanged from my_bot.py) ────────────────────────

    def use_transform(self, obs):
        return abs(obs.k_mine) <= FLAT_THRESHOLD
