# CLAUDE.md

Context for building the Kaggriculture competition agent. Read fully before writing code.

## 1. Project

Build `main.py` exposing `agent(obs) -> action_dict` that maximises **bank at turn 720**.
Two players, separate 10x10 farms, **shared market**. Unsold inventory scores zero.

Deliverable: `main.py` at repo root. Multi-file submits as `tar -czf submission.tar.gz main.py agent/`.

## 2. Runtime contract

```python
{"farmer": ["VERB", "ARG", ...],          # ONE action, token list
 "hands":  [["VERB", ...], ...],          # one entry per hand, index-aligned to farms[me]["hands"]
 "market": [["BUY_SEED","WHEAT",1], ...]} # ordered, max 10 processed/turn, extras SILENTLY DROPPED
```

- **`configuration` IS passed.** Declare `def agent(obs, config)`. `agent.py:169-172` builds `[observation, configuration]` and truncates to `co_argcount`, so a 2-arg agent gets the full config: read `turnsPerDay`, `townShopSellInterval`, `townCenterSellInterval`, `townShopUnlockInterval`, `shedCapacity`, `maxMarketOrdersPerTurn`, `startingMoney`, `weedSpawnChance`, `farmHandCostMult` and `marketParams` directly. Only `seed` is stripped. Keep inference as a fallback, not the primary path.
- **Persist state in module-level globals.** `obs["step"]` **is** present for both players (verified) alongside `day`/`hour`; reset on `step == 0` or `day == 0 and hour == 0`.
- **CPU budget: `actTimeout` = 1 second per turn**, plus a **60 s episode-wide overage bank** exposed as `obs["remainingOverageTime"]`. Watch that field and degrade to a cheap path when it runs low.
- **The episode ends at step 718, not 719.** `interpreter` sets DONE when `step >= episodeSteps - 2`, and reward is read then. Step 718 is day 29 hour 22, so **all liquidation must complete by day 29 hour 22.**
- Per-turn CPU budget is small and there are 720 turns. Expensive planning runs **once per day** (`hour == 0`), never per turn.
- Any exception forfeits the episode. Every turn ends in `guard.py`.

**Infer configuration; never hardcode it.** The quick start shows `agent(obs)` with one argument, so `configuration` may not reach us at all, and the episode seed is deliberately stripped from observations. Everything needed is derivable:

| Value | How to infer |
|---|---|
| `turnsPerDay` | max observed `hour` + 1 |
| `townShopUnlockInterval` | day on which `len(unlocked_shops)` first increments |
| `townShopSellInterval`, `townCenterSellInterval` | `town_drain = our_sales - inventory_delta - opponent_sales`; measure on early days before the opponent sells |
| Opponent sales | same equation rearranged, once drain rate is known |

Shop **draws** are random every episode and the expected-drain table in §4 is an average, not a prediction. Recompute from live `unlocked_shops` each day.

## 3. Price function (exact, verified)

```python
x = abs(inv - I0)
f = {linear: x, sq: x**2, sqrt: sqrt(x), log: ln(1+x), log10: log10(1+x),
     hinge: (u := x/T) + 8*max(0, u-1)**2}
amp   = target * base / f(T)      # f(T)==1 for hinge, so amp = target*base
price = base + sign*amp*f(x)      # sign=+1 if inv<I0 else -1
price = max(1, round(price))
```

Reimplementing this in `market_model.py` reproduces all 27 published table values exactly. Treat as ground truth.

| Resource | base | T | below | b_tgt | above | a_tgt | Net glut units to $1 floor |
|---|---|---|---|---|---|---|---|
| WHEAT | 25 | 400 | sqrt | 0.80 | log | 0.20 | never |
| EGG | 50 | 332 | hinge | 0.40 | log | 0.20 | never |
| CARROT | 35 | 450 | hinge | 1.00 | sqrt | 0.70 | 842 |
| TOMATO | 60 | 200 | hinge | 0.40 | sqrt | 0.60 | 529 |
| FERTILIZER | 100 | 200 | linear | 0.40 | linear | 0.40 | 493 |
| MELON | 250 | 300 | log | 0.20 | sq | 3.60 | **158** |
| MILK | 160 | 122 | sqrt | 0.60 | linear | 1.60 | **76** |
| STRAWBERRY | 120 | 100 | sqrt | 0.70 | linear | 1.60 | **62** |
| WOOL | 200 | 105 | log | 0.20 | sq | 3.20 | **59** |

All `I0 = 10000`. Inventory only moves two ways: players add (SELL) / remove (BUY_PRODUCT, wheat+fertilizer only), town removes (free).

**Read the last column carefully.** "Net glut units to $1 floor" is measured from `I0`, i.e. **net of town drain**. It is not a production cap. Milk's 76 looks lethal until you notice the town drains 327 milk over the season — selling 300 milk spread against that drain averages **$272/unit** (verified). The real rule is that *cumulative sales must track cumulative drain*; the floor only bites when you outrun it. Melon is the exception (drain 30), which is why it behaves completely differently from the other three steep products.

Verified by reimplementation: the price formula above reproduces all 27 published table values (9 resources x `P(I0-T)`, `P(I0+T)`, `P(I0+2T)`) exactly, and every derived figure in §3 and §4 of this file recomputes exactly.

## 4. Town demand (drives everything)

Shops unlock days 3, 6, 9, 12, 15, 18, 21, 24 (8 total, uniform with replacement, permanent) = **132 shop-days**. Each instance consumes 1 of each demanded product per 4 turns = 6/day; single-product shops 12/day. Town center consumes 1 of every non-fertilizer product per day, flat.

Expected season drain and the price if we supply **nothing**:

| Product | Drain | Price at zero supply |
|---|---|---|
| WHEAT | 525 | $48 |
| STRAWBERRY | 426 | **$293** |
| MILK | 327 | **$317** |
| CARROT | 327 | $60 |
| EGG | 228 | $64 |
| TOMATO | 228 | $91 |
| WOOL | 228 | **$247** |
| MELON | 30 | $280 |
| FERTILIZER | 0 | $100 (only falls) |

**Prices start at base on day 0 and rise thereafter.** Early selling sells at the season's worst price.

`unlocked_shops` is in the observation and may repeat. Recompute drain from the actual draw each day, never from the expected table.

Shop demand map (8 types, drawn uniformly, `2x` = single-product so double rate):

| Shop | Demands |
|---|---|
| Bakery | eggs, wheat |
| Pizza Shop | milk, tomatoes, wheat |
| Brunch Spot | eggs, wheat, strawberries |
| Yarn Store | wool (2x) |
| Ice Cream Shop | strawberries, milk, wheat |
| Pet Cafe | carrots (2x) |
| Smoothie Shop | strawberries, milk |
| Farmers Market | wheat, carrots, tomatoes, strawberries |

**No shop demands melon.** Melon's entire season demand is the town center's 1/day = **30 units**, versus a 158-unit glut-to-floor distance. Every melon past the first 30 is pure self-inflicted glut, and the market is shared — if both players plant 25 melon tiles (300 units combined) the second seller gets the floor. Melon is the only steep product where you eat the whole price decline yourself; milk/wool/strawberry all have 228-426 units of drain absorbing your output.

Melon marginal revenue selling into a 30-unit drain (verified): 150 units → $32.5k total, $217 avg, **$106 marginal**; 200 units → $34.7k, $1 marginal. The last 50 melons are worth $44 each. Cap melon around 150-180 units and cut it hard if the opponent's `tiles` show melon.

## 5. Non-obvious economics (the core thesis)

- **Steep products are demand-capped, not supply-capped.** Milk/wool/strawberry/melon floor after 59-158 net units. Correct policy is to produce at ~the town's consumption rate and sell in a trickle at $200-320, not to maximise volume. Saturation points: **~7 cows** (milk drain ~11/day ÷ 1.5/cow/day), **~6 sheep**, ~25 melon tiles.
- **Wheat and egg use `log` on the glut side and never floor**, but "never floors" is not "scales freely." Egg slides $64 → $52 → $43 → $40 at 200/300/600 units sold. They degrade gracefully; they do not hold price.
- **Growing wheat to sell is unprofitable** at any realistic action shadow price. Wheat's role is animal feed and nothing else.
- **Buying feed wheat costs more than the headline.** Wheat is $48 at zero supply, but *our own buying drains the same inventory the price reads from*, and wheat's scarcity side is `sqrt` at target 0.80. Buying 300-400 units on top of the 525-unit town drain puts the marginal at **$50-56**, not $48. Verified: 400 units bought from `I0-525` cost $20.7k, avg $51.8, marginal $55.
- **Feed cost dominates goose economics — geese are a filler, not a business.** 1 wheat/animal/day (**assumed**, see §12 Q10). A cared goose makes 2 eggs; at 300-600 cumulative eggs sold that is $80-86 revenue against $50-55 feed, so **$25-35/day for ~2.5-4.5 actions = $7-13 per action**, straddling `lambda ≈ 12-18`. An **uncared** goose makes 1 egg and is clearly net negative. Cows (1.5 milk/day ≈ $300+) and sheep (1.33 wool/day ≈ $280) dwarf geese. Build geese only when the action budget would otherwise idle.
- **Collected fertilizer is one of the best lines in the game and neither tiles nor seeds are spent on it.** Every *surviving* animal makes 1 available per day whether or not it was fed or cared for, and `COLLECT_FERTILIZER` is one action. Verified sale curve from `I0`: 325 units → $22.0k ($67.6 avg), **425 units → $24.5k ($57.6 avg, $15 marginal)**, floor at 493. That is **~$58 per action**, 3-4x `lambda`, and roughly a quarter of the 100k target. Halve the estimate for opponent competition on the same shared inventory. Collect every day from every animal until `price(FERTILIZER) < lambda`; sell early because the curve only falls.
- **Applying fertilizer almost never pays.** One `FERTILIZE` covers 3 days (`fertilized_until_day = day + 2`) and needs FERTILIZER in the acting unit's inventory. Wheat: +2 units (6 vs 4) ≈ $100-110 — break-even at best. Carrot: **+1 unit** (4 vs 3) ≈ $60 — never. Melon: **worthless.** It reaches the 6-unit cap at age 8, but `first_yield_day = 10` blocks HARVEST until age 10 regardless, so the only gain is skipping two waterings. The one real use is **ongoing crops, and only if you harvest between ticks** — see §9.12.
- **The opponent is nearly fully observable.** Their `tiles` expose `crop` and `planted_day`. `market.inventory` delta minus known town drain minus our own sales = their sales exactly. Forecast their melon/milk/wool supply and sell before their harvest lands.

## 6. Labor: cheap, and the real constraint is actions

Hire cost is `farmHandCostMult * fib(hires_today)`, fib = 1,1,2,3,5,8,13,... Cumulative for k hands:

| k | 1 | 3 | 5 | 8 | 10 | 12 | 13 | 15 |
|---|---|---|---|---|---|---|---|---|
| cost | 1 | 4 | 12 | 54 | **143** | 376 | 609 | 1596 |

**Coin cost is negligible but hands are still work-bounded.** The binding test is available work, not price. Daily task queue at full build-out is only ~140 actions (7 cows ~30, 6 sheep ~25, 25 melon tiles ~50, 16 feed-wheat tiles ~35). At ~20 usable slots per unit per day that is **7 units: farmer plus ~6 hands**. Hiring 13 leaves half idle.

```
hire while (pending_tasks > units * 20) and (fib(hires_today) < 20 * lambda)
```

The second clause almost never binds. Size hires to **that morning's** queue, not a constant: melon harvest day adds ~25 tile-visits at once, and days 0-2 (build, place, plant) are equally spiky. Over-hiring on a crunch day costs a few coins and is correct; over-hiring every day wastes nothing but achieves nothing.

Corollary for land: profitable production needs ~54 tiles. NW gives 25, NW+NE gives 50. Buy NE ($1k) yes, SW ($2k) probably, **SE ($4k) almost certainly not** since it creates work with no market to absorb the output.

Everyone respawns at the shed each morning and vanishes at day end (auto-dropping inventory). Travel is one-way: ~3-5 moves out, none back. Budget **~18-20 useful actions per unit per day**, so ~10 crop tiles or ~4-5 animals serviced per unit.

**Layout is a decision variable.** Plant in dense contiguous rectangles so a unit can snake tile-to-tile (1 move between actions). Fragmented planting burns ~30% of the action budget. Cluster animals near the shed (3-4 actions each, fewer tiles visited). Low-touch crops go to the far corners.

## 7. The lambda framework (use this instead of hardcoded rules)

`lambda` = marginal value of one unit-action per day. Compute it daily: rank every candidate activity by coins-per-action, fill the action budget top-down, read off the cutoff. Expect **lambda ≈ 12-18**; calibrate in sim.

Every decision then becomes one comparison:

| Decision | Rule |
|---|---|
| Hire hand k | `pending_tasks > k*20` **and** `fib(k) < 20*lambda` (first clause binds) |
| Plant crop C | `price(C) > actions_per_unit(C) * lambda` |
| Buy vs grow wheat | `market_price_wheat vs (seed_cost/yield + 2.5*lambda)` |
| Add animal | `daily_yield*price - feed_cost > actions_per_day(animal) * lambda` |
| Collect fertilizer | `price(FERTILIZER) > lambda` — true until ~425 cumulative units, so effectively always |
| Apply fertilizer | `price(FERTILIZER) < extra_units * price(crop)` — wheat +2, carrot +1, melon 2 tile-days |
| Buy quadrant | added serviceable tiles * yield/tile/day * remaining_days > cost |
| Harvest a ripe one-time crop | unconditional, and **first in the turn order** (§9.10) |
| Sell unit n of product P | `marginal_price(P, n) > actions_per_unit(P) * lambda`, and for melon check the opponent's melon tiles first |

Initial `actions_per_unit` priors (**calibrate against sim, do not trust**): melon ~3.0, wheat ~2.5, carrot ~3.3, tomato ~5.5, strawberry ~7.0, goose ~2.3/egg, cow ~2.2/milk, sheep ~3.2/wool.

## 8. Derived schedules (hardcode these)

**Costs and lead times.** Purchase prices are fixed (the market has unlimited seed/animal supply). Lead time is the gap between planting/placing and the *first* harvestable unit — it is why animal deadlines in the table below sit so early.

| Asset | Buy cost | First yield | Then | Max held | Base price |
|---|---|---|---|---|---|
| WHEAT seed | 10 | age 2 | one-time, harvest age 4 | — | 25 |
| CARROT seed | 20 | age 2 | one-time, harvest age 3 | — | 35 |
| TOMATO seed | 50 | age 8 | daily x4 (ages 8-11) | 4 | 60 |
| MELON seed | 80 | age 10 | one-time | — | 250 |
| STRAWBERRY seed | 100 | age 10 | every 2nd day x4 (10,12,14,16) | 4 | 120 |
| GOOSE | 300 | **day +4** | every day, indefinite | 4 | 50 (egg) |
| SHEEP | 500 | **day +6** | every 3 days, indefinite | 6 | 200 (wool) |
| COW | 400 | **day +8** | every 2 days, indefinite | 6 | 160 (milk) |
| FERTILIZER (buy) | 100 | — | — | — | 100 |
| Land: NE / SW / SE | 1k / 2k / 4k | — | — | — | — |

Setup actions beyond the buy: `BUILD_COOP`/`BUILD_PASTURE` (1) + `PICKUP` from shed (1) + travel + `PLACE` (1). Budget ~4 actions per animal before it produces anything.

**Cash-flow consequence.** 7 cows + 6 sheep = $5,800 in animals alone, before coops, seeds, and land. Starting cash cannot fund the target herd, and **the cow is the worst-timed purchase in the game** — $400 down for nothing until day +8. Sequence animal buys against projected revenue, and buy cows first precisely because their lead time is longest.

**Watering calendars.** One-time crops gain +1 yield per watered day in the bonus window (fertilized: +2). Outside the window, watering is only for survival (a plant dies after 2 consecutive unwatered days).

Bonus window is `ceil(max_yield_day/2) <= age <= max_yield_day`, verified from source (`window_start = (max_yield_day + 1) // 2`). Decay begins at step `(planted_day + max_yield_day + 1) * turnsPerDay` — note this uses `max_yield_day`, which for melon is **12**, not the 10 in the published table.

| Crop | Water on days (age) | Harvest window | Rot begins | Yield |
|---|---|---|---|---|
| WHEAT | 0, 2, 3, 4 | ages 2-4 | age 5 | 4 (6 fertilized) |
| CARROT | 0, 2, 3 | ages 2-3 | age 4 | 3 (4 fertilized) |
| MELON | 0, 2, 4, 6, 7, 8, 9, 10 | **ages 10-12** | **age 13** | 6 |
| TOMATO | every 2nd day survival + every production day if fertilizing | ages 8,9,10,11 | day after 4th tick | 1/tick, 2 if fertilized+watered |
| STRAWBERRY | same pattern | ages 10,12,14,16 | day after 4th tick | 1/tick, 2 if fertilized+watered |

Skipping non-bonus waterings saves ~15% of the farm's action budget. Melon's 3-day harvest window (ages 10-12) is the slack that makes it schedulable; wheat and carrot have effectively none.

**Animal care.** `pending_care_bonus` increments only on days the animal was both fed AND cared, and is consumed on the next scheduled production. Steady-state yields: goose **2/day**, cow **3 per 2 days**, sheep **4 per 3 days**. Harvest lazily up to `max_held` (goose 4, cow 6, sheep 6) to save actions.

**Care through the lead-in, then harvest full.** Production is evaluated *before* today's CARE is banked, so the bank accumulates 1/day through the pre-first-yield window and is paid out whole on the first tick, capped by `max_held`. Feed and care from the day of placement and **the first harvest arrives full**: goose 4 eggs on day +4, **cow 6 milk on day +8**, sheep 6 wool on day +6. Skipping care during the lead-in throws that away for nothing.

**Last-useful-planting days** (season ends after day 29):

| Asset | Latest start |
|---|---|
| CARROT | 26 |
| WHEAT | 25 |
| GOOSE | ~22 |
| SHEEP | ~20 |
| MELON | 19 |
| STRAWBERRY | 19 (one tick only) |
| COW | ~18 |
| TOMATO | ~18 |
| 4th quadrant ($4k) | ~22, and probably never |

## 9. Invariants and traps

1. **`consecutive_unwatered` starts at 1 on planting.** PLANT and WATER must both land on the tile the same day or the seed dies overnight.
2. **Simultaneous PLANT with insufficient seeds plants nothing at all.** Reserve seeds across all units when assembling a turn, not per-unit. **Worse: the count includes phantom entries.** The pre-validation sums PLANT requests over `[farmer, *hands]` as submitted, before any position check, so a PLANT from a `hands` slot that doesn't correspond to a real hand still counts against seeds and can block a *real* plant. Verified: 2 requests + 1 seed + 1 real hand = nothing planted, seed untouched. Never emit more `hands` entries than `len(farms[me]["hands"])`.
3. **Shed cap is 100 non-seed items; overflow at end-of-day drop is destroyed silently.** Sell continuously; never bank inventory for a final dump. **A full shed also blocks purchases**: `BUY_ANIMAL` and `BUY_PRODUCT` both check `sum(shed.values()) >= shedCapacity` and abort the order silently, so a clogged shed can starve the herd of feed wheat. Seeds are exempt (`private["seeds"]` is separate and uncapped).
4. **Alternate-day feeding is a false economy.** An unfed production day still zeroes `pending_care_bonus`, so a goose drops from 2/day to 1/day, not to 1.5.
5. **HIRE and BUY_LAND consume market-order slots** (10/turn). 13 hires = 2 turns. Issue hires at `hour == 0`.
6. **First hire of each day spawns on (5,4)**, locked until NE is bought. Passable but a wasted move; a small hidden argument for buying NE early.
7. **Buy-then-sell arbitrage is closed** (buy quoted post-buy, sell quoted pre-sell). Do not look for it.
8. Tile actions no-op on `"LOCKED"` tiles. Shed PICKUP/DROP/PLACE work from locked center tiles.
9. Weeds spawn at 0.005/empty unlocked tile/day. Roughly 6 per season. Keeping tiles occupied is mildly self-reinforcing.
10. **Mature crops rot per *turn*, not per day — confirmed in source.** `_decay_plants` runs every step and drops 1 unit whenever `(step - max_lifespan_step) % 2 == 0`, i.e. **1 unit per 2 turns**, and the tile becomes a WEED at zero. A ripe 6-unit melon that sits past age 12 is **worth nothing 12 turns later, half a day**. Route ripe one-time crops **first in the turn order**, before watering or feeding. `yield_units` is the live number — if it is falling you are already losing money.
11. **FEED and FERTILIZE consume from the acting unit's inventory, not the shed**, and no-op silently if it isn't carried. A feeding round is `PICKUP WHEAT n` at the shed *then* the animal circuit; a unit that runs dry mid-circuit leaves the rest of the herd unfed, which zeroes their care bonus (see #4) and escapes them on the second day. Pick up feed for the whole circuit plus a margin.
12. **Fertilized ongoing crops yield 8, not 4, if you harvest between ticks.** `yield_units = min(max_yield, yield_units + 2)` caps *held* units at 4, not lifetime output; `production_count` still advances one per tick. Harvesting after each tick lets all four ticks pay 2, so a fertilized+watered tomato returns 8 units instead of 4. This is the only place applying fertilizer clearly pays.
13. **`SELL` at the $1 floor does not add to market inventory**, so the floor stays responsive and dumping at the floor does not deepen it further. It also means the floor is not a punishment you can inflict permanently.
14. Market orders resolve **one unit at a time, concurrently with the opponent**. Selling N at once and selling N spread across the day differ only by interleaved town drain, which is real but second-order. Spreading across **days** is what matters.

## 10. Repo layout

```
main.py                # entry: agent(obs); imports agent/; holds persistent globals
agent/
  constants.py         # crop/animal/market tables, watering calendars, deadlines
  state.py             # obs -> typed World; diffs vs last turn
  market_model.py      # price(inv), drain forecast, opponent-supply inference
  economics.py         # lambda solver, coins-per-action ranking
  planner.py           # daily: production targets, buy list, sell rates, layout
  scheduler.py         # per-turn: zone assignment + snake routing -> actions
  guard.py             # legality check, seed reservation, try/except fallback
sim/
  fast_sim.py          # our reimplementation, no kaggle_environments overhead
  calibrate.py         # assert fast_sim == real env over N random-action episodes
tools/
  tune.py              # CEM / random search over planner params via self-play
  replay_analysis.py   # parse downloaded replays, mine opponent behaviour
tests/
```

Keep `main.py` import-light and side-effect-free at module scope apart from state init.

## 11. Commands

```bash
pip install -U kaggle-environments kaggle
python -c "from kaggle_environments import make; e=make('kaggriculture',debug=True); \
  e.run(['main.py','starter']); print([(i,s.reward) for i,s in enumerate(e.steps[-1])])"
kaggle competitions submit kaggriculture -f submission.tar.gz -m "vN"
kaggle competitions episodes <SUBMISSION_ID> -v
kaggle competitions logs <EPISODE_ID> 0
```

Built-in opponents: `"pass"`, `"random"`, `"starter"`.

## 12. Resolved from source

`kaggriculture.py` **is the environment and ships inside the pip package.** We do not write it and never modify it. We write `main.py` (the submission) and optionally `sim/fast_sim.py` (a validated fast copy for tuning).

```bash
python -c "import kaggle_environments,os;print(os.path.dirname(kaggle_environments.__file__))"
# envs/kaggriculture/kaggriculture.py  +  kaggriculture.json (config defaults)
```

All 13 open questions are answered. Read against source, and where marked, confirmed by running the real env.

| # | Question | Answer |
|---|---|---|
| 1 | `hands` length mismatch; can a hand act the turn it's hired? | Neither padded nor an error — **extra entries silently no-op**, missing entries idle. **No**: unit actions run before `_process_market`, so a hand hired at hour h first acts at h+1. *Verified.* |
| 2 | HARVEST all or one? | **All of `yield_units` in one action**, plants and animals. One-time crop tile → `None`, replantable by a later unit the same turn. No-ops before `first_yield_day`. |
| 3 | `yield_units` accumulated or at harvest? | **Accumulated live.** WATER adds +1 (+2 fertilized) only inside the bonus window. **Late watering never helps.** |
| 4 | BUY_ANIMAL → shed or inventory? | **Shed, counted against `shedCapacity`**; the order fails silently at 100. See §9.3. |
| 5 | FEED vs production order; CARE today or tomorrow? | Produce first (using today's `fed_today`, consuming the *prior* bank), **then** bank today's CARE. So CARE pays on the **next** tick — hence the lead-in banking trick in §8. |
| 6 | Melon window 5-10 or 6-12? | **6-12.** Source has melon `max_yield_day: 12`; the published "Time to Max Yield 10" is when the cap is *reached*. Also moves melon's rot deadline to age 13. |
| 7 | Sell animals or structures back? | **No.** `SELL` requires `item in PRODUCTS`; animals aren't products. `DIG` clears an empty structure for nothing. One-way purchase. |
| 8 | `weedSpawnChance` on empty structures? | **No** — only tiles that are exactly `None`. Structures/plants/weeds/`LOCKED` exempt. Rate 0.005. |
| 9 | Is `configuration` passed? | **Yes**, as the 2nd arg. See §2. `actTimeout` 1 s/turn, 60 s overage bank. |
| 10 | Wheat per FEED? | **1, from the acting unit's inventory**, not the shed. Silent no-op if not carried. See §9.11. |
| 11 | Decay per turn or per day? | **Per turn** — 1 unit per 2 turns. See §9.10. *Verified.* |
| 12 | Starting cash? | **3000** (`startingMoney`). |
| 13 | Fertilizer from unfed/newly placed animals? | **Yes to both** — `fertilizer_available = True` unconditionally for every survivor each night, including its first. *Verified on a never-fed, never-cared goose.* |

Remaining source facts worth keeping:

- **First hire spawns on `(5,4)`, which is LOCKED until NE is bought, so it cannot do tile work until it moves.** *Verified* — a PLANT from a freshly hired hand silently no-ops. Move it west first.
- Shop unlocks draw from `rng.choice(sorted(SHOPS))` with `rng = Random((seed * 1_000_003) ^ day)`, and **player 0's weed rolls consume that RNG before player 1's**, so weeds and shop draws are coupled. Deterministic per seed; do not try to predict the draw.
- Town center consumes at `step % 24 == 0` **including step 0**, so drain starts on turn 0. Shops at `step % 4 == 0`.
- `_process_market` truncates each queue to `maxMarketOrdersPerTurn` **before** parsing, and HIRE/BUY_LAND resolve first within an order index. Prices move per unit inside an order; `market["prices"]` in the observation only refreshes after each order index.
- One-time crops set `max_lifespan_step` at planting; ongoing crops keep `-1` until the 4th production fires, then set it to the following day.
