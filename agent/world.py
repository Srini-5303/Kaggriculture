"""obs -> typed World, with every derived field the policy needs.

Everything here is read-only interpretation of the observation. All the "is this
urgent" logic lives in derived properties so the policy never re-derives it.
"""

from .constants import (
    ANIMALS,
    CROPS,
    DEFAULTS,
    ROT_AGE,
    TARGET_HARVEST_AGE,
    USEFUL_BONUS_DAYS,
    WATER_DAYS,
)


def _g(obj, key, default=None):
    """Observation objects are structify-ed: support dict and attribute access."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class Plant:
    __slots__ = ("x", "y", "crop", "age", "watered", "unwatered", "units", "fert_until", "rot_step")

    def __init__(self, x, y, tile, day):
        self.x, self.y = x, y
        self.crop = tile["crop"]
        self.age = day - tile["planted_day"]
        self.watered = bool(tile["watered_today"])
        self.unwatered = tile["consecutive_unwatered"]
        self.units = tile["yield_units"]
        self.fert_until = tile.get("fertilized_until_day", -1)
        self.rot_step = tile.get("max_lifespan_step", -1)

    @property
    def pos(self):
        return (self.x, self.y)

    @property
    def dies_tonight(self):
        """consecutive_unwatered reaches 2 at the end-of-day refresh -> weed."""
        return not self.watered and self.unwatered >= 1

    @property
    def wants_water(self):
        if self.watered:
            return False
        return self.dies_tonight or self.age in WATER_DAYS[self.crop]

    @property
    def is_bonus_day(self):
        return self.age in USEFUL_BONUS_DAYS[self.crop]

    @property
    def harvestable(self):
        return self.units > 0 and self.age >= CROPS[self.crop]["first_yield_day"]

    @property
    def should_harvest(self):
        """One-time crops: at target age, because decay is per-turn once rot starts.
        Ongoing crops: whenever produce sits on the tile, since max_yield caps held
        units and leaving it there forfeits the next tick."""
        if not self.harvestable:
            return False
        if CROPS[self.crop]["ongoing"]:
            return True
        return self.age >= TARGET_HARVEST_AGE[self.crop]

    @property
    def rotting(self):
        rot = ROT_AGE[self.crop]
        return rot is not None and self.age >= rot


class Animal:
    __slots__ = ("x", "y", "kind", "animal", "age", "fed", "cared", "unfed", "units", "fert", "bonus")

    def __init__(self, x, y, tile, day):
        self.x, self.y = x, y
        self.kind = tile["kind"]
        self.animal = tile.get("animal")
        self.age = day - tile.get("placed_day", day)
        self.fed = bool(tile.get("fed_today"))
        self.cared = bool(tile.get("cared_today"))
        self.unfed = tile.get("consecutive_unfed", 0)
        self.units = tile.get("yield_units", 0)
        self.fert = bool(tile.get("fertilizer_available"))
        self.bonus = tile.get("pending_care_bonus", 0)

    @property
    def pos(self):
        return (self.x, self.y)

    @property
    def escapes_tonight(self):
        return not self.fed and self.unfed >= 1

    @property
    def spec(self):
        return ANIMALS[self.animal]

    @property
    def produces_tonight(self):
        """A tick fires when (day + 1 - placed_day - first_yield_day) % interval == 0."""
        a = self.spec
        since = (self.age + 1) - a["first_yield_day"]
        return since >= 0 and since % a["interval"] == 0

    @property
    def should_harvest(self):
        """max_held destroys overflow, so harvest before the next tick would exceed it."""
        a = self.spec
        if self.units <= 0:
            return False
        next_tick = 1 + max(self.bonus, 1)
        return self.units >= a["max_held"] or self.units + next_tick > a["max_held"]


class World:
    def __init__(self, obs, config=None):
        cfg = config or {}

        def conf(key):
            val = _g(cfg, key, None)
            return int(val) if val else DEFAULTS[key]

        self.turns_per_day = conf("turnsPerDay")
        self.board = conf("boardSize")
        self.shed_cap = conf("shedCapacity")
        self.max_orders = conf("maxMarketOrdersPerTurn")
        self.hire_mult = conf("farmHandCostMult")
        self.episode_steps = conf("episodeSteps")
        self.shop_interval = conf("townShopSellInterval")
        self.center_interval = conf("townCenterSellInterval")

        self.me = int(_g(obs, "player", 0) or 0)
        self.day = int(_g(obs, "day", 0) or 0)
        self.hour = int(_g(obs, "hour", 0) or 0)
        self.step = self.day * self.turns_per_day + self.hour
        # Reward is read when step >= episodeSteps - 2, so that is the real deadline.
        self.last_step = self.episode_steps - 2
        self.steps_left = max(0, self.last_step - self.step)
        self.last_day = self.last_step // self.turns_per_day
        self.days_left = max(0, self.last_day - self.day)

        farms = _g(obs, "farms", []) or []
        self.farm = farms[self.me]
        self.opp_farm = farms[1 - self.me] if len(farms) > 1 else None

        self.money = float(self.farm["money"])
        self.tiles = self.farm["tiles"]
        self.quadrants = list(self.farm["unlocked_quadrants"])
        self.hires_today = int(self.farm["hires_today"])

        priv = _g(obs, "private", {}) or {}
        self.shed = dict(_g(priv, "shed", {}) or {})
        self.seeds = dict(_g(priv, "seeds", {}) or {})
        self.inventories = [dict(i) for i in (_g(priv, "inventories", [{}]) or [{}])]

        market = _g(obs, "market", {}) or {}
        self.inv = dict(_g(market, "inventory", {}) or {})
        self.prices = dict(_g(market, "prices", {}) or {})
        town = _g(obs, "town", {}) or {}
        self.shops = list(_g(town, "unlocked_shops", []) or [])

        # units[0] is the farmer; 1+ are hands, index-aligned to farm["hands"].
        self.units = [tuple(self.farm["farmer"])] + [tuple(p) for p in self.farm["hands"]]
        self.n_units = len(self.units)

        self.plants, self.animals, self.structures, self.weeds, self.empty = [], [], [], [], []
        half = self.board // 2
        self.shed_tiles = {
            (half - 1, half - 1),
            (half, half - 1),
            (half - 1, half),
            (half, half),
        }
        for y, row in enumerate(self.tiles):
            for x, tile in enumerate(row):
                if tile is None:
                    self.empty.append((x, y))
                elif tile == "LOCKED":
                    continue
                elif isinstance(tile, dict):
                    kind = tile.get("kind")
                    if kind == "PLANT":
                        self.plants.append(Plant(x, y, tile, self.day))
                    elif kind == "WEED":
                        self.weeds.append((x, y))
                    elif "animal" in tile:
                        self.animals.append(Animal(x, y, tile, self.day))
                    else:
                        self.structures.append((x, y, kind))

    # --- helpers ----------------------------------------------------------

    def shed_used(self):
        return sum(self.shed.values())

    def shed_free(self):
        return max(0, self.shed_cap - self.shed_used())

    def carried(self, idx, item):
        return self.inventories[idx].get(item, 0) if idx < len(self.inventories) else 0

    def is_shed_adjacent(self, pos):
        return tuple(pos) in self.shed_tiles

    def unlocked(self, x, y):
        return self.tiles[y][x] != "LOCKED"

    def count_animals(self, kind=None):
        return sum(1 for a in self.animals if kind is None or a.animal == kind)

    def empty_structures(self, structure):
        return [(x, y) for x, y, k in self.structures if k == structure]

    def opp_tiles_of(self, crop):
        """Opponent planted tiles of a crop -- exact, unlike inventory inference."""
        if not self.opp_farm:
            return []
        out = []
        for y, row in enumerate(self.opp_farm["tiles"]):
            for x, tile in enumerate(row):
                if isinstance(tile, dict) and tile.get("kind") == "PLANT" and tile.get("crop") == crop:
                    out.append((x, y, self.day - tile["planted_day"]))
        return out
