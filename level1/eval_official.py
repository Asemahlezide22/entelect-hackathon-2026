#!/usr/bin/env python3
"""
OFFICIAL-FORMULA evaluator.  Single source of truth for every number we quote.

    density_factor = C / (rows * cols)
    main_score     = entropy * density_factor          (alpha = 1)
    longevity      = sum_ij (age_ij / T)^1 / (rows*cols)
    score          = 0.8 * main_score + 0.2 * longevity
    leaderboard    = score * 1e9
    entropy        = -sum p_i log_31 p_i

Locked mechanics (asserted in assert_mechanics()):
  * planting onto an occupied cell is DENIED (no replacement)
  * cells absent from the level file ARE plantable dirt (terrain 0, soil 0)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from photospheria import plants, scoring, simulator, solution, world as world_mod
from photospheria.config import SimConfig

K = 1e9

#: The one config every number in this project is produced under.
OFFICIAL = SimConfig(
    plantable_terrains=(0,),          # only terrain 0 accepts plants
    unlisted_is_void=False,           # unlisted cells are plain dirt
    planting_replaces_occupant=False,  # DENIED
    spread_displaces_established=True,
    drain_dead_matter=0.5,
    dead_matter_persists=True,
    entropy_base_species=31,
    alpha=1.0,
    k=1.0,
)

LEVELS = {
    1: ("data/level1.json", "submitted/solution.json"),
    2: ("data/level2.json", "submitted/solution_level2.json"),
    3: ("data/level3.json", "submitted/solution_level3.json"),
    4: ("data/level4.json", "submitted/solution_level4.json"),
}


def evaluate(world, actions, cfg=OFFICIAL):
    res = simulator.simulate(world, actions, cfg)
    s = scoring.score(res, alpha=1.0, k=1.0, n_species_in_game=31)
    return res, s


def report(tag, res, s):
    names = ", ".join("%s=%d" % (plants.get(i).name, n)
                      for i, n in sorted(s.counts.items(), key=lambda kv: -kv[1]))
    print("%-22s C=%6d  dens=%.4f  H=%.4f  long=%.5f  main=%.5f  "
          "score=%.5f  LB=%.1fM" %
          (tag, s.occupied, s.coverage, s.entropy, s.longevity, s.main,
           s.final, s.final * K / 1e6))
    print("%-22s %s" % ("", names))
    return s.final * K


# --------------------------------------------------------------- assertions
def assert_mechanics():
    """Guard rails: these are the two corrections that cost us the last run."""
    w = world_mod.load(Path(__file__).parent / "data/level1.json")
    cfg = OFFICIAL

    # 1. unlisted cells are plantable
    assert w.terrain[0][0] is None, "expected (0,0) to be absent from level1.json"
    assert cfg.plantable_terrains == (0,)
    assert w.cell_terrain(0, 0, cfg) == 0, "unlisted cell must read as terrain 0"
    assert len(w.plantable_cells(cfg)) == 1440 + 360 + 360, \
        "unlisted-plantable rule changed"

    # 2. planting on an occupied cell is DENIED, not a replacement
    acts = {0: [(plants.GRASS, 0, 0)], 1: [(plants.OAK_TREE, 0, 0)]}
    r = simulator.simulate(w, acts, cfg)
    assert r.plant_idx[0] in (plants.GRASS, 0), "occupied-cell planting replaced!"
    assert any("DENIED" in m for m in r.rejected), "no denial recorded"

    # 3. scoring formula
    s = scoring.score(r, alpha=1.0, k=1.0, n_species_in_game=31)
    assert abs(s.coverage - s.occupied / (w.rows * w.cols)) < 1e-12
    assert abs(s.main - s.entropy * s.coverage) < 1e-12
    assert abs(s.final - (0.8 * s.main + 0.2 * s.longevity)) < 1e-12

    # 4. entropy base 31
    import math
    h = scoring.entropy({1: 1, 2: 1}, 31)
    assert abs(h - math.log(2) / math.log(31)) < 1e-12
    print("mechanics assertions: OK")


def main():
    assert_mechanics()
    root = Path(__file__).resolve().parent
    which = [int(a) for a in sys.argv[1:]] or [1, 2, 3, 4]
    for lv in which:
        lvl, sol = LEVELS[lv]
        p = root / sol
        if not p.exists():
            print("level %d: %s missing" % (lv, sol))
            continue
        w = world_mod.load(root / lvl)
        acts = solution.load(p)
        res, s = evaluate(w, acts)
        report("L%d %s" % (lv, p.name), res, s)
        denied = sum(1 for m in res.rejected if "DENIED" in m)
        print("%-22s actions=%d denied=%d other-rejected=%d deaths=%s" %
              ("", sum(len(v) for v in acts.values()), denied,
               len(res.rejected) - denied,
               {k: v for k, v in res.deaths.items() if v}))
        print()


if __name__ == "__main__":
    main()
