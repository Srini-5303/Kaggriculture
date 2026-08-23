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

- `obs` is the only input. No memory is passed in. **Persist state in module-level globals**; detect episode start with `obs["step"] == 0` (or `day==0 and hour==0`) and reset.
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

## 5. Non-obvious economics (the core thesis)

- **Steep products are demand-capped, not supply-capped.** Milk/wool/strawberry/melon floor after 59-158 net units. Correct policy is to produce at ~the town's consumption rate and sell in a trickle at $200-320, not to maximise volume. Saturation points: **~7 cows** (milk drain ~11/day ÷ 1.5/cow/day), **~6 sheep**, ~25 melon tiles.
- **Wheat and egg use `log` on the glut side and never floor.** They are the only products that scale with volume.
- **Growing wheat to sell is unprofitable** at any realistic action shadow price. Wheat's role is animal feed and nothing else.
- **Feed cost dominates goose economics.** 1 wheat/animal/day at $40-48 market price. A cared goose makes 2 eggs (~$100) minus ~$45 feed for ~4.5 actions. An **uncared** goose makes 1 egg and is net negative. Cows (1.5 milk/day ≈ $300+) and sheep (1.33 wool/day ≈ $280) dwarf geese.
- **Fertilizer has zero town demand**, so its price only falls (floor at 493 cumulative sales). Sell it early; only apply it once its price drops below the yield it buys (+2 units on wheat/carrot, or 2 saved tile-days on melon).
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
| Collect fertilizer | `price(FERTILIZER) > lambda` |
| Buy quadrant | added serviceable tiles * yield/tile/day * remaining_days > cost |

Initial `actions_per_unit` priors (**calibrate against sim, do not trust**): melon ~3.0, wheat ~2.5, carrot ~3.3, tomato ~5.5, strawberry ~7.0, goose ~2.3/egg, cow ~2.2/milk, sheep ~3.2/wool.

## 8. Derived schedules (hardcode these)

**Watering calendars.** One-time crops gain +1 yield per watered day in the bonus window (fertilized: +2). Outside the window, watering is only for survival (a plant dies after 2 consecutive unwatered days).

| Crop | Water on days (age) | Harvest | Yield |
|---|---|---|---|
| WHEAT | 0, 2, 3, 4 | 4 | 4 (6 fertilized) |
| CARROT | 0, 2, 3 | 3 | 3 (4 fertilized) |
| MELON | 0, 2, 4, 6, 7, 8, 9, 10 | 10 (8 if fertilized) | 6 |
| TOMATO | every 2nd day survival + every production day if fertilizing | ages 8,9,10,11 | 1/tick, 2 if fertilized+watered |
| STRAWBERRY | same pattern | ages 10,12,14,16 | 1/tick, 2 if fertilized+watered |

Skipping non-bonus waterings saves ~15% of the farm's action budget.

**Animal care.** `pending_care_bonus` increments only on days the animal was both fed AND cared, and is consumed on the next scheduled production. Yields: goose **2/day**, cow **3 per 2 days**, sheep **4 per 3 days**. Harvest lazily up to `max_held` (goose 4, cow 6, sheep 6) to save actions.

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
2. **Simultaneous PLANT with insufficient seeds plants nothing at all.** Reserve seeds across all units when assembling a turn, not per-unit.
3. **Shed cap is 100 non-seed items; overflow at end-of-day drop is destroyed silently.** Sell continuously; never bank inventory for a final dump.
4. **Alternate-day feeding is a false economy.** An unfed production day still zeroes `pending_care_bonus`, so a goose drops from 2/day to 1/day, not to 1.5.
5. **HIRE and BUY_LAND consume market-order slots** (10/turn). 13 hires = 2 turns. Issue hires at `hour == 0`.
6. **First hire of each day spawns on (5,4)**, locked until NE is bought. Passable but a wasted move; a small hidden argument for buying NE early.
7. **Buy-then-sell arbitrage is closed** (buy quoted post-buy, sell quoted pre-sell). Do not look for it.
8. Tile actions no-op on `"LOCKED"` tiles. Shed PICKUP/DROP/PLACE work from locked center tiles.
9. Weeds spawn at 0.005/empty unlocked tile/day. Roughly 6 per season. Keeping tiles occupied is mildly self-reinforcing.
10. Market orders resolve **one unit at a time, concurrently with the opponent**. Selling N at once and selling N spread across the day differ only by interleaved town drain, which is real but second-order. Spreading across **days** is what matters.

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

## 12. Resolve from source before trusting the model

`kaggriculture.py` **is the environment and ships inside the pip package.** We do not write it and never modify it. We write `main.py` (the submission) and optionally `sim/fast_sim.py` (a validated fast copy for tuning). Find and read the real one first:

```bash
python -c "import kaggle_environments,os;print(os.path.dirname(kaggle_environments.__file__))"
find <that dir>/envs/kaggriculture -name '*.py'
```

Answer these, then update this file:

1. `hands` list length on mismatch: padded, truncated, or error? Can a hand hired this turn act this turn?
2. Does HARVEST take all `yield_units` or one unit?
3. Is `yield_units` accumulated during growth or computed at harvest? (Determines whether late watering still helps.)
4. Does BUY_ANIMAL deliver to shed or inventory?
5. Order of FEED vs production tick within the day refresh (does today's CARE land today or tomorrow?).
6. **Melon window conflict:** the general rule gives ages 5-10, the spec text says 6-12. Which does the code implement?
7. Can animals or structures be sold back?
8. Does `weedSpawnChance` apply to tiles occupied by structures without animals?
9. Is `configuration` passed to the agent as a second argument? If yes, read intervals directly and keep inference as a fallback.
