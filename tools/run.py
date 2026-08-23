"""Parallel episode runner.

The real environment does a full 720-step episode in ~2.75 s, so ~22 episodes/min
single-core and ~220/min across 12 workers. That is fast enough that there is no
reason to maintain a separate fast simulator and risk it silently diverging.

Usage:
    python tools/run.py --n 20 --opponent starter
    python tools/run.py --n 50 --opponent starter --seeds fixed
    python tools/run.py --profile
"""

import argparse
import io
import json
import os
import statistics
import sys
import time
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

AGENT = os.path.join(ROOT, "main.py")


def _quiet_make():
    """kaggle_environments prints unrelated OpenSpiel warnings on import."""
    stderr = sys.stderr
    sys.stderr = io.StringIO()
    try:
        from kaggle_environments import make
    finally:
        sys.stderr = stderr
    return make


def play(job):
    """Run one episode. Returns a result dict; never raises."""
    seed, opponent, swap, want_replay = job
    make = _quiet_make()
    config = {"episodeSteps": 720}
    if seed is not None:
        config["seed"] = seed
    agents = [opponent, AGENT] if swap else [AGENT, opponent]
    me = 1 if swap else 0

    t0 = time.perf_counter()
    try:
        env = make("kaggriculture", configuration=config, debug=True)
        env.run(agents)
    except Exception as exc:  # noqa: BLE001 - runner must survive anything
        return {"seed": seed, "error": f"{type(exc).__name__}: {exc}", "bank": 0.0,
                "opp_bank": 0.0, "won": False, "status": "ERROR", "errors": []}
    elapsed = time.perf_counter() - t0

    final = env.steps[-1]
    banks = [float(s.observation.farms[i]["money"]) for i, s in enumerate(final)]
    statuses = [s.status for s in final]

    # Any stderr from our agent is a failure, even if the episode completed.
    agent_errors = []
    for entry in (env.logs or []):
        if not isinstance(entry, list):
            continue
        log = entry[me] if me < len(entry) else None
        if isinstance(log, dict):
            err = (log.get("stderr") or "").strip()
            if err:
                agent_errors.append(err)

    replay = None
    if want_replay and (agent_errors or statuses[me] != "DONE"):
        replay = env.toJSON()

    return {
        "seed": seed,
        "swap": swap,
        "bank": banks[me],
        "opp_bank": banks[1 - me],
        "won": banks[me] > banks[1 - me],
        "status": statuses[me],
        "errors": agent_errors[:3],
        "elapsed": elapsed,
        "replay": replay,
    }


def profile():
    """Per-turn agent cost against the 1 s actTimeout and 60 s overage bank."""
    make = _quiet_make()
    sys.path.insert(0, ROOT)
    import main

    times = []

    def timed(obs, config=None):
        t = time.perf_counter()
        out = main.agent(obs, config)
        times.append(time.perf_counter() - t)
        return out

    t0 = time.perf_counter()
    env = make("kaggriculture", configuration={"episodeSteps": 720}, debug=True)
    env.run([timed, "starter"])
    total = time.perf_counter() - t0

    times.sort()
    print(f"episode wall time : {total:.2f}s")
    print(f"turns measured    : {len(times)}")
    print(f"mean  per turn    : {statistics.mean(times)*1000:.3f} ms")
    print(f"p50   per turn    : {times[len(times)//2]*1000:.3f} ms")
    print(f"p99   per turn    : {times[int(len(times)*0.99)]*1000:.3f} ms")
    print(f"worst per turn    : {times[-1]*1000:.3f} ms   (actTimeout = 1000 ms)")
    print(f"agent total       : {sum(times):.2f}s   (overage bank = 60 s)")
    budget = 1.0
    over = [t for t in times if t > budget]
    print(f"turns over 1000ms : {len(over)}")
    return 1 if over else 0


def main_cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--opponent", default="starter")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--seeds", choices=["fixed", "random"], default="fixed")
    ap.add_argument("--swap", action="store_true", help="also play as player 1")
    ap.add_argument("--replay", action="store_true", help="dump replay.json on first failure")
    ap.add_argument("--profile", action="store_true")
    args = ap.parse_args()

    if args.profile:
        return profile()

    seeds = [1000 + i for i in range(args.n)] if args.seeds == "fixed" else [None] * args.n
    jobs = [(s, args.opponent, bool(i % 2) and args.swap, args.replay) for i, s in enumerate(seeds)]

    t0 = time.perf_counter()
    with Pool(min(args.workers, args.n)) as pool:
        results = pool.map(play, jobs)
    wall = time.perf_counter() - t0

    broken = [r for r in results if r.get("error") or r.get("errors") or r.get("status") != "DONE"]
    banks = sorted(r["bank"] for r in results)
    wins = sum(1 for r in results if r.get("won"))

    print(f"\n{len(results)} episodes vs {args.opponent!r} in {wall:.1f}s "
          f"({len(results)/wall*60:.0f}/min, {args.workers} workers)")
    print(f"  win rate : {wins}/{len(results)}")
    print(f"  median   : {statistics.median(banks):,.0f}")
    print(f"  p25      : {banks[len(banks)//4]:,.0f}")
    print(f"  min / max: {banks[0]:,.0f} / {banks[-1]:,.0f}")
    print(f"  mean opp : {statistics.mean([r.get('opp_bank', 0.0) for r in results]):,.0f}")

    if broken:
        print(f"\n  FAILURES: {len(broken)}/{len(results)}  <-- gate, not a metric")
        for r in broken[:5]:
            print(f"    seed={r['seed']} status={r.get('status')} {r.get('error') or ''}")
            for e in (r.get("errors") or [])[:1]:
                print(f"      {e.splitlines()[-1][:200]}")
        dump = next((r["replay"] for r in broken if r.get("replay")), None)
        if dump:
            with open(os.path.join(ROOT, "replay.json"), "w") as fh:
                json.dump(dump, fh)
            print("    wrote replay.json")
        return 1

    print("\n  no errors")
    return 0


if __name__ == "__main__":
    sys.exit(main_cli())
