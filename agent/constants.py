"""Game tables transcribed verbatim from kaggriculture.py, plus derived schedules.

Do NOT edit these from the published docs -- the docs and the source disagree in
at least one place (melon's max_yield_day is 12 in source, 10 in the table).
Source: <site-packages>/kaggle_environments/envs/kaggriculture/kaggriculture.py
"""

# --- verbatim from source -------------------------------------------------

CROPS = {
    "WHEAT":      {"seed": 10,  "first_yield_day": 2,  "max_yield_day": 4,  "interval": 0, "max_yield": 6, "ongoing": False},
    "CARROT":     {"seed": 20,  "first_yield_day": 2,  "max_yield_day": 3,  "interval": 0, "max_yield": 4, "ongoing": False},
    "TOMATO":     {"seed": 50,  "first_yield_day": 8,  "max_yield_day": 8,  "interval": 1, "max_yield": 4, "ongoing": True},
    "STRAWBERRY": {"seed": 100, "first_yield_day": 10, "max_yield_day": 10, "interval": 2, "max_yield": 4, "ongoing": True},
    "MELON":      {"seed": 80,  "first_yield_day": 10, "max_yield_day": 12, "interval": 0, "max_yield": 6, "ongoing": False},
}

ANIMALS = {
    "GOOSE": {"cost": 300, "structure": "COOP",    "first_yield_day": 4, "interval": 1, "max_held": 4, "product": "EGG"},
    "COW":   {"cost": 400, "structure": "PASTURE", "first_yield_day": 8, "interval": 2, "max_held": 6, "product": "MILK"},
    "SHEEP": {"cost": 500, "structure": "PASTURE", "first_yield_day": 6, "interval": 3, "max_held": 6, "product": "WOOL"},
}

PRODUCTS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER"]

MARKET_I0 = 10000
PRICE_FLOOR = 1
HINGE_GAIN = 8.0

MARKET_PARAMS = {
    "WHEAT":      {"base":  25, "I0": MARKET_I0, "T": 400, "below_func": "sqrt",   "below_target": 0.80, "above_func": "log",    "above_target": 0.20},
    "CARROT":     {"base":  35, "I0": MARKET_I0, "T": 450, "below_func": "hinge",  "below_target": 1.00, "above_func": "sqrt",   "above_target": 0.70},
    "TOMATO":     {"base":  60, "I0": MARKET_I0, "T": 200, "below_func": "hinge",  "below_target": 0.40, "above_func": "sqrt",   "above_target": 0.60},
    "STRAWBERRY": {"base": 120, "I0": MARKET_I0, "T": 100, "below_func": "sqrt",   "below_target": 0.70, "above_func": "linear", "above_target": 1.60},
    "MELON":      {"base": 250, "I0": MARKET_I0, "T": 300, "below_func": "log",    "below_target": 0.20, "above_func": "sq",     "above_target": 3.60},
    "EGG":        {"base":  50, "I0": MARKET_I0, "T": 332, "below_func": "hinge",  "below_target": 0.40, "above_func": "log",    "above_target": 0.20},
    "MILK":       {"base": 160, "I0": MARKET_I0, "T": 122, "below_func": "sqrt",   "below_target": 0.60, "above_func": "linear", "above_target": 1.60},
    "WOOL":       {"base": 200, "I0": MARKET_I0, "T": 105, "below_func": "log",    "below_target": 0.20, "above_func": "sq",     "above_target": 3.20},
    "FERTILIZER": {"base": 100, "I0": MARKET_I0, "T": 200, "below_func": "linear", "below_target": 0.40, "above_func": "linear", "above_target": 0.40},
}

SHOPS = {
    "BAKERY":         ["EGG", "WHEAT"],
    "PIZZA_SHOP":     ["MILK", "TOMATO", "WHEAT"],
    "BRUNCH_SPOT":    ["EGG", "WHEAT", "STRAWBERRY"],
    "YARN_STORE":     ["WOOL"],
    "ICE_CREAM_SHOP": ["STRAWBERRY", "MILK", "WHEAT"],
    "PET_CAFE":       ["CARROT"],
    "SMOOTHIE_SHOP":  ["STRAWBERRY", "MILK"],
    "FARMERS_MARKET": ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY"],
}

TOWN_CENTER_PRODUCTS = [p for p in PRODUCTS if p != "FERTILIZER"]
MAX_SHOP_INSTANCES = 8

LAND_ORDER = ["NE", "SW", "SE"]
LAND_PRICES = [1000, 2000, 4000]

# (dx, dy); y grows downward.
MOVES = {"NORTH": (0, -1), "SOUTH": (0, 1), "EAST": (1, 0), "WEST": (-1, 0)}

BUYABLE_PRODUCTS = ("WHEAT", "FERTILIZER")

# --- config defaults (kaggriculture.json) ---------------------------------

DEFAULTS = {
    "episodeSteps": 720,
    "boardSize": 10,
    "startingMoney": 3000,
    "maxMarketOrdersPerTurn": 10,
    "turnsPerDay": 24,
    "shedCapacity": 100,
    "weedSpawnChance": 0.005,
    "townShopUnlockInterval": 3,
    "townShopSellInterval": 4,
    "townCenterSellInterval": 24,
    "farmHandCostMult": 1,
    "actTimeout": 1,
}

# --- derived schedules ----------------------------------------------------
#
# All of these follow from source, not from the published tables:
#   window_start   = (max_yield_day + 1) // 2          (WATER branch)
#   one-time yield = 1 at plant, +1 per watered bonus day, capped at max_yield
#   rot begins at  = (planted_day + max_yield_day + 1) * turnsPerDay
#   ongoing yield  = +1 per scheduled tick regardless of watering


def _bonus_window(crop):
    """Ages at which WATER adds yield to a one-time crop."""
    cd = CROPS[crop]
    if cd["ongoing"]:
        return ()
    return tuple(range((cd["max_yield_day"] + 1) // 2, cd["max_yield_day"] + 1))


def _useful_bonus_days(crop):
    """Bonus days that actually add yield. Yield starts at 1 and caps at max_yield,
    so only the first (max_yield - 1) days of the window can ever pay.

    This is why melon waters to age 10 and not 12: its window is 6-12, but the cap
    of 6 is reached at age 10 and ages 11-12 add nothing.
    """
    window = _bonus_window(crop)
    if not window:
        return ()
    return window[: CROPS[crop]["max_yield"] - 1]


def _yield_ages(crop):
    """Ages at which produce is available. One-time crops: the harvestable range,
    starting at first_yield_day (harvesting earlier is a no-op) and ending at the
    last age before rot."""
    cd = CROPS[crop]
    if cd["ongoing"]:
        return tuple(cd["first_yield_day"] + i * cd["interval"] for i in range(cd["max_yield"]))
    return tuple(range(cd["first_yield_day"], cd["max_yield_day"] + 1))


def _target_harvest_age(crop):
    """Earliest age at which the crop is both harvestable and at full yield."""
    cd = CROPS[crop]
    if cd["ongoing"]:
        return None
    useful = _useful_bonus_days(crop)
    ripe = cd["first_yield_day"]
    return max(ripe, useful[-1]) if useful else ripe


def _water_days(crop):
    """Ages to water. Bonus days that pay, plus survival waterings so we never
    leave two consecutive unwatered days before we are done with the tile.

    consecutive_unwatered starts at 1 on planting, so age 0 is always included:
    a seed planted and not watered the same day is a weed by morning.
    """
    cd = CROPS[crop]
    last = _target_harvest_age(crop) if not cd["ongoing"] else _yield_ages(crop)[-1]
    days = set(_useful_bonus_days(crop))
    days.add(0)
    age = 0
    while age <= last:
        # Only water for survival if neither neighbour day is already watered.
        if age not in days and (age - 1) not in days and (age + 1) not in days:
            days.add(age)
        age += 1
    return tuple(sorted(d for d in days if d <= last))


BONUS_WINDOW = {c: _bonus_window(c) for c in CROPS}
USEFUL_BONUS_DAYS = {c: _useful_bonus_days(c) for c in CROPS}
WATER_DAYS = {c: _water_days(c) for c in CROPS}
YIELD_AGES = {c: _yield_ages(c) for c in CROPS}
TARGET_HARVEST_AGE = {c: _target_harvest_age(c) for c in CROPS}

# Age at which yield starts decaying (1 unit per 2 turns). None for ongoing crops,
# which only set max_lifespan_step after their final scheduled production.
ROT_AGE = {c: (None if CROPS[c]["ongoing"] else CROPS[c]["max_yield_day"] + 1) for c in CROPS}

# max_held destroys overflow rather than deferring it, so this is the longest gap
# in days we can leave between harvests without losing production.
HARVEST_CADENCE = {
    a: (ANIMALS[a]["max_held"] // (1 + ANIMALS[a]["interval"])) * max(1, ANIMALS[a]["interval"])
    for a in ANIMALS
}

# Latest day an asset can be started and still return anything (season ends day 29).
LAST_USEFUL_START = {c: 29 - CROPS[c]["first_yield_day"] for c in CROPS}
LAST_USEFUL_START.update({a: 29 - ANIMALS[a]["first_yield_day"] for a in ANIMALS})

# Latest start that still returns FULL yield -- this is the one the planner wants.
# (LAST_USEFUL_START above is the laxer "returns at least one unit" bound.)
LAST_FULL_YIELD_START = {
    c: 29 - (TARGET_HARVEST_AGE[c] if TARGET_HARVEST_AGE[c] is not None else YIELD_AGES[c][-1])
    for c in CROPS
}
LAST_FULL_YIELD_START.update({a: 29 - ANIMALS[a]["first_yield_day"] for a in ANIMALS})
