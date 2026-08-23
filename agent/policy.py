"""Day plan and per-turn routing.

Stage 2 scope: cows, feed wheat, and fertilizer collection. Melon and sheep sit
behind the TARGETS table, so Stage 3 is a change to constants, not to logic.

The priority order is not arbitrary -- each rank corresponds to something the
environment actually punishes, ordered by what it costs to be late:

  rot     one unit lost per 2 TURNS once a one-time crop passes its rot age
  escape  two consecutive unfed days and the animal is gone permanently
  wither  consecutive_unwatered reaching 2 turns the tile into a weed overnight
  cap     max_held destroys animal production rather than deferring it
  idle    a $400 cow waiting in the shed for a pasture earns nothing at all
"""

from .constants import (
    ANIMALS,
    CROPS,
    LAND_PRICES,
    LAST_FULL_YIELD_START,
    MARKET_PARAMS,
    MOVES,
    PRODUCTS,
)
from .market import price, units_until_price

# --- tunables -------------------------------------------------------------

# Swept over 16 seeds, not derived. Demand maths suggested 7 cows / 6 sheep;
# measurement prefers 8 cows / 3 sheep, and 6 sheep costs 16% of the bank. Sheep
# are the least action-efficient of the three (a 3-day tick against a 6-cap, so
# they must be harvested every tick) and they crowd out cow servicing.
# Geese stay off: ~$7-13/action, straddling lambda.
# Melon stays off. Its theoretical ~$100/action never materialises: 11 animals
# plus feed wheat already fill all 25 NW tiles, and buying land to make room for
# melon spreads ~4 units too thin to service any of it (see LAND_ENABLED).
TARGETS = {"COW": 8, "SHEEP": 3, "GOOSE": 0}
MELON_TILES = 0
WHEAT_TILE_MARGIN = 3       # feed tiles beyond one per animal
FEED_BUFFER_DAYS = 3        # days of feed in the shed
MAX_HANDS = 9
ANIMAL_QUEUE = 2            # animals allowed to queue in the shed for a structure
SHED_HEADROOM = 20          # a full shed silently blocks BUY_PRODUCT / BUY_ANIMAL
LIQUIDATE_FROM_DAY = 27
LAND_ENABLED = False        # swept: buying NE/SW raises the median ~1% but halves
                            # the worst case (min 45k -> 23k). ~4 units cannot service
                            # 50 tiles, and the purchase risks starving the herd.
LAND_CASH_MULT = 2.0        # require this multiple of the price before buying
LAND_MIN_DAYS_LEFT = 12     # a quadrant needs time to pay itself back
TASKS_PER_UNIT_DAY = 10     # swept: a clean peak at 10 (4->33k, 8->38k, 10->46k,
                            # 14->43k, 20->36k). More hands is worse, not better.

# Sell while the marginal price holds above this fraction of base.
SELL_FLOOR_FRACTION = {
    "MILK": 0.55, "WOOL": 0.55, "STRAWBERRY": 0.55, "MELON": 0.45,
    "EGG": 0.60, "CARROT": 0.60, "TOMATO": 0.60, "WHEAT": 0.80,
    "FERTILIZER": 0.15,
}

# Parameter overrides for sweeping, via the KAGG_PARAMS env var (JSON). The
# submission never sets it, so this is inert in competition; tools/sweep.py uses
# it to tune without editing source between runs.
def _apply_overrides():
    import json
    import os

    raw = os.environ.get("KAGG_PARAMS")
    if not raw:
        return
    try:
        params = json.loads(raw)
    except ValueError:
        return
    g = globals()
    for key, value in params.items():
        if key in ("COW", "SHEEP", "GOOSE"):
            TARGETS[key] = value
        elif key in g:
            g[key] = value


_apply_overrides()


# Priorities: lower runs first.
P_HARVEST_CROP = 1
P_BUILD_URGENT = 2          # only when animals are queued in the shed
P_FEED = 3
P_WATER_DYING = 4
P_HARVEST_ANIMAL = 5
P_WATER_BONUS = 6
P_CARE = 7
P_COLLECT = 8
P_PLACE_ANIMAL = 9
P_PLANT = 10
P_BUILD = 11
P_DIG = 12


def _dist(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _shed_pos(world):
    half = world.board // 2
    return (half - 1, half - 1)


def _step_toward(world, pos, target):
    """One Manhattan step. Every tile is passable, LOCKED included, so there is
    never any pathfinding to do on this board."""
    x, y = pos
    dx, dy = target[0] - x, target[1] - y
    order = ("EAST" if dx > 0 else "WEST", "SOUTH" if dy > 0 else "NORTH")
    if abs(dy) > abs(dx):
        order = (order[1], order[0])
    for verb in order:
        mx, my = MOVES[verb]
        if (mx and dx) or (my and dy):
            if 0 <= x + mx < world.board and 0 <= y + my < world.board:
                return [verb]
    return ["PASS"]


# --- layout ---------------------------------------------------------------

def _slots(world):
    """Unlocked tiles ordered by distance from the shed.

    Animals take the closest slots because each costs ~3 actions every single day
    (FEED, CARE, amortised HARVEST), so their travel is paid 25 times over. (4,4)
    is both the spawn tile and a normal buildable tile, so an animal there is
    serviced with zero movement forever.
    """
    shed = _shed_pos(world)
    tiles = [(x, y) for y in range(world.board) for x in range(world.board) if world.unlocked(x, y)]
    tiles.sort(key=lambda t: (_dist(t, shed), t[1], t[0]))
    return tiles


def _plan_layout(world):
    """Give every unlocked tile a role: animals near the shed, then feed wheat,
    then melon out in the far corners where its 8 waterings cost least."""
    slots = _slots(world)
    n_animals = sum(TARGETS.values())
    wheat_n = min(max(0, len(slots) - n_animals), n_animals + WHEAT_TILE_MARGIN)
    animal_slots = slots[:n_animals]
    wheat_slots = slots[n_animals:n_animals + wheat_n]
    melon_slots = slots[n_animals + wheat_n:][::-1][:MELON_TILES]
    return animal_slots, wheat_slots, melon_slots


# --- market ---------------------------------------------------------------

def _fib(n):
    a, b = 1, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def _sell_orders(world):
    """Trickle sells. The marginal price is what matters, not the average: these
    curves are steep enough that the last unit of a batch can pay a fraction of
    the first."""
    liquidating = world.day >= LIQUIDATE_FROM_DAY
    orders = []
    for item in PRODUCTS:
        have = world.shed.get(item, 0)
        if have <= 0:
            continue
        inv = world.inv.get(item, 10000)
        if liquidating:
            n = have
        else:
            current = world.prices.get(item) or price(item, inv)
            floor = max(2, int(SELL_FLOOR_FRACTION.get(item, 0.5) * MARKET_PARAMS[item]["base"]))
            if current < floor:
                continue
            n = min(have, max(1, units_until_price(item, inv, floor)))
        if n > 0:
            orders.append((item, n))
    # Order slots are capped at 10 a turn, so spend them on the biggest tickets.
    orders.sort(key=lambda o: -price(o[0], world.inv.get(o[0], 10000)) * o[1])
    return [["SELL", item, n] for item, n in orders]


def _feed_need(world):
    return len(world.animals) * (1 + FEED_BUFFER_DAYS)


def _buy_orders(world):
    orders = []
    money = world.money
    shed_free = world.shed_free()
    animal_slots, wheat_slots, melon_slots = _plan_layout(world)

    # 1. Feed FIRST. Protecting assets we already own beats acquiring new ones:
    #    an animal that misses two consecutive feedings is gone permanently, and
    #    buying cows until the cash runs out is exactly how that happens.
    wheat_unit = price("WHEAT", world.inv.get("WHEAT", 10000) - 1)
    feed_short = max(0, _feed_need(world) - world.shed.get("WHEAT", 0))
    if feed_short > 0 and shed_free > SHED_HEADROOM:
        n = min(feed_short, shed_free - SHED_HEADROOM, int(money // max(1, wheat_unit)))
        if n > 0:
            orders.append(["BUY_PRODUCT", "WHEAT", n])
            money -= n * wheat_unit
            shed_free -= n
            feed_short -= n

    # Whatever feed we still could not buy has to stay affordable next turn.
    feed_reserve = feed_short * wheat_unit

    # 2. Animals: the compounding asset. Fertilizer pays from day 1 whether or not
    #    the animal is fed, so a cow starts earning tomorrow, long before it milks.
    for kind, target in TARGETS.items():
        if target <= 0 or world.day > LAST_FULL_YIELD_START[kind]:
            continue
        in_shed = world.shed.get(kind, 0)
        owned = world.count_animals(kind) + in_shed
        cost = ANIMALS[kind]["cost"]
        # Cap the queue: an animal waiting in the shed earns nothing, and buying
        # seven cows on day 0 strands $2,400 for a week.
        # Animals cannot be sold back, so one left in the shed at the end is a
        # total write-off. Late in the season, only buy against a pasture that
        # already exists.
        queue = ANIMAL_QUEUE if world.days_left > 6 else 0
        deployable = len(world.empty_structures(ANIMALS[kind]["structure"])) + queue
        want = min(target - owned, len(animal_slots), max(0, deployable - in_shed))
        # Each new animal adds its own feed bill for the rest of the season.
        per_animal_feed = wheat_unit * (1 + FEED_BUFFER_DAYS)
        while want > 0 and money - feed_reserve >= cost + per_animal_feed and shed_free > 0:
            orders.append(["BUY_ANIMAL", kind, 1])
            money -= cost
            shed_free -= 1
            want -= 1

    # 3. Land, once there is more work than there are tiles to put it on.
    extra = len(world.quadrants) - 1
    if extra < len(LAND_PRICES):
        n_animals = sum(TARGETS.values())
        needed = n_animals * 2 + WHEAT_TILE_MARGIN + MELON_TILES
        # A week of feed for the whole herd, so land never starves the animals:
        # buying NE on day 9 with $2.4k once cost ~$4k of escaped livestock.
        safety = wheat_unit * len(world.animals) * 7
        spare = money - feed_reserve - safety
        if (LAND_ENABLED and len(_slots(world)) < needed
                and spare >= LAND_PRICES[extra] * LAND_CASH_MULT
                and world.days_left >= LAND_MIN_DAYS_LEFT):
            orders.append(["BUY_LAND"])
            money -= LAND_PRICES[extra]

    # 4. Seeds for whatever we still intend to plant.
    for crop, slots in (("WHEAT", wheat_slots), ("MELON", melon_slots)):
        if not slots or world.day > LAST_FULL_YIELD_START[crop]:
            continue
        planted = sum(1 for p in world.plants if p.crop == crop)
        want = len(slots) - planted - world.seeds.get(crop, 0)
        seed_cost = CROPS[crop]["seed"]
        n = 0
        while n < want and money - feed_reserve >= seed_cost:
            money -= seed_cost
            n += 1
        if n > 0:
            orders.append(["BUY_SEED", crop, n])
    return orders


def _pending_task_count(world):
    n = sum(1 for p in world.plants if p.wants_water or p.should_harvest)
    for a in world.animals:
        n += (0 if a.fed else 1) + (0 if a.cared else 1)
        n += (1 if a.fert else 0) + (1 if a.should_harvest else 0)
    n += min(len(world.empty), 8)
    return n


def _hire_orders(world):
    """Hands cost a few coins; the binding constraint is available work. A hand
    hired now cannot act until next turn, so this only runs at hour 0."""
    pending = _pending_task_count(world)
    want = min(MAX_HANDS, max(1, (pending + TASKS_PER_UNIT_DAY - 1) // TASKS_PER_UNIT_DAY))
    orders, money = [], world.money
    for k in range(world.hires_today, want):
        cost = world.hire_mult * _fib(k)
        if money < cost:
            break
        orders.append(["HIRE"])
        money -= cost
    return orders


def market_plan(world):
    """Order slots are capped at 10 per turn and HIRE consumes one each, so the
    two compete. Hiring is time-critical (a hand cannot act until the next turn)
    while selling is not -- there are 23 more turns today to sell in. So hour 0
    belongs to hires, and sells start at hour 1.

    Getting this backwards cost ~24% of the bank: nine hire orders were being
    truncated away by sells that could have waited.
    """
    if world.hour == 0:
        hires = _hire_orders(world)
        return (hires + _sell_orders(world))[: world.max_orders]
    if world.hour == 1:
        return (_buy_orders(world) + _sell_orders(world))[: world.max_orders]
    return _sell_orders(world)[: world.max_orders]


# --- tasks ----------------------------------------------------------------

def build_tasks(world):
    """Everything worth doing right now, as (priority, pos, verb, arg)."""
    tasks = []
    animal_slots, wheat_slots, melon_slots = _plan_layout(world)
    occupied = {p.pos for p in world.plants} | {a.pos for a in world.animals}
    occupied |= {(x, y) for x, y, _ in world.structures}

    for p in world.plants:
        if p.should_harvest:
            tasks.append((P_HARVEST_CROP, p.pos, "HARVEST", None))
        elif p.wants_water:
            tasks.append((P_WATER_DYING if p.dies_tonight else P_WATER_BONUS, p.pos, "WATER", None))

    for a in world.animals:
        if not a.fed:
            tasks.append((P_FEED, a.pos, "FEED", None))
        if a.should_harvest:
            tasks.append((P_HARVEST_ANIMAL, a.pos, "HARVEST", None))
        if not a.cared:
            tasks.append((P_CARE, a.pos, "CARE", None))
        if a.fert:
            tasks.append((P_COLLECT, a.pos, "COLLECT_FERTILIZER", None))

    waiting = 0
    for kind in ANIMALS:
        in_shed = world.shed.get(kind, 0)
        waiting += in_shed
        for pos in world.empty_structures(ANIMALS[kind]["structure"])[:in_shed]:
            tasks.append((P_PLACE_ANIMAL, pos, "PLACE", kind))

    # When animals are queued in the shed, the structure they need is nearly the
    # most urgent thing on the farm -- every idle day is a day of lost fertilizer.
    free_structures = sum(len(world.empty_structures(ANIMALS[k]["structure"])) for k in ANIMALS)
    build_prio = P_BUILD_URGENT if waiting > free_structures else P_BUILD
    for pos in animal_slots:
        if pos not in occupied:
            tasks.append((build_prio, pos, "BUILD_PASTURE", None))

    for crop, slots in (("WHEAT", wheat_slots), ("MELON", melon_slots)):
        if world.day > LAST_FULL_YIELD_START[crop] or world.seeds.get(crop, 0) <= 0:
            continue
        for pos in slots:
            if pos not in occupied:
                tasks.append((P_PLANT, pos, "PLANT", crop))

    for pos in world.weeds:
        tasks.append((P_DIG, pos, "DIG", None))
    return tasks


# Claims persist across turns within a day. Without them a unit re-picks the
# globally highest-priority task every turn and ping-pongs across the farm; that
# alone was burning 62% of all actions on movement.
_CLAIMS = {"day": -1, "by_unit": {}}


def reset():
    """New episode: drop routing state carried over from the previous one."""
    _CLAIMS["day"] = -1
    _CLAIMS["by_unit"] = {}


def assign(world, tasks):
    """Sticky greedy assignment: a unit keeps its target until the job is done.

    Deliberately not optimal -- this is a team orienteering problem, and greedy
    plus stickiness captures most of the value at no runtime cost.
    """
    if _CLAIMS["day"] != world.day:
        _CLAIMS["day"] = world.day
        _CLAIMS["by_unit"] = {}
    claims = _CLAIMS["by_unit"]

    live = {(pos, verb, arg) for _, pos, verb, arg in tasks}
    for idx in list(claims):
        if idx >= world.n_units or claims[idx] not in live:
            del claims[idx]

    held = set(claims.values())
    # Seeds are shared, and an over-request plants nothing at all for that crop,
    # so reserve against claims already outstanding.
    seeds_left = dict(world.seeds)
    for _pos, verb, arg in held:
        if verb == "PLANT":
            seeds_left[arg] = seeds_left.get(arg, 0) - 1

    unclaimed = [i for i in range(world.n_units) if i not in claims]
    for _prio, pos, verb, arg in sorted(tasks, key=lambda t: t[0]):
        if not unclaimed:
            break
        key = (pos, verb, arg)
        if key in held:
            continue
        if verb == "PLANT" and seeds_left.get(arg, 0) <= 0:
            continue
        pool = unclaimed
        if verb == "FEED":
            # A unit already holding wheat can feed without a shed round trip.
            carriers = [i for i in unclaimed if world.carried(i, "WHEAT") > 0]
            pool = carriers or unclaimed
        idx = min(pool, key=lambda i: (_dist(world.units[i], pos), i))
        claims[idx] = key
        held.add(key)
        if verb == "PLANT":
            seeds_left[arg] = seeds_left.get(arg, 0) - 1
        unclaimed.remove(idx)

    actions = {}
    for idx, (pos, verb, arg) in list(claims.items()):
        unit_pos = world.units[idx]

        # FEED draws wheat from this unit's inventory, never the shed, and no-ops
        # silently when the unit is empty-handed.
        if verb == "FEED" and world.carried(idx, "WHEAT") <= 0:
            actions[idx] = _fetch(world, unit_pos, "WHEAT", max(2, len(world.animals)))
            continue
        if verb == "PLACE" and world.carried(idx, arg) <= 0:
            actions[idx] = _fetch(world, unit_pos, arg, 1)
            continue

        if tuple(unit_pos) == tuple(pos):
            actions[idx] = [verb] + ([arg] if arg else [])
            del claims[idx]
        else:
            actions[idx] = _step_toward(world, unit_pos, pos)

    for idx in range(world.n_units):
        actions.setdefault(idx, ["PASS"])
    return actions


def _fetch(world, unit_pos, item, count):
    """Head to the shed and pick `item` up, keeping the current claim intact.

    Hands spawn on shed-access tiles that are LOCKED until NE/SW are bought, but
    PICKUP resolves before the LOCKED guard in the environment -- it uses the tile
    only as a standing position -- so this works from turn one.
    """
    if world.is_shed_adjacent(unit_pos):
        available = world.shed.get(item, 0)
        return ["PICKUP", item, min(count, available)] if available > 0 else ["PASS"]
    return _step_toward(world, unit_pos, _shed_pos(world))


def decide(world):
    """Full turn: unit actions plus market orders."""
    actions = assign(world, build_tasks(world))
    hands = [actions.get(i + 1, ["PASS"]) for i in range(max(0, world.n_units - 1))]
    return {"farmer": actions.get(0, ["PASS"]), "hands": hands, "market": market_plan(world)}
