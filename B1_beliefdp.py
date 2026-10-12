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
from math import comb, exp, sqrt


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
    name = "KV3B1"

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
        # -- archetype classifier state (within-deal only) --
        self._tape_seen = 0        # auction_log entries already processed
        self._con_seen = 0         # contracts already processed
        self._sched_hits = 0       # their winning bids == exact 0.60 schedule
        self._sched_miss = 0       # their winning bids off the schedule
        self._opp_spend = 0        # their observed TE spend (winning bids)
        self._opp_forced = 0       # rounds they forced as Taker (endgame-unaware)
        self._opp_taker_rounds = 0 # completed rounds where they were Taker
        self._prev_revealed = None # transform-fire detection
        self._binom_cache = {}     # n -> pmf of a sum of n fair ±1 coins

    # ── archetype classifier ────────────────────────────────────────

    def _sched60(self, power, r):
        """The modal 0.60-shade bid: int(POWER_VALUES[p][r] / 0.08 * 0.60)."""
        return int(POWER_VALUES.get(power, {}).get(r, 0.0) / 0.08 * 0.60)

    def _classify_sync(self, obs):
        """Incrementally fold public evidence into archetype counters.

        Cheap: touches only tape entries / contracts not yet seen. All
        conclusions are within-deal (state is wiped between deals).
        """
        # TRANSFORM fired? My revealed prefix silently changed -> hands were
        # swapped, and their revealed set is now EXACTLY my old one.
        prev = self._prev_revealed
        if prev is not None and obs.my_revealed[:len(prev)] != prev:
            self._post = {max(-20, min(20, sum(prev))): 1.0}
            self._post_round = obs.round
        self._prev_revealed = tuple(obs.my_revealed)

        tape = obs.auction_log
        while self._tape_seen < len(tape):
            e = tape[self._tape_seen]
            self._tape_seen += 1
            try:
                if e["seat"] == self.seat:
                    continue
                cost = int(e["cost"])
                self._opp_spend += cost
                sched = self._sched60(e["power"], e["round"])
                if sched > 0 and cost == sched:
                    self._sched_hits += 1
                else:
                    self._sched_miss += 1
            except Exception:
                pass

        cons = obs.contracts
        while self._con_seen < len(cons):
            c = cons[self._con_seen]
            self._con_seen += 1
            try:
                if c.maker_seat == self.seat:      # they were the Taker
                    self._opp_taker_rounds += 1
                    if c.forced and c.forcer == (1 - self.seat):
                        self._opp_forced += 1
            except Exception:
                pass

    def _p_clone(self):
        """Snipe gate: exact schedule matches with zero misses."""
        return self._sched_hits >= 1 and self._sched_miss == 0

    def _p_aware(self):
        """They have completed >=2 Taker rounds and never let one force."""
        return self._opp_taker_rounds >= 2 and self._opp_forced == 0

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
            # Kernel confidence follows the archetype posterior: schedule
            # bidders / passives are honest-centre with high probability;
            # off-schedule or heavy bidders get the fatter tail.
            self._seen_open.add(r)
            y = (quote[0] + quote[1]) / 2.0 - self._their_leak_correction(obs)
            if self._p_clone() or (self._opp_spend == 0 and r >= 2):
                w_info, w_flat = 0.9, 0.08
            elif self._sched_miss >= 2 or self._opp_spend >= 16:
                w_info, w_flat = 0.6, 0.30
            else:
                w_info, w_flat = 0.8, 0.15
            self._obs_gauss(y, 1.5, w_info, w_flat)
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

    # ── belief engine (B1): full discrete posterior over S ──────────

    def _binom_pmf(self, n):
        d = self._binom_cache.get(n)
        if d is None:
            d = {2 * k - n: comb(n, k) / (1 << n) for k in range(n + 1)}
            self._binom_cache[n] = d
        return d

    def _s_posterior(self, obs):
        """p(S) = k_mine + p(k_opp | filter) ⊗ Binom(2·(20−4r)).

        Both unrevealed tails are sums of independent fair coins, so they
        collapse into one binomial. ≤ 21×33 terms — well under a millisecond.
        """
        tails = self._binom_pmf(2 * max(0, 20 - 4 * obs.round))
        out = {}
        base = obs.k_mine
        for k, p in self._post.items():
            if p <= 1e-12:
                continue
            for t, q in tails.items():
                s = base + k + t
                out[s] = out.get(s, 0.0) + p * q
        return out

    def _margin(self, obs):
        """Uncertainty-scaled accept margin (replaces the fixed 0.5).

        The margin prices the option of staying in the round; option value
        scales with the sd of what we still do not know. Calibrated so the
        round-1 margin reproduces the ~0.5 that measured best: sd(S) ≈ 6 in
        round 1 → 0.08·6 = 0.48. By round 5 the posterior is tight and the
        margin shrinks toward ~0.1, taking thin edges the fixed rule passed.
        """
        return 0.08 * sqrt(max(0.0, self._var_s(obs)))

    def _value_bayes(self, obs, quote):
        self._classify_sync(obs)
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

    # ── auction: snipe ONLY on strong clone evidence ────────────────

    def _bid_c1(self, obs, offered):
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
            if bid_amount > 0:
                # Upward-only +{0,1} jitter: our bid never sits exactly on
                # the public 0.60 schedule, so a schedule-sniper (bidding
                # sched+1, as our own C5 does) cannot reliably outbid us by
                # one tick — and against an exact-schedule clone the +1 half
                # converts coin-flip ties into outright wins. Never bids
                # DOWN, so no auction we would have won is given away.
                bid_amount = min(bid_amount + self.rng.choice((0, 1)),
                                 obs.te_mine)
            if bid_amount > 0:
                out[name] = bid_amount
        return out

    def bid(self, obs, offered):
        if not offered or obs.te_mine <= 0:
            return {}
        try:
            self._classify_sync(obs)
            if not self._p_clone():
                return self._bid_c1(obs, offered)
            # Their observed winning bids sit exactly on the 0.60 schedule:
            # outbid the schedule by 1 (+{0,1}) wherever that is still under
            # our fair value; otherwise concede and bank the TE.
            out = {}
            for name in offered:
                if name == "TRANSFORM":
                    v = self._transform_value(obs)
                else:
                    v = self._power_value(obs, name)
                if v <= 0:
                    continue
                fair_te = v / self.config.TE_SALVAGE
                target = self._sched60(name, obs.round) + 1 + self.rng.choice((0, 1))
                if target <= fair_te:
                    amount = min(target, obs.te_mine)
                    if amount > 0:
                        out[name] = amount
            return out
        except Exception:
            try:
                return self._bid_c1(obs, offered)
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

    # ── portfolio steering (C8) ─────────────────────────────────────
    #
    # All five contracts settle against the SAME S, so my book is a single
    # exposure: PnL = N·S − Σ(signed prices) with N = (# long) − (# short).
    # Mean-variance utility U = E[PnL] − (γ/2)·Var[PnL], Var = N²·σ², where
    # σ² = Var(S | posterior) = Var(k_opp | filter) + (20 − 4r)_mine
    #      + (20 − 4r)_theirs   (both unrevealed tails are fair coins).
    # Adding a long changes Var by ((N+1)² − N²)σ² = (2N+1)σ², a short by
    # (1 − 2N)σ². So each side's edge is charged its marginal risk:
    #     penalty_long  = (γ/2)(2N+1)σ²,  penalty_short = (γ/2)(1−2N)σ²
    # A trade that REDUCES |N| gets a negative penalty (a bonus) — exactly
    # "require a better price to add, accept a worse one to reduce". This is
    # derived, not tuned; the only free constant is γ. γ = 0.01: at round-1
    # uncertainty (σ² ≈ 36) the first contract costs 0.18 ticks of edge and
    # the fourth same-direction add costs ~1.3 — small nudges, not vetoes.
    RISK_GAMMA = 0.01

    def _net_position(self, obs):
        n = 0
        for c in obs.contracts:
            n += 1 if c.long_seat == self.seat else -1
        return n

    def _var_s(self, obs):
        m = self._post_mean()
        var_k = sum(p * (k - m) ** 2 for k, p in self._post.items())
        tail = max(0, 20 - 4 * obs.round)
        return var_k + 2.0 * tail

    def _respond_v2(self, obs, quote, turn):
        bid, ask = int(quote[0]), int(quote[1])
        v = self._value(obs, quote)
        floor = obs.final_cap

        ev_buy = v - ask
        ev_sell = bid - v
        try:
            n = self._net_position(obs)
            var_s = self._var_s(obs)
            pen_long = 0.5 * self.RISK_GAMMA * (2 * n + 1) * var_s
            pen_short = 0.5 * self.RISK_GAMMA * (1 - 2 * n) * var_s
        except Exception:
            pen_long = pen_short = 0.0
        ev_buy -= pen_long
        ev_sell -= pen_short
        best_acc = max(ev_buy, ev_sell)
        accept = "ACCEPT_BUY" if ev_buy >= ev_sell else "ACCEPT_SELL"
        ev_force = self._forced_fill_ev(obs, bid, ask, v)
        # The forced fill is also a position: Maker ends long, Taker short.
        ev_force -= pen_long if obs.is_maker else pen_short

        last = (turn == obs.n_turns)

        if last and not obs.is_maker:
            if best_acc >= ev_force:
                return accept
            w = ask - bid
            max_w = min(w, max(floor, w - self.config.MIN_REDUCTION))
            return ("COUNTER", bid + (w - max_w), ask)

        margin = ACCEPT_MARGIN
        try:
            margin = self._margin(obs)
        except Exception:
            pass
        if obs.is_maker:
            if self._p_aware():
                # An endgame-aware Taker never lets the round force, so the
                # fee-collecting fill is unreachable: holding out just hands
                # them a free pick off my counter range at turn 6. Take real
                # edge when it shows.
                if best_acc > margin:
                    return accept
            elif best_acc > ev_force + margin:
                return accept
        else:
            if best_acc >= max(ev_force, 0.0) + margin:
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
        fire = abs(obs.k_mine) <= FLAT_THRESHOLD
        if fire:
            try:
                # After MY swap their revealed set becomes exactly my current
                # one: collapse the opponent-sum posterior to a point mass.
                self._post = {max(-20, min(20, obs.k_mine)): 1.0}
                self._post_round = obs.round
                self._prev_revealed = None   # my own revealed will change too
            except Exception:
                pass
        return fire
