# Name: Kartikya
# College: IIT Bombay
# Roll Number: 24B4519

"""
Divided Oracle entry — a Bayesian pricer that takes bounded-downside,
unbounded-upside risk when the engine offers it.

SIX COMPONENTS, each measured against an independently-written opponent
population before it was kept:

1. BELIEF. An exact discrete posterior p(k_opp) over the opponent's revealed
   coin sum on the lattice [-20..20]: predicted forward each round by the
   4-coin step {-4:1, -2:4, 0:6, +2:4, +4:1}/16, updated from their opening
   midpoints (corrected for any FORESIGHT they hold of my coins), their
   counters, my own FORESIGHT samples, and every past acceptance against a
   quote I made -- a hard inequality on their estimate (they bought at p
   => k_opp > p - my_mid). All kernels are mixtures with a flat component,
   so an implausible quote cannot drag the posterior far.

2. THE INSURED FLOOR QUOTE. SUBSTITUTE floors my loss on the round's
   contract at -2 and the engine pays that refund out of the counterparty.
   While holding it as Maker, quoting (-N_COINS - w, -N_COINS) is therefore
   a bounded-loss option, and the direction is forced by the engine rather
   than chosen: with last_quoter_sells over six turns the Maker is always
   the forced-fill LONG, so
       they ride  -> long at ~-42 => S + 42 >= +2   (uncapped)
       they sell  -> long at  -44 => S + 44 >= +4   (uncapped)
       they lift  -> short at -40, raw <= 0, FLOORED AT -2
   Both winning branches are arithmetically guaranteed non-negative because
   |S| <= N_COINS. The mirror quote at the top is strictly worse. One lifted
   ask disarms it for the rest of the deal.

3. NEGOTIATION. Backward induction from the forced fill, with the fill
   priced exactly (including TRICK_ROOM / STEALTH_ROCK shifts). The fill is
   NOT treated as a fallback this seat controls: countering hands the next
   move to the opponent, who can take the very edge being declined, so an
   available acceptance is compared against the fill value directly rather
   than against the fill value plus a premium. The 0.5 margin survives only
   as the absolute floor on trading at all -- an adverse-selection guard.

4. QUOTING. Otherwise the opening quote maximises its own settlement value,
   lam*(P_true - p_baseline(w)) - premium*(w - floor), searching width and
   integer alignment over the posterior. S lives on an even lattice, so the
   alignment is worth as much as the width.

5. ARCHETYPE LAYER. Passive, within-deal classification from public evidence
   only (auction tape, contract records, my own revealed prefix for
   TRANSFORM detection). It gates schedule-sniping, drops the fill-chasing
   line against endgame-aware opponents, weights the estimator kernels, and
   gates a downward centre shade against confirmed midpoint-latchers.

6. SAFETY. Every strategy path falls back to simpler behaviour on any
   internal error rather than to the engine's own fallback, all randomness
   runs through self.rng seeded in reset(), and no state survives a deal.
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
    name = "KV6X2"

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
        self._acc_seen = set()     # contracts already used as accept evidence
        self._shaded_rounds = set()  # rounds where I shaded my opening quote
        self._shade_burned = False   # kill-switch: shading was punished
        self._opp_bought = 0         # times they took MY ask (any round)
        self._bluff_rounds = set()   # rounds where I posted the insured floor
        self._bluff_burned = False   # they lifted the insured ask -> stop

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
                    # G1 gate evidence. The shade's ONLY losing branch is
                    # the Taker buying at my lowered ask, so the decisive
                    # passive statistic is whether this opponent takes my
                    # ask at all. A pure latcher rides or sells from a low
                    # window; an endgame-aware or sharp Taker lifts it.
                    # One observed lift disarms the shade for the deal.
                    if not c.forced and c.long_seat != self.seat:
                        self._opp_bought += 1
                        if c.round in self._shaded_rounds:
                            self._shade_burned = True
                        # Insured-floor kill-switch: the ONLY losing branch
                        # is the Taker lifting my ask (I end short, floored
                        # at -2 by my own SUBSTITUTE). One lift proves this
                        # opponent prices from its own value rather than
                        # latching my centre; stop offering it this deal.
                        if c.round in self._bluff_rounds:
                            self._bluff_burned = True
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

    def _accept_evidence(self, obs):
        """D1: every past acceptance against MY quote is a hard inequality
        on the opponent's estimate, and I know both sides of it exactly.

        In a round I made, the Taker's value is v = (their read of my
        opening midpoint) + k_them ≈ my_mid + k_them. The engine records
        the execution price, so:
            they went long  at price p  ->  v > p  ->  k_them > p - my_mid
            they went short at price p  ->  v < p  ->  k_them < p - my_mid
        This is the sharpest evidence in the deal — sharper than a quote
        midpoint, because it is a decision they had to commit PnL to — and
        the filter never used it. Applied with slack for the coins revealed
        since (sd 2 per round) and a flat floor for non-latching archetypes.
        """
        for c in obs.contracts:
            key = c.round
            if key in self._acc_seen:
                continue
            self._acc_seen.add(key)
            if c.forced or c.maker_seat != self.seat:
                continue
            mid = self._my_open_mid.get(c.round)
            if mid is None:
                continue
            thresh = c.price - mid
            slack = 2.0 + 2.0 * max(0, obs.round - c.round)
            if c.long_seat != self.seat:      # they bought: k above thresh
                self._bayes_update(
                    lambda k: 0.7 if k > thresh - slack else 0.3)
            else:                             # they sold: k below thresh
                self._bayes_update(
                    lambda k: 0.7 if k < thresh + slack else 0.3)

    def _filter_sync(self, obs, quote):
        self._predict_to(obs.round)
        r = obs.round
        try:
            self._accept_evidence(obs)
        except Exception:
            pass

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

    #: TE paid for SUBSTITUTE. Its tabled value (0.29-1.46 ticks) prices it
    #: as an ordinary loss-cap on an ordinary contract. Holding it as Maker
    #: instead unlocks the insured floor quote above, whose winning branches
    #: are worth ~+40 and whose losing branch is floored at -2 — so the
    #: power is worth an order of magnitude more than the row says, and the
    #: row is what every schedule bidder will pay. 13 clears the 0.60
    #: schedule's best round-1 bid (10) with room to spare, and 13 TE costs
    #: about one tick of salvage against a play worth tens.
    SUBSTITUTE_BID = 18

    def _bid_c1(self, obs, offered):
        out = {}
        for name in offered:
            if name == "SUBSTITUTE" and not self._bluff_burned:
                amt = min(self.SUBSTITUTE_BID, obs.te_mine)
                if amt > 0:
                    out[name] = amt
                continue
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

    # ── quoting (B4): posterior-optimal width and lattice alignment ─

    def _binom_pmf(self, n):
        d = self._binom_cache.get(n)
        if d is None:
            d = {2 * k - n: comb(n, k) / (1 << n) for k in range(n + 1)}
            self._binom_cache[n] = d
        return d

    def _s_posterior(self, obs):
        """p(S) = k_mine + p(k_opp | filter) ⊗ Binom(2·(20−4r)) — both
        unrevealed tails collapse into one binomial."""
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

    def _quote_b4(self, obs):
        """Choose opening width AND integer alignment to maximise the
        settlement EV of the quote:

            EV(lo, w) = λ·(P_true(lo ≤ S ≤ lo+w) − p_baseline(w))
                        − premium·(w − floor)

        where P_true uses MY posterior (filter + any FORESIGHT) and
        p_baseline is the engine's exact lattice straddle prob the
        obligation is scored against. With no information beyond the prior,
        P_true ≈ p_baseline at every width and this collapses to the floor
        quote we already play; with information it widens or re-aligns only
        when the obligation arithmetic actually pays for it. S lives on the
        even lattice, so alignment can matter as much as width.
        """
        self._classify_sync(obs)
        self._filter_sync(obs, None)
        dist = self._s_posterior(obs)
        mean = sum(s * p for s, p in dist.items())
        floor = obs.final_cap
        cap = obs.spread_cap
        lam = float(self.config.MAKER_OBLIGATION)
        prem = float(self.config.WIDTH_PREMIUM)
        r = obs.round

        best = None
        for w in range(floor, cap + 1):
            p_base = self.config.straddle_prob(r, w)
            centre = int(round(mean)) - w // 2
            # G2b: pure search widening — a superset of B4's alignments, so
            # it can only find a higher value of B4's own objective.
            for lo in (centre - 3, centre - 2, centre - 1, centre,
                       centre + 1, centre + 2, centre + 3):
                hi = lo + w
                p_true = sum(p for s, p in dist.items() if lo <= s <= hi)
                ev = lam * (p_true - p_base) - prem * (w - floor)
                # Tie-break toward the floor width and the centred lo: the
                # floor quote is take-it-or-leave-it, which is its own edge.
                key = (ev, -(w - floor), -abs(lo - (centre)))
                if best is None or key > best[0]:
                    best = (key, lo, w)
        _, lo, w = best
        return (lo, lo + w)

    # ── G1: downward centre shade against confirmed latchers ────────
    #
    # Clone shift-invariance (algebraic): a midpoint-latching Taker sets
    # v = my_mid + k_opp, so its accept/counter test compares k_opp against
    # the window half-widths — MY CENTRE CANCELS. Shifting the whole quote
    # by delta changes none of its actions, only the price at which each
    # happens:
    #     they sell at my bid   -> I am long, cheaper  : gain -delta
    #     they ride to the fill -> I am long, cheaper  : gain -delta
    #     they buy at my ask    -> I am short, cheaper : loss -delta
    # so  gain(delta) = -delta * (P(ride) + P(sell) - P(buy)), the three
    # probabilities read off the filter posterior on k_opp. Cost is the
    # obligation term lam * (p_true(centred) - p_true(shifted)), small
    # because the even lattice is flat near the centre. Fire only while
    # gain > cost. Nothing tuned.
    SHADE_DELTAS = (-2, -4)

    def _shade_delta(self, obs, lo, hi, dist):
        if self._shade_burned or not self._p_clone():
            return 0
        if self._opp_bought:
            return 0
        if "SUBSTITUTE" in obs.powers_theirs:
            return 0
        w = hi - lo
        lam = float(self.config.MAKER_OBLIGATION)
        p_sell = sum(p for k, p in self._post.items() if k < -(w // 2))
        p_buy = sum(p for k, p in self._post.items() if k > w - w // 2)
        p_ride = max(0.0, 1.0 - p_sell - p_buy)
        edge = p_ride + p_sell - p_buy
        if edge <= 0:
            return 0
        p_true0 = sum(p for s, p in dist.items() if lo <= s <= hi)
        best_d, best_net = 0, 0.0
        for d in self.SHADE_DELTAS:
            p_true = sum(p for s, p in dist.items() if lo + d <= s <= hi + d)
            net = (-d) * edge - lam * (p_true0 - p_true)
            if net > best_net:
                best_d, best_net = d, net
        return best_d

    # ── X1: the insured floor quote ─────────────────────────────────
    #
    # SUBSTITUTE floors MY loss on this round's contract at -2, and the
    # engine pays that refund out of the COUNTERPARTY (apply_settlement_
    # powers). So while I hold it, a quote at the very bottom of the
    # reachable score range is a bounded-downside, unbounded-upside option.
    #
    # Direction is forced by the engine, not chosen: on a forced fill the
    # MAKER is the long (last_quoter_sells + six turns => the Taker is
    # always the short). Quoting (-40-w, -40) at floor width:
    #
    #   they ride to the fill -> fill = -40 - ceil(w/2); I am LONG
    #                            => S + 42 >= +2, typically +42   (uncapped)
    #   they sell at my bid   -> I am LONG at -44
    #                            => S + 44 >= +4, typically +44   (uncapped)
    #   they lift my ask      -> I am SHORT at -40, raw -(S+40) <= 0,
    #                            FLOORED AT -2 by my own SUBSTITUTE
    #
    # Since |S| <= N_COINS, the first two branches are arithmetically
    # guaranteed non-negative. The mirror-image quote at the TOP is strictly
    # worse: riding would make me long at +40, i.e. the capped branch.
    # A midpoint-latching opponent sets v = my_mid + k ~ -40 + k, sees both
    # sides as roughly fair, counters, and rides straight into it.
    #
    # Cost: the opening quote misses S almost surely, so the obligation pays
    # -lam * p_w ~ -1.5, plus the TE spent winning SUBSTITUTE. Fires only
    # while HOLDING SUBSTITUTE and only as Maker, which is ~0.5 rounds per
    # deal, so the downside is bounded at roughly -3.5 per occurrence and
    # ends entirely after one lifted ask.
    def _insured_floor_quote(self, obs):
        if "SUBSTITUTE" not in obs.powers_mine or self._bluff_burned:
            return None
        if not obs.is_maker:
            return None
        w = obs.final_cap
        reach = int(self.config.N_COINS)
        hi = -reach                 # ask: the lowest ask the engine will not
        lo = hi - w                 # slide (slides only if ask < -N_COINS)
        self._bluff_rounds.add(obs.round)
        return (lo, hi)

    def quote(self, obs):
        try:
            self._classify_sync(obs)
            forced_quote = self._insured_floor_quote(obs)
            if forced_quote is not None:
                lo, hi = forced_quote
                self._my_open_mid[obs.round] = (lo + hi) / 2.0
                return (lo, hi)
        except Exception:
            pass
        try:
            lo, hi = self._quote_b4(obs)
        except Exception:
            try:
                v = int(round(self._value(obs, None)))
            except Exception:
                v = round(obs.k_mine + sum(obs.foresight))
            cap = obs.final_cap
            lo, hi = v - cap // 2, v - cap // 2 + cap
        try:
            d = self._shade_delta(obs, lo, hi, self._s_posterior(obs))
            if d:
                lo, hi = lo + d, hi + d
                self._shaded_rounds.add(obs.round)
        except Exception:
            pass
        try:
            self._my_open_mid[obs.round] = (lo + hi) / 2.0
        except Exception:
            pass
        return (lo, hi)

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

        if obs.is_maker:
            if self._p_aware():
                # An endgame-aware Taker never lets the round force, so the
                # fee-collecting fill is unreachable: holding out just hands
                # them a free pick off my counter range at turn 6. Take real
                # edge when it shows.
                if best_acc > ACCEPT_MARGIN:
                    return accept
            elif best_acc > ev_force + ACCEPT_MARGIN:
                return accept
        else:
            # The forced fill is NOT a fallback I control: if I counter, the
            # opponent moves next and can take the same edge I am looking at,
            # leaving me the complementary side (+best_acc becomes -best_acc).
            # With p = P(they decline), continuation = p*ev_force -
            # (1-p)*best_acc, so accepting is right iff
            # best_acc*(2-p) > p*ev_force. The old rule was the p=1 corner
            # PLUS a margin on top; even at p=1 the correct comparison is
            # best_acc > ev_force with no margin. ACCEPT_MARGIN is kept as
            # the ABSOLUTE floor on trading (the adverse-selection guard),
            # just no longer stacked on the fill value. Bites exactly where
            # floor(width/2) == 2 (widths 4-5), where the two are tied.
            if best_acc >= max(ev_force, ACCEPT_MARGIN):
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
