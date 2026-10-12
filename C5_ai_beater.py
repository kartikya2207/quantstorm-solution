# Name: Kartikya
# College: IIT Bombay
# Roll Number: 24B4519

"""
C1_estimator.py — v2_endgame + exact discrete posterior on the opponent's
revealed coin sum.

The filter maintains p(k_opp) on the even lattice [-20..20], where k_opp is
the opponent's CURRENT revealed sum (grows by 4 coins per round):
  predict: convolve with the 4-coin step {−4:1, −2:4, 0:6, +2:4, +4:1}/16
  update:  their opening midpoint (when I am Taker; corrected for a FORESIGHT
           leak they hold of MY coins), their first counter's low end (when I
           am Maker; clone-family counters put round(v) at the low end),
           and my own FORESIGHT samples of their revealed coins.
Kernels are mixtures (informative Gaussian + flat component) so a shading or
non-clone opponent cannot drag the posterior far.

v = k_mine + E[k_opp] replaces the latch-anchor everywhere, including the
Maker-side estimate (which previously ignored the opponent entirely) and the
opening-quote centre. Every filter path falls back to the v2_endgame latch
logic on any internal error.

Negotiation logic is v2_endgame's, unchanged.
"""

import random
from math import exp, sqrt


POWER_VALUES = {
    "FORESIGHT":    {1: 0.76, 2: 1.16, 3: 1.48, 4: 1.97, 5: 2.02},
    "TRICK_ROOM":   {1: 1.14, 2: 0.00, 3: 0.00, 4: 0.60, 5: 0.52},
    "SUBSTITUTE":   {1: 1.46, 2: 1.15, 3: 0.95, 4: 0.57, 5: 0.29},
    "STEALTH_ROCK": {1: 1.51, 2: 0.75, 3: 0.75, 4: 0.75, 5: 0.00},
    "TRANSFORM":    {1: 1.58, 2: 1.24, 3: 1.31, 4: 0.00, 5: 0.00},
}

SHADE = 0.60
FLAT_THRESHOLD = 1
OPP_FLAT_THRESHOLD = 2.0
DENIAL_WEIGHT = 0.0
ACCEPT_MARGIN = 0.5

_SHIFT_POWERS = ("TRICK_ROOM", "STEALTH_ROCK")

#: 4-coin reveal step distribution (sum of 4 fair ±1 coins).
_STEP = ((-4, 1.0 / 16), (-2, 4.0 / 16), (0, 6.0 / 16), (2, 4.0 / 16), (4, 1.0 / 16))
_GRID = tuple(range(-20, 21, 2))


class Bot:
    name = "KV2C5"

    def reset(self, seat, config, seed):
        self.seat = seat
        self.config = config
        self.rng = random.Random(seed)
        self._anchor = {}
        self._opp_anchor = {}
        self._leak_sum = None
        # -- filter state --
        self._post = {0: 1.0}      # p(k_opp) at round self._post_round
        self._post_round = 0       # rounds of reveals folded into the prior
        self._my_open_mid = {}     # r -> midpoint of MY opening quote
        self._seen_open = set()    # rounds where their opening was ingested
        self._seen_counter = set() # rounds where their first counter was ingested
        self._leak_rounds = set()  # rounds whose leak was ingested

    # ── filter internals ────────────────────────────────────────────

    def _predict_to(self, r):
        while self._post_round < r:
            new = dict.fromkeys(_GRID, 0.0)
            for k, p in self._post.items():
                if p <= 0.0:
                    continue
                for d, q in _STEP:
                    t = k + d
                    if -20 <= t <= 20:
                        new[t] += p * q
            s = sum(new.values())
            self._post = {k: v / s for k, v in new.items()} if s > 0 else dict.fromkeys(_GRID, 1.0 / len(_GRID))
            self._post_round += 1

    def _bayes_update(self, like):
        new = {k: self._post.get(k, 0.0) * like(k) for k in _GRID}
        s = sum(new.values())
        if s > 1e-12:
            self._post = {k: v / s for k, v in new.items()}
        # else: observation carried no information / contradiction — keep prior

    def _obs_gauss(self, y, sigma, w_info, w_flat):
        two_s2 = 2.0 * sigma * sigma
        self._bayes_update(lambda k: w_info * exp(-((y - k) ** 2) / two_s2) + w_flat)

    def _their_leak_correction(self, obs):
        """Expected contribution of THEIR foresight leak (of my coins) to
        their value estimate."""
        if "FORESIGHT" not in obs.powers_theirs:
            return 0.0
        n = 4 * obs.round
        f = min(16, n)
        return (f / n) * obs.k_mine

    def _filter_sync(self, obs, quote):
        self._predict_to(obs.round)
        r = obs.round

        # My FORESIGHT sample of their revealed coins: f draws w/o replacement.
        if obs.foresight and r not in self._leak_rounds:
            self._leak_rounds.add(r)
            n = 4 * r
            f = len(obs.foresight)
            L = sum(obs.foresight)
            if f >= n:
                self._obs_gauss(L, 0.3, 1.0, 0.001)      # saw everything: k = L
            else:
                frac = f / n
                sigma = max(0.9, sqrt(f * (n - f) / n))
                two_s2 = 2.0 * sigma * sigma
                self._bayes_update(
                    lambda k: exp(-((L - frac * k) ** 2) / two_s2) + 0.01)

        if quote is None:
            return

        if not obs.is_maker and r not in self._seen_open:
            # Their opening quote: midpoint ≈ their k (+ their leak of mine).
            self._seen_open.add(r)
            y = (quote[0] + quote[1]) / 2.0 - self._their_leak_correction(obs)
            self._obs_gauss(y, 1.5, 0.8, 0.15)
        elif obs.is_maker and r not in self._seen_counter and r in self._my_open_mid:
            # Their first counter (I see it at my turn-3 respond). Clone-family
            # puts round(v_them) at the LOW end; v_them = anchor + k_them where
            # anchor latches MY opening midpoint (half-blended with their leak).
            self._seen_counter.add(r)
            corr = self._their_leak_correction(obs)
            if corr:
                y = quote[0] - 0.5 * self._my_open_mid[r] - 0.5 * corr
            else:
                y = quote[0] - self._my_open_mid[r]
            self._obs_gauss(y, 2.5, 0.6, 0.25)

    def _post_mean(self):
        return sum(k * p for k, p in self._post.items())

    def _value_bayes(self, obs, quote):
        self._filter_sync(obs, quote)
        return float(obs.k_mine + self._post_mean())

    # ── legacy pricing (v2_endgame) — the fallback ──────────────────

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
        try:
            return self._post_mean()
        except Exception:
            earlier = [k for k in self._opp_anchor if k < obs.round]
            if not earlier:
                return None
            return self._opp_anchor[max(earlier)]

    def _note_foresight(self, obs):
        if obs.foresight:
            self._leak_sum = sum(obs.foresight)

    def _value_legacy(self, obs, quote=None):
        self._note_foresight(obs)
        leak = self._leak_sum
        if obs.is_maker or quote is None:
            return float(obs.k_mine + (leak if leak is not None else 0))
        anchor = self._get_anchor(obs, quote)
        if leak is not None:
            anchor = 0.5 * anchor + 0.5 * leak
        return float(anchor + obs.k_mine)

    def _value(self, obs, quote=None):
        try:
            # Keep the legacy latch fed so a mid-deal fallback stays sane.
            self._note_foresight(obs)
            self._get_anchor(obs, quote)
            return self._value_bayes(obs, quote)
        except Exception:
            return self._value_legacy(obs, quote)

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

    # ── auction (C5: snipe the modal bid schedule) ──────────────────

    def _clone_bid(self, name, r):
        """The modal bot's exact bid: int(POWER_VALUES[p][r] / 0.08 * 0.60).

        The 0.60-shade family (the reference bot, its near-copies, and our
        own earlier bots) all bid this deterministic integer. Bidding one
        above it converts every would-be coin-flip tie into an outright win.
        """
        v = POWER_VALUES.get(name, {}).get(r, 0.0)
        return int(v / 0.08 * 0.60)

    def _bid_snipe(self, obs, offered):
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
            target = self._clone_bid(name, obs.round) + 1 + self.rng.choice((0, 1))
            if target <= fair_te:
                amount = min(target, obs.te_mine)
            else:
                # The schedule prices it above our value: concede, pay 0.
                continue
            if amount > 0:
                out[name] = amount

        return out

    def _bid_legacy(self, obs, offered):
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
            out[name] = max(0, min(int(fair_te * SHADE), obs.te_mine))
        return out

    def bid(self, obs, offered):
        try:
            return self._bid_snipe(obs, offered)
        except Exception:
            try:
                return self._bid_legacy(obs, offered)
            except Exception:
                return {}

    # ── quoting: centred on the full posterior ──────────────────────

    def quote(self, obs):
        try:
            v = int(round(self._value(obs, None)))
        except Exception:
            v = round(obs.k_mine + sum(obs.foresight))
        cap = obs.final_cap
        lo = v - cap // 2
        try:
            self._my_open_mid[obs.round] = lo + cap / 2.0
        except Exception:
            pass
        return (lo, lo + cap)

    # ── negotiation (v2_endgame, unchanged) ─────────────────────────

    def _shift_mag(self, powers):
        total = 0
        for name in _SHIFT_POWERS:
            if name in powers and name in self.config.POWERS:
                total += int(self.config.POWERS[name]["magnitude"])
        return total

    def _forced_fill_ev(self, obs, bid, ask, v):
        mid = (bid + ask) // 2
        fee = float(self.config.FORCED_FILL_FEE)
        mine = self._shift_mag(obs.powers_mine)
        theirs = self._shift_mag(obs.powers_theirs)
        if obs.is_maker:
            fill = mid + (theirs - mine)
            return (v - fill) + fee
        fill = mid + (mine - theirs)
        return (fill - v) - fee

    def _counter_toward(self, target, bid, ask, floor):
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
            if best_acc >= ev_force:
                return accept
            w = ask - bid
            max_w = min(w, max(floor, w - self.config.MIN_REDUCTION))
            return ("COUNTER", bid + (w - max_w), ask)

        if obs.is_maker:
            if best_acc > ev_force + ACCEPT_MARGIN:
                return accept
        else:
            if best_acc >= max(ev_force, 0.0) + ACCEPT_MARGIN:
                return accept

        return self._counter_toward(v, bid, ask, floor)

    def _respond_legacy(self, obs, quote, turn):
        bid, ask = quote
        v = self._value_legacy(obs, quote)

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
                return ("COUNTER", quote[0], quote[1])

    def use_transform(self, obs):
        return abs(obs.k_mine) <= FLAT_THRESHOLD
