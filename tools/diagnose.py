"""Single-episode telemetry: where the money and the actions actually go.

These are the regression signals from the PRD. Most of them show a problem long
before the final bank does -- an animal escaping on day 6 costs ~$8k of milk that
never appears as anything but a slightly lower score.
"""

import io
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_stderr = sys.stderr
sys.stderr = io.StringIO()
from kaggle_environments import make  # noqa: E402
sys.stderr = _stderr

import main  # noqa: E402
from agent.world import World  # noqa: E402


def run(opponent="starter", seed=1000, verbose=True):
    verbs = Counter()
    daily = {}
    events = []
    prev = {"animals": 0, "plants": {}, "money": 3000.0}

    def instrumented(obs, config=None):
        action = main.agent(obs, config)
        w = World(obs, config)

        verbs[action["farmer"][0]] += 1
        for h in action["hands"]:
            verbs[h[0]] += 1
        for order in action["market"]:
            verbs["mkt:" + order[0]] += 1

        # An animal count that drops without us selling means an escape.
        n_animals = len(w.animals)
        if n_animals < prev["animals"]:
            events.append(f"day {w.day:2d} h{w.hour:02d}  ANIMAL LOST ({prev['animals']} -> {n_animals})")
        prev["animals"] = n_animals

        # A plant that becomes a weed died of thirst.
        for pos in w.weeds:
            if pos in prev["plants"]:
                events.append(f"day {w.day:2d} h{w.hour:02d}  WITHERED {prev['plants'][pos]} at {pos}")
                del prev["plants"][pos]
        prev["plants"] = {p.pos: p.crop for p in w.plants}

        # Rot: yield draining off a mature tile we failed to harvest in time.
        for p in w.plants:
            if p.rotting and p.units > 0:
                events.append(f"day {w.day:2d} h{w.hour:02d}  ROTTING {p.crop} at {p.pos} units={p.units}")

        if w.shed_used() >= w.shed_cap:
            events.append(f"day {w.day:2d} h{w.hour:02d}  SHED FULL ({w.shed_used()}) - buys now blocked")

        if w.hour == 0:
            daily[w.day] = {
                "money": w.money,
                "units": w.n_units,
                "animals": Counter(a.animal for a in w.animals),
                "plants": Counter(p.crop for p in w.plants),
                "shed": w.shed_used(),
                "wheat": w.shed.get("WHEAT", 0),
                "tiles": len(w.quadrants) * 25,
                "prices": {k: w.prices.get(k) for k in ("MILK", "FERTILIZER", "WHEAT", "MELON")},
            }
        return action

    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=True)
    env.run([instrumented, opponent])
    final = env.steps[-1]
    bank = float(final[0].observation.farms[0]["money"])
    opp = float(final[0].observation.farms[1]["money"])

    if verbose:
        print(f"=== seed {seed} vs {opponent}:  bank {bank:,.0f}   opponent {opp:,.0f} ===\n")
        print(f"{'day':>3} {'money':>9} {'un':>3} {'tiles':>5} {'animals':>16} {'plants':>14} {'shed':>5} {'wht':>4}  milk/fert/wheat")
        for d in sorted(daily):
            r = daily[d]
            an = ",".join(f"{k[:2]}{v}" for k, v in sorted(r["animals"].items())) or "-"
            pl = ",".join(f"{k[:2]}{v}" for k, v in sorted(r["plants"].items())) or "-"
            p = r["prices"]
            print(f"{d:>3} {r['money']:>9,.0f} {r['units']:>3} {r['tiles']:>5} {an:>16} {pl:>14} "
                  f"{r['shed']:>5} {r['wheat']:>4}  {p['MILK']}/{p['FERTILIZER']}/{p['WHEAT']}")

        total_unit_actions = sum(v for k, v in verbs.items() if not k.startswith("mkt:"))
        print(f"\n--- unit actions ({total_unit_actions:,} total) ---")
        for verb, n in verbs.most_common():
            if not verb.startswith("mkt:"):
                print(f"  {verb:<20} {n:>6}  {n/total_unit_actions*100:>5.1f}%")
        print("\n--- market orders ---")
        for verb, n in verbs.most_common():
            if verb.startswith("mkt:"):
                print(f"  {verb[4:]:<20} {n:>6}")

        losses = [e for e in events if "ROTTING" not in e]
        rot = [e for e in events if "ROTTING" in e]
        print(f"\n--- losses ({len(losses)}) ---")
        for e in losses[:25]:
            print("  " + e)
        if rot:
            print(f"  (+{len(rot)} rot ticks, first: {rot[0]})")
        if not events:
            print("  none")
    return bank, opp, verbs, events


if __name__ == "__main__":
    opponent = sys.argv[1] if len(sys.argv) > 1 else "starter"
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
    run(opponent, seed)
