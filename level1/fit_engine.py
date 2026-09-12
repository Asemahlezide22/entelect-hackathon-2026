#!/usr/bin/env python3
"""
Fit engine2.Rules to the OFFICIAL evaluation results.

We have three official fingerprints (final species counts + C + H).  Every rule
the PDF leaves open is an axis in engine2.Rules; this script runs the submitted
solution under each combination and ranks them by distance to the official
outcome.  A rule set that cannot reproduce the official numbers is not a rule
set we are allowed to optimise against.

    py fit_engine.py l1            # fit on Level 1 (fast, most constrained)
    py fit_engine.py verify        # re-run the top rule sets on L2 and L3
"""
from __future__ import annotations

import itertools
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from photospheria import engine2, solution, world as world_mod  # noqa: E402
from photospheria.engine2 import Rules                          # noqa: E402

ROOT = Path(__file__).resolve().parent

# --------------------------------------------------------------- ground truth
# Species name -> plant index
GRASS, ROSE, SUN, LAV, OAK = 1, 2, 5, 6, 12

OFFICIAL = {
    1: {"level": "data/level1.json", "sol": "submitted/solution.json",
        "C": 1800, "H": 0.4252, "score": 0.2576,
        "counts": {GRASS: 706, LAV: 455, OAK: 288, SUN: 200, ROSE: 151}},
    2: {"level": "data/level2.json", "sol": "submitted/solution_level2.json",
        "C": 2714, "H": 0.2159, "score": 0.0729,
        "counts": {SUN: 1602, LAV: 1071, OAK: 41}},
    3: {"level": "data/level3.json", "sol": "submitted/solution_level3.json",
        "C": 14955, "H": 0.0171, "score": 0.0100,
        "counts": {OAK: 14797, SUN: 158}},
}


def load(level):
    spec = OFFICIAL[level]
    w = world_mod.load(ROOT / spec["level"])
    acts = solution.load(ROOT / spec["sol"])
    return w, acts, spec


def distance(res, spec):
    """L1 distance on the species histogram, normalised by the official C."""
    got = dict(res.counts)
    keys = set(got) | set(spec["counts"])
    err = sum(abs(got.get(k, 0) - spec["counts"].get(k, 0)) for k in keys)
    return err / spec["C"]


def describe(rules):
    return ("rate=%-6s pick=%-6s mat=%-2s disp=%-7s reset=%-5s xh=%-8s vn=%-7s "
            "dm=%.1f" % (rules.rate_mode, rules.pick, rules.mature,
                         rules.displace, rules.reset_on_plant, rules.crosshatch,
                         rules.vonneumann, rules.drain_dead))


def _run(args):
    level, rules = args
    w, acts, spec = load(level)
    res = engine2.simulate(w, acts, rules)
    s = engine2.score(res)
    return (distance(res, spec), rules, s, dict(res.counts), res.denied)


def axes_grid():
    grid = []
    for rate_mode in ("period", "cells"):
        picks = ("near",) if rate_mode == "period" else ("near", "sorted", "rotate")
        for pick in picks:
            for mature in ("gt", "ge", "none"):
                for disp in ("never", "rank_gt", "rank_ge", "always"):
                    for reset in (False, True):
                        for xh in ("diagonal", "star"):
                            grid.append(Rules(rate_mode=rate_mode, pick=pick,
                                              mature=mature, displace=disp,
                                              reset_on_plant=reset,
                                              crosshatch=xh))
    return grid


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "l1"
    level = int(mode[1]) if mode.startswith("l") and mode[1:].isdigit() else 1
    spec = OFFICIAL[level]
    grid = axes_grid()
    print("fitting level %d over %d rule sets" % (level, len(grid)))
    print("official: C=%d H=%.4f %s" % (spec["C"], spec["H"], spec["counts"]))
    print()

    out = []
    with ProcessPoolExecutor() as ex:
        for r in ex.map(_run, [(level, g) for g in grid], chunksize=4):
            out.append(r)
    out.sort(key=lambda t: t[0])

    import json
    json.dump([{"err": d, "rules": describe(r), "C": sc["C"], "H": sc["H"],
                "long": sc["longevity"], "LB": sc["leaderboard"],
                "counts": {str(k): v for k, v in c.items()}, "denied": dn}
               for d, r, sc, c, dn in out],
              open("out/fit_level%d.json" % level, "w"), indent=1)

    for dist, rules, s, counts, denied in out[:18]:
        print("err=%.3f  C=%5d H=%.4f LB=%7.1fM denied=%5d | %s" %
              (dist, s["C"], s["H"], s["leaderboard"] / 1e6, denied, describe(rules)))
        print("            %s" % dict(sorted(counts.items(), key=lambda kv: -kv[1])))
    return out


if __name__ == "__main__":
    main()
