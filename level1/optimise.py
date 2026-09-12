#!/usr/bin/env python3
"""
Checkpoint 4 - parameter sweep.

Tries every sensible combination of (which species go early, how much spread
slack the late species get, which species neighbours which) and scores each one
in the local simulator.

Crucially, each variant is scored under BOTH readings of the unresolved
nutrient rule (UNKNOWN #3, the dead-matter 0.5/tick bonus) and we rank by the
WORST of the two.  A variant that wins only if a coin-flip assumption happens
to be right is not actually a good submission.

Runtime: a few seconds - each simulation is ~0.3 s.
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from photospheria import plants, scoring, simulator, world as world_mod   # noqa: E402
from photospheria.config import SimConfig                                  # noqa: E402
from strategies import phased_paint                                        # noqa: E402

NAME = {plants.GRASS: "Grass", plants.ROSE_BUSH: "Rose", plants.LAVENDER: "Lav",
        plants.DWARF_SUNFLOWER: "Sun", plants.OAK_TREE: "Oak"}

# Candidate early-phase sets.  Anything containing Oak is excluded: a mature
# Oak shades radius 4 and kills every Grass near it.
EARLY_SETS = [
    (plants.LAVENDER, plants.ROSE_BUSH),
    (plants.GRASS, plants.ROSE_BUSH),
    (plants.GRASS, plants.LAVENDER),
    (plants.GRASS, plants.ROSE_BUSH, plants.LAVENDER),
    (plants.ROSE_BUSH,),
    (plants.LAVENDER, plants.ROSE_BUSH, plants.DWARF_SUNFLOWER),
]

# Block orders control adjacency.  Grass (rank 1) is the only species anything
# can overwrite, so the useful orders keep it away from Rose/Lavender.
BLOCK_ORDERS = [
    [plants.LAVENDER, plants.ROSE_BUSH, plants.DWARF_SUNFLOWER, plants.GRASS, plants.OAK_TREE],
    [plants.GRASS, plants.OAK_TREE, plants.DWARF_SUNFLOWER, plants.ROSE_BUSH, plants.LAVENDER],
    [plants.OAK_TREE, plants.GRASS, plants.DWARF_SUNFLOWER, plants.LAVENDER, plants.ROSE_BUSH],
    [plants.ROSE_BUSH, plants.LAVENDER, plants.GRASS, plants.OAK_TREE, plants.DWARF_SUNFLOWER],
]

READINGS = {
    "dead-matter bonus real": SimConfig(plantable_terrains=(0, 1, 2), drain_dead_matter=0.5),
    "bonus not real":         SimConfig(plantable_terrains=(0, 1, 2), drain_dead_matter=1.0),
    "pessimistic map":        SimConfig(plantable_terrains=(0,),      drain_dead_matter=1.0),
}


def evaluate(world, sol):
    """Score one solution under every reading; return (worst, best, detail)."""
    out = {}
    for label, cfg in READINGS.items():
        result = simulator.simulate(world, sol.as_actions(), cfg)
        out[label] = (scoring.score(result), result)
    optimistic = [v[0].final for k, v in out.items() if k != "pessimistic map"]
    return min(optimistic), max(optimistic), out


def main():
    root = Path(__file__).resolve().parent
    world = world_mod.load(root / "data/level1.json")

    rows = []
    for early, slack, order in itertools.product(EARLY_SETS, (0, 4, 8), BLOCK_ORDERS):
        try:
            sol = phased_paint.build(world, early_tick=401, burn=False,
                                     early=early, slack=slack, block_order=order,
                                     verbose=False)
        except ValueError:
            continue                    # schedule does not fit; skip
        worst, best, detail = evaluate(world, sol)
        s = detail["dead-matter bonus real"][0]
        rows.append({
            "early": "+".join(NAME[p] for p in early),
            "slack": slack,
            "order": "".join(NAME[p][0] for p in order),
            "worst": worst, "best": best,
            "H": s.entropy, "C": s.occupied, "age": s.mean_age,
            "counts": s.counts,
        })

    rows.sort(key=lambda r: -r["worst"])
    print("%-22s %5s %6s | %8s %8s | %6s %4s %6s" %
          ("early phase", "slack", "order", "WORST", "best", "H", "C", "age"))
    print("-" * 78)
    for r in rows[:18]:
        print("%-22s %5d %6s | %8.5f %8.5f | %6.4f %4d %6.1f" %
              (r["early"], r["slack"], r["order"], r["worst"], r["best"],
               r["H"], r["C"], r["age"]))

    print("\nBEST (ranked by worst case):")
    b = rows[0]
    print("  early=%s slack=%d order=%s" % (b["early"], b["slack"], b["order"]))
    print("  counts: %s" % {plants.get(i).name: n for i, n in sorted(b["counts"].items())})
    print("  worst-case final score %.5f, best-case %.5f" % (b["worst"], b["best"]))
    print("\n  %d variants evaluated" % len(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
