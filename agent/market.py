"""Market price curve and revenue integration.

`price` mirrors `market_price` in kaggriculture.py exactly, including the int(round())
and the PRICE_FLOOR clamp. Verified against all 27 published table values.
"""

import math

from .constants import (
    HINGE_GAIN,
    MARKET_PARAMS,
    PRICE_FLOOR,
    PRODUCTS,
    SHOPS,
    TOWN_CENTER_PRODUCTS,
)


def _shape(func, x, T=None):
    x = max(0.0, x)
    if func == "linear":
        return x
    if func == "sq":
        return x * x
    if func == "sqrt":
        return math.sqrt(x)
    if func == "log":
        return math.log(1.0 + x)
    if func == "log10":
        return math.log10(1.0 + x)
    if func == "hinge":
        if not T or T <= 0:
            return x
        u = x / T
        return u + HINGE_GAIN * max(0.0, u - 1.0) ** 2
    return x


def price(item, inventory, params=None):
    """Sell price of `item` at market inventory `inventory`."""
    p = (params or MARKET_PARAMS)[item]
    base, I0, T = p["base"], p["I0"], p["T"]
    if inventory < I0:
        f, target, sign = p["below_func"], p["below_target"], 1.0
    else:
        f, target, sign = p["above_func"], p["above_target"], -1.0
    amp = target * base / _shape(f, T, T)
    return max(PRICE_FLOOR, int(round(base + sign * amp * _shape(f, abs(inventory - I0), T))))


def sell_revenue(item, inventory, n, params=None):
    """Total proceeds from selling `n` units one at a time, and the last unit's price.

    Sells are quoted at pre-sell inventory. A unit sold at the $1 floor still pays
    but does NOT increase market inventory, so the floor stays responsive.
    """
    inv, total, last = inventory, 0, price(item, inventory, params)
    for _ in range(max(0, n)):
        last = price(item, inv, params)
        total += last
        if last > PRICE_FLOOR:
            inv += 1
    return total, last


def buy_cost(item, inventory, n, params=None):
    """Total cost to buy `n` units. Buys are quoted at POST-buy inventory, which is
    what closes the buy-then-sell round trip."""
    inv, total, last = inventory, 0, price(item, inventory, params)
    for _ in range(max(0, n)):
        inv -= 1
        last = price(item, inv, params)
        total += last
    return total, last


def units_until_price(item, inventory, floor_price, params=None):
    """How many units can be sold before the marginal price drops below `floor_price`."""
    inv, n = inventory, 0
    while n < 5000:
        p = price(item, inv, params)
        if p < floor_price:
            return n
        n += 1
        if p > PRICE_FLOOR:
            inv += 1
        else:
            return n  # at the floor forever; no point counting further
    return n


def daily_drain(unlocked_shops, turns_per_day=24, shop_interval=4, center_interval=24):
    """Units of each product the town removes per day, from the live shop list."""
    ticks = turns_per_day // max(1, shop_interval)
    drain = {p: 0 for p in PRODUCTS}
    for shop in unlocked_shops:
        items = SHOPS.get(shop)
        if not items:
            continue
        mult = 2 if len(items) == 1 else 1
        for item in items:
            drain[item] += mult * ticks
    for item in TOWN_CENTER_PRODUCTS:
        drain[item] += turns_per_day // max(1, center_interval)
    return drain


def forecast_drain(unlocked_shops, days_remaining, **kw):
    """Season-remaining drain, assuming no further shop unlocks (conservative)."""
    per_day = daily_drain(unlocked_shops, **kw)
    return {k: v * max(0, days_remaining) for k, v in per_day.items()}
