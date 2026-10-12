# Divided Oracle — Ground-Truth Recon (QuantStorm 2026)

Sources read in full: `RULEBOOK.md`, `README.md`, `FAQs.txt`, `engine.py`,
`game_config.py`, `starter_bot.py`, `backtester.py`, `bot_loader.py`,
`policy.py`, `limits.py`, `sandbox.py`, `strategies/{naive_ev,rational,adaptive_bidder,__init__}.py`.
All line references are to the files in `quantstorm-ps/`. Engine code is treated as
ground truth throughout; every RULEBOOK/docstring disagreement found is flagged in §9.

`FAQs.txt` contains only: "This file will be updated as the competition goes on."

---

## 1. The game

### The asset
A hidden score `S` is the sum of **40 fair ±1 coins** (`game_config.py:80`,
`engine.py:603-605`: `make_coins` draws `1 if rng.getrandbits(1) else -1` 40 times).
`S ∈ [-40, +40]` and — because it is a sum of 40 ±1 values — **`S` is always even**.
20 coins are your private hand, 20 the opponent's (`split_coins`, engine.py:608-617).
`S = sum(hand0) + sum(hand1)` (engine.py:1110). Each round you are shown 4 more of
*your own* coins; after round 5 you have seen all 20 of yours and 0 of theirs
(except via FORESIGHT).

### A deal, in exact engine order (`play_deal`, engine.py:1051-1326)
1. Coins validated (must be 40 values of ±1) — engine.py:1080-1084.
2. RNG streams derived (see "Randomness" below); the whole deal's **power slate is
   drawn up front** from a stream keyed only on the deal seed — engine.py:1106,
   `GameConfig.draw_slate` game_config.py:522-553.
3. Hands split; on the mirror leg the hands are swapped — engine.py:1109.
4. Both bots wrapped, then **`reset(seat, config, seed)` called on each**
   (engine.py:1117-1119). TE set to `[24, 24]` (engine.py:1121).
5. **Rounds r = 1..5** (engine.py:1139):
   1. **Reveal**: 4 new coins appended to each seat's revealed list
      (engine.py:1143-1147).
   2. **Maker determined**: `maker_seat = 0 if r % 2 == 1 else 1`, inverted on the
      mirror leg / `--first_maker 1` (engine.py:1160-1162). So seat 0 (bot A) makes
      rounds 1, 3, 5 on the direct leg; seat 1 makes 2, 4.
   3. `offered` = this round's slate entry minus already-consumed one-shots
      (engine.py:1169-1172). With `SLOTS_PER_ROUND = 1` it is always exactly one
      power name.
   4. **Pre-auction Obs built** for both seats (no foresight field, tape without
      this round) — engine.py:1178-1182.
   5. **Auction**: `bid()` called on both seats (seat 0 first, but both see the same
      pre-auction state — blind), first-price resolution — `run_auction`,
      engine.py:827-913.
   6. **TRANSFORM decision**: if a seat won TRANSFORM this round, a fresh Obs is
      built (now including the win on the tape and the reduced TE) and
      `use_transform(obs)` is called; `True` swaps the hands wholesale —
      engine.py:1193-1209, `apply_transform` engine.py:648-667.
   7. **FORESIGHT sampled** (after TRANSFORM, so the leak describes the post-swap
      hand) — engine.py:1213, `apply_foresight` engine.py:624-645.
   8. Score-invariance assertion (engine.py:1216-1219).
   9. **Post-auction Obs built** (with `foresight`) — engine.py:1233-1238.
   10. **Negotiation** (`trade_round`, engine.py:730-820): Maker's `quote()` is
       turn 1; turns 2..6 alternate `respond()` starting with the Taker; ends on
       an accept or a forced midpoint fill. Exactly **one contract per round**.
6. **Settlement** (engine.py:1253-1316): all five contracts settle at once against
   the revealed `S`: raw contract PnL → maker obligation → forcing fees →
   SUBSTITUTE refunds → TE salvage → zero-sum assertion (`|pnl0+pnl1| ≤ 1e-9`).

### What each player sees / what is hidden
Seen (all via `Obs`, built fresh per call, engine.py:1005-1048):
your seat, round, **your own revealed coins** (`my_revealed`, length `4*round`),
**both TE balances** (`te_mine`, `te_theirs`), this round's `spread_cap`/`final_cap`,
`is_maker`, **both sides' active powers** (`powers_mine`, `powers_theirs`), the
**full public auction tape** (`auction_log`: every win as
`{"round", "seat", "power", "cost"}` — winning bids are public), all **contracts so
far this deal** (full `Contract` records incl. the Maker's opening quote), your
`foresight` leak (else `()`), `n_unknown_both = 40 − 8·round`, `n_turns = 6`.

Hidden: the opponent's coins (except a FORESIGHT sample of their *revealed* ones),
the opponent's **losing** bids, `S` itself, and **the future slate** — you learn each
round's offered power only when `bid()` is called.

### Match structure
A match = `n_deals` deals, each played **twice back-to-back**: direct leg, then
immediately its mirror (hands swapped, Maker roles inverted, same coin vector) —
engine.py:1391-1394 `legs = [(False, invert_base)] + [(True, not invert_base)]`.
Default `DEALS_PER_PHASE = 10` (game_config.py:86) → 20 deals per match. The match
ends after all deals, or **early** the moment either bot exceeds
`MAX_TIME_VIOLATIONS` (engine.py:1443-1444), in which case the 250-PnL forfeit
transfer is applied (engine.py:1450-1462). There is no per-match "winner" flag in
the engine — the result is the aggregate PnL pair; tournament ranking is summed PnL.

### Randomness (all deterministic given the seed)
- Match stream: `random.Random(derive_seed("match", seed))` draws each deal's coin
  vector (engine.py:1366, 1387). `derive_seed` = BLAKE2b of the stringified parts
  (engine.py:66-74).
- Per-deal seed: `derive_seed("phase", seed, d)` — **same for both legs**
  (engine.py:1389).
- `rng` (per-leg): `derive_seed("deal", seed, swap, invert_roles)` — only used for
  the forced-fill coin flip under `MIDPOINT_SIDE_RULE == "coin_flip"`, which is NOT
  the shipped rule, so effectively unused (engine.py:1087, 797-802).
- `sym` (mirror-invariant): `derive_seed("deal-sym", seed)` — decides tied auctions
  (`sym.randrange(2) ^ tie_flip`, where `tie_flip = int(swap)` so the mirror leg
  hands the same tie to the other seat) and samples FORESIGHT leaks
  (engine.py:1099-1100, 887, 1213).
- Slate: `derive_seed("deal-slate", seed)` (engine.py:1106).
- Your `reset` seed: `derive_seed("bot", deal_seed, seat, swap, invert_roles)`
  (engine.py:1119) — different per leg and per seat.

---

## 2. The five methods

Your file must define `class Bot` (exact name), constructed with **no arguments**.
All five methods are required (`bot_loader.py:54` `REQUIRED_METHODS`); a file
missing any is rejected at the static gate (`bot_loader.py:200-221`).

### `reset(self, seat: int, config: GameConfig, seed: int) -> None`
- **Call site**: engine.py:1117-1119, once per deal before round 1, via
  `BotWrapper.do_reset` (engine.py:282-286).
- `seat`: 0 or 1 — your index for this deal (bot A is always seat 0 on both legs;
  the mirror swaps hands and roles, not seats).
- `config`: the frozen `GameConfig` (mutation raises `ConfigError`,
  game_config.py:317-326).
- `seed`: 64-bit int, deterministic per deal/leg/seat.
- Return value ignored (`sandbox._normalise` maps it to `None`, sandbox.py:194-195).
- If it raises / times out: `wrapper.failed = True` and **every remaining call in
  the deal takes its fallback** (engine.py:284-286; fallbacks below). Same if
  `__init__` raises (`UnbuiltBot`, engine.py:189-208).

### `bid(self, obs: Obs, offered: list[str]) -> dict[str, int]`
- **Call site**: `run_auction`, engine.py:862-865 (from play_deal engine.py:1185),
  once per round, **before** negotiation, with the pre-auction Obs
  (`foresight = ()`, tape excludes this round). `offered` is a **copy** you may
  mutate (engine.py:304). Under the shipped config it always has exactly one name.
- Valid return: `{power_name: te_int}`; `{}` bids nothing.
- Validation (`_sanitise_bid`, engine.py:310-377):
  - non-dict → `{}`; keys not in `offered` → discarded (warned); non-numeric
    values → discarded; `int()` applied (floats **truncate toward zero**;
    inf/nan → discarded); negative → 0; clamped to `MAX_REASONABLE_VALUE = 10000`.
  - **If the cleaned total exceeds `obs.te_mine`, EVERY bid is set to 0**
    (engine.py:368-375) — you contest nothing that round. Not rescaled.
- In `--isolate`, an extra worker-side check first: >64 keys or non-str keys →
  treated as a crashed call (sandbox.py:200-210).

### `quote(self, obs: Obs) -> tuple[int, int]`
- **Call site**: `trade_round`, engine.py:748, turn 1 of the negotiation, only for
  the Maker seat, with the **post-auction Obs** (foresight included if you hold it).
- Valid return: `(bid, ask)` with `obs.final_cap ≤ ask − bid ≤ obs.spread_cap`.
- Validation (`_sanitise_quote`, engine.py:407-473): non-indexable/short → default
  quote; values `int()`-truncated and clamped to ±10000; `bid > ask` → swapped;
  width outside `[final_cap, spread_cap]` → **re-centred on the nearer edge
  preserving the midpoint** (`mid = (bid+ask)//2; bid = mid − target//2;
  ask = bid + target`, engine.py:443-449); a quote lying entirely outside
  `[-40, +40]` is slid rigidly to the edge, width preserved (engine.py:461-471).
- Fallback (crash/timeout/failed): `(-(cap//2), cap − cap//2)` — e.g. round 1
  `(-4, +5)` (engine.py:397-399, 421-422).

### `respond(self, obs: Obs, quote: tuple[int, int], turn: int)`
- **Call site**: `trade_round`, engine.py:761, turns 2..6. Turn order: 2 = Taker,
  3 = Maker, 4 = Taker, 5 = Maker, **6 = Taker**. `obs` is the same post-auction
  Obs built once per round (TE already net of the auction); `quote` is the live
  range; `turn` is 2..6 (`config.N_TURNS = 6`).
- Valid returns: `"ACCEPT_BUY"` (you go long at the current `ask` — contract
  engine.py:772), `"ACCEPT_SELL"` (you go short at the current `bid` —
  engine.py:780), or `("COUNTER", new_bid, new_ask)`.
- Counter validation (`_sanitise_response`, engine.py:538-596): unknown string /
  unparseable / first element ≠ `"COUNTER"` (**case-sensitive**) → `"ACCEPT_BUY"`;
  values truncated to int and clamped ±10000; swapped if inverted; clamped
  **inside** the current range; width above
  `max_width = min(ask−bid, max(final_cap, (ask−bid) − 1))` → re-centred at
  `max_width` (engine.py:588-594). Width **0 counters are legal** (there is no
  minimum width, only no *forced* shrink below `final_cap`).
- Fallback: `"ACCEPT_BUY"` (engine.py:489-496).

### `use_transform(self, obs: Obs) -> bool`
- **Call site**: engine.py:1193-1209 — immediately after the auction, in the round
  TRANSFORM was won, only for the winner, **before FORESIGHT sampling and before
  the negotiation**. Its Obs includes the TRANSFORM win in `powers_mine` and on
  the tape, but `foresight = ()` always.
- Return `True` → `apply_transform` swaps hands; anything falsy → decline.
  Non-bool returns are coerced with `bool()` (a raising `__bool__` → decline,
  engine.py:520-536). Fallback: `False`.
- **The power is consumed either way** (`PowerState.acquire` marks it used at win
  time, engine.py:162-173).

### The `Obs` dataclass (game_config.py:586-615) — frozen, rebuilt per call
`seat:int`, `round:int (1-5)`, `my_revealed:tuple[±1,...]` (len `4*round`),
`te_mine:int`, `te_theirs:int`, `spread_cap:int`, `final_cap:int`, `is_maker:bool`,
`powers_mine:frozenset[str]`, `powers_theirs:frozenset[str]`,
`auction_log:tuple[dict,...]`, `contracts:tuple[Contract,...]`,
`foresight:tuple[±1,...]`, `n_unknown_both:int`, `n_turns:int`; property
`k_mine = sum(my_revealed)`.

`Contract` NamedTuple (game_config.py:618-638): `round, price, long_seat, forced,
forcer=-1, shift=0, maker_seat=-1, open_bid=0, open_ask=0`. First four also
readable positionally.

---

## 3. The transform

Mechanics (`apply_transform`, engine.py:648-667):

```python
hands[0][:], hands[1][:] = list(hands[1]), list(hands[0])
n0, n1 = len(revealed[0]), len(revealed[1])
revealed[0][:] = hands[0][:n0]
revealed[1][:] = hands[1][:n1]
```

- **Both entire 20-coin private hands are exchanged, revealed portions included.**
  Your revealed list becomes the first `4r` coins of what was the opponent's hand
  (both sides always have equal revealed counts, `4r`). `S` is unchanged — the
  partition of coins between seats changes, not the multiset (asserted at
  engine.py:1216-1219).
- **When**: eligible to be drawn only in rounds 1–3 (game_config.py:231-235),
  placed on the slate **at most once per deal** (`draw_slate`,
  game_config.py:546-552). It appears in roughly one deal in three
  (adaptive_bidder docstring) — the slate is drawn, not guaranteed.
- **Cost**: whatever you bid to win the auction (first price). `magnitude` is 0 in
  the config table because its value is state-dependent.
- **The option**: winning gives you a single, immediate decision via
  `use_transform(obs)` in the same round, before the leak and the negotiation. You
  cannot defer it. Declining still consumes it (`used` set at acquire time,
  engine.py:166-169), so buying-and-declining is a **veto**: the opponent can never
  obtain it later in the deal.
- After a swap, subsequent reveals (rounds r+1..5) come from your *new* hand
  (engine.py:1144-1147 slices `hands[s]`, which was mutated in place).
- FORESIGHT sampled after TRANSFORM in the same round describes the post-swap
  opponent hand (engine.py:1210-1213).
- **Detectability**: the *win* and its cost are on the public tape; the *firing* is
  not broadcast, but both sides can detect it by comparing `obs.my_revealed`
  against what they remembered from earlier in the round/deal — after a fire your
  own revealed coins silently change.
- The engine `break`s after the first winner (engine.py:1209) — with one slot per
  round only one seat can hold it anyway.

---

## 4. The auction

`run_auction`, engine.py:827-913. Blind, simultaneous, **first-price**:

```python
b0 = raw_bids[0].get(name, 0); b1 = raw_bids[1].get(name, 0)
if b0 == b1:
    if b0 == 0: continue                      # nobody bid: no winner, no free power
    winner = sym.randrange(2) ^ tie_flip      # tie -> coin flip (mirror-replayed)
else:
    winner = 0 if b0 > b1 else 1
cost = raw_bids[winner].get(name, 0)
if cost > te[winner]: continue                # can't afford -> not awarded
te[winner] -= cost
won[winner].add(name)
auction_log.append({"round": r, "seat": winner, "power": name, "cost": cost})
```

- **Winner pays exactly its own bid; the loser pays nothing.**
- **Equal non-zero bids** → coin flip from the deal-seeded `sym` stream (the mirror
  leg flips the same outcome to the other seat via `tie_flip`); the winner still
  pays its bid.
- **Both zero** → no award.
- The affordability check (engine.py:894-896) exists but is unreachable under the
  shipped config: `SLOTS_PER_ROUND = 1` means one power per round, and your bid
  vector was already zeroed if it exceeded `te_mine` at bid time.
- The win (power name + price paid) is public on the tape. Losing bids stay private.
- Budget: 24 TE per deal (game_config.py:98), shared across the deal's five
  auctions; no carry-over between deals, no replenishment between rounds. Unspent
  TE settles at 0.08 PnL per point of *difference* (see §5), so 1 tick = 12.5 TE
  and the whole budget is worth 1.92 ticks banked.
- What the winner gets: the power's effect for that round (FORESIGHT leak,
  TRICK_ROOM shift, SUBSTITUTE loss cap), for the rest of the deal
  (STEALTH_ROCK, persistent — `PowerState.persistent`, engine.py:169-170), or the
  swap option (TRANSFORM).

### The five powers (config table game_config.py:210-236)

| Power | magnitude | eligible rounds | once/deal | effect |
|---|---|---|---|---|
| FORESIGHT | 16 | 1–5 | no | shown `min(16, 4r)` of the opponent's revealed coins, sampled without replacement (engine.py:624-645); this round only, via `obs.foresight` |
| TRICK_ROOM | 3 | 1–5 | no | forced midpoint fill shifts 3 ticks in your favour, this round only |
| SUBSTITUTE | 2 | 1–5 | no | your loss on this round's contract capped at 2 ticks at settlement; profit uncapped; refund paid by the counterparty |
| STEALTH_ROCK | 2 | 1–4 | yes | every forced fill for the remainder of the deal (incl. this round) shifts 2 ticks in your favour |
| TRANSFORM | 0 | 1–3 | yes | the swap option (§3) |

Fill shift (`fill_shift`, engine.py:670-686): for each seat holding TRICK_ROOM /
STEALTH_ROCK, add `+magnitude` if that seat is the short, `−magnitude` if the long.
Opposing holders cancel exactly. Applied only to forced fills:
`fill_price = (bid + ask) // 2 + shift` (engine.py:806 — Python **floor** division,
rounds toward −∞).

### The negotiation endgame (who forces, who is short)
`MIDPOINT_SIDE_RULE = "last_quoter_sells"` (game_config.py:180). A forced fill only
happens if **all five responses (turns 2–6) were counters**, and the turn-6 speaker
is always the **Taker** (turns 2/4/6 = Taker, 3/5 = Maker). Therefore under the
shipped config, on every forced fill: **the Taker is the last quoter, hence the
short (seller), hence the forcer, and pays the 2.0 forcing fee; the Maker is always
long**. (Contract built at engine.py:817-820 with `forcer=last_quoter`.)

---

## 5. PnL and scoring

Settlement order in `play_deal` (engine.py:1259-1293), all as zero-sum transfers:

1. **Raw contract PnL** (engine.py:1262-1265), for each of the 5 contracts:
   `raw = S − price`; long seat `+raw`, short seat `−raw`. Integer arithmetic.
2. **Maker obligation** (`apply_maker_obligation`, engine.py:920-972), per contract:
   ```python
   width    = c.open_ask - c.open_bid
   straddle = c.open_bid <= score <= c.open_ask       # inclusive both ends
   p_w      = config.straddle_prob(c.round, width)    # exact lattice prob
   amount   = +3.0 * (1 - p_w)  if straddle else  -3.0 * p_w      # to the maker
   amount  -= 0.22 * max(0, width - final_cap(round)) # width premium, always
   pnl[maker] += amount; pnl[taker] -= amount
   ```
   `MAKER_OBLIGATION = 3.0` (game_config.py:146), `WIDTH_PREMIUM = 0.22`
   (game_config.py:174). `straddle_prob(r, w)` (game_config.py:477-498) is the
   exact probability that a width-`w` window centred on the posterior contains the
   residual of `m = 40 − 4r` unseen coins (`_lattice_straddle`,
   game_config.py:34-53 — binomial mass over even offsets in
   `[-(w//2), w − w//2]`). An honestly-centred maker breaks even in expectation at
   **every** width; the premium is a pure cost of width above the floor.
3. **Forcing fee** (`apply_forcing_fee`, engine.py:975-998): each forced contract
   with `forcer >= 0` transfers `FORCED_FILL_FEE = 2.0` from the forcer to the
   counterparty.
4. **SUBSTITUTE** (`apply_settlement_powers`, engine.py:701-723): for each round a
   seat held it, `raw = (S − price)` if long else `(price − S)`; if `raw < −2.0`,
   the counterparty refunds `(−2.0) − raw` (loss floored at exactly −2).
5. **TE salvage** (engine.py:1291-1293):
   `pnl[0] += 0.08 * (te_left[0] − te_left[1])`, and the negation for seat 1.
   `TE_SALVAGE = 0.08` (game_config.py:99).
6. **Zero-sum assertion**: `|pnl0 + pnl1| > 1e-9` raises (engine.py:1303-1308).

Match level (engine.py:1424-1462): deal PnLs summed; if a bot's hard-time
violations exceed `MAX_TIME_VIOLATIONS = 5` the remaining deals are skipped and
`FORFEIT_PNL = 250.0` is transferred to the opponent.

### Every `GameConfig` constant (game_config.py, literal values)

| Constant | Value | Line | Controls |
|---|---|---|---|
| `N_COINS` | 40 | 80 | total coins; also the ±reach clamp for quotes |
| `N_PRIVATE` | 20 | 81 | coins per hand |
| `N_ROUNDS` | 5 | 82 | rounds per deal |
| `REVEAL_PER_ROUND` | 4 | 83 | coins revealed to you per round |
| `DEALS_PER_PHASE` | 10 | 86 | default deals; mirror doubles to 20 |
| `TE_BUDGET` | 24 | 98 | TE per deal |
| `TE_SALVAGE` | 0.08 | 99 | PnL per point of unspent-TE *difference* |
| `TIE_RULE` | "coin_flip" | 112 | equal non-zero bids → flip, winner pays |
| `N_TURNS` | 6 | 135 | 1 open + 5 responses |
| `MIN_REDUCTION` | 1 | 136 | min spread shrink per counter (above floor) |
| `SPREAD_C` | 0.5 | 142 | coefficient in `final_cap` formula |
| `FORCED_FILL_FEE` | 2.0 | 145 | paid by the final-turn counterer |
| `MAKER_OBLIGATION` | 3.0 | 146 | λ in the obligation transfer |
| `WIDTH_PREMIUM` | 0.22 | 174 | per tick of opening width above the floor |
| `MIDPOINT_SIDE_RULE` | "last_quoter_sells" | 180 | forced-fill short side |
| `SLOTS_PER_ROUND` | 1 | 246 | powers drawn onto the block per round |
| `SLATE_MODE` | "draw" | 251 | slate is sampled from the eligible pool |
| `POWERS_PER_ROUND` | 2 | 256 | ceiling (inert in draw mode) |
| `TIME_BUDGET_MS` | 2.0 | 262 | advisory average; warned locally, never scored |
| `HARD_TIME_LIMIT_MS` | 50.0 | 263 | per-call hard limit; violations counted |
| `MAX_TIME_VIOLATIONS` | 5 | 272 | 6th violation forfeits the match |
| `FORFEIT_PNL` | 250.0 | 277 | transfer on forfeit |
| `BOT_MEMORY_LIMIT_MB` | 512 | 280 | OS memory cap per worker |
| `MATCH_TIMEOUT_S` | 600.0 | 289 | CPU-seconds backstop per worker per match |
| `ZERO_SUM_TOL` | 1e-9 | 292 | zero-sum assertion tolerance |
| `MAX_REASONABLE_VALUE` | 10000 | 293 | output clamp |

Derived (formulas at game_config.py:419-460):
`final_cap(r) = max(1, round(4·0.5·sqrt(6−r)))` → **4, 4, 3, 3, 2** for r = 1..5;
`spread_cap(r) = final_cap(r) + 5` → **9, 9, 8, 8, 7**;
`unknown_to_both(r) = 40 − 8r` → 32, 24, 16, 8, 0;
`residual_sd(r) = sqrt(40 − 4r)` → 6.00, 5.66, 5.29, 4.90, 4.47;
`sigma_score() = sqrt(40) ≈ 6.32`;
`straddle_prob(r, width=None→spread_cap(r), unseen=None→40−4r)`;
`baseline_straddle(r) = straddle_prob(r, spread_cap(r))`;
`offered_powers(r)` = eligibility pool (NOT the slate);
`open_width_floor(r) = final_cap(r)`.

---

## 6. Baselines

### `strategies/naive_ev.py` — full source

```python
# Name: Quantstorm Reference Bot
# College: Quantstorm
# Roll Number: REF-000

"""
naive_ev.py — Baseline: Naive Expected-Value Bot
==================================================

Strategy:
  • Prices the score as E[S | my coins] = sum(my_revealed).
  • Ignores the opponent's opening quote entirely.
  • Never bids on powers.

This is the zero-shot archetype. If you can't beat it, you ARE it.
The tournament gate filters out entries that lose to NaiveEV.

Why it's weak, worst first:
  • Never bids, so the opponent buys every power it wants at its own price.
    Worth +56.1 ± 4.8 ticks/match to the opponent -- nearly twice what
    ignoring the quote costs.
  • Ignores the opponent's opening quote, which is the only clean read of
    their hand in the game. Worth +31.0 ± 7.0 ticks/match.
  • Opens at the maximum width every round and pays WIDTH_PREMIUM for it
    without getting anything for the option.
  • Doesn't adjust for FORESIGHT leaks or any power effects.

Beating it requires both halves. A bot that reads perfectly and never bids
(see rational.py) still loses to one that prices naively and bids sensibly.
"""

import random


class Bot:
    name = "NaiveEV"

    def reset(self, seat, config, seed):
        self.seat = seat
        self.config = config
        self.rng = random.Random(seed)

    def bid(self, obs, offered):
        # Never bid on anything — this is the zero-shot baseline
        return {}

    def quote(self, obs):
        # Centre on E[S | my coins] = k_mine (opponent coins are mean-zero to us)
        v = obs.k_mine + sum(obs.foresight)  # use FORESIGHT if we got it free
        cap = obs.spread_cap
        lo = round(v) - cap // 2
        return (lo, lo + cap)

    def respond(self, obs, quote, turn):
        bid, ask = quote
        v = obs.k_mine + sum(obs.foresight)

        # Accept if our value estimate is outside the range
        if v > ask:
            return "ACCEPT_BUY"
        if v < bid:
            return "ACCEPT_SELL"

        # Counter toward our estimate
        w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
        center = max(bid, min(round(v), ask - w))
        return ("COUNTER", center, center + w)

    def use_transform(self, obs):
        """Fire the swap only from a flat hand. ..."""
        return abs(obs.k_mine) <= 1
```

Decision rules: `reset` stores seat/config/RNG. `bid` always `{}` (concedes every
auction). `quote` centres on `k_mine + sum(foresight)` at **maximum width**
(spread_cap). `respond` accepts only when its estimate lies strictly outside the
range, otherwise counters toward its estimate with the minimum 1-tick shrink —
including on turn 6, so it walks into forced fills and forcing fees. `use_transform`
fires iff `|k_mine| ≤ 1`.

### `strategies/rational.py` — full source

```python
# Name: Quantstorm Reference Bot
# College: Quantstorm
# Roll Number: REF-000

"""
rational.py — Baseline: Rational Pricing Bot
==============================================

Strategy:
  • As Maker: centres quote on k_mine (broadcasts its hand honestly).
  • As Taker: reads the Maker's opening quote to infer their revealed sum,
    then estimates S = k_mine + inferred_opponent_sum.
  • Never bids on powers.

Why it's stronger than NaiveEV:
  • Uses the opponent's quote as a signal, worth +31.0 ± 7.0 ticks/match
    against an opponent identical in every other respect.
  • Optimal posterior given an honest opponent: E[S] = k_mine + k_theirs.

Why it's still beatable, in order of how much it costs:
  • Never acquires powers. [...]
  • Opens at the widest legal width every round, and pays WIDTH_PREMIUM [...]
  • Reads the opponent's quote at face value with no distortion correction.

WITHDRAWN. Earlier versions of this docstring claimed "a Maker that distorts
its quote can exploit this (measured at -240/match)". That number did not
survive replication [...] Distortion is priced monotonically and does not pay.
Do not build an entry around beating it.

This is the honest-play reference point, not a target to converge on.
"""

import random


class Bot:
    name = "Rational"

    def reset(self, seat, config, seed):
        self.seat = seat
        self.config = config
        self.rng = random.Random(seed)
        self._anchor = {}

    def _get_anchor(self, obs, quote):
        r = obs.round
        if r not in self._anchor:
            if not obs.is_maker and quote is not None:
                # As taker, the quote midpoint ≈ maker's k_mine
                self._anchor[r] = (quote[0] + quote[1]) / 2
            else:
                self._anchor[r] = 0.0
        return self._anchor[r]

    def _value(self, obs, quote=None):
        if obs.is_maker or quote is None:
            return float(obs.k_mine + sum(obs.foresight))
        anchor = self._get_anchor(obs, quote)
        if obs.foresight:
            leak_sum = sum(obs.foresight)
            anchor = 0.5 * anchor + 0.5 * leak_sum
        return float(anchor + obs.k_mine)

    def bid(self, obs, offered):
        return {}

    def quote(self, obs):
        v = round(obs.k_mine + sum(obs.foresight))
        cap = obs.spread_cap
        lo = v - cap // 2
        return (lo, lo + cap)

    def respond(self, obs, quote, turn):
        bid, ask = quote
        v = self._value(obs, quote)

        edge_buy = v - ask    # profit from buying at ask
        edge_sell = bid - v   # profit from selling at bid

        if edge_buy > 0 and edge_buy >= edge_sell:
            return "ACCEPT_BUY"
        if edge_sell > 0:
            return "ACCEPT_SELL"

        w = max(0, (ask - bid) - self.config.MIN_REDUCTION)
        center = max(bid, min(round(v), ask - w))
        return ("COUNTER", center, center + w)

    def use_transform(self, obs):
        return abs(obs.k_mine) <= 1
```

Decision rules: as Taker it **latches the first quote midpoint it sees each round**
as an estimate of the Maker's revealed sum and never re-anchors; value estimate is
`anchor + k_mine`, blending the anchor 50/50 with a FORESIGHT leak sum when held.
Accepts on any positive edge (buy if `v > ask`, sell if `v < bid`, choosing the
larger edge). Otherwise counters toward its value with the minimum shrink. As Maker
it quotes honestly at **maximum width**. Never bids. Transform: fires iff
`|k_mine| ≤ 1`.

### `strategies/adaptive_bidder.py` — full source

```python
# Name: Quantstorm Reference Bot
# College: Quantstorm
# Roll Number: REF-000

"""
adaptive_bidder.py — Strategy 1: State-Conditional Power Bidder
================================================================

Core idea: Value each power based on the CURRENT game state, not
a fixed table. Shade bids at 0.60 of fair value (first-price auction).
[... long docstring: per-round power values are measured; TRANSFORM is bid
from both sides (fire from a flat hand, veto from a decisive one); denial
weight shipped at 0.0 but flagged as a stale measurement worth re-running;
the slate is drawn so TRANSFORM appears in ~1/3 of deals ...]
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

SHADE = 0.60            # fraction of fair value to bid (first-price shading)
FLAT_THRESHOLD = 1      # |k_mine| <= 1 counts as a flat (swappable) hand
OPP_FLAT_THRESHOLD = 2.0
DENIAL_WEIGHT = 0.0     # shipped at zero; docstring flags it as stale


class Bot:
    name = "AdaptiveBidder"

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
        return POWER_VALUES.get(name, {}).get(obs.round, 0.5)

    def _transform_value(self, obs):
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
        # Width stance: the FLOOR (tightest legal opening).
        cap = obs.final_cap
        lo = v - cap // 2
        return (lo, lo + cap)

    def respond(self, obs, quote, turn):
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

    def use_transform(self, obs):
        return abs(obs.k_mine) <= FLAT_THRESHOLD
```

(The long docstring and comment blocks are reproduced above in abbreviated form
where they are commentary; every executable line is verbatim.)

Decision rules: prices each offered power off a **per-round measured value table**,
converts ticks → TE at `v / 0.08` (12.5 TE per tick), and bids `0.60 ×` that,
capped at `te_mine`. Example: round-5 FORESIGHT → `int(2.02/0.08 × 0.60)` =
15 TE. TRANSFORM: full value from a flat hand (`|k_mine| ≤ 1`); from a decisive
hand, `DENIAL_WEIGHT = 0.0` × value even when the opponent looks flat (i.e. it
never actually pays for denial as shipped). Quotes honestly at the **floor** width.
Responds like `rational`, plus a 1-tick looser accept threshold when it holds
SUBSTITUTE. Transform fires iff `|k_mine| ≤ 1`.

---

## 7. Hard constraints

### Time
- `HARD_TIME_LIMIT_MS = 50.0` per call, any method incl. `reset`. Exceeding it is a
  counted violation (`TimeTracker.record`, engine.py:101-110). The **6th** violation
  (`violations > MAX_TIME_VIOLATIONS = 5`) forfeits the match: −250 PnL transfer
  and the remaining deals are skipped (engine.py:1443-1462).
- `TIME_BUDGET_MS = 2.0` average is **advisory only** — the backtester prints a
  warning above 2 ms average (backtester.py:169-170); nothing in the engine scores it.
- Under `--isolate`: on POSIX an in-worker `setitimer` alarm aborts the call at
  50 ms (sandbox.py:120-151, armed at 393-398); the call takes its fallback and the
  engine marks the bot **failed for the rest of the deal** (BotTimeout handling,
  engine.py:259-267). On **Windows there is no alarm** (sandbox.py:137-138): the
  parent kills the worker only when a call burns > `_cpu_kill_s` =
  `max(2×50ms, 50ms+50ms)` = **100 ms of CPU** (sandbox.py:462-469, 638-650) or
  goes unresponsive past `_deadline_s = max(2.0, 20×0.05)` = **2.0 s wall**
  (sandbox.py:470-473, 651-657). A killed worker ends the bot's deal
  (`_dead_this_deal`, sandbox.py:739-746). A 50–100 ms call on Windows completes,
  is *used*, and merely records a violation. RULEBOOK §11 explicitly warns the
  graded run assumes the stricter (POSIX/container) behaviour.
- Timing charged is measured **inside the worker around your call**
  (`last_call_ms`, engine.py:274-277; sandbox.py:387-400) — IPC not billed.
- `MATCH_TIMEOUT_S = 600` CPU-seconds per worker per match, OS-enforced
  (RLIMIT_CPU / Job Object `PerProcessUserTimeLimit`, limits.py:97, 292-294).

### Memory / processes / filesystem
- 512 MB address-space cap per worker: `RLIMIT_AS`+`RLIMIT_DATA` on POSIX
  (limits.py:95-96), Job Object `ProcessMemoryLimit` on Windows (limits.py:295).
  Exceeding it → `MemoryError` in your frame → scored as a crashed call.
- No child processes (`RLIMIT_NPROC 0` / `ActiveProcessLimit 1`, limits.py:99, 291).
- No file writes (`RLIMIT_FSIZE 0` on POSIX; `open` deleted from builtins + audit
  hook everywhere, policy.py:211-213, 300-305).

### Imports and language (policy.py / bot_loader.py)
- Allowed imports (`ALLOWED_MODULES`, policy.py:79-82): `math`, `random`,
  `statistics`, `collections`, `heapq`, `bisect`, `itertools`, `functools`,
  `typing`. Plus `from __future__ import annotations` (and the internal
  `annotationlib`) via `_LANGUAGE_MODULES` (policy.py:97-101). Nothing else — no
  numpy/scipy/pandas.
- Static gate (bot_loader.py): rejects illegal imports, relative imports, calls to
  `__import__ eval exec compile open input globals vars breakpoint memoryview`
  (line 57-60), and attribute access to `__class__ __bases__ __mro__
  __subclasses__ __globals__ __builtins__ __code__ __closure__ __dict__
  __getattribute__ __reduce__ __reduce_ex__ __loader__ __spec__ f_back f_locals
  f_globals f_builtins tb_frame tb_next gi_frame cr_frame _getframe
  __traceback__` (line 66-72). The same names appearing as *string literals* only
  produce a warning, not a rejection (line 190-195).
- Runtime (worker) backup: module cache purged, builtins rewritten
  (`open/input/breakpoint/help/exit/quit` removed, `__import__` guarded —
  policy.py:211-213, 221-234), and an un-removable audit hook denies imports
  outside the allowlist, `exec`/`eval`/`compile` (with narrow carve-outs so
  `collections.namedtuple`, `typing.NamedTuple` and stringified annotations still
  work — policy.py:429-544), `open`, frame access, and all os/socket/ctypes/etc.
  event families (policy.py:284-305, 605-666).

### Failure handling (fallback table, engine `BotWrapper`)
| Failure | Result |
|---|---|
| `__init__` or `reset()` raises/times out | bot `failed` for the whole deal; every call below takes its fallback (engine.py:189-208, 282-286) |
| `bid()` fails | `{}` — bid nothing this round (engine.py:300-306) |
| `quote()` fails | `(-(cap//2), cap − cap//2)` — centred ~0 at max width (engine.py:397-399) |
| `respond()` fails | `"ACCEPT_BUY"` at the current ask (engine.py:489-496) |
| `use_transform()` fails | `False` — decline (engine.py:515-519) |
| In-worker timeout (POSIX isolate) | fallback + 1 violation + **rest of deal all fallbacks** (engine.py:259-267) |
| Worker killed (CPU/deadline/memory/segfault) | same as timeout; worker restarted for the next deal (sandbox.py:579-583, 697-737) |
| Invalid/exotic return type | reduced/normalised in the worker (sandbox.py:176-241); anything unreducible = crashed call → fallback |

### Statelessness
- **Within a deal (5 rounds): state persists** — instance attributes set in
  `reset()` survive all calls of the deal.
- **Between deals: enforced wipe.** A fresh `Bot()` per deal (engine.py:1411-1414);
  under `--isolate` the submission module is **re-executed from source** each deal
  (sandbox.py:353-374) and `StateGuard` restores every importable module's globals
  and class attributes to a pristine snapshot, reseeding `random`'s global
  generator with `derive_seed("deal-state", filename, deal_index)`
  (policy.py:311-412; sandbox.py:721-724). Detected tampering is recorded and
  surfaced (`sandbox.tampering`). RULEBOOK §8: the graded run additionally uses a
  brand-new interpreter per deal (`fresh_process_per_deal`, sandbox.py:437, 709-715).
- **Between matches: nothing survives** (separate processes per pairing).
- **Plain local runs (no `--isolate`) do NOT enforce any of this** — module globals
  persist across deals in-process (engine.py:1407-1410 comment). That is exactly
  the divergence `--isolate` exists to expose.

### What `--isolate` strips away (vs a plain run)
Separate spawn-mode process per bot (engine's `hands`/`score` not in your address
space), OS memory/CPU/process caps, per-call timeout enforcement with kills,
module re-execution + StateGuard between deals, purged module cache, rewritten
builtins, audit hook, return-value normalisation over the pipe. A plain run gives
you none of these — only output clamping and exception catching.

---

## 8. Commands

Dependencies: **Python ≥ 3.10, stdlib only** (README). No third-party packages.

```bash
# Duel two bots (defaults in backtester.py:56-57 are rational vs naive_ev)
python backtester.py --bot1 strategies/my_bot.py --bot2 strategies/rational.py

# Run with no args → rational vs naive_ev, 10 deals + 10 mirrors, seed 42, verbose
python backtester.py

# Deals per phase (mirror doubles it). NOTE: --n_deals 0 falls back to 10
python backtester.py --n_deals 50 --quiet

# Seed (default is the FIXED value 42 from backtester.py:62, not random)
python backtester.py --seed 123

# Mirroring: on by default; disable with
python backtester.py --no_mirror

# Force an exact 40-coin vector for every deal
python backtester.py --coins "+1,-1,+1,...(40 values)"

# Override who is Maker in round 1 (0 = bot1, 1 = bot2)
python backtester.py --first_maker 1

# Tournament conditions: sandboxed processes, enforced limits, per-deal reload
python backtester.py --bot1 strategies/my_bot.py --bot2 strategies/rational.py --isolate

# Static submission check (nothing executed). Exit 0 = accepted, 1 = rejected.
python backtester.py --validate strategies/my_bot.py
```

Reading the output (`print_summary`, backtester.py:123-203):
- Verbose per-round log: coin vector and `S` (shown to *you*, the operator), each
  seat's hand, reveals, TE, auction bids and winner+cost, TRANSFORM fire/decline,
  each negotiation turn with per-call ms, contract line, then the settlement
  breakdown (raw PnL per contract, maker obligation per round, forcing fees, TE
  salvage, final PnL with the zero-sum check).
- MATCH SUMMARY: aggregate / mean-per-deal / stdev PnL per bot, W/D/L record,
  timing (avg/max/total ms per call; ">2ms avg" warning), all warnings (clamps,
  violations, crashes), and a per-deal breakdown where rows alternate
  Direct/Mirror (deal 1 direct, deal 2 its mirror, ...).
- `--isolate` additionally prints load errors and "NO OS resource caps" warnings
  after the match (backtester.py:379-384).

There is no CLI flag for "number of matches" — one invocation = one match; loop it
yourself with different `--seed` values.

---

## 9. Gotchas, discrepancies, and edge cases

**Documentation vs engine (engine wins):**

1. **`starter_bot.py:85` is flat wrong**: "Bids totalling more than obs.te_mine are
   scaled down proportionally." The engine **zeroes every bid** in an over-budget
   vector (engine.py:368-375), and RULEBOOK §4 + starter_bot.py:137 say so
   correctly. Never trust the starter docstring's auction paragraph.
2. **RULEBOOK §3 opening line** says a match is "N direct deals, then N mirror
   deals" in two phases; the engine interleaves direct/mirror per deal
   (engine.py:1391-1394). The RULEBOOK corrects itself two paragraphs later; the
   backtester labels rows accordingly.
3. **RULEBOOK §6 "If nobody ever countered, the Maker quoted last and is the
   seller"** — unreachable in the shipped config. A forced fill requires all five
   responses (turns 2–6) to be counters, and turn 6 is always the Taker's. So on
   every forced fill the **Taker is short, is the forcer, and pays the 2.0 fee**;
   the Maker is always long. This materially changes what TRICK_ROOM/STEALTH_ROCK
   are worth to you in each role.
4. **RULEBOOK §4 rule 4** (winner's bid exceeding remaining TE → power not awarded,
   engine.py:894-896) is dead code under `SLOTS_PER_ROUND = 1` + bid-time zeroing.
5. `game_config.py:602` comments `final_cap` as "Max final spread" — it is actually
   the *minimum opening width* / negotiation floor (RULEBOOK and engine agree).
6. The engine's fallback quote `(-(cap//2), cap − cap//2)` is centred on +0.5 for
   odd caps (e.g. `(-4, +5)`), not exactly 0 as RULEBOOK's table says. Cosmetic.

**PnL math details a naive bot gets wrong:**

7. **`S` is always even** (sum of 40 ±1 coins), and so is the residual
   `S − k_mine` (sum of `40−4r` coins, always an even count). Consequences:
   - The lattice straddle probability is a step function:
     `p_w` is **identical for widths 4, 5, 6** (even-offset masses `{-2,0,2}`),
     and identical for 8, 9, 10, etc. Choosing width 5 or 6 over 4 buys zero
     straddle probability and costs 0.22/tick of width premium — the extra width
     only buys negotiation room. `straddle_prob` is exact; use it, don't use a
     normal approximation (game_config.py:34-53, 477-498).
   - A price estimate at an odd integer is never equal to `S`; edges should be
     evaluated knowing `S` sits on the even lattice.
8. **Floor division everywhere**: forced-fill midpoint `(bid+ask)//2`
   (engine.py:806) rounds toward −∞ (an odd-sum range fills 0.5 tick low —
   good for the long, i.e. the Maker, per #3). Quote/counter re-centring uses
   `//2` the same way (engine.py:443-449, 590-594). Float returns are
   **truncated toward zero** by `int()`, not rounded (engine.py:417, 556).
9. **Maker obligation is scored against the *opening* quote only** — inclusive on
   both ends (`open_bid <= S <= open_ask`, engine.py:955), at the width you
   actually opened, with `unseen = 40 − 4r` (assumes no foresight). If you hold a
   FORESIGHT leak of `f` coins as Maker, your true straddle rate at the same width
   is `straddle_prob(r, w, unseen=40−4r−f)` > `p_w`, so honest-centred quoting
   with foresight has strictly positive obligation EV. Conversely, off-centring
   your quote to deceive costs obligation EV monotonically (rational.py's
   WITHDRAWN note: distortion measured not to pay).
10. **SUBSTITUTE caps the raw contract leg only** (strictly below −2.0 triggers a
    refund to exactly −2; engine.py:718-723). Forcing fees, obligation transfers,
    and salvage are NOT capped. Profit uncapped.
11. **TE salvage is on the difference** of leftovers, not your absolute leftover
    (engine.py:1291): spending TE only costs you 0.08/point *relative to the
    opponent*; if both sides spend the same, salvage nets zero.

**Mechanics that reward/punish specific behaviours:**

12. **Over-budget bid = conceded auction** (engine.py:368-375). Track your TE
    yourself; `obs.te_mine` is authoritative at bid time.
13. **Both bidding 0 kills the power** — there are no free powers; and a 1-TE bid
    against a 0-bid opponent wins outright. Against never-bidding opponents
    (naive_ev, rational) **every power costs 1 TE**.
14. **Ties are coin flips and the winner still pays** — matching a predictable
    opponent's bid is a 50% win at full price, not free denial.
15. `respond` accepts only the exact strings `"ACCEPT_BUY"`/`"ACCEPT_SELL"` and
    the exact first element `"COUNTER"` — case-sensitive; anything else silently
    becomes `ACCEPT_BUY` at the ask (engine.py:545-567), which is about the worst
    default possible. Same for power names in `bid()` keys.
16. **Width-0 counters are legal** (no minimum width, engine.py:588-594): counter
    `(x, x)` pins the price; the opponent's only moves are accept at `x` or ride
    to a forced fill at `x + shift` (with the turn-6 forcer paying 2).
17. **A Maker opening at the floor is take-it-or-leave-it** — counters cannot
    shrink below `final_cap`, so the range can only be relocated inside itself,
    and at floor width it cannot move at all (`max_width = w` when `w ≤ floor`,
    but the counter must stay *inside* the current range, so a floor-width counter
    inside a floor-width range is the identity). The Taker's real choices are
    accept, or force and pay 2.
18. **All three baselines counter on turn 6 whenever their estimate is inside the
    range** — they systematically eat the 2-tick forcing fee and the forced-fill
    short side. Their opening quotes are honestly centred on
    `round(k_mine + sum(foresight))`, so the opening midpoint hands you their
    revealed sum ±0.5 (this is what `rational`'s anchor exploits).
19. `obs.contracts[i].open_bid/open_ask` is the only clean read of a past Maker's
    information; later ranges are contaminated by both sides (RULEBOOK §9,
    game_config.py:618-638).
20. **FORESIGHT leak arrives only in the round it was won** (`obs.foresight` reset
    to `()` afterwards) — remember it yourself in instance state. It samples
    without replacement from the opponent's *revealed* coins: round 4 gives you
    their entire revealed set (16 of 16); round 5 gives 16 of 20.
21. **TRANSFORM detection**: the win+cost is public on the tape, the *firing* is
    not — but you can detect it by comparing `obs.my_revealed` to the copy you
    remembered; if the prefix changed, the swap fired. A bot that doesn't track
    this misprices everything after a swap. Also note `use_transform`'s Obs never
    contains foresight, and the decision cannot be deferred past the round.
22. **STEALTH_ROCK is worthless in round 5** (not eligible) and its forced-fill
    shift only pays if forced fills actually happen — against an opponent who
    always accepts by turn 6 it never fires. Same for TRICK_ROOM.
23. **Timing on Windows is deceptively forgiving**: no in-worker alarm, kills only
    at ~100 ms CPU / 2 s wall. RULEBOOK §11 says assume the POSIX behaviour
    (abort at 50 ms + rest-of-deal forfeit). Do not calibrate timing on a local
    Windows run.
24. `reset()` is timed too — a slow `reset` collects violations like any call.
25. **Local non-isolate runs let state leak across deals** (module globals
    persist) and enforce no time limits — a bot that scores differently under
    `--isolate` is broken for the tournament (README/RULEBOOK, and the engine
    comment at engine.py:1407-1410).
26. **The backtester's default seed is 42** (backtester.py:62) and the leaderboard
    runs on fixed seeds against 10 hidden bots — a locally-great score on seed 42
    is one sample. Vary seeds.
27. The engine's per-call charge under `--isolate` comes from
    `getattr(self.bot, "last_call_ms", ...)` (engine.py:274-276). In-process
    (non-isolate) a bot exposing its own `last_call_ms` attribute could spoof
    local timing — irrelevant in the tournament, where the SandboxedBot adapter
    supplies it, but don't fool yourself locally.
28. The `sym` RNG stream is consumed by both tie flips and foresight sampling in
    play order (engine.py:887, 1213); across the two legs of a mirrored deal the
    stream stays aligned only if the legs' auction outcomes are symmetric — with
    two identical bots it is, which is what makes self-play net exactly 0.0.
    Against different bots it is just deterministic-but-path-dependent noise.
29. Submission-side sandbox trivia that can bite honest code: builtins `help`,
    `exit`, `quit`, `open`, `input`, `breakpoint` are deleted in the worker
    (policy.py:211-213); `getattr(x, "__class__")`-style strings only warn but the
    attribute forms are hard rejections; `collections.namedtuple` /
    `typing.NamedTuple` / `from __future__ import annotations` are explicitly
    supported (policy.py:429-544).
30. **Deadlines (README)**: leaderboard submissions use the Unstop registration
    email, 10-minute cooldown, any (appropriate) filename but real Name/College in
    the header comments. The final Google-form link appears in the README at
    11:00 PM and closes **11:59 PM, 17 August** — and the form accepts your final
    strategy **once**.
