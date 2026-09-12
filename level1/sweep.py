#!/usr/bin/env python3
"""Parameter sweep for strategies.balanced, ranked on the WORST rule reading.

Our spread model is the one thing the official logs do not pin down exactly, so
a candidate is judged on its worst case across the readings in bench.READINGS,
not its best.  Ties are broken on the mean.

    py sweep.py 2                # sweep level 2
    py sweep.py 3 --readings A,C # cheaper sweep on the big boards
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bench                                                  # noqa: E402
from photospheria import world as world_mod                   # noqa: E402
from strategies import balanced                               # noqa: E402

ROOT = Path(__file__).resolve().parent
_W = {}


def world(lv):
    if lv not in _W:
        _W[lv] = world_mod.load(ROOT / ("data/level%d.json" % lv))
    return _W[lv]


def job(args):
    lv, params, rkeys = args
    r = {k: bench.READINGS[k] for k in rkeys}
    sol = balanced.build(world(lv), **params)
    out = bench.evaluate(lv, sol, readings=r, quiet=True)
    return params, out["worst"], out["mean"], out["best"], out["actions"], {
        k: (v["C"], round(v["H"], 4), round(v["longevity"], 4),
            dict(sorted(v["counts"].items())))
        for k, v in out["detail"].items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("level", type=int)
    ap.add_argument("--readings", default="A,C")
    ap.add_argument("--seed-ticks", default="")
    ap.add_argument("--caps", default="4,6,8,12,16,24,32")
    ap.add_argument("--finish", default="99")
    ap.add_argument("--paint", default="rr,rose")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    w = world(a.level)
    if a.seed_ticks:
        seeds = [int(x) for x in a.seed_ticks.split(",")]
    else:
        T = w.ticks
        seeds = sorted({0, T // 8, T // 4, T * 3 // 8, T // 2, T * 5 // 8, T * 3 // 4})
    caps = [int(x) for x in a.caps.split(",")]
    fin = [int(x) for x in a.finish.split(",")]
    paints = a.paint.split(",")
    rkeys = a.readings.split(",")

    combos = [{"seed_tick": s, "cap": c, "finish_ticks": f, "paint": p}
              for s, c, f, p in itertools.product(seeds, caps, fin, paints)]
    print("level %d: %d combos x %d readings" % (a.level, len(combos), len(rkeys)))
    with ProcessPoolExecutor() as ex:
        res = list(ex.map(job, [(a.level, c, rkeys) for c in combos], chunksize=1))
    res.sort(key=lambda x: (-x[1], -x[2]))
    for params, worst, mean, best, n, det in res[:a.top]:
        print("worst=%.4f mean=%.4f best=%.4f acts=%5d %s"
              % (worst, mean, best, n, params))
        for k, (C, H, lg, cnt) in det.items():
            print("      [%s] C=%6d H=%.4f long=%.4f %s" % (k, C, H, lg, cnt))
    if a.out:
        json.dump([{"params": p, "worst": w_, "mean": m, "best": b, "actions": n}
                   for p, w_, m, b, n, _ in res],
                  open(ROOT / a.out, "w"), indent=1)
        print("wrote", a.out)


if __name__ == "__main__":
    main()
