#!/usr/bin/env python3
"""
Band-ORDER sweep.  The single free lever we have found: with identical species,
identical band sizes and an identical planting budget, re-ordering which species
sits in which band changed the Level-3 simulated score from 217M to 250M.

Neighbour relationships decide how much a high-invasiveness species (Oak, rank
10) can eat from its neighbours, and whether Grass (no_shade_survival) ends up
inside a matured Oak's shade radius.  Nothing here costs a single extra
planting action, so coverage is not traded away - unlike every per-species
stride experiment, which all lost.

Usage:  py sweep_order.py 3 [max_perms]
Writes the best candidate to out/cand_lN_order.json only if it beats the
incumbent recorded in BEST below.
"""
from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from photospheria import scoring, simulator, world as world_mod   # noqa: E402
from photospheria.config import SimConfig                          # noqa: E402
from strategies import territory as TT                             # noqa: E402

ROOT = Path(__file__).resolve().parent
G, R, S, L, O, RZ = 1, 2, 5, 6, 12, 19

#: live official score + the simulated score of the file that produced it
BEST = {
    2: {"live": 294771143, "sim": None, "file": "out/solution_level2.json",
        "species": (G, R, S, L, O), "late": (), "stride": {G: 6, O: 5, S: 2, R: 1, L: 3},
        "seed": 401, "late_tick": 430},
    3: {"live": 241997527, "sim": None, "file": "out/solution_level3.json",
        "species": (G, R, S, L, O, RZ), "late": (RZ,), "stride": 3,
        "seed": 701, "late_tick": 730},
}


def build(world, order, spec):
    """order = tuple of plant indices, one per band, left to right."""
    cells = TT.bands(TT.plantable(world), len(order), "col")
    late = set(spec["late"])
    early = [(pi, cells[i]) for i, pi in enumerate(order) if pi not in late]
    sol = TT.build(world, species=[p for p, _ in early], stride=spec["stride"],
                   seed_start=spec["seed"], band_cells=[c for _, c in early])
    for i, pi in enumerate(order):
        if pi in late:
            sol = TT.build(world, species=[pi], stride=spec["stride"],
                           seed_start=spec["late_tick"], sol=sol,
                           band_cells=[cells[i]])
    return sol


def main():
    lv = int(sys.argv[1])
    cap = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    spec = BEST[lv]
    world = world_mod.load(ROOT / ("data/level%d.json" % lv))
    cfg = SimConfig(plantable_terrains=(0,))

    # incumbent: simulate the file that is actually live
    from photospheria import solution as SO
    inc = simulator.simulate(world, SO.load(ROOT / spec["file"]), cfg)
    inc_s = scoring.score(inc)
    spec["sim"] = inc_s.final * 1e9
    print("L%d incumbent: live=%d  sim C=%d H=%.4f -> %.0f"
          % (lv, spec["live"], inc.occupied, inc_s.entropy, spec["sim"]))
    print("ranking by SCORE (= H x density), not entropy alone")
    print()

    perms = list(itertools.permutations(spec["species"]))
    # deterministic spread through the permutation space rather than the first N
    step = max(1, len(perms) // cap)
    perms = perms[::step][:cap]

    rows, best = [], None
    t0 = time.perf_counter()
    for i, order in enumerate(perms):
        try:
            sol = build(world, order, spec)
        except Exception:                      # noqa: BLE001
            continue
        r = simulator.simulate(world, sol.as_actions(), cfg)
        s = scoring.score(r)
        val = s.final * 1e9
        rows.append((val, order, r.occupied, s.entropy))
        flag = ""
        if best is None or val > best[0]:
            best = (val, order, sol, r, s)
            flag = "  <-- BEST"
        print("  %2d/%d %-22s C=%6d H=%.4f -> %11.0f%s"
              % (i + 1, len(perms), "".join("%d," % p for p in order)[:-1],
                 r.occupied, s.entropy, val, flag), flush=True)

    print()
    print("elapsed %.0fs" % (time.perf_counter() - t0))
    rows.sort(reverse=True)
    print("TOP 5:")
    for v, o, c, h in rows[:5]:
        print("   %-22s C=%6d H=%.4f -> %11.0f"
              % ("".join("%d," % p for p in o)[:-1], c, h, v))

    if best and best[0] > spec["sim"]:
        out = ROOT / ("out/cand_l%d_order.json" % lv)
        best[2].write(out)
        gain = best[0] / spec["sim"]
        print()
        print("IMPROVEMENT x%.3f over incumbent sim -> wrote %s" % (gain, out.name))
        print("  order=%s  C=%d  H=%.4f" % (best[1], best[3].occupied, best[4].entropy))
        json.dump({"order": list(best[1]), "sim": best[0], "C": best[3].occupied,
                   "H": best[4].entropy, "incumbent_sim": spec["sim"],
                   "incumbent_live": spec["live"]},
                  open(ROOT / ("out/l%d_order.json" % lv), "w"), indent=2)
    else:
        print()
        print("no ordering beat the incumbent - keeping the live file")


if __name__ == "__main__":
    raise SystemExit(main())
