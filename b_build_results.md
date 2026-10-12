# B1-B4 build results — base: C9_shielded (the phase-4 leader)

All tests: 12-bot field f01-f12, 60 paired seeds 7000-7059, paired diff vs
C9_shielded unless noted. Selection rule: keep only significant positives.

| Candidate | Change | Field diff vs C9 | Verdict |
|---|---|---|---|
| B1_beliefdp | full S-posterior engine + uncertainty-scaled accept margin (0.08·σ_S, ≈0.5 in r1 shrinking to ~0.1 in r5) | **−0.47*** [−0.83, −0.12] | REJECT margin; keep engine (inert) |
| B2_salvage | round-rising bid shade {.58,.58,.62,.72,.88} (TE option value declines; r5 TE worth only salvage) | **−1.81*** [−2.41, −1.21] | REJECT |
| B3_substitute | exact truncated EVs under the S posterior: my loss floored at −2 holding SUBSTITUTE, my gain capped at +2 against it; accepts and fills | **−0.71*** [−1.26, −0.16] | REJECT |
| B4_width | maker quote chooses width w ∈ [floor, cap] AND integer alignment lo maximizing 3·(P_true(lo≤S≤lo+w) − p_baseline(w)) − 0.22·(w−floor), P_true from the filter posterior | **+6.23*** [+4.97, +7.49] | **KEEP** |

## B4 replication (guards against seed-set selection bias)

- Fresh field seeds 12000-12079 (80 paired): **+5.15*** [+3.88, +6.43]
  (B4 +114.29 vs C9 +109.13 unweighted mean)
- Old herd, seeds 8000-8059 (60 paired): **+4.97*** [+3.34, +6.61]
  (B4 weighted +100.76; worst matchup h2 +51.90)

Three independent seed sets, all significant, similar magnitude. This is the
first genuine improvement since C7's conditional sniping.

Why it works: the obligation is scored against the baseline lattice straddle
at the width the maker actually quotes. Whenever the filter/FORESIGHT gives
us a posterior tighter or better-located than the baseline, there is a width
and an even-lattice alignment whose true straddle probability exceeds the
baseline's by more than the width premium — B4 finds it each round instead
of always quoting round(mean) at the floor. With an uninformative posterior
it collapses to the old floor quote (P_true ≈ p_baseline at every width →
premium dominates → floor wins), so nothing is lost early.

## The consistent negative finding

Every variant that loosens accepting — C2 (drop taker margin), B1 (shrink
margin with certainty), B3 (credit SUBSTITUTE option value) — measures
significantly worse. Accepting into a quoted price is adversely selected;
the fixed 0.5 margin is an adverse-selection guard, not an approximation
error. Stop trying to remove it.

## NEW LEADER: B4_width.py (name KV3B4)

= C1 estimator + C7 archetype layer + C8 risk steering + C9 bid shield +
B4 posterior-optimal quoting.
- --validate: ACCEPTED, exit 0
- isolate parity: EXACT (+89.56 vs rational seed 42, per-deal identical)
- max single call: 0.447 ms isolate (limit 50 ms)
- randomness: self.rng only, seeded in reset()
- bid path identical to C9, so the anti-sniper shield result carries over

Lineage of live results: field mean +110.59 (7000-7059) / +114.29
(12000-12079); herd weighted +100.76 (8000-8059).
