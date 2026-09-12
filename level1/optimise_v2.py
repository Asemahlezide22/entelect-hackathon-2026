#!/usr/bin/env python3
"""
Parameter search for the territory strategy, scored with the OFFICIAL formula.

    score = 0.8 * H * C/(rows*cols) + 0.2 * longevity      leaderboard = score * 1e9

Two numbers are reported for every candidate:

    PRIMARY  - the score under the calibrated rule set (photospheria.rules.BEST)
    WORST    - the lowest score across the whole robustness set

Candidates are ranked on PRIMARY but WORST is what stops us shipping something
that only works under one reading of the rules.  Nothing is ever written over a
known-good solution: winners go to out/*.candidate.

    py optimise_v2.py 3 coarse
    py optimise_v2.py 3 refine
"""
from __future__ import annotations

import itertools
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from photospheria import fastsim, solution, world as world_mod   # noqa: E402
from photospheria.rules import BEST, ROBUST                      # noqa: E402
from strategies import territory as terr                         # noqa: E402

ROOT = Path(__file__).resolve().parent
GRASS, ROSE, SUN, LAV, OAK = 1, 2, 5, 6, 12

_W = {}
_BANDS = {}


def world(level):
    if level not in _W:
        _W[level] = world_mod.load(ROOT / ("data/level%d.json" % level))
    return _W[level]


def band_cells(level, k, axis, weights=None):
    key = (level, k, axis, tuple(weights) if weights else None)
    if key not in _BANDS:
        _BANDS[key] = terr.bands(terr.plantable(world(level)), k, axis,
                                 list(weights) if weights else None)
    return _BANDS[key]


def make(level, p):
    w = world(level)
    species = list(p["species"])
    return terr.build(w, species=species, stride=p["stride"],
                      seed_start=p["seed_start"], waves=p["waves"],
                      wave_gap=p["wave_gap"], axis=p["axis"],
                      topup_start=p["topup_start"],
                      topup_stride=p.get("topup_stride", 1),
                      band_cells=band_cells(level, len(species), p["axis"]))


def evaluate(level, sol, robust=True):
    """Score under every reading; the WORST one is what we rank on."""
    w = world(level)
    acts = sol.as_actions()
    out = {"by_rule": {}, "detail": {}}
    scores = []
    for name, r in ROBUST.items():
        s = fastsim.score(fastsim.simulate(w, acts, r))
        out["by_rule"][name] = s["score"]
        out["detail"][name] = s
        scores.append(s["score"])
    out["worst"] = min(scores)
    out["mean"] = sum(scores) / len(scores)
    out["best"] = max(scores)
    # the headline single-model number, for continuity with earlier reports
    out["primary"] = out["detail"].get("period-none-diff") or out["detail"][
        next(iter(out["detail"]))]
    return out


def _run(args):
    level, p, robust = args
    try:
        sol = make(level, p)
    except ValueError as exc:                     # >20 actions in a tick
        return None, p, str(exc)
    ev = evaluate(level, sol, robust)
    return ev, p, None


def describe(p):
    return ("sp=%s stride=%d seed=%d waves=%dx%d axis=%s topup=%s/%s" %
            ("".join(str(s) for s in p["species"]), p["stride"], p["seed_start"],
             p["waves"], p["wave_gap"], p["axis"], p["topup_start"],
             p.get("topup_stride", 1)))


def sweep(level, grid, robust=True, top=12, label=""):
    print("\n=== level %d : %s : %d candidates ===" % (level, label, len(grid)))
    rows = []
    with ProcessPoolExecutor() as ex:
        for ev, p, err in ex.map(_run, [(level, p, robust) for p in grid],
                                 chunksize=1):
            if ev:
                rows.append((ev["worst"], ev, p))
    rows.sort(key=lambda t: -t[0])
    for sc, ev, p in rows[:top]:
        pr = ev["primary"]
        print("worst=%7.1fM mean=%7.1fM best=%7.1fM | %s" %
              (ev["worst"] * 1e9 / 1e6, ev["mean"] * 1e9 / 1e6,
               ev["best"] * 1e9 / 1e6, describe(p)))
        print("      per-rule " + "  ".join(
            "%s=%.0fM" % (n.split("-")[0][:4] + n.split("-")[-1][:3],
                          v * 1e9 / 1e6) for n, v in ev["by_rule"].items()))
        print("      primary C=%6d dens=%.3f H=%.4f long=%.4f  %s" %
              (pr["C"], pr["density"], pr["H"], pr["longevity"],
               dict(sorted(pr["counts"].items(), key=lambda kv: -kv[1]))))
    return rows


def coarse_grid(level):
    T = world(level).ticks
    grid = []
    orders = [
        (GRASS, ROSE, SUN, LAV, OAK),
        (OAK, SUN, ROSE, LAV, GRASS),
        (GRASS, LAV, ROSE, SUN, OAK),
        (OAK, LAV, ROSE, SUN, GRASS),
        (GRASS, SUN, OAK, LAV, ROSE),
    ]
    for species in orders:
        for stride in (4, 6, 9):
            for seed_start in (0, T // 2, T - 300, T - 180, T - 120):
                for waves, gap in ((1, 150), (3, 120)):
                    for topup in (None, T - 100, T - 55):
                        if seed_start < 0:
                            continue
                        grid.append(dict(species=species, stride=stride,
                                         seed_start=max(0, seed_start),
                                         waves=waves, wave_gap=gap, axis="col",
                                         topup_start=topup, topup_stride=1))
    return grid


def main():
    level = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    stage = sys.argv[2] if len(sys.argv) > 2 else "coarse"
    if stage == "coarse":
        rows = sweep(level, coarse_grid(level), robust=True, label="coarse")
        json.dump([{"score": s, "params": {k: (list(v) if isinstance(v, tuple) else v)
                                           for k, v in p.items()},
                    "worst": ev["worst"], "C": ev["primary"]["C"],
                    "H": ev["primary"]["H"]}
                   for s, ev, p in rows[:80]],
                  open(ROOT / ("out/v2_coarse_l%d.json" % level), "w"), indent=1)


if __name__ == "__main__":
    main()
