"""Parameter sweep over policy constants via the KAGG_PARAMS env var.

This is the embryo of the M5 tuner. It exists because guessing at parameters was
producing confident regressions: sheep, melon and extra land each looked
obviously good and each made the median worse.
"""

import io
import json
import os
import statistics
import sys
import time
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
AGENT = os.path.join(ROOT, "main.py")


def _one(job):
    params, seed, opponent = job
    os.environ["KAGG_PARAMS"] = json.dumps(params)
    stderr = sys.stderr
    sys.stderr = io.StringIO()
    try:
        from kaggle_environments import make
    finally:
        sys.stderr = stderr
    try:
        env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=True)
        env.run([AGENT, opponent])
        final = env.steps[-1]
        bad = False
        for entry in (env.logs or []):
            if isinstance(entry, list) and entry and isinstance(entry[0], dict):
                if (entry[0].get("stderr") or "").strip():
                    bad = True
                    break
        return float(final[0].observation.farms[0]["money"]), bad
    except Exception:
        return 0.0, True


def evaluate(name, params, seeds, opponent="starter", workers=10):
    jobs = [(params, s, opponent) for s in seeds]
    with Pool(min(workers, len(jobs))) as pool:
        out = pool.map(_one, jobs)
    banks = sorted(b for b, _ in out)
    broken = sum(1 for _, bad in out if bad)
    med = statistics.median(banks)
    p25 = banks[len(banks) // 4]
    flag = f"  ERRORS={broken}" if broken else ""
    print(f"  {name:<34} median {med:>9,.0f}   p25 {p25:>9,.0f}   min {banks[0]:>9,.0f}{flag}")
    return med, p25


if __name__ == "__main__":
    seeds = [2000 + i for i in range(int(os.environ.get("SWEEP_N", 12)))]
    configs = json.load(open(sys.argv[1])) if len(sys.argv) > 1 else None
    if not configs:
        print("usage: python tools/sweep.py configs.json")
        sys.exit(2)
    print(f"\nsweep over {len(seeds)} seeds vs starter\n")
    t0 = time.perf_counter()
    results = {}
    for name, params in configs.items():
        results[name] = evaluate(name, params, seeds)
    best = max(results.items(), key=lambda kv: kv[1][0])
    print(f"\nbest: {best[0]}  median {best[1][0]:,.0f}   ({time.perf_counter()-t0:.0f}s)")
