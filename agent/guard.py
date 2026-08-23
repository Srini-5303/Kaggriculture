"""Legality filter and last-resort fallback.

Every rule here corresponds to a real behaviour in kaggriculture.py, and most of
them fail *silently* in the environment -- a bad action is not an error, it is a
wasted turn. The expensive ones are the two that poison other units:

  * a `hands` entry with no matching hand still counts against the PLANT seed
    budget, and an over-budget PLANT plants NOTHING for that crop
  * `BUY_PRODUCT` / `BUY_ANIMAL` abort when the shed is full, which starves the
    herd of feed while cash sits idle
"""

from .constants import ANIMALS, BUYABLE_PRODUCTS, CROPS, MOVES, PRODUCTS

SAFE_TURN = {"farmer": ["PASS"], "hands": [], "market": []}

TILE_VERBS = {
    "PLANT", "WATER", "HARVEST", "FERTILIZE", "DIG",
    "BUILD_COOP", "BUILD_PASTURE", "FEED", "COLLECT_FERTILIZER", "CARE",
}
SHED_VERBS = {"PICKUP", "DROP", "PLACE"}
VALID_VERBS = TILE_VERBS | SHED_VERBS | set(MOVES) | {"PASS"}

MARKET_VERBS = {"BUY_SEED", "BUY_PRODUCT", "BUY_ANIMAL", "SELL", "HIRE", "BUY_LAND"}


def safe_turn(n_hands=0):
    return {"farmer": ["PASS"], "hands": [["PASS"]] * n_hands, "market": []}


def _tile_at(world, pos):
    x, y = pos
    if not (0 <= x < world.board and 0 <= y < world.board):
        return "LOCKED"
    return world.tiles[y][x]


def _unit_action_ok(world, idx, action, plant_budget):
    """True if the action will actually do something. Mutates plant_budget."""
    if not isinstance(action, list) or not action:
        return False
    verb = action[0]
    if verb not in VALID_VERBS:
        return False
    if verb == "PASS":
        return True

    if idx >= len(world.units):
        return False
    pos = world.units[idx]
    x, y = pos

    if verb in MOVES:
        dx, dy = MOVES[verb]
        # Off-board moves are no-ops in the env, so they waste the turn.
        return 0 <= x + dx < world.board and 0 <= y + dy < world.board

    tile = _tile_at(world, pos)
    shed_adj = world.is_shed_adjacent(pos)

    # Shed verbs resolve BEFORE the LOCKED guard in the env: they use the tile
    # only as a standing position, which is why a hand spawned on a locked
    # shed-access tile can still pick up.
    if verb == "DROP":
        return shed_adj and bool(world.inventories[idx] if idx < len(world.inventories) else {})
    if verb == "PICKUP":
        if len(action) < 2 or not shed_adj:
            return False
        return world.shed.get(action[1], 0) > 0
    if verb == "PLACE":
        if len(action) < 2:
            return False
        item = action[1]
        if item in ANIMALS:
            ok_tile = (
                isinstance(tile, dict)
                and tile.get("kind") == ANIMALS[item]["structure"]
                and "animal" not in tile
            )
            if ok_tile:
                return world.carried(idx, item) > 0
        if shed_adj:
            return world.carried(idx, item) > 0 and world.shed_free() > 0
        return False

    # Everything below mutates the tile, so it needs the tile to be owned.
    if tile == "LOCKED":
        return False

    if verb == "PLANT":
        if len(action) < 2 or action[1] not in CROPS or tile is not None:
            return False
        crop = action[1]
        if plant_budget.get(crop, 0) <= 0:
            return False
        plant_budget[crop] -= 1
        return True

    is_plant = isinstance(tile, dict) and tile.get("kind") == "PLANT"
    is_animal = isinstance(tile, dict) and "animal" in tile

    if verb == "WATER":
        return is_plant and not tile["watered_today"]
    if verb == "HARVEST":
        if is_plant:
            age = world.day - tile["planted_day"]
            return tile["yield_units"] > 0 and age >= CROPS[tile["crop"]]["first_yield_day"]
        return is_animal and tile.get("yield_units", 0) > 0
    if verb == "FERTILIZE":
        return is_plant and world.carried(idx, "FERTILIZER") > 0
    if verb == "DIG":
        return tile is not None and not is_animal
    if verb in ("BUILD_COOP", "BUILD_PASTURE"):
        return tile is None
    if verb == "FEED":
        return is_animal and not tile.get("fed_today") and world.carried(idx, "WHEAT") > 0
    if verb == "COLLECT_FERTILIZER":
        return is_animal and bool(tile.get("fertilizer_available"))
    if verb == "CARE":
        return is_animal and not tile.get("cared_today")
    return False


def _market_order_ok(world, order, budget):
    if not isinstance(order, list) or not order:
        return False
    op = order[0]
    if op not in MARKET_VERBS:
        return False
    if op in ("HIRE", "BUY_LAND"):
        return True
    if len(order) < 3:
        return False
    item = order[1]
    try:
        n = int(order[2])
    except (TypeError, ValueError):
        return False
    if n <= 0:
        return False
    if op == "SELL":
        return item in PRODUCTS and world.shed.get(item, 0) > 0
    if op == "BUY_SEED":
        return item in CROPS
    if op == "BUY_PRODUCT":
        # Buys land in the shed and abort outright when it is full.
        if item not in BUYABLE_PRODUCTS or budget["shed_free"] <= 0:
            return False
        budget["shed_free"] -= 1
        return True
    if op == "BUY_ANIMAL":
        if item not in ANIMALS or budget["shed_free"] <= 0:
            return False
        budget["shed_free"] -= 1
        return True
    return False


def sanitize(world, action):
    """Filter a proposed turn down to actions that will actually take effect."""
    n_hands = len(world.farm["hands"])
    if not isinstance(action, dict):
        return safe_turn(n_hands)

    # Seeds are shared across units, so the budget must be global to the turn.
    plant_budget = dict(world.seeds)

    farmer = action.get("farmer", ["PASS"])
    if not _unit_action_ok(world, 0, farmer, plant_budget):
        farmer = ["PASS"]

    raw_hands = action.get("hands", [])
    if not isinstance(raw_hands, list):
        raw_hands = []
    # Exactly one entry per real hand. Surplus entries are not merely ignored --
    # they consume the PLANT seed budget and can block a real unit from planting.
    hands = []
    for i in range(n_hands):
        candidate = raw_hands[i] if i < len(raw_hands) else ["PASS"]
        hands.append(candidate if _unit_action_ok(world, i + 1, candidate, plant_budget) else ["PASS"])

    raw_market = action.get("market", [])
    if not isinstance(raw_market, list):
        raw_market = []
    budget = {"shed_free": world.shed_free()}
    market = []
    for order in raw_market:
        if len(market) >= world.max_orders:
            break
        if _market_order_ok(world, order, budget):
            market.append(list(order))

    return {"farmer": list(farmer), "hands": hands, "market": market}
