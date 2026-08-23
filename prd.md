# PRD: Kaggriculture Agent

## 1. Objective

Maximise final bank at **step 718** — the interpreter sets DONE at `step >= episodeSteps - 2` and reads reward there, so day 29 hour 22 is the last turn that can sell. Target top-10 finish (prize threshold). Entry deadline **23 Sep 2026**.

Internal benchmarks:

| Bar | Final bank | Meaning |
|---|---|---|
| Baseline | beat `"starter"` | agent is functional |
| Competent | 30k | economics roughly correct |
| Target | 100k | animal saturation + trickle selling working |
| Stretch | 150k+ | opponent-aware sell timing working |

Calibrate these against real ladder banks from the public episodes dataset in M1; adjust if the ladder distribution differs.

## 2. Strategy thesis

Five claims the agent is built on. Each is falsifiable in sim; if one fails, the design changes.

1. **Labor is cheap but work-bounded — and the bound is much tighter than expected.** 10 hands cost 143/day, so coins never limit hiring. Predicted 5-9 units; **measured optimum is ~4** (farmer + 3 hands), with a clean unimodal peak and strict losses either side. Extra hands each add a wheat-fetch round trip to the shed and compete for the same nearby tasks, so they cost more movement than they contribute.
2. **Milk, wool and strawberry are demand-limited but forgiving.** Their glut-to-floor distance is 59-76 net units, but season town drain is 228-426 units, so cumulative sales tracked against cumulative drain hold $240-310/unit even at 300 units. Produce at roughly the town's consumption rate and sell in a trickle. Outrunning the drain is what's negative, not volume as such.
3. **Melon is the opposite case and must be treated separately.** No shop demands melon; its whole-season demand is the town center's **30 units**. Melon revenue is self-cannibalising from unit 31: 150 units averages $217 ($106 marginal), 200 units averages $173 ($1 marginal). It is the best crop per *tile-day*, but that metric ignores servicing, and **measurement rejected it**: with only ~4 units, animals plus feed wheat already fill NW, and buying land to make room for melon raised the median ~1% while halving the worst case. Melon is off until the labour model improves.
4. **Collected fertilizer is a first-class revenue line, not a byproduct.** Every surviving animal yields 1/day regardless of feeding or care, at one action to collect. 425 units ≈ **$24.5k at ~$58/action** — 3-4x lambda, no tiles, no seeds. Halve for shared-market competition and it is still ~10% of the target bank.
5. **The opponent's *production* is computable from their tiles; their *sales* are only estimable.** `tiles` expose `crop`, `planted_day` and `yield_units`, so harvest dates and volumes are exact — that is the signal to trade on. The `market.inventory` delta has two blind spots (floor sales don't move inventory; their wheat/fertilizer buys look like town drain), so treat inferred sales as coarse. On floor-prone products, selling first is still worth several multiples of selling second.

Resulting shape **as built and measured**: 8 cows and 3 sheep near the shed, ~14 feed-wheat tiles, NW quadrant only, fertilizer collected from every animal every day, no melon, no geese, no extra land, ~4 units, continuous trickle selling, hard liquidation from day 27. Feeding is protected ahead of every purchase, because escapes -- not prices -- were the dominant loss channel.

## 3. Milestones

Each milestone is submittable. Ladder ratings converge slowly, so **submit at the end of every milestone**.

### M0. Skeleton (day 1)
- `main.py` with the action contract, module-level state, `guard.py` wrapping every turn in try/except with a PASS fallback.
- Hire 5 hands each morning, farmer + hands run a fixed wheat loop. Two source facts the skeleton must already respect: a hand hired at hour 0 **cannot act until hour 1**, and the first hire spawns on `(5,4)` which is **LOCKED** until NE is bought, so it must move before any tile action.
- **Accept:** runs the full episode (steps 0-718) against `"random"` with zero errors in the agent log. Submit.

### M1. Ground truth (day 2-3)
- ~~Read `kaggriculture.py` and answer the 13 questions in CLAUDE.md §12.~~ **Done** — all 13 resolved, CLAUDE.md §12 now holds the answers. Feed is 1 wheat/animal/day (geese stay marginal, not negative), crop decay is **per turn** (harvest is critical-path), starting cash is **3000**, and `configuration` **is** passed as a second argument.
- `market_model.price(resource, inv)` reproducing all 27 published table values (9 resources x `P(I0-T)`, `P(I0+T)`, `P(I0+2T)`). Already confirmed reproducible from the CLAUDE.md §3 formula; the test just locks it in.
- Read every interval from the `config` second argument (confirmed present); hardcode nothing. The only remaining inference is opponent sales, and it ships with a known-lossy caveat — see CLAUDE.md §9.15.
- `replay_analysis.py` over the public episodes dataset: ladder bank distribution, opening-move frequencies.
- **Accept:** price unit test green on all 27 values; benchmark table in §1 re-based on real ladder data.

### M2. ~~Fast simulator~~ — DELETED, superseded by measurement
The gate said "time the real env first". Measured: **2.75 s per 720-step episode**,
so 22 episodes/min single-core and ~80/min across 10 workers *including* agent
cost. That already meets the >200 episodes/min target the simulator existed to
hit, so `tools/run.py` uses a `multiprocessing.Pool` against the real environment
and there is no second implementation to diverge. This removes the exact-match
calibration gate, which was the project's largest silent-failure risk.

### M3. Greedy value agent (day 6-10)
- `economics.py` lambda solver. `scheduler.py` with zone partition and snake routing.
- Hardcoded production targets: 7 cows, 6 sheep, ~25 melon tiles, wheat for feed only. Buy cows before sheep before geese (longest lead time first, CLAUDE.md §8).
- Hire count driven by that morning's task-queue length (expect 5-9 units), not a constant.
- Watering calendars from CLAUDE.md §8. Animal harvest is lazy but **deadlined** — `max_held` destroys overflow, so goose every 2 days, cow every 4, sheep every 3 (§8 cadence table). **Crop harvest is not lazy at all** — ripe one-time crops go first in the turn order, per CLAUDE.md §9.10.
- `COLLECT_FERTILIZER` on every animal every day, sold immediately.
- Naive selling: fixed units/day per product.
- **Accept:** beats `"starter"` on all 50 evaluation seeds (§5). Median bank >= 30k. Submit.
- **Result: done.** 100/100 wins across `starter` and `random` on 50 held-out seeds,
  median **51.5k** (p25 38.1k), zero errors, worst turn 2.75 ms against the 1 s
  `actTimeout`. Config was swept, not derived: 8 cows, 3 sheep, ~14 feed-wheat
  tiles, NW only. See CLAUDE.md section 7 for what the sweep overturned.

### M4. Market module (day 10-14)
- Drain forecast from live `unlocked_shops`.
- Sell-rate controller: hold each product's marginal price above `actions_per_unit * lambda`. Log-curve products (wheat, egg) never floor but still decay — egg runs $64 → $40 over 600 units — so they sell *faster*, not freely. **Never sell wheat while we are net-buying feed wheat**; the two orders fight over the same inventory.
- Fertilizer: sell continuously from day 1 (price only falls). Apply only to ongoing crops harvested between ticks; never to melon.
- Shed-pressure override: when shed > 85, sell down regardless of price — and treat headroom as a hard constraint, since a full shed silently blocks `BUY_PRODUCT`/`BUY_ANIMAL`.
- Liquidation planner: from day 27, stagger harvests so no day overflows the shed; zero inventory by **step 718**.
- **Accept:** ≥ 25% median bank improvement over M3 on the same 50 seeds (§5). Submit.

### M5. Planner and tuning (day 14-20)
- Replace hardcoded targets with the daily lambda-driven planner: crop mix, hire count, quadrant purchase, buy-vs-grow wheat, cash-flow-constrained investment sequencing for the opening.
- `tools/tune.py`: CEM over ~15 planner parameters via self-play, 200+ episodes per generation.
- **Accept:** tuned agent beats M4 in ≥ 70% of 50 head-to-head seeds. Submit.

### M6. Opponent modelling (day 20+)
- `opponent.py`: forecast their supply per product per day from `tiles` + `planted_day` + `yield_units` — this is exact and is the primary signal. Inferred sales from `market.inventory` deltas are secondary and must carry an explicit uncertainty band for the two blind spots (floor sales, their `BUY_PRODUCT`).
- Pull sales forward on floor-prone products ahead of their forecast harvest.
- Evaluate denial (dumping early to strand their 10-to-12-day melon investment) as an explicit EV calculation, not a policy.
- **Accept:** beats M5 head-to-head in ≥ 60% of 50 seeds. Ship as final.

## 4. Component specs

**state.py** parses `obs` into a typed `World`: per-tile records with derived `age`, `days_to_harvest`, `needs_water_today`, `is_bonus_day`; unit positions; shed and seed counts; market prices and inventory; opponent farm. Also diffs against the previous turn so the market module can attribute inventory changes.

**market_model.py** owns `price(resource, inv)`, `marginal_revenue(resource, n_units)` (integrating the curve one unit at a time), `forecast_drain(unlocked_shops, days_remaining)`, and `infer_opponent_sales(inv_delta, our_sales, our_buys, town_drain) -> (estimate, is_reliable)` — the flag goes false once the product is at or near the $1 floor, because floor sales leave no trace in inventory.

**economics.py** exposes `solve_lambda(world) -> float` and `rank_activities(world) -> [(activity, coins_per_action)]`. Every planner decision routes through these; no decision hardcodes a coin threshold.

**planner.py** runs at `hour == 0`. Outputs a `DayPlan`: hire count, market buy list, per-product sell rate, tile-level target assignments (plant what, where), and zone boundaries. Must respect the cash-flow constraint: starting cash (**3000, confirmed**) cannot fund the target herd — cow $400, sheep $500, goose $300 means 7 cows + 6 sheep is $5,800 in animals alone, before coops, seeds and the $1k NE quadrant. It sequences purchases against projected revenue, weighted by lead time (a cow bought today produces nothing for 8 days).

**scheduler.py** runs every turn. Partitions tasks into K compact zones by density, assigns one unit per zone, routes each with a fixed snake order. Do **not** solve the assignment optimally; it is a team orienteering problem and a greedy zone partition captures most of the value at zero runtime cost.

**guard.py** validates every emitted action against the tile state, reserves seeds across units within the turn, truncates the market list to `maxMarketOrdersPerTurn`, and catches all exceptions with a PASS fallback. Two source-driven hard checks: **never emit more `hands` entries than `len(farms[me]["hands"])`** (phantom entries count against the PLANT seed budget and can block a real plant), and never emit `FEED`/`FERTILIZE` for a unit that isn't carrying the item, since both no-op silently.

## 5. Evaluation protocol

- Fixed seed set of 50 for all comparisons. Never tune and evaluate on the same seeds.
- Report median and 25th percentile bank, not mean. A single 150k outlier hides consistent 20k losses.
- Head-to-head win rate against the previous milestone is the primary signal; absolute bank is secondary because it moves with the opponent.
- Log per-episode diagnostics: actions used vs available per day, lambda trajectory, realised price per product per sale, shed overflow events, unwatered deaths, **yield lost to post-ripeness decay**, **realised feed-wheat cost per unit**, and **fertilizer units collected vs available**. Most regressions show up here before they show up in bank.

## 6. Risks

| Risk | Mitigation |
|---|---|
| Fast sim diverges from real env | M2 calibration gate is exact-match, not approximate |
| Tuned parameters overfit self-play | Validate against `"starter"` and downloaded ladder replays, not just self-play |
| Per-turn timeout | All heavy work at `hour == 0`; profile worst-case turn in M3 |
| Thesis 2 wrong (volume beats trickle) | M4 accept criterion tests it directly; if selling freely wins, revert the sell controller |
| **Opponent also plants melon** — combined 300 units floors the price and the 10-day investment is stranded | Read their `tiles` from day 10; cap our melon at `180 − their_forecast` and shift the tiles to strawberry/carrot. Test explicitly against a melon-heavy self-play opponent, not just `"starter"` |
| **Fertilizer market is shared** — both players dumping 425 units blows past the 493 floor | Sell fertilizer early and continuously; it is the one product where being first is free (zero town demand means the price never recovers) |
| **Feed wheat price rises as we buy it** — 400 units puts marginal at $55, not $48 | Grow feed wheat when `market_price > seed_cost/yield + 2.5*lambda`; log realised feed cost per episode as a diagnostic |
| **Crop decay is per turn (confirmed)** — a ripe melon is worthless half a day past its window | Ripe one-time crops route first in the turn order, ahead of watering and feeding; log yield lost to decay every episode as a hard regression signal |
| **A full shed silently blocks BUY_PRODUCT and BUY_ANIMAL (confirmed)** — the herd can starve for feed while cash sits idle | Keep shed headroom as an explicit planner constraint, not a consequence of the sell rate; alarm below ~15 free slots |
| **1 s per-turn `actTimeout`, 60 s episode overage bank** | Heavy planning at `hour == 0` only; watch `obs["remainingOverageTime"]` and fall back to a cached plan when it drops |
| Ladder rating noise | Submit every milestone so ratings accumulate; do not judge a version on fewer than ~30 games |
