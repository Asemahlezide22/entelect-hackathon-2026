#!/usr/bin/env python3
"""
Fit the spread rules against the ONE fully-known official run.

2.log is a Level-2 evaluation of out/solution_level2.json - confirmed because
all 425 denied coordinates in the log appear in that file and in no other.  It
gives us, exactly:

    C = 6034, H = 0.351848, longevity = 0.076012, score = 0.257837
    counts  Grass 2993, Lavender 1713, Oak 968, Sunflower 191, Rose 169
    425 denied placements, with coordinates, i.e. 1,299 labelled
    (cell, tick) -> occupied?  observations

The denial set is the sharp part: every legal action is a labelled probe of the
board at a known tick.  A rule set is scored on the species histogram, on C, and
on how many of those 1,299 probes it gets right.
"""
from __future__ import annotations

import itertools
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from photospheria import fastsim, plants, solution, world as world_mod   # noqa: E402
from photospheria.fastsim import Rules                                   # noqa: E402

ROOT = Path(__file__).resolve().parent
EXPECT = {1: 2993, 2: 169, 5: 191, 6: 1713, 12: 968}
C_OFF, H_OFF, LONG_OFF = 6034, 0.351848, 0.076012


def load():
    w = world_mod.load(ROOT / "data/level2.json")
    acts = solution.load(ROOT / "out/solution_level2.json")
    fp = json.load(open(ROOT / "official/fingerprints.json"))["2"]
    return w, acts, set(tuple(x) for x in fp["denied"])


_STATE = {}


def state():
    if not _STATE:
        _STATE["v"] = load()
    return _STATE["v"]


def score_rules(rules):
    w, acts, off = state()
    res = fastsim.simulate(w, acts, rules)
    s = fastsim.score(res)
    got = set((p, r, c) for p, r, c, _ in res.denied_at)
    hist = sum(abs(s["counts"].get(k, 0) - EXPECT.get(k, 0))
               for k in set(s["counts"]) | set(EXPECT)) / C_OFF
    cov = abs(s["C"] - C_OFF) / C_OFF
    ent = abs(s["H"] - H_OFF) / H_OFF
    lon = abs(s["longevity"] - LONG_OFF) / LONG_OFF
    probe = (len(got - off) + len(off - got)) / len(off)
    total = hist + cov + ent + 0.5 * lon + probe
    return total, s, res.denied, len(got & off), len(got - off), len(off - got), \
        (hist, cov, ent, lon, probe)


def describe(r):
    return ("rate=%-6s pick=%-6s mat=%-4s disp=%-9s dm=%.1f xh=%-4s vn=%-4s" %
            (r.rate_mode, r.pick, r.mature, r.displace, r.drain_dead,
             r.crosshatch[:4], r.vonneumann[:4]))


def _run(r):
    res = score_rules(r)
    return (res[0], r) + res[1:]


def grid():
    out = []
    for rate_mode in ("period", "cells"):
        picks = ("near",) if rate_mode == "period" else ("all", "near", "sorted")
        for pick in picks:
            for mature in ("gt", "ge", "none"):
                for disp in ("never", "rank_gt", "rank_ge", "different", "always"):
                    for dm in (0.5, 1.0):
                        for xh in ("diagonal", "star"):
                            for vn in ("diamond", "axes"):
                                out.append(Rules(rate_mode=rate_mode, pick=pick,
                                                 mature=mature, displace=disp,
                                                 drain_dead=dm, crosshatch=xh,
                                                 vonneumann=vn))
    return out


def main():
    g = grid()
    print("fitting %d rule sets against the Level-2 official run" % len(g))
    print("official: C=%d H=%.4f long=%.4f %s  denied=425\n" %
          (C_OFF, H_OFF, LONG_OFF, EXPECT))
    rows = []
    with ProcessPoolExecutor() as ex:
        for r in ex.map(_run, g, chunksize=2):
            rows.append(r)
    rows.sort(key=lambda t: t[0])
    for tot, rules, s, den, tp, extra, miss, parts in rows[:20]:
        print("err=%.3f (hist %.2f cov %.2f ent %.2f lon %.2f probe %.2f) "
              "C=%5d H=%.4f long=%.4f den=%4d(ok%3d x%3d m%3d) | %s" %
              ((tot,) + parts + (s["C"], s["H"], s["longevity"], den, tp, extra,
                                 miss, describe(rules))))
        print("      %s" % dict(sorted(s["counts"].items(), key=lambda kv: -kv[1])))
    json.dump([{"err": t, "rules": describe(r), "C": s["C"], "H": s["H"],
                "long": s["longevity"], "denied": d,
                "counts": {str(k): v for k, v in s["counts"].items()},
                "spec": {k: getattr(r, k) for k in
                         ("rate_mode", "pick", "mature", "displace", "drain_dead",
                          "crosshatch", "vonneumann")}}
               for t, r, s, d, tp, e, m, p in rows],
              open(ROOT / "out/fit_l2.json", "w"), indent=1)
    print("\nwrote out/fit_l2.json")


if __name__ == "__main__":
    main()
