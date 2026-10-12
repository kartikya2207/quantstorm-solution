# Day-3 build results — winner: C5_ai_beater.py

Baseline: v2_endgame weighted herd mean +59.92 (stderr 3.58), seeds 2000-2039.
Herd weights: h1 .20, h2 .15, h3 .10, h4 .15, h5 .15, h6 .15, h7 .10.

## Candidates (paired CIs, * = significant at 95%)

| Candidate | Change | Weighted mean | Paired diff | Verdict |
|---|---|---|---|---|
| C1_estimator | Bayesian filter on opp revealed sum | +89.65 | +29.73* vs v2 [+24.00,+35.47] | keep |
| C2_endgame_exact | drop taker accept-margin | +58.98 | −0.94* vs v2 [−1.17,−0.71] | reject |
| C3_full | C1 + C2 | +86.81 | −2.84* vs C1 [−3.47,−2.21] | reject |
| C4_full_jitter | C1 + ±1 jitter + indiff. mixing | +85.15 | −4.50* vs C1 [−7.77,−1.24] | reject |
| C5_ai_beater | C1 + modal-schedule bid sniping | +91.31 (160 seeds) | +5.19* vs C1 [+3.04,+7.34] | **WINNER** |

Direct C5 vs v2_endgame (fresh seeds 4000-4059): **+37.13* [+32.20, +42.07]**,
better against every one of the 7 herd classes (min class-diff +14.1 vs h7).

## Round robin (13 bots, 40 paired seeds 2000-2039, totals)

1. C5 +797.9 | 2. C1 +711.6 | 3. C3 +690.9 | 4. C4 +640.8 | 5. v2 +328.6 |
6. h5 +328.6 | 7. C2 +317.8 | 8. h6 +57.6 | 9. h2 −231.6 | 10. h3 −247.0 |
11. h1 −316.2 | 12. h4 −1386.1 | 13. h7 −1692.9

Both rankings agree (weighted herd AND round robin put C5 first). C5 beats every
other candidate head-to-head: +11.9 C1, +12.4 C3, +14.1 C4, +42.3 v2.

## Final checks on C5_ai_beater.py

- --validate: ACCEPTED, exit 0 (Kartikya / IIT Bombay / 24B4519)
- --isolate parity: EXACT (+100.48 vs rational seed 42, per-deal identical)
- timing: max single call 0.240 ms under isolate (limit 50 ms; local target 10 ms)
- stability, 100 fresh seeds (5000-5099):
  vs h5 (endgame-aware mirror): +36.96 [+30.79, +43.13], 89W/11L
  vs h6 (my-modal):             +46.60 [+41.58, +51.63], 93W/7L

## What C5 is

v2_endgame (forced-fill-aware negotiation, unchanged) plus:
1. **C1's discrete Bayesian filter** on the opponent's revealed coin sum
   (predict: 4-coin binomial step per round; update: their opening midpoints
   corrected for foresight-of-mine, their first counter's low end when I'm
   maker, my own FORESIGHT samples; mixture kernels for robustness). Posterior
   mean replaces the latch-anchor everywhere, including maker-side value and
   quote centring.
2. **Bid sniping**: bid int(POWER_VALUES/0.08×0.60)+1 (+{0,1}) — one above the
   modal deterministic schedule — whenever that price is under my fair value;
   concede otherwise. Converts coin-flip ties vs the 0.60-shade family into
   outright wins and drops auctions aggressive bidders would overpay for.

Rejected on evidence: C2's closed-form margin (the 0.5 option-value margin
earns ~1/match), downward bid jitter and indifference mixing (insurance
premium ~4.5/match with no herd that exploits determinism).
