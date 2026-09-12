#!/usr/bin/env python3
"""
Fit fastsim.Rules to the official evaluation results.

Stage 1 fits on Level 1 - the most constrained fingerprint we have (the paint
covers every plantable cell, so C, the species histogram AND the longevity all
have to come out right at once).  Stage 2 re-runs the survivors on Levels 2 and
3, where the spread engine, not the paint, decides the outcome.

    py fit_fast.py stage1
    py fit_fast.py stage2
"""
from __future__ import annotations

import itertools
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from photospheria import fastsim, solution, world as world_mod   # noqa: E402
from photospheria.fastsim import Rules                           # noqa: E402

ROOT = Path(__file__).resolve().parent
GRASS, ROSE, SUN, LAV, OAK = 1, 2, 5, 6, 12

OFFICIAL = {
    1: {"level": "data/level1.json", "sol": "submitted/solution.json",
        "C": 1800, "H": 0.4252, "score": 0.2576, "long": 0.0634,
        "counts": {GRASS: 706, LAV: 455, OAK: 288, SUN: 200, ROSE: 151}},
    2: {"level": "data/level2.json", "sol": "submitted/solution_level2.json",
        "C": 2714, "H": 0.2159, "score": 0.0729, "long": 0.0135,
        "counts": {SUN: 1602, LAV: 1071, OAK: 41}},
    3: {"level": "data/level3.json", "sol": "submitted/solution_level3.json",
        "C": 14955, "H": 0.0171, "score": 0.0100, "long": 0.0045,
        "counts": {OAK: 14797, SUN: 158}},
}

_CACHE = {}


def load(level):
    if level not in _CACHE:
        spec = OFFICIAL[level]
        _CACHE[level] = (world_mod.load(ROOT / spec["level"]),
                         solution.load(ROOT / spec["sol"]), spec)
    return _CACHE[level]


def err_of(s, spec):
    """Histogram error + coverage error + entropy error, all normalised."""
    got = s["counts"]
    keys = set(got) | set(spec["counts"])
    hist = sum(abs(got.get(k, 0) - spec["counts"].get(k, 0)) for k in keys) / spec["C"]
    cov = abs(s["C"] - spec["C"]) / spec["C"]
    ent = abs(s["H"] - spec["H"]) / max(spec["H"], 0.02)
    lon = abs(s["longevity"] - spec["long"]) / max(spec["long"], 0.005)
    return hist + cov + ent + 0.5 * lon, hist, cov, ent, lon


def describe(r):
    return ("rate=%-6s pick=%-6s mat=%-4s disp=%-7s dm=%.1f rg=%.1f reset=%d xh=%s"
            % (r.rate_mode, r.pick, r.mature, r.displace, r.drain_dead,
               r.regen, r.reset_on_plant, r.crosshatch[:4]))


def grid():
    out = []
    for rate_mode in ("period", "cells"):
        for pick in (("near",) if rate_mode == "period" else ("near", "sorted")):
            for mature in ("gt", "ge", "none"):
                for disp in ("never", "rank_gt", "rank_ge", "always"):
                    for dm in (0.5, 1.0):
                        for rg in (1.0, 2.0):
                            for reset in (False, True):
                                for xh in ("diagonal", "star"):
                                    out.append(Rules(
                                        rate_mode=rate_mode, pick=pick,
                                        mature=mature, displace=disp,
                                        drain_dead=dm, regen=rg,
                                        reset_on_plant=reset, crosshatch=xh))
    return out


def _run(args):
    level, rules = args
    w, acts, spec = load(level)
    s = fastsim.score(fastsim.simulate(w, acts, rules))
    e = err_of(s, spec)
    return e[0], rules, s, e


def run_level(level, rules_list, workers=None):
    out = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(_run, [(level, g) for g in rules_list], chunksize=2):
            out.append(r)
    out.sort(key=lambda t: t[0])
    return out


def show(out, spec, n=15):
    print("official: C=%d H=%.4f long=%.4f %s" %
          (spec["C"], spec["H"], spec["long"], spec["counts"]))
    for tot, rules, s, e in out[:n]:
        print("err=%.3f (hist %.2f cov %.2f ent %.2f lon %.2f)  C=%6d H=%.4f "
              "long=%.4f LB=%6.1fM | %s" %
              (tot, e[1], e[2], e[3], e[4], s["C"], s["H"], s["longevity"],
               s["leaderboard"] / 1e6, describe(rules)))
        print("     %s" % dict(sorted(s["counts"].items(), key=lambda kv: -kv[1])))


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "stage1"
    if stage == "stage1":
        g = grid()
        print("stage 1: %d rule sets on Level 1" % len(g))
        out = run_level(1, g)
        show(out, OFFICIAL[1])
        json.dump([{"err": t, "rules": describe(r), "C": s["C"], "H": s["H"],
                    "long": s["longevity"],
                    "counts": {str(k): v for k, v in s["counts"].items()},
                    "spec": {k: getattr(r, k) for k in
                             ("rate_mode", "pick", "mature", "displace",
                              "drain_dead", "regen", "reset_on_plant",
                              "crosshatch")}}
                   for t, r, s, e in out],
                  open("out/fit_fast_l1.json", "w"), indent=1)
    else:
        data = json.load(open("out/fit_fast_l1.json"))
        top = [Rules(**d["spec"]) for d in data[:24]]
        for level in (2, 3):
            print("\n===== LEVEL %d =====" % level)
            show(run_level(level, top), OFFICIAL[level], n=24)


if __name__ == "__main__":
    main()
