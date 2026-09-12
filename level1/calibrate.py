#!/usr/bin/env python3
"""
Calibrate fastsim.Rules against the OFFICIAL evaluation logs.

The logs (Downloads/2.log, 3.log, 4.log) turned out to be three runs of the
SAME 1,980-action file - out/solution.json, the Level-1 paint - on Levels 2, 3
and 4.  That is a gift: one fixed input, three very different boards, three
exact outcomes.  Any rule set we optimise against has to reproduce all three.

Per level the log pins down:
    C, entropy, longevity_score, main_score, score, density_factor,
    the full 31-slot species histogram, and every denied placement (plant +
    coordinates), which dates exactly when the board filled up.

    py calibrate.py            # grid search
    py calibrate.py best       # detail for the winning rule set
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from photospheria import fastsim, solution, world as world_mod   # noqa: E402
from photospheria.fastsim import Rules                           # noqa: E402

ROOT = Path(__file__).resolve().parent
SOL = ROOT / "submitted/solution.json"        # the file all four runs used
FP = json.load(open(ROOT / "official/fingerprints.json"))

# Level 1's log is not in hand; these are the numbers reported for it.
FP["1"] = {"C": 1800, "H": 0.4252, "long": 0.0634, "score": 0.2576,
           "counts": {"1": 706, "6": 455, "12": 288, "5": 200, "2": 151},
           "denied": None}

LEVELS = (1, 2, 3, 4)
_W = {}


def world(level):
    if level not in _W:
        _W[level] = world_mod.load(ROOT / ("data/level%d.json" % level))
    return _W[level]


def err_for(level, s, denied):
    f = FP[str(level)]
    exp = {int(k): v for k, v in f["counts"].items()}
    keys = set(s["counts"]) | set(exp)
    hist = sum(abs(s["counts"].get(k, 0) - exp.get(k, 0)) for k in keys) / max(f["C"], 1)
    cov = abs(s["C"] - f["C"]) / max(f["C"], 1)
    ent = abs(s["H"] - f["H"]) / max(f["H"], 0.02)
    lon = abs(s["longevity"] - f["long"]) / max(f["long"], 0.002)
    den = 0.0
    if f["denied"] is not None:
        n = len(f["denied"])
        den = abs(denied - n) / max(n, 20)
    return hist + cov + ent + 0.5 * lon + 0.5 * den


def describe(r):
    return ("rate=%-6s pick=%-6s mat=%-4s disp=%-7s dm=%.1f rg=%.1f reset=%d "
            "xh=%-4s vn=%-4s nut=%d" %
            (r.rate_mode, r.pick, r.mature, r.displace, r.drain_dead, r.regen,
             r.reset_on_plant, r.crosshatch[:4], r.vonneumann[:4], r.nutrients_on))


def _run(rules):
    acts = solution.load(SOL)
    tot, detail = 0.0, {}
    for lv in LEVELS:
        res = fastsim.simulate(world(lv), acts, rules)
        s = fastsim.score(res)
        e = err_for(lv, s, res.denied)
        tot += e
        detail[lv] = (e, s["C"], s["H"], s["longevity"], s["score"],
                      res.denied, s["counts"])
    return tot, rules, detail


def grid():
    """
    `displace` is FIXED to "different" - the logs determine it on their own:

      * Level 2 ends with Rose holding 169 of the 527 cells it successfully
        planted.  Nothing could have starved those 358: Rose was painted at
        ticks 401-479 against T = 500 and a 100-tick nutrient clock, so its
        oldest plant is age 98.  They were taken by spread, and the only
        species that gained enough to have taken them is Grass - whose
        invasiveness_rank is 1 against Rose's 2.  Displacement is therefore NOT
        rank-ordered, which rules out never / rank_gt / rank_ge.
      * "always" (a species overwrites even itself) resets the age of every
        interior cell every few ticks and drives longevity towards 1 tick.  The
        logs report mean ages of 32 (L3) and 44 (L2), so self-overwrite is out.

    What survives: a DIFFERENT species takes the cell, the same species does
    not.  Every other rule is still open and is swept below.
    """
    out = []
    for rate_mode in ("period", "cells"):
        for pick in (("near",) if rate_mode == "period" else ("near", "sorted")):
            for mature in ("gt", "ge", "none"):
                for dm in (0.5, 1.0):
                    for rg in (0.5, 1.0, 2.0):
                        for xh in ("diagonal", "star"):
                            for vn in ("diamond", "axes"):
                                for nut in (True, False):
                                    out.append(Rules(
                                        rate_mode=rate_mode, pick=pick,
                                        mature=mature, displace="different",
                                        drain_dead=dm, regen=rg,
                                        nutrients_on=nut,
                                        crosshatch=xh, vonneumann=vn))
    return out


def report(tot, rules, detail):
    print("TOTAL err=%.3f | %s" % (tot, describe(rules)))
    for lv in LEVELS:
        e, C, H, lo, sc, den, counts = detail[lv]
        f = FP[str(lv)]
        print("  L%d err=%.3f  C=%6d/%-6d H=%.4f/%.4f long=%.4f/%.4f "
              "LB=%6.1fM/%6.1fM den=%s/%s" %
              (lv, e, C, f["C"], H, f["H"], lo, f["long"], sc * 1e3,
               f["score"] * 1e3, den,
               len(f["denied"]) if f["denied"] is not None else "?"))
        print("     got %s" % dict(sorted(counts.items(), key=lambda kv: -kv[1])))
        print("     exp %s" % dict(sorted(((int(k), v) for k, v in f["counts"].items()),
                                          key=lambda kv: -kv[1])))


def main():
    g = grid()
    print("calibrating %d rule sets against 4 official fingerprints\n" % len(g))
    out = []
    with ProcessPoolExecutor() as ex:
        for r in ex.map(_run, g, chunksize=1):
            out.append(r)
    out.sort(key=lambda t: t[0])
    for tot, rules, detail in out[:6]:
        report(tot, rules, detail)
        print()
    json.dump([{"err": t, "rules": describe(r),
                "spec": {k: getattr(r, k) for k in
                         ("rate_mode", "pick", "mature", "displace", "drain_dead",
                          "regen", "crosshatch", "vonneumann", "nutrients_on")},
                "per_level": {str(lv): d[lv][:6] for lv in LEVELS}}
               for t, r, d in out],
              open(ROOT / "out/calibration.json", "w"), indent=1)
    print("wrote out/calibration.json")


if __name__ == "__main__":
    main()
