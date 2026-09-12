"""
Level 2 strategy - "trigger carpet, then deadline-aware paint".

Level 2 turns animals on and fires a Rain event at tick 250, so 26 of the 31
species become reachable instead of Level 1's 5.  Entropy is log_N of the
species mix, so SPECIES COUNT is the dominant lever: log31(5)=0.47 but
log31(12)=0.72.

  A. TRIGGER CARPET (ticks 0+).  Plant the starters in the proportions
     animals.json needs - Grass 0.05 coverage, Dwarf Sunflower 0.03, Rose Bush
     0.02, Lavender 0.02.  Coverage is measured against rows*cols (p.8), so on
     a 70x100 board 0.05 = 350 cells.  Oak is deliberately EXCLUDED: once a
     carpet Oak matures at tick ~305 its shade radius 4 kills every Grass
     nearby and its rank 10 spread eats everything else.
     The carpet is replanted every `refresh` ticks because the nutrient clock
     kills a plant after 100 ticks.

  B. DISCOVERY.  Run our simulator over phase A, read `unlock_log`, and learn
     which species are actually legal to plant by the time the paint starts.
     Nothing here is guessed from the PDF - it is measured.

  C. DEADLINE-AWARE PAINT (ticks 401-499).  This is the Level 1 insight applied
     to an arbitrary species list.  Every species gets a "not before" tick:

         not_before = T - min(time_to_maturity + spread_rate,
                              time_to_maturity if it casts shade)

     A species planted after that tick can never spread and can never shade, so
     it cannot unbalance the counts.  High-invasiveness species are packed
     against the final tick first (they do the most damage if given time); the
     low-rank species take the earlier slots, where they also collect the
     longevity score.

  D. SELF-HEALING.  Some species cannot survive a solid block - Blue Moss has
     die_if_neighbors_greater_than 4, Crimson Vine has die_if_isolated, Stone
     Reed needs rock/path adjacency.  Rather than special-casing each, we
     simulate, drop any species that fails to hold its cells, and redistribute
     them to the survivors.  Repeat a few rounds.

Deterministic throughout: no randomness, identical output for identical input.
"""
from __future__ import annotations

from photospheria import plants, simulator, solution

PLANTS_PER_TICK = solution.MAX_PLANTS_PER_TICK

#: Fractions of rows*cols needed to switch the round-1 animals on, read out of
#: animals.json, with a little headroom so a few deaths do not drop us under.
#: A carpet entry is (plant_index, coverage_fraction, minimum_count).  The cell
#: target is max(minimum_count, fraction * rows * cols).
#:
#: The crucial economics, read straight out of animals.json: FOUR animals are
#: triggered by absolute COUNTS, not coverage, and are therefore almost free -
#: Barkskips (Oak >= 8), Canorals (Trees >= 10), Virexids (Lavender >= 10 AND
#: Grass >= 10) and Rhizorends (Shallow-root >= 25).  Together they cost ~60
#: cells.  Verdelopes by contrast wants Grass at 0.05 COVERAGE, which on the
#: Level 4 board is 3,000 of only 5,406 plantable cells - 55% of the whole
#: garden - and all it unlocks is Razorgrass.  Spending coverage on the
#: count-based animals first is the single biggest lever in Levels 2-4.
CARPET_MIX = [
    (plants.LAVENDER, 0.021, 10),      # Nectaris (cov >= 0.02) + Virexids (>= 10)
    (plants.GRASS, 0.0, 10),           # Virexids need Grass >= 10
    (plants.OAK_TREE, 0.0, 10),        # Barkskips (>= 8) and Canorals (>= 10 trees)
    (plants.ROSE_BUSH, 0.0, 15),       # Loamcrawlers/Grazeleths need Rose >= 10
    (plants.DWARF_SUNFLOWER, 0.0, 15),
]

#: Carpets tried by the search in optimise_levels.py.  Each is a different bet
#: about how much coverage is worth spending on the expensive animals.
CARPET_CANDIDATES = {
    "cheap-counts": CARPET_MIX,
    "counts+loam": [
        (plants.LAVENDER, 0.021, 10),
        (plants.GRASS, 0.041, 10),     # + Loamcrawlers (Grass cov >= 0.04)
        (plants.OAK_TREE, 0.0, 10),
        (plants.ROSE_BUSH, 0.0, 15),
        (plants.DWARF_SUNFLOWER, 0.0, 15),
    ],
    "counts+loam+solwings": [
        (plants.LAVENDER, 0.021, 10),
        (plants.GRASS, 0.041, 10),
        (plants.DWARF_SUNFLOWER, 0.031, 15),   # + Solwings
        (plants.ROSE_BUSH, 0.021, 15),
        (plants.OAK_TREE, 0.0, 10),
    ],
    "full-verdelopes": [
        (plants.GRASS, 0.055, 10),     # + Verdelopes (expensive)
        (plants.DWARF_SUNFLOWER, 0.035, 15),
        (plants.ROSE_BUSH, 0.025, 15),
        (plants.LAVENDER, 0.025, 10),
        (plants.OAK_TREE, 0.0, 10),
    ],
}


def target_cells(world, terrains=(0, 1, 2), soils=(0, 1)):
    return [(r, c)
            for r in range(world.rows)
            for c in range(world.cols)
            if world.terrain[r][c] is not None
            and world.terrain[r][c] in terrains
            and world.soil[r][c] in soils]


def not_before(plant_index, T):
    """Latest tick at which this species can be planted and still never act."""
    p = plants.get(plant_index)
    limit = p.time_to_maturity + p.spread_rate
    if p.shade_radius:
        limit = min(limit, p.time_to_maturity)
    return max(0, T - limit)


def _carpet(world, cells, mix=None):
    total = world.rows * world.cols
    plan, cursor = [], 0
    for entry in (mix or CARPET_MIX):
        pi, frac, floor = entry if len(entry) == 3 else (entry[0], entry[1], 0)
        want = max(floor, int(round(frac * total)))
        want = min(want, len(cells) - cursor)
        plan.extend((p, cell) for p, cell in ((pi, c) for c in cells[cursor:cursor + want]))
        cursor += want
    return plan


def _paint(sol, world, cells, species, weights, paint_start):
    """Deadline-aware paint.  Returns {plant_index: [(tick, r, c), ...]}.

    Species are packed against the final tick in order of DESCENDING
    invasiveness, so the dangerous ones get the latest (safest) slots and the
    harmless ones fall back to the earlier slots where they also age.
    """
    T = world.ticks
    last = T - 1
    free = {t: sol.free_slots(t) for t in range(paint_start, T)}

    total_weight = sum(weights.values()) or 1
    capacity = sum(free.values())
    budget = min(capacity, len(cells))
    want = {pi: max(1, int(budget * weights[pi] / total_weight)) for pi in species}

    # Cells are handed out in contiguous blocks so each species stays compact -
    # a species can only lose cells to spread along its block boundary.
    order = sorted(species, key=lambda pi: -plants.get(pi).invasiveness_rank)
    blocks, cursor = {}, 0
    for pi in order:
        p = plants.get(pi)
        block = []
        while len(block) < want[pi] and cursor < len(cells):
            r, c = cells[cursor]
            cursor += 1
            if world.soil[r][c] in p.preferred_soil:
                block.append((r, c))
        blocks[pi] = block

    assigned = {}
    for pi in order:                       # most invasive first = latest ticks
        floor = max(not_before(pi, T), paint_start)
        picks, t = [], last
        while len(picks) < len(blocks[pi]) and t >= paint_start:
            if t < floor and len(picks) < len(blocks[pi]):
                pass                       # below the safe window: still allowed,
                                           # but only after safer ticks are gone
            take = min(free[t], len(blocks[pi]) - len(picks))
            if take > 0:
                picks.extend([t] * take)
                free[t] -= take
            t -= 1
        picks.sort()
        assigned[pi] = [(tick, r, c) for tick, (r, c) in zip(picks, blocks[pi])]
    return assigned


def build(world, cfg, terrains=(0, 1, 2), paint_start=401, refresh=95,
          carpet_cycles=4, rounds=4, carpet_mix=None,
          grass_fill_tick=None, grass_stride=3, hedge_unlisted=False,
          verbose=True):
    """grass_fill_tick: on the big boards the paint budget (20/tick x 99 safe
    ticks) cannot reach every plantable cell - Level 4 has 5,406 of them and
    only 1,980 slots.  Seeding Grass on a lattice just before the paint lets it
    spread into the cells the paint will never touch, which raises coverage for
    free.  Grass specifically because invasiveness_rank 1 is the lowest in the
    game, so it fills EMPTY cells only and can never overwrite the painted
    garden.  Set to None to disable (correct for Levels 1-2, where the budget
    already covers the board)."""
    cells = target_cells(world, terrains)
    carpet = _carpet(world, cells, carpet_mix)

    species = list(plants.LEVEL1_PLANT_INDICES)
    weights = {pi: 1.0 for pi in species}
    best = (None, -1.0, None)

    for rnd in range(rounds):
        sol = solution.Solution()

        # ---- phase A: carpet, replanted to hold the unlock thresholds -----
        for cycle in range(carpet_cycles):
            t = cycle * refresh
            for pi, (r, c) in carpet:
                while t < paint_start and sol.free_slots(t) == 0:
                    t += 1
                if t >= paint_start:
                    break
                sol.plant(t, pi, r, c)

        # ---- phase B2: grass lattice to fill what the paint cannot reach --
        if grass_fill_tick is not None:
            g = plants.get(plants.GRASS)
            t = grass_fill_tick
            lattice = list(cells)
            if hedge_unlisted:
                # UNKNOWN #2: the level file omits most cells.  Aiming Grass at
                # them is free - an illegal action is silently ignored (p.5) -
                # and if they ARE plantable, coverage (the term the real
                # leaderboard punishes hardest) rises enormously.
                lattice += [(r, c)
                            for r in range(world.rows)
                            for c in range(world.cols)
                            if world.terrain[r][c] is None]
            for i, (r, c) in enumerate(lattice):
                soil = world.soil[r][c]
                if i % grass_stride or (soil is not None
                                        and soil not in g.preferred_soil):
                    continue
                while t < paint_start and sol.free_slots(t) == 0:
                    t += 1
                if t >= paint_start:
                    break
                sol.plant(t, plants.GRASS, r, c)

        # ---- phase C: deadline-aware paint --------------------------------
        assigned = _paint(sol, world, cells, species, weights, paint_start)
        planned = {pi: len(items) for pi, items in assigned.items()}
        for pi, items in assigned.items():
            for tick, r, c in items:
                sol.plant(tick, pi, r, c)

        # ---- measure ------------------------------------------------------
        result = simulator.simulate(world, sol.as_actions(), cfg)
        from photospheria import scoring
        score = scoring.score(result).final
        if score > best[1]:
            best = (sol, score, result)

        if verbose:
            print("  round %d: %2d species alive  C=%4d  FINAL=%.5f"
                  % (rnd + 1, result.species_present(), result.occupied, score))

        # ---- phase D: heal ------------------------------------------------
        # Add anything that unlocked in time; drop anything that could not hold
        # its cells (Blue Moss crowding, Crimson Vine isolation, Stone Reed
        # terrain adjacency), and redistribute its share to the survivors.
        unlocked = {pi for pi, tick in (result.unlock_log or {}).items()
                    if tick < paint_start}
        unlocked |= set(plants.LEVEL1_PLANT_INDICES)

        new_species, new_weights = [], {}
        for pi in sorted(unlocked):
            kept = result.counts.get(pi, 0)
            if pi in planned:
                target = planned[pi]
                ratio = kept / target if target else 0.0
                if ratio < 0.30:
                    continue            # this species cannot survive here at all
                # Reward species that hold their block, shrink the leaky ones.
                new_weights[pi] = max(0.15, weights.get(pi, 1.0) * ratio)
            else:
                new_weights[pi] = 1.0   # newly unlocked: give it a full share
            new_species.append(pi)
        if new_species:
            species, weights = new_species, new_weights

    return best[0], best[2]
