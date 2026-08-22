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

Three claims the agent is built on. Each is falsifiable in sim; if one fails, the design changes.

1. **Labor is nearly free, so the binding constraint is actions/day, not money.** 10 hands cost 143/day against a five-figure daily revenue. Everything is priced in coins-per-action (`lambda`).
2. **Steep-curve products (milk, wool, strawberry, melon) are demand-limited.** They floor after 59-158 net units against 228-426 units of season town demand. Produce at the town's consumption rate, sell in a trickle, collect $200-320/unit. Overproduction is actively negative.
3. **The opponent's supply is computable** from their visible `tiles` plus market-inventory arithmetic. On floor-prone products, selling first is worth several multiples of selling second.

Resulting shape: cows and sheep to saturation early, melon as the crop core, geese and wheat only to fill spare actions, continuous trickle selling, hard liquidation from day 27.

## 3. Milestones

Each milestone is submittable. Ladder ratings converge slowly, so **submit at the end of every milestone**.

### M0. Skeleton (day 1)
- `main.py` with the action contract, module-level state, `guard.py` wrapping every turn in try/except with a PASS fallback.
- Hire 5 hands each morning, farmer + hands run a fixed wheat loop.
- **Accept:** completes 720 turns against `"random"` with zero errors in the agent log. Submit.

### M1. Ground truth (day 2-3)
- Read `kaggriculture.py` from the installed package. Answer all 8 questions in CLAUDE.md §12 and update that file.
- `market_model.price(resource, inv)` reproducing all 27 published table values.
- `replay_analysis.py` over the public episodes dataset: ladder bank distribution, opening-move frequencies.
- **Accept:** price unit test green on all 27 values; benchmark table in §1 re-based on real ladder data.

### M2. Fast simulator (day 3-6)
- `sim/fast_sim.py`, headless, no `kaggle_environments` overhead. Target **>200 episodes/min single-core**.
- `sim/calibrate.py`: run 50 seeded episodes with identical scripted action streams through both `fast_sim` and the real env; assert identical final bank, market inventory, and tile states.
- **Accept:** 50/50 exact matches. This gate is non-negotiable; a wrong simulator produces confidently wrong tuning for the rest of the project.

### M3. Greedy value agent (day 6-10)
- `economics.py` lambda solver. `scheduler.py` with zone partition and snake routing.
- Hardcoded production targets: 7 cows, 6 sheep, ~20 melon tiles, wheat for feed only.
- Watering calendars and lazy animal harvest from CLAUDE.md §8.
- Naive selling: fixed units/day per product.
- **Accept:** beats `"starter"` in 20/20 seeds. Median bank ≥ 30k. Submit.

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

**planner.py** runs at `hour == 0`. Outputs a `DayPlan`: hire count, market buy list, per-product sell rate, tile-level target assignments (plant what, where), and zone boundaries. Must respect the cash-flow constraint: 3000 starting coins cannot fund 13 animals, so it sequences purchases against projected revenue.

**scheduler.py** runs every turn. Partitions tasks into K compact zones by density, assigns one unit per zone, routes each with a fixed snake order. Do **not** solve the assignment optimally; it is a team orienteering problem and a greedy zone partition captures most of the value at zero runtime cost.

**guard.py** validates every emitted action against the tile state, reserves seeds across units within the turn, truncates the market list to 10, and catches all exceptions with a PASS fallback.

## 5. Evaluation protocol

- Fixed seed set of 50 for all comparisons. Never tune and evaluate on the same seeds.
- Report median and 25th percentile bank, not mean. A single 150k outlier hides consistent 20k losses.
- Head-to-head win rate against the previous milestone is the primary signal; absolute bank is secondary because it moves with the opponent.
- Log per-episode diagnostics: actions used vs available per day, lambda trajectory, realised price per product per sale, shed overflow events, unwatered deaths. Most regressions show up here before they show up in bank.

## 6. Risks

| Risk | Mitigation |
|---|---|
| Fast sim diverges from real env | M2 calibration gate is exact-match, not approximate |
| Tuned parameters overfit self-play | Validate against `"starter"` and downloaded ladder replays, not just self-play |
| Per-turn timeout | All heavy work at `hour == 0`; profile worst-case turn in M3 |
| Thesis 2 wrong (volume beats trickle) | M4 accept criterion tests it directly; if selling freely wins, revert the sell controller |
| Ladder rating noise | Submit every milestone so ratings accumulate; do not judge a version on fewer than ~30 games |
