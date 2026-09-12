"""
Strategy v3 - "grass carpet, then repaint", for the big boards (Levels 3 & 4).

WHY THIS EXISTS.  On Level 1 the planting budget (20/tick x 99 safe ticks =
1,980 slots) comfortably exceeds the ~700 plantable cells, so the best play is
to hand-paint the final garden and suppress spreading entirely.  On Level 4
that inverts: there are 5,406 plantable cells and still only 1,980 slots in the
window where a plant survives to the final tick.  Hand-painting can therefore
reach at most ~37% of the board, and coverage (C / C_max) is the term that
dominates the score.

So on the big boards SPREADING IS THE COVERAGE ENGINE, not a liability:

  A. CARPET - the starters, planted at the coverage/count thresholds
     animals.json needs, so the unlock ladder climbs and we have more than five
     species to work with later.

  B. GRASS SEEDS - at `seed_tick`, drop single Grass plants on a lattice (every
     `stride`-th plantable cell).  Grass matures in 1 tick and spreads every 2,
     so a few hundred actions become thousands of occupied cells.
     Grass specifically, because its invasiveness_rank is 1 - the lowest in the
     game - so it can never overwrite anything we plant afterwards.
     Seeding a faster spreader instead is tempting and wrong: Dwarf Sunflower
     (rank 4, 8 cells per action) reaches slightly higher coverage but then
     eats every other species.  Measured: H = 0.10 versus H = 0.40.

  C. REPAINT - the carpet is monoculture Grass, which scores H = 0.  Spend the
     whole remaining budget overwriting it with the other unlocked species.
     Every repainted cell was ALREADY occupied, so this buys entropy at zero
     cost in coverage - the one genuinely free trade on these boards.
     Repainted species are allowed to mature and spread here, unlike Level 1,
     because the only thing they can displace is the surplus Grass, which
     pushes the mix further towards balance rather than away from it.

  D. SELF-HEALING - simulate, see which species actually held ground, shift the
     repaint shares towards them, repeat.

Deterministic: cells are walked in row-major order and species assigned by
position, so identical inputs always produce an identical file.
"""
from __future__ import annotations

from photospheria import plants, scoring, simulator, solution
from .level2_ladder import CARPET_MIX, _carpet, target_cells

PLANTS_PER_TICK = solution.MAX_PLANTS_PER_TICK

#: Oak is never used here: shade radius 4 kills Grass, and at invasiveness 10
#: it overwrites everything it reaches.
EXCLUDE = {plants.OAK_TREE}

#: See the module docstring - rank 1 is the whole point.
SEED_SPECIES = plants.GRASS


def _fill(sol, tick, last_tick, items):
    """Place (plant_index, r, c) items from `tick` onward, 20 per tick."""
    t, placed = tick, 0
    for pi, r, c in items:
        while t <= last_tick and sol.free_slots(t) == 0:
            t += 1
        if t > last_tick:
            break
        sol.plant(t, pi, r, c)
        placed += 1
    return placed


def build(world, cfg, terrains=(0, 1, 2, 3, 4), carpet_mix=None,
          carpet_cycles=4, refresh=95, seed_tick=None, stride=6,
          rounds=3, verbose=True):
    T = world.ticks
    last_tick = T - 1
    cells = target_cells(world, terrains)
    carpet = _carpet(world, cells, carpet_mix or CARPET_MIX)
    seed_tick = seed_tick if seed_tick is not None else T - 110

    # A plant placed at this tick still has nutrients at T, so this is the
    # earliest tick whose plants are guaranteed alive when the garden is scored.
    repaint_start = T - 99

    weights = None
    best = (None, -1.0, None)

    for rnd in range(rounds):
        sol = solution.Solution()

        # ---- A. carpet, replanted so the unlock thresholds stay met --------
        for cycle in range(carpet_cycles):
            t = cycle * refresh
            for pi, (r, c) in carpet:
                while t < seed_tick and sol.free_slots(t) == 0:
                    t += 1
                if t >= seed_tick:
                    break
                sol.plant(t, pi, r, c)

        # ---- B. grass lattice ----------------------------------------------
        seeds = [(SEED_SPECIES, r, c)
                 for i, (r, c) in enumerate(cells)
                 if i % stride == 0
                 and world.soil[r][c] in plants.get(SEED_SPECIES).preferred_soil]
        _fill(sol, seed_tick, repaint_start - 1, seeds)

        # ---- C. repaint ----------------------------------------------------
        probe = simulator.simulate(world, sol.as_actions(), cfg)
        unlocked = {pi for pi, tk in (probe.unlock_log or {}).items()
                    if tk < repaint_start}
        unlocked |= set(plants.LEVEL1_PLANT_INDICES)
        pool = sorted(pi for pi in unlocked
                      if pi not in EXCLUDE and pi != SEED_SPECIES)
        if not pool:
            pool = [plants.ROSE_BUSH, plants.LAVENDER, plants.DWARF_SUNFLOWER]
        if weights is None:
            weights = {pi: 1.0 for pi in pool}
        for pi in pool:
            weights.setdefault(pi, 1.0)

        # Only cells the carpet actually filled are worth repainting.
        targets = [(r, c) for (r, c) in cells
                   if probe.plant_idx[r * world.cols + c] != 0]
        capacity = (last_tick - repaint_start + 1) * PLANTS_PER_TICK
        budget = min(capacity, len(targets))

        total_w = sum(weights[pi] for pi in pool) or 1.0
        # Least invasive first: they go in earliest and get the most ticks to
        # spread into the surplus Grass; the aggressive ones go last and have
        # the least time to eat their neighbours.
        order = sorted(pool, key=lambda pi: plants.get(pi).invasiveness_rank)

        items, cursor = [], 0
        for pi in order:
            want = int(budget * weights[pi] / total_w)
            p = plants.get(pi)
            placed = 0
            while placed < want and cursor < len(targets):
                r, c = targets[cursor]
                cursor += 1
                if world.soil[r][c] in p.preferred_soil:
                    items.append((pi, r, c))
                    placed += 1
        _fill(sol, repaint_start, last_tick, items)

        # ---- D. measure and heal -------------------------------------------
        result = simulator.simulate(world, sol.as_actions(), cfg)
        s = scoring.score(result)
        if verbose:
            print("   round %d: species=%2d C=%5d H=%.4f FINAL=%.5f"
                  % (rnd + 1, result.species_present(), result.occupied,
                     s.entropy, s.final))
        if s.final > best[1]:
            best = (sol, s.final, result)

        # Entropy wants equal counts, so push weight towards whatever came out
        # under-represented and away from whatever over-shot.
        target = result.occupied / max(1, len(pool) + 1)
        for pi in pool:
            got = result.counts.get(pi, 0)
            if got <= 0:
                weights[pi] = max(0.1, weights[pi] * 0.5)
            else:
                weights[pi] = max(0.1, min(4.0, weights[pi] * (target / got) ** 0.5))

    return best[0], best[2]
