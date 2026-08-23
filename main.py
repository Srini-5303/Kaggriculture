"""Kaggriculture agent entry point.

Submission contract, both parts learned the hard way from the harness:

  * `configuration` IS delivered as a second argument -- kaggle_environments
    truncates [obs, config] to the callable arity -- so intervals are read, not
    inferred.
  * This file is loaded with `exec(code_object, env)`, so **`__file__` does not
    exist**. Any path bootstrap has to work without it or the submission dies on
    import with InvalidArgument.
"""

import os
import sys


def _bootstrap():
    """Make the sibling `agent` package importable without relying on __file__."""
    candidates = []
    here = globals().get("__file__")
    if here:
        candidates.append(os.path.dirname(os.path.abspath(here)))
    candidates.append(os.getcwd())
    raw = os.environ.get("KAGGRICULTURE_ROOT")
    if raw:
        candidates.append(raw)
    for path in candidates:
        if path and os.path.isdir(os.path.join(path, "agent")) and path not in sys.path:
            sys.path.insert(0, path)


_bootstrap()

from agent import guard, policy
from agent.world import World

# obs carries no memory of its own, so anything durable lives here.
_STATE = {"errors": 0, "last_step": -1, "reported": False}


def _report(where):
    """Announce the first fallback on stderr and stay quiet after that.

    This exists because a totally broken policy is otherwise indistinguishable
    from a working one: the guard swallows the exception, the agent PASSes for 719
    turns, and the episode completes "cleanly" with the starting bank. The runner
    treats any agent stderr as a hard failure, so one line here turns a silent
    degradation into a visible one.
    """
    _STATE["errors"] += 1
    if not _STATE["reported"]:
        _STATE["reported"] = True
        import traceback
        print(f"kaggriculture agent fell back in {where}:", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)


def agent(obs, config=None):
    """One turn. Any escaping exception forfeits the episode, so none escapes."""
    try:
        world = World(obs, config)
    except Exception:
        _report("World")
        return {"farmer": ["PASS"], "hands": [], "market": []}

    if world.step <= 0 or world.step < _STATE["last_step"]:
        _STATE.update(errors=0, reported=False)
        policy.reset()
    _STATE["last_step"] = world.step

    try:
        proposed = policy.decide(world)
    except Exception:
        _report("policy.decide")
        proposed = guard.safe_turn(len(world.farm["hands"]))

    try:
        return guard.sanitize(world, proposed)
    except Exception:
        _report("guard.sanitize")
        return guard.safe_turn(len(world.farm["hands"]))
