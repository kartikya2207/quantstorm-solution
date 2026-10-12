# Phase-4 results — uncontaminated field, archetype detection, portfolio steering

## THE HEADLINE FINDING

**C5's advantage did NOT survive contact with independently-generated opponents.**
On the new f01-f12 field, C5 vs C1 paired diff = −0.95 [−2.54, +0.65] — the +5.19
"significant" edge measured on our own herd was a herd-construction artifact
(we over-weighted exact-0.60-schedule bidders at 50%; the independent field has
~1-2/12). The estimator edge (C1 over v2: +44.57* on the field) is real and
survives. The conditional version (C7) recovers the sniping upside without the
overfit: +6.09* over C1 on the field, +11.16* over C1 on the herd.

## Table 1 — old herd (weighted, paired seeds)

| bot | weighted mean | paired diff | seeds |
|---|---|---|---|
| v2_endgame | +59.92 | baseline | 2000-2039 |
| C1 | +89.65 (2000) / base col at 8000 | +29.73* vs v2 | 2000-2039 |
| C5 | +91.31 | +5.19* vs C1 (HERD ONLY — did not replicate) | 3000-3159 |
| C7 | +94.04 | +11.16* vs C1 [+8.09,+14.22] | 8000-8059 |
| C8 | +93.81 | −0.23 vs C7 (ns) | 8000-8059 |
| C9 | +95.79 | +1.75 vs C7 (ns) | 8000-8059 |

## Table 2 — NEW field f01-f12 (equal weight, 60 paired seeds 7000-7059)

| bot | mean | paired diff vs C1 |
|---|---|---|
| v2_endgame | +53.56 | −44.57* |
| C5 | +97.19 | −0.95 (ns) |
| C4 | +97.58 | −0.55 (ns) |
| C1 | +98.13 | baseline |
| C7 | +104.22 | **+6.09*** [+4.42,+7.75] |
| C9 | +104.37 | (≈C8: −0.35 ns vs C8) |
| C8 | +104.72 | +0.50 vs C7 (ns) |

Per-opponent rows: all candidates positive vs every field bot EXCEPT f12
(quote-shader): C1 −9.4, C5 −14.4, C7 +12.2, C8 +14.2, C9 +12.0 — the
archetype-aware kernel is the only thing that turns f12 positive.

## Table 3 — round robin v2/C1/C5/C7/C8 (60 paired seeds 9000-9059)

```
             v2       C1       C5       C7       C8      TOTAL
   v2      +0.0    -33.4    -47.1    -44.1    -46.0     -170.6
   C1     +33.4     +0.0    -14.6    -15.9    -18.4      -15.6
   C5     +47.1    +14.6     +0.0    +14.0    +12.8      +88.5
   C7     +44.1    +15.9    -14.0     +0.0     -3.8      +42.2
   C8     +46.0    +18.4    -12.8     +3.8     +0.0      +55.5
```

C5 tops this table by FARMING C7/C8's exact-schedule default bids — the same
snipe turned on us. Fix: C9 adds upward-only +{0,1} jitter to default bids.
C9 vs C5 head-to-head: −6.33 [−13.5, +0.9] (ns) vs C8's −10.46* — shield
recovers +4.13* [+0.01, +8.25] and neutralises the sniper matchup, at zero
field cost (−0.35 ns vs C8).

## C8 portfolio steering (derived formula, in code comment)

U = E − (γ/2)Var, Var = N²σ²; marginal penalty (γ/2)(2N+1)σ² long,
(γ/2)(1−2N)σ² short, σ² = filter posterior var + both unrevealed tails,
γ = 0.01. Effect: ≈ 0 everywhere (ns positive on the field). Kept in C9
because it is derived, free, and slightly positive-pointed.

## SHIP: C9_shielded.py

= C1 estimator + C7 archetype classifier (conditional snipe, aware-maker
gate, evidence-weighted kernel, transform-fire posterior collapse) + C8 risk
steering + anti-sniper bid shield.
- --validate ACCEPTED, exit 0
- isolate parity EXACT (+104.56 vs rational seed 42, per-deal identical)
- max call 0.330 ms isolate (limit 50 ms)
- all randomness via self.rng seeded in reset() — parity is genuine
- worst matchup on either population: f12 +11.95 (still positive)

Frozen and untouched: my_bot.py, v2_endgame.py, C5_ai_beater.py.
