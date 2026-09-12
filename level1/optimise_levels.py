#!/usr/bin/env python3
"""
Search the carpet strategy x paint timing space for Levels 2-4 and write the
best solution found for each.

The search axis that matters is WHICH ANIMALS TO PAY FOR.  animals.json prices
four animals in absolute counts (Barkskips 8 Oak, Canorals 10 Trees, Virexids
10 Lavender + 10 Grass, Rhizorends 25 shallow-root) and the rest in coverage
measured against the whole grid.  On the big boards a coverage threshold is
brutally expensive - Verdelopes wants Grass at 0.05, which is 3,000 of Level
4's 5,406 plantable cells - so the question is how much of the garden to spend
on unlocks versus how much to keep for the scored paint.

Every candidate is scored under BOTH readings of the dead-matter nutrient rule
and ranked on the WORST of the two, so we never pick a configuration that only
looks good if an unresolved assumption happens to break our way.

Runtime: several minutes (Level 4 is a 60,000-cell board).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from photospheria import plants, scoring, simulator, world as world_mod   # noqa: E402
from photospheria.config import SimConfig                                  # noqa: E402
from strategies import level2_ladder as L2                                 # noqa: E402

ROOT = Path(__file__).resolve().parent
TERRAINS = (0, 1, 2, 3, 4)

LEVELS = {
    2: {"file": "data/level2.json", "out": "out/solution_level2.json",
        "paint_starts": (401, 371)},
    3: {"file": "data/level3.json", "out": "out/solution_level3.json",
        "paint_starts": (701, 651)},
    4: {"file": "data/level4.json", "out": "out/solution_level4.json",
        "paint_starts": (701, 651)},
}


def evaluate(world, sol):
    """Score under both nutrient readings; rank on the worst."""
    out = {}
    for label, dm in (("bonus", 0.5), ("nobonus", 1.0)):
        cfg = SimConfig(plantable_terrains=TERRAINS, drain_dead_matter=dm)
        res = simulator.simulate(world, sol.as_actions(), cfg)
        out[label] = (scoring.score(res), res)
    worst = min(v[0].final for v in out.values())
    return worst, out


def run(level):
    spec = LEVELS[level]
    world = world_mod.load(ROOT / spec["file"])
    cfg = SimConfig(plantable_terrains=TERRAINS)
    rows, best = [], None

    for carpet_name, mix in L2.CARPET_CANDIDATES.items():
        for ps in spec["paint_starts"]:
            t0 = time.perf_counter()
            try:
                sol, _ = L2.build(world, cfg, terrains=TERRAINS, paint_start=ps,
                                  carpet_cycles=5, rounds=3, carpet_mix=mix,
                                  verbose=False)
            except Exception as exc:                      # noqa: BLE001
                print("   %-22s paint=%d  FAILED: %s" % (carpet_name, ps, exc))
                continue
            worst, detail = evaluate(world, sol)
            s = detail["bonus"][0]
            res = detail["bonus"][1]
            rows.append({"carpet": carpet_name, "paint": ps, "worst": worst,
                         "best": max(v[0].final for v in detail.values()),
                         "species": res.species_present(), "C": res.occupied,
                         "H": s.entropy})
            print("   %-22s paint=%3d  species=%2d C=%5d H=%.4f  "
                  "worst=%.5f best=%.5f  (%.0fs)"
                  % (carpet_name, ps, res.species_present(), res.occupied,
                     s.entropy, worst, rows[-1]["best"], time.perf_counter() - t0))
            if best is None or worst > best[0]:
                best = (worst, sol, carpet_name, ps, res)

    if best:
        path = best[1].write(ROOT / spec["out"])
        print("   -> BEST: carpet=%s paint=%d  worst-case %.5f  wrote %s"
              % (best[2], best[3], best[0], path.name))
    return rows, best


def main():
    wanted = [int(a) for a in sys.argv[1:]] or sorted(LEVELS)
    summary = {}
    for lv in wanted:
        print("=== LEVEL %d ===" % lv)
        rows, best = run(lv)
        summary[lv] = {
            "rows": rows,
            "best": None if not best else
            {"worst": best[0], "carpet": best[2], "paint": best[3],
             "species": best[4].species_present(), "C": best[4].occupied},
        }
        print()
    (ROOT / "out" / "optimise_report.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print("report -> out/optimise_report.json")


if __name__ == "__main__":
    raise SystemExit(main())
