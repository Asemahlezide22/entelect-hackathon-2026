#!/usr/bin/env python3
"""Score a solution (or a strategy) on every level, under several rule readings.

The official formula is exact (fastsim.score reproduces six official runs to 9
decimals).  What is NOT exact is our spread model, so every candidate is scored
under a spread of readings and judged on the WORST as well as the best: a
candidate that only wins under one reading is a candidate we do not ship.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from photospheria import fastsim, world as world_mod          # noqa: E402
from photospheria.fastsim import Rules                        # noqa: E402

ROOT = Path(__file__).resolve().parent

# The Level-1 accounting identity forces displace="never"; the remaining axes
# the official logs do not separate are swept here.
READINGS = {
    "A": Rules(rate_mode="period", mature="gt", displace="never", drain_dead=0.5),
    "B": Rules(rate_mode="period", mature="none", displace="never", drain_dead=0.5),
    "C": Rules(rate_mode="cells", mature="none", displace="never", drain_dead=1.0),
    "D": Rules(rate_mode="cells", mature="gt", displace="never", drain_dead=0.5),
}

_W = {}


def world(lv):
    if lv not in _W:
        _W[lv] = world_mod.load(ROOT / ("data/level%d.json" % lv))
    return _W[lv]


def actions_of(sol_or_path):
    if hasattr(sol_or_path, "as_actions"):
        return sol_or_path.as_actions()
    d = json.load(open(sol_or_path))
    out = {}
    for a in d["actions"]:
        out.setdefault(a["tick"], []).extend(
            (x["plant_index"], x["row"], x["col"]) for x in a["plants"])
    return out


def evaluate(lv, sol, readings=READINGS, quiet=False):
    acts = actions_of(sol)
    n = sum(len(v) for v in acts.values())
    got = {}
    for name, r in readings.items():
        res = fastsim.simulate(world(lv), acts, r)
        s = fastsim.score(res)
        s["denied"] = res.denied
        s["rejected"] = res.rejected
        got[name] = s
        if not quiet:
            print("   [%s] C=%6d d=%.3f H=%.4f long=%.4f score=%.4f (%.0fM) "
                  "denied=%d rejected=%d %s"
                  % (name, s["C"], s["density"], s["H"], s["longevity"],
                     s["score"], s["score"] * 1e3, s["denied"], s["rejected"],
                     dict(sorted(s["counts"].items()))))
    scores = [s["score"] for s in got.values()]
    return {"actions": n, "best": max(scores), "worst": min(scores),
            "mean": sum(scores) / len(scores), "detail": got}


def main(argv):
    paths = {1: None, 2: None, 3: None, 4: None}
    if argv:
        for a in argv:
            lv, p = a.split("=", 1)
            paths[int(lv)] = p
    else:
        paths = {1: "out/solution.json", 2: "out/solution_level2.json",
                 3: "out/solution_level3.json", 4: "out/solution_level4.json"}
    tot_b = tot_w = 0.0
    for lv in (1, 2, 3, 4):
        if not paths[lv] or not (ROOT / paths[lv]).exists():
            print("L%d  (missing)" % lv)
            continue
        print("L%d  %s" % (lv, paths[lv]))
        r = evaluate(lv, ROOT / paths[lv])
        print("   actions=%d  best=%.4f worst=%.4f mean=%.4f"
              % (r["actions"], r["best"], r["worst"], r["mean"]))
        tot_b += r["best"]
        tot_w += r["worst"]
    print("\nTOTAL best=%.4f (%.0f)  worst=%.4f (%.0f)"
          % (tot_b, tot_b * 1e9, tot_w, tot_w * 1e9))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
