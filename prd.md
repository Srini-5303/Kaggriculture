# PRD: Kaggriculture Agent

## 1. Objective

Maximise final bank at turn 720. Target top-10 finish (prize threshold). Entry deadline **23 Sep 2026**.

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

1. **Labor is cheap but work-bounded.** 10 hands cost 143/day, so coins never limit hiring; available work does, and work is capped by market saturation. Expect 5-9 units, sized to the daily task queue. Everything is still priced in coins-per-action (`lambda`).
2. **Milk, wool and strawberry are demand-limited but forgiving.** Their glut-to-floor distance is 59-76 net units, but season town drain is 228-426 units, so cumulative sales tracked against cumulative drain hold $240-310/unit even at 300 units. Produce at roughly the town's consumption rate and sell in a trickle. Outrunning the drain is what's negative, not volume as such.
3. **Melon is the opposite case and must be treated separately.** No shop demands melon; its whole-season demand is the town center's **30 units**. Melon revenue is self-cannibalising from unit 31: 150 units averages $217 ($106 marginal), 200 units averages $173 ($1 marginal). It is still the best crop per tile-day, but the cap is ~150-180 units *combined across both players*, so its value is contingent on the opponent not planting it.
4. **Collected fertilizer is a first-class revenue line, not a byproduct.** Every surviving animal yields 1/day regardless of feeding or care, at one action to collect. 425 units ≈ **$24.5k at ~$58/action** — 3-4x lambda, no tiles, no seeds. Halve for shared-market competition and it is still ~10% of the target bank.
5. **The opponent's supply is computable** from their visible `tiles` plus market-inventory arithmetic. On floor-prone products, selling first is worth several multiples of selling second.

Resulting shape: cows and sheep to saturation early (buying cows first — 8-day lead time), melon as the crop core but capped and opponent-contingent, fertilizer collected from every animal every day, geese and wheat only to fill spare actions, continuous trickle selling, hard liquidation from day 27.

## 3. Milestones

Each milestone is submittable. Ladder ratings converge slowly, so **submit at the end of every milestone**.

### M0. Skeleton (day 1)
- `main.py` with the action contract, module-level state, `guard.py` wrapping every turn in try/except with a PASS fallback.
- Hire 5 hands each morning, farmer + hands run a fixed wheat loop.
- **Accept:** completes 720 turns against `"random"` with zero errors in the agent log. Submit.

### M1. Ground truth (day 2-3)
- Read `kaggriculture.py` from the installed package. Answer all 13 questions in CLAUDE.md §12 and update that file. Q10 (wheat per FEED), Q11 (decay per turn vs per day) and Q12 (starting cash) each change the design if they come back the wrong way — resolve those first.
- `market_model.price(resource, inv)` reproducing all 27 published table values (9 resources x `P(I0-T)`, `P(I0+T)`, `P(I0+2T)`). Already confirmed reproducible from the CLAUDE.md §3 formula; the test just locks it in.
- Config inference: `turnsPerDay`, shop-unlock interval, and town drain rate measured from observation, with hardcoded defaults only as fallback. Confirm whether `configuration` reaches the agent.
- `replay_analysis.py` over the public episodes dataset: ladder bank distribution, opening-move frequencies.
- **Accept:** price unit test green on all 27 values; benchmark table in §1 re-based on real ladder data.

### M2. Fast simulator (day 3-6)
**Gate first:** time the real env. If `kaggle_environments` already sustains the tuning loop, skip this milestone entirely and delete it. Build only what measurement justifies.
- `sim/fast_sim.py`, headless, no `kaggle_environments` overhead. Target **>200 episodes/min single-core**.
- `sim/calibrate.py`: run 50 seeded episodes with identical scripted action streams through both `fast_sim` and the real env; assert identical final bank, market inventory, and tile states.
- **Accept:** 50/50 exact matches. This gate is non-negotiable; a wrong simulator produces confidently wrong tuning for the rest of the project.

### M3. Greedy value agent (day 6-10)
- `economics.py` lambda solver. `scheduler.py` with zone partition and snake routing.
- Hardcoded production targets: 7 cows, 6 sheep, ~25 melon tiles, wheat for feed only. Buy cows before sheep before geese (longest lead time first, CLAUDE.md §8).
- Hire count driven by that morning's task-queue length (expect 5-9 units), not a constant.
- Watering calendars and lazy animal harvest from CLAUDE.md §8. **Crop harvest is not lazy** — ripe one-time crops go first in the turn order, per CLAUDE.md §9.10.
- `COLLECT_FERTILIZER` on every animal every day, sold immediately.
- Naive selling: fixed units/day per product.
- **Accept:** beats `"starter"` on all 50 evaluation seeds (§5). Median bank ≥ 30k. Submit.

### M4. Market module (day 10-14)
- Drain forecast from live `unlocked_shops`.
- Sell-rate controller: hold each product's price above `actions_per_unit * lambda`; for log-curve products (wheat, egg) sell freely.
- Fertilizer sell-vs-apply crossover.
- Shed-pressure override: when shed > 85, sell down regardless of price.
- Liquidation planner: from day 27, stagger harvests so no day overflows the shed; bank hits zero inventory by turn 719.
- **Accept:** ≥ 25% median bank improvement over M3 on the same 20 seeds. Submit.

### M5. Planner and tuning (day 14-20)
- Replace hardcoded targets with the daily lambda-driven planner: crop mix, hire count, quadrant purchase, buy-vs-grow wheat, cash-flow-constrained investment sequencing for the opening.
- `tools/tune.py`: CEM over ~15 planner parameters via self-play, 200+ episodes per generation.
- **Accept:** tuned agent beats M4 in ≥ 70% of 50 head-to-head seeds. Submit.

### M6. Opponent modelling (day 20+)
- `opponent.py`: forecast their supply per product per day from `tiles` + `planted_day`; infer realised sales from `market.inventory` deltas.
- Pull sales forward on floor-prone products ahead of their forecast harvest.
- Evaluate denial (dumping early to destroy their 10-11 day melon investment) as an explicit EV calculation, not a policy.
- **Accept:** beats M5 head-to-head in ≥ 60% of 50 seeds. Ship as final.

## 4. Component specs

**state.py** parses `obs` into a typed `World`: per-tile records with derived `age`, `days_to_harvest`, `needs_water_today`, `is_bonus_day`; unit positions; shed and seed counts; market prices and inventory; opponent farm. Also diffs against the previous turn so the market module can attribute inventory changes.

**market_model.py** owns `price(resource, inv)`, `marginal_revenue(resource, n_units)` (integrating the curve one unit at a time), `forecast_drain(unlocked_shops, days_remaining)`, and `infer_opponent_sales(inv_delta, our_sales, town_drain)`.

**economics.py** exposes `solve_lambda(world) -> float` and `rank_activities(world) -> [(activity, coins_per_action)]`. Every planner decision routes through these; no decision hardcodes a coin threshold.

**planner.py** runs at `hour == 0`. Outputs a `DayPlan`: hire count, market buy list, per-product sell rate, tile-level target assignments (plant what, where), and zone boundaries. Must respect the cash-flow constraint: starting cash (assumed 3000, confirm in M1) cannot fund the target herd — cow $400, sheep $500, goose $300 means 7 cows + 6 sheep is $5,800 in animals alone, before coops, seeds and the $1k NE quadrant. It sequences purchases against projected revenue, weighted by lead time (a cow bought today produces nothing for 8 days).

**scheduler.py** runs every turn. Partitions tasks into K compact zones by density, assigns one unit per zone, routes each with a fixed snake order. Do **not** solve the assignment optimally; it is a team orienteering problem and a greedy zone partition captures most of the value at zero runtime cost.

**guard.py** validates every emitted action against the tile state, reserves seeds across units within the turn, truncates the market list to 10, and catches all exceptions with a PASS fallback.

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
| Q10/Q11 resolve badly (2 wheat per FEED, or per-turn crop decay) | Both are M1 gates. 2 wheat/FEED makes geese strictly negative; per-turn decay makes harvest routing critical-path. Design branches, so resolve before M3 |
| Ladder rating noise | Submit every milestone so ratings accumulate; do not judge a version on fewer than ~30 games |
