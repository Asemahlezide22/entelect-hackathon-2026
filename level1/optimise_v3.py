#!/usr/bin/env python3
"""
Refinement pass: per-species seeding density + an end-game rebalance paint.

The coarse sweep got Level 3 to a worst case of 88M (official today: 30.9M) but
its entropy stalls at H = 0.32 against the 0.4687 ceiling, because two species
always die out: Rose Bush spreads Row-only from maturity 10 and Lavender only
reaches 4 diagonal neighbours, so both lose their band to Sunflower (rank 4) and
Oak (rank 10).

Two fixes, both of which the official logs support:

  * PER-SPECIES SEED DENSITY - seed the slow species densely and the fast ones
    sparsely, so the bands start closer to equal instead of equal-by-area.

  * END-GAME REBALANCE - spend the final ticks planting whichever species is
    under-represented into cells that are still empty.  This is the one move
    that cannot be undone by the spread engine: there is no time left for
    anything to displace it, and a denied action costs nothing but the slot.
    Entropy is worth ~10x coverage on L3, and this buys entropy directly.

Ranked on the WORST score across all six rule readings.  See photospheria.rules.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np                                               # noqa: E402

from photospheria import fastsim, plants, solution, world as world_mod  # noqa: E402
from photospheria.rules import BEST, ROBUST                      # noqa: E402
from strategies import territory as terr                         # noqa: E402
from optimise_v2 import world, band_cells, evaluate, describe    # noqa: E402

ROOT = Path(__file__).resolve().parent
GRASS, ROSE, SUN, LAV, OAK = 1, 2, 5, 6, 12
PER_TICK = 20


def build(level, p):
    w = world(level)
    species = list(p["species"])
    sol = terr.build(w, species=species, stride=p["stride"],
                     seed_start=p["seed_start"], waves=p["waves"],
                     wave_gap=p["wave_gap"], axis=p["axis"],
                     topup_start=p["topup_start"],
                     topup_stride=p.get("topup_stride", 1),
                     band_cells=band_cells(level, len(species), p["axis"],
                                           p.get("weights")),
                     reserve_last=p.get("rebalance", 0))
    if p.get("rebalance"):
        sol = rebalance(level, sol, p["species"], p["rebalance"])
    return sol


def rebalance(level, sol, species, n_ticks, rule=None):
    """Fill the last `n_ticks` with whichever species are behind.

    Targets are the cells the simulator says are still empty at the end.  The
    simulator is not exact, so this is deliberately fail-soft: a target that
    turns out to be occupied is simply denied and costs one of 20 slots in a
    tick we had no better use for.
    """
    w = world(level)
    T = w.ticks
    start = T - n_ticks
    rule = rule or BEST
    # Two snapshots: the FINAL board tells us who is under-represented, the
    # board at `start` tells us which cells are actually free to paint at the
    # moment we paint them.  Using the final board for both was wrong - a cell
    # empty at T may well be occupied at T-40.
    final = fastsim.simulate(w, sol.as_actions(), rule)
    res = fastsim.simulate(w, sol.as_actions(), rule, stop_at=start)

    counts = {s: final.counts.get(s, 0) for s in species}
    empty = (res.pidx == 0)
    free = []
    for s in species:
        ok = plants.get(s).preferred_soil
        mask = empty & np.isin(
            np.array([[(w.soil[r][c] if w.soil[r][c] is not None else 0)
                       for c in range(w.cols)] for r in range(w.rows)]),
            np.array(sorted(ok)))
        free.append((s, mask))

    terrain_ok = np.array([[(w.terrain[r][c] if w.terrain[r][c] is not None else 0) == 0
                            for c in range(w.cols)] for r in range(w.rows)])

    slots = sum(sol.free_slots(t) for t in range(start, T))
    # Hand every free slot to the species that is furthest behind, recomputing
    # the deficit as we go so the paint lands where entropy gains most.
    want = {}
    for _ in range(slots):
        s = min(species, key=lambda x: counts[x] + want.get(x, 0))
        want[s] = want.get(s, 0) + 1
        counts[s] += 0
    cursor = {}
    tick = start
    for s in sorted(want, key=lambda x: counts[x]):
        mask = None
        for sp, m in free:
            if sp == s:
                mask = m & terrain_ok
        cells = list(zip(*np.nonzero(mask)))
        # spread the paint over the whole board so it never piles into one
        # corner that the engine might sweep
        step = max(1, len(cells) // max(1, want[s]))
        picked = cells[::step][:want[s]]
        for (r, c) in picked:
            while tick < T and sol.free_slots(tick) == 0:
                tick += 1
            if tick >= T:
                break
            sol.plant(tick, s, int(r), int(c))
        if tick >= T:
            break
    return sol


def _run(args):
    level, p = args
    try:
        sol = build(level, p)
    except ValueError:
        return None, p
    ev = evaluate(level, sol)
    ev["actions"] = sol.total_actions()
    return ev, p


def sweep(level, grid, top=14, label=""):
    print("\n=== level %d : %s : %d candidates ===" % (level, label, len(grid)))
    rows = []
    with ProcessPoolExecutor() as ex:
        for ev, p in ex.map(_run, [(level, p) for p in grid], chunksize=1):
            if ev:
                rows.append((ev["worst"], ev, p))
    rows.sort(key=lambda t: -t[0])
    for sc, ev, p in rows[:top]:
        pr = ev["primary"]
        print("worst=%7.1fM mean=%7.1fM best=%7.1fM | %s reb=%s" %
              (ev["worst"] * 1e3, ev["mean"] * 1e3, ev["best"] * 1e3,
               describe(p), p.get("rebalance")))
        print("      per-rule " + "  ".join("%s=%.0fM" % (n[:8], v * 1e3)
                                            for n, v in ev["by_rule"].items()))
        print("      primary C=%6d dens=%.3f H=%.4f long=%.4f %s" %
              (pr["C"], pr["density"], pr["H"], pr["longevity"],
               dict(sorted(pr["counts"].items(), key=lambda kv: -kv[1]))))
    return rows


def refine_grid(level):
    T = world(level).ticks
    grid = []
    # Order the bands by invasiveness_rank so each species only ever borders a
    # neighbour of adjacent rank: Grass 1, Rose 2, Lavender 2, Sunflower 4,
    # Oak 10.  Oak then touches only Sunflower instead of eating into three
    # bands at once, which is what wiped Rose and Lavender in the coarse sweep.
    orders = [(GRASS, ROSE, LAV, SUN, OAK), (OAK, SUN, LAV, ROSE, GRASS),
              (GRASS, LAV, ROSE, SUN, OAK), (GRASS, ROSE, SUN, LAV, OAK),
              (SUN, OAK, GRASS, ROSE, LAV), (OAK, GRASS, ROSE, LAV, SUN)]
    # slow species dense, fast species sparse
    strides = [4, 3,
               {GRASS: 8, LAV: 4, ROSE: 2, SUN: 6, OAK: 4},
               {GRASS: 10, LAV: 3, ROSE: 2, SUN: 8, OAK: 5},
               {GRASS: 6, LAV: 3, ROSE: 2, SUN: 5, OAK: 3}]
    for species in orders:
        for stride in strides:
            for seed in (T - 160, T - 120, T - 90):
                for topup in (None, seed + 40, seed + 65):
                    for reb in (0, 30, 60):
                        grid.append(dict(species=species, stride=stride,
                                         seed_start=seed, waves=1, wave_gap=150,
                                         axis="col", topup_start=topup,
                                         topup_stride=1, rebalance=reb))
    return grid


def main():
    level = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    rows = sweep(level, refine_grid(level), label="refine")
    json.dump([{"worst": s, "mean": ev["mean"], "best": ev["best"],
                "C": ev["primary"]["C"], "H": ev["primary"]["H"],
                "params": {k: (list(v) if isinstance(v, tuple) else v)
                           for k, v in p.items()}}
               for s, ev, p in rows[:60]],
              open(ROOT / ("out/v3_refine_l%d.json" % level), "w"), indent=1)
    print("\nwrote out/v3_refine_l%d.json" % level)


if __name__ == "__main__":
    main()
