#!/usr/bin/env python3
"""
The hybrid strategy: a SPREAD ENGINE for coverage plus a LATE DIVERSITY PAINT
for entropy, swept against several readings of the spread rules at once.

Why this shape.  The official Level-3 run reports C = 14,955 (density 0.665)
with H = 0.0171 - Oak alone owns 14,797 cells and 2,631 Lavender plantings left
no trace.  Coverage is not the problem; a monoculture is.  Two facts decide the
design:

  * score = 0.8 * H * (C / rows*cols) + 0.2 * longevity, so on L3 the entropy
    term is worth ~10x what another few points of coverage are worth;
  * a planting action on an OCCUPIED cell is DENIED, so diversity can only be
    added to cells that are EMPTY at the moment we plant.

Over 800 ticks the highest invasiveness rank present wins every contested cell,
which is exactly what happened to that Lavender.  The only diversity that
survives is diversity injected so late that the dominant species has no time to
displace it.  Hence: let an engine species build coverage in one part of the
board, keep a RESERVE region unseeded, and spend the last ticks painting the
reserve with a balanced species mix.

Because our simulator does not reproduce the official numbers exactly (see
fit_engine.py), every candidate is scored under SEVERAL rule sets and ranked by
its WORST case, not its best.  A candidate that only wins under one reading of
the PDF is not a candidate.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from photospheria import engine2, plants, solution, world as world_mod
from photospheria.engine2 import Rules

GRASS, ROSE, SUN, LAV, OAK = 1, 2, 5, 6, 12
STARTERS = (GRASS, ROSE, SUN, LAV, OAK)
PER_TICK = 20

# --------------------------------------------------------------- rule sets --
# The readings of the spread rules that fit_engine.py could not rule out.
# Every candidate is scored under all of them.
RULESETS = {
    "period-gt-rankgt": Rules(rate_mode="period", mature="gt", displace="rank_gt"),
    "period-gt-never":  Rules(rate_mode="period", mature="gt", displace="never"),
    "cells-none-never": Rules(rate_mode="cells", pick="near", mature="none",
                              displace="never"),
    "cells-gt-rankge":  Rules(rate_mode="cells", pick="sorted", mature="gt",
                              displace="rank_ge"),
    "cells-none-rankgt": Rules(rate_mode="cells", pick="near", mature="none",
                               displace="rank_gt"),
}


# ---------------------------------------------------------------- geometry --
def plantable(world, pi=None):
    """Cells a starter species may legally occupy: terrain 0, soil 0 or 1."""
    soils = plants.get(pi).preferred_soil if pi else {0, 1}
    out = []
    for r in range(world.rows):
        for c in range(world.cols):
            t, s = world.terrain[r][c], world.soil[r][c]
            if t is None:
                t, s = 0, 0
            if t == 0 and s in soils:
                out.append((r, c))
    return out


def split_columns(cells, frac, cols):
    """Engine zone = the left `frac` of the columns, reserve = the rest."""
    cut = int(cols * frac)
    engine = [(r, c) for (r, c) in cells if c < cut]
    reserve = [(r, c) for (r, c) in cells if c >= cut]
    return engine, reserve, cut


# ------------------------------------------------------------------ build ---
@dataclass(frozen=True)
class Params:
    engine_species: int = OAK
    engine_frac: float = 0.6      # share of the board handed to the engine
    engine_stride: int = 7        # lattice spacing of the engine seeds
    engine_tick: int = 0          # first seeding tick
    engine_waves: int = 1         # re-seeding waves
    engine_wave_gap: int = 120
    paint_species: tuple = (GRASS, ROSE, SUN, LAV)
    paint_start: int = 700        # first tick of the diversity paint
    paint_order: str = "contested"  # contested | far | rows
    paint_engine_zone: bool = False  # also aim paint at the engine zone
    seed_budget: int = 400        # max engine seed actions per wave


def build(world, p: Params) -> solution.Solution:
    T = world.ticks
    cols = world.cols
    cells = plantable(world)
    engine_cells, reserve_cells, cut = split_columns(cells, p.engine_frac, cols)
    sol = solution.Solution()

    # ---- A. engine seeds -------------------------------------------------
    if p.engine_species:
        soils = plants.get(p.engine_species).preferred_soil
        lattice = [(r, c) for (r, c) in engine_cells
                   if r % p.engine_stride == 0 and c % p.engine_stride == 0
                   and (world.soil[r][c] if world.soil[r][c] is not None else 0) in soils]
        for wave in range(p.engine_waves):
            t = p.engine_tick + wave * p.engine_wave_gap
            placed = 0
            for (r, c) in lattice:
                if placed >= p.seed_budget:
                    break
                while sol.free_slots(t) == 0:
                    t += 1
                if t >= p.paint_start:
                    break
                sol.plant(t, p.engine_species, r, c)
                placed += 1

    # ---- B. late diversity paint ------------------------------------------
    targets = list(reserve_cells)
    if p.paint_engine_zone:
        targets = list(cells)
    if p.paint_order == "contested":
        # Cells closest to the engine zone fill up first, so aim at them while
        # they are still empty; the far edge stays empty either way.
        targets.sort(key=lambda rc: (rc[1], rc[0]))
    elif p.paint_order == "far":
        targets.sort(key=lambda rc: (-rc[1], rc[0]))
    else:
        targets.sort()

    species = list(p.paint_species)
    if species:
        tick = p.paint_start
        i = 0
        for (r, c) in targets:
            if tick > T - 1:
                break
            # round-robin so the painted histogram is balanced by construction
            for _ in range(len(species)):
                pi = species[i % len(species)]
                i += 1
                soil = world.soil[r][c]
                if soil is None:
                    soil = 0
                if soil in plants.get(pi).preferred_soil:
                    break
            else:
                continue
            while tick <= T - 1 and sol.free_slots(tick) == 0:
                tick += 1
            if tick > T - 1:
                break
            sol.plant(tick, pi, r, c)
    return sol


# --------------------------------------------------------------- evaluate ---
def evaluate(world, sol, rulesets=None):
    rulesets = rulesets or RULESETS
    acts = sol.as_actions()
    out = {}
    for name, rules in rulesets.items():
        res = engine2.simulate(world, acts, rules)
        s = engine2.score(res)
        s["counts"] = dict(res.counts)
        out[name] = s
    lbs = [v["score"] for v in out.values()]
    out["_min"] = min(lbs)
    out["_mean"] = sum(lbs) / len(lbs)
    return out


def summarise(tag, ev):
    parts = []
    for name in RULESETS:
        if name in ev:
            s = ev[name]
            parts.append("%s:%.1fM(C=%d,H=%.3f)" %
                         (name.split("-")[0][:4], s["score"] * 1e3, s["C"], s["H"]))
    return "%-30s min=%6.1fM mean=%6.1fM | %s" % (
        tag, ev["_min"] * 1e9 / 1e6, ev["_mean"] * 1e9 / 1e6, "  ".join(parts))
