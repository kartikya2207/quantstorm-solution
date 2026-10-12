# Synthesis — Divided Oracle, main build day

## (a) The game, as the engine actually scores it

Money flows, ranked by how much PnL they move per deal:

1. **Contract PnL** (`S − price` per contract, 5 contracts, all against the same S).
   Biggest lever. Estimation error converts to PnL at ~1 tick per tick of error,
   five times per deal, and positions are perfectly correlated through S.
2. **Forced-fill mechanics**. Under `last_quoter_sells` + 6 turns, the Taker is
   ALWAYS the forced-fill short and pays the 2.0 fee; the Maker is always long and
   receives it; `(bid+ask)//2` floor-division favours the long by ~0.5 on odd sums.
   A bot that counters blindly on turn 6 donates ~2-3 ticks per forced round.
   Proven today: this one change was worth +48 to +119 PnL/match.
3. **Maker obligation** (±3.0 scaled by exact lattice straddle prob, + 0.22/tick
   width premium). Zero-EV for an honest maker at any width; a maker who centres
   BETTER than the no-foresight baseline (e.g. holds a leak, or estimates the
   opponent's sum) has positive obligation EV. Widths 4,5,6 have IDENTICAL straddle
   probability (even lattice) — width above floor is pure cost plus negotiation room.
4. **Auction / TE**. 1 tick = 12.5 TE; whole 24-TE budget = 1.92 ticks. Salvage is
   on the DIFFERENCE of leftovers, so symmetric spend is free and asymmetric
   overpaying is cheap but real. Powers are worth ~0.3-2 ticks each; the auction is
   first-price, winner pays own bid, ties are coin flips at full price.
5. **Information**: my revealed coins (4r), opponent's opening quote (the one clean
   read of their revealed sum), the public tape (their winning bids), FORESIGHT
   leaks (min(16,4r) of their revealed coins — arrives once, must be persisted).

## (b) What today's experiments taught us

| Experiment | Result | Lesson |
|---|---|---|
| Insurance bot (adaptive_bidder copy) | leaderboard **−32.23**, lost to 9/10 | The reference bot is the FLOOR of the real field, not the median. The field is better than the shipped baselines. |
| v2_endgame (forced-fill-aware respond) | leaderboard **−0.16**, beats 5/10; paired +77.85 (rational), +48.18 (adaptive), +60.58 (naive), +119.37 (camper) | The endgame subgame is the single biggest local edge, and roughly half the leaderboard field has some version of it. The other half doesn't. |
| Denial bidding (value + opponent value) | REJECTED: −7 to −33 vs everyone except heavy bidders (+25 vs camper) | First-price overpaying against a passive field burns TE. Bid sizing must key off what the OPPONENT will bid, not off total contested value. |

Leaderboard telling: −0.16 vs 10 hidden bots means v2_endgame is roughly AT the
median of a curated field. The margin is in (1) estimation and (2) auction pricing
against the modal opponent, not in more endgame depth.

## (c) The modal AI-written bot — my own prediction

I am the model most of the field is using. When a student pastes this repo and asks
for "a good bot", the assistant (Claude or ChatGPT) will, with high probability:

1. Read RULEBOOK + starter_bot + the three strategies.
2. Anchor on adaptive_bidder because the rulebook explicitly blesses copying it.
3. Produce: **adaptive_bidder + quote-reading (latch first midpoint) + POWER_VALUES
   × ~0.6 bidding + honest floor-or-cap-width quotes + accept-any-positive-edge +
   TRANSFORM iff |k|≤1.** That IS the modal bot. Decision rules verbatim:
   - bid: `int(POWER_VALUES[p][r] / 0.08 * 0.6)` capped at te_mine
   - quote: centre `round(k_mine + foresight)`, width = floor (or cap for the lazier)
   - respond: accept iff edge > 0, else counter toward v with min shrink — INCLUDING
     turn 6 (donates the forcing fee)
   - use_transform: `abs(k) <= 1`

   Common variations (the follow-up prompts students actually type):
   - "make it more aggressive" → SHADE up to 0.75-0.9, accept threshold loosened
   - "improve the bidding" → per-round tweaks, denial experiments, mostly overpaying
   - "improve the endgame / don't pay the fee" → a crude turn-6 check without shift
     awareness (compare accept vs midpoint − 2). This is the sharpest common variant.
   - a fraction of broken bots: metadata fine but crashy logic, over-budget bids,
     wrong return shapes → engine fallbacks (ACCEPT_BUY at ask = free money).

## (d) Top 3 exploits vs that population (EV × confidence)

1. **Forced-fill asymmetry** (already shipped in v2_endgame): harvest the fee as
   Maker from turn-6 blind counterers; never donate it as Taker. EV: huge vs the
   ~half of the field without it, ~0 vs the rest. Confidence: proven (+48..+119).
2. **Predictable-bid capping/sniping**: the modal bid schedule is a KNOWN integer
   table (`int(v × 7.5)`). Bidding `min(my_value, clone_bid + 1)` wins every
   contested auction outright instead of coin-flipping ties at full price, and wins
   the clone's zero-bid rounds (TRICK_ROOM r2/3, STEALTH r5) for 1 TE. Pure gain vs
   clone family (~45% of field), tiny cost vs others. EV: ~0.3-0.8 ticks/deal ×
   high confidence.
3. **Cross-round opponent-sum posterior**: the latch anchor throws away everything
   except the current round's midpoint, and v2's MAKER-side estimate ignores the
   opponent entirely (v = k_mine). A small filter over the opponent's revealed sum
   (propagate ±4-coin steps, update on their midpoints/counters/leaks) gives the
   maker rounds an opponent estimate for free → better quote centring (obligation
   EV + fewer crossings) and better accepts. EV: several ticks/deal × medium-high
   confidence. This is C1.

Explicitly NOT doing: anchor-poisoning (organisers measured distortion at
+0.80 ± 1.51 and withdrew it — the obligation is a proper scoring rule), tape
signalling (herd doesn't read the tape), deep level-3 meta (assumes opponents model
me; they model a generic "good bot").
