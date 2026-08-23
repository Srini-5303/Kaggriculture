"""The 27 published market table values, plus the invariants the docs assert."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.constants import MARKET_I0, MARKET_PARAMS, PRODUCTS
from agent.market import buy_cost, daily_drain, price, sell_revenue

# P(I0-T), P(I0+T), P(I0+2T) for each resource, straight from the competition tables.
PUBLISHED = {
    "WHEAT":      (45, 20, 19),
    "CARROT":     (70, 10, 1),
    "TOMATO":     (84, 24, 9),
    "STRAWBERRY": (204, 1, 1),
    "MELON":      (300, 1, 1),
    "EGG":        (70, 40, 39),
    "MILK":       (256, 1, 1),
    "WOOL":       (240, 1, 1),
    "FERTILIZER": (140, 60, 20),
}


def test_all_27_published_values():
    for item, expected in PUBLISHED.items():
        T = MARKET_PARAMS[item]["T"]
        got = (
            price(item, MARKET_I0 - T),
            price(item, MARKET_I0 + T),
            price(item, MARKET_I0 + 2 * T),
        )
        assert got == expected, f"{item}: got {got}, published {expected}"


def test_base_price_at_equilibrium():
    for item in PRODUCTS:
        assert price(item, MARKET_I0) == MARKET_PARAMS[item]["base"]


def test_price_is_monotone_non_increasing_in_inventory():
    for item in PRODUCTS:
        prev = None
        for inv in range(MARKET_I0 - 900, MARKET_I0 + 900, 25):
            p = price(item, inv)
            if prev is not None:
                assert p <= prev, f"{item} rose with inventory at {inv}"
            prev = p


def test_buy_then_sell_round_trip_nets_zero():
    """Buys quote post-buy, sells quote pre-sell, so the arbitrage is closed."""
    for item in ("WHEAT", "FERTILIZER"):
        cost, _ = buy_cost(item, MARKET_I0, 1)
        revenue, _ = sell_revenue(item, MARKET_I0 - 1, 1)
        assert cost == revenue, f"{item}: buy {cost} vs sell {revenue}"


def test_floor_sales_do_not_deepen_the_glut():
    """At $1 the unit pays but is not added to inventory, so price stays responsive."""
    deep = MARKET_I0 + 5000
    assert price("MELON", deep) == 1
    total, last = sell_revenue("MELON", deep, 50)
    assert total == 50 and last == 1


def test_documented_drain_rates():
    """Per CLAUDE.md section 4: a wheat shop pulls 6/day, a single-product shop 12/day."""
    assert daily_drain(["BAKERY"])["WHEAT"] == 6 + 1        # shop + town centre
    assert daily_drain(["YARN_STORE"])["WOOL"] == 12 + 1    # single-product doubles
    assert daily_drain(["BAKERY", "BAKERY"])["WHEAT"] == 12 + 1
    assert daily_drain([])["FERTILIZER"] == 0               # town centre skips fertilizer
    assert daily_drain(list(range(0)))["MELON"] == 1        # no shop demands melon


def test_melon_has_no_shop_demand():
    from agent.constants import SHOPS
    assert not any("MELON" in items for items in SHOPS.values())
