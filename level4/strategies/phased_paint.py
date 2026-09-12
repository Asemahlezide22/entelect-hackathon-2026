"""
Strategy v2 - "phased paint".

Level 1 has no unlock game at all: every one of the 26 locked species needs an
animal or a weather event, and level1.json disables both.  So the whole problem
is WHERE and WHEN to place the five starter species - Grass, Rose Bush,
Lavender, Dwarf Sunflower, Oak Tree.

Four mechanics from the problem statement drive every decision below.

1. THE NUTRIENT CLOCK (p.6).  A cell holds 100 nutrient points and loses 1 per
   tick while occupied; at 0 the plant dies.  So NOTHING planted before tick
   401 is still alive when the garden is scored at tick 500.  The scored garden
   must be built in the last 99 ticks, and tick 401 is the earliest tick that
   is safe under every reading of the rules.

2. THE 20-PER-TICK BUDGET (p.5).  99 safe ticks x 20 = 1,980 planting slots.
   That is far more than the ~700 cells the level file actually contains, so we
   never need natural spreading to get coverage - we can paint the final garden
   by hand.  Spreading is therefore a liability, not a tool.

3. INVASIVENESS (p.6).  A higher invasiveness_rank overwrites a lower-ranked
   neighbour when it spreads.  Ranks: Grass 1, Lavender 2, Rose Bush 2,
   Dwarf Sunflower 4, Oak Tree 10.  Oak also casts shade radius 4 once mature,
   and shade KILLS Grass outright (no_shade_survival).
   => EARLY phase - Grass, Rose Bush, Lavender.  Grass is rank 1 so nothing it
      does can unbalance the counts; Rose and Lavender are both rank 2 so they
      cannot overwrite each other.  Planted from tick 401, so these carry the
      longevity score (age 79-99 at scoring).
   => LATE phase - Oak Tree and Dwarf Sunflower.  Packed against the final tick
      so they never reach the age at which they would spread
      (time_to_maturity + spread_rate), and Oak never reaches the age at which
      it would start shading.  They stay young, but they keep the species count
      at five and the entropy at its ceiling.

4. ENTROPY (p.9).  H is maximised when the five species have EQUAL counts, so
   the listed cells are split into five equal contiguous blocks.  Contiguous
   matters: a species can only lose cells to spread along the boundary of its
   block.

Two free bets are layered on top.  An illegal planting action is silently
IGNORED by the solver (p.5), never rejected, and we have spare planting slots -
so aiming at cells that MIGHT be plantable costs nothing if we are wrong:
  * terrain 1 and 2 cells (the PDF never defines the terrain enum);
  * the 1,440 cells level1.json does not mention at all.
Real, definitely-plantable cells are always scheduled first so they keep the
best ticks; the speculative ones only ever use slots that would go unused.

Everything here is deterministic - no randomness anywhere, byte-identical
output for identical parameters.
"""
from __future__ import annotations

from photospheria import plants, solution

PLANTS_PER_TICK = solution.MAX_PLANTS_PER_TICK

#: Which species are planted in the EARLY phase (they carry the longevity
#: score).  Chosen by the sweep in optimise.py.  Oak and Sunflower must not be
#: here: given ~99 ticks they would overwrite everything else.
DEFAULT_EARLY = (plants.GRASS, plants.ROSE_BUSH, plants.LAVENDER)

#: Grass (rank 1) is the only species anything can overwrite, so keep it away
#: from Rose Bush and Lavender by putting Sunflower between them.
DEFAULT_BLOCK_ORDER = [plants.LAVENDER, plants.ROSE_BUSH, plants.DWARF_SUNFLOWER,
                       plants.GRASS, plants.OAK_TREE]

ALL_SPECIES = (plants.LAVENDER, plants.ROSE_BUSH, plants.GRASS,
               plants.OAK_TREE, plants.DWARF_SUNFLOWER)


def first_spread_age(plant_index):
    """Age at which a species first performs a spread action."""
    p = plants.get(plant_index)
    return p.time_to_maturity + p.spread_rate


def first_shade_age(plant_index):
    """Age at which a shade caster starts shading (0 = never shades)."""
    p = plants.get(plant_index)
    return p.time_to_maturity if p.shade_radius else 0


class Phase:
    """One species' planting instruction."""

    def __init__(self, plant_index, mode, not_before=0):
        self.plant_index = plant_index
        self.mode = mode          # "early" = pack forwards, "late" = pack backwards
        self.not_before = not_before


def deadline(plant_index, T, slack=0):
    """Latest-safe "not before" tick for a late-phase species.

    A plant that never reaches first_spread_age can never unbalance the species
    counts, and an Oak that never reaches first_shade_age can never shade Grass
    to death.  `slack` relaxes the deadline, trading a few spread actions for
    extra age.
    """
    limit = first_spread_age(plant_index)
    shade = first_shade_age(plant_index)
    if shade:
        limit = min(limit, shade)
    return max(0, T - limit - slack)


def default_plan(world, early=DEFAULT_EARLY, slack=0):
    """The plan, with every tick derived from the plant data, not guessed."""
    T = world.ticks
    phases = []
    for pi in ALL_SPECIES:
        if pi in early:
            phases.append(Phase(pi, "early"))
        elif pi == plants.GRASS:
            # Grass is rank 1: it can never overwrite anything, so it needs a
            # slot but no deadline.
            phases.append(Phase(pi, "late", 0))
        else:
            phases.append(Phase(pi, "late", deadline(pi, T, slack)))
    return phases


# --------------------------------------------------------------------------
# Cell selection
# --------------------------------------------------------------------------
def target_cells(world, terrains, soils=(0, 1)):
    """Listed cells we aim at, row-major.  Clay (soil 2) is skipped: no Level-1
    species has 2 in preferred_soil, so planting there is always wasted."""
    return [(r, c)
            for r in range(world.rows)
            for c in range(world.cols)
            if world.terrain[r][c] is not None
            and world.terrain[r][c] in terrains
            and world.soil[r][c] in soils]


def unlisted_cells(world):
    """The 1,440 cells level1.json does not mention (UNKNOWN #2)."""
    return [(r, c)
            for r in range(world.rows)
            for c in range(world.cols)
            if world.terrain[r][c] is None]


def split_blocks(cells, order):
    """Equal contiguous row-major blocks, one per species."""
    base, extra = divmod(len(cells), len(order))
    blocks, cursor = {}, 0
    for i, pi in enumerate(order):
        size = base + (1 if i < extra else 0)
        blocks[pi] = cells[cursor:cursor + size]
        cursor += size
    return blocks


# --------------------------------------------------------------------------
# Scheduling
# --------------------------------------------------------------------------
def _late_windows(plan, early_tick, last_tick):
    """Ticks reserved for each late species, packed against `last_tick`,
    tightest deadline first.  Returns (ticks_by_species, lowest_tick_used)."""
    free = {t: PLANTS_PER_TICK for t in range(early_tick, last_tick + 1)}
    windows, lowest = {}, last_tick + 1
    for ph in sorted([p for p in plan if p.mode == "late"],
                     key=lambda p: p.not_before, reverse=True):
        ticks, t = [], last_tick
        floor = max(ph.not_before, early_tick)
        while t >= floor:
            ticks.extend([t] * free[t])
            if free[t]:
                lowest = min(lowest, t)
            free[t] = 0
            t -= 1
        windows[ph.plant_index] = sorted(ticks)      # earliest first = oldest
    return windows, lowest


def _interleave(order, blocks):
    """Round-robin across species so every species' Nth cell is scheduled
    before anyone's (N+1)th.  This is what keeps the definitely-real cells of
    ALL species in the earliest (oldest) ticks."""
    out, i = [], 0
    while True:
        added = False
        for pi in order:
            if i < len(blocks.get(pi, ())):
                out.append((pi, blocks[pi][i]))
                added = True
        if not added:
            return out
        i += 1


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------
def build(world, terrains=(0, 1, 2), early_tick=401, burn=False,
          block_order=None, last_tick=None, early=DEFAULT_EARLY, slack=0,
          hedge_unlisted=True, exclude=(), verbose=True):
    """
    early_tick : first tick of the early phase.  401 is the earliest tick whose
                 plants are still alive at tick 500 under EVERY reading of the
                 nutrient rules.  301 would nearly double their age, but only
                 if the dead-matter 0.5/tick bonus is real - the sweep shows
                 that bet gains ~4% when right and loses ~60% when wrong.
    burn       : plant a throwaway generation-1 grass carpet at tick 0 to create
                 dead matter.  Pointless at early_tick=401; kept for experiments.
    """
    T = world.ticks
    last_tick = T - 1 if last_tick is None else last_tick
    block_order = [pi for pi in (block_order or DEFAULT_BLOCK_ORDER)
                   if pi not in exclude]
    early = tuple(pi for pi in early if pi not in exclude)
    plan = [ph for ph in default_plan(world, early=early, slack=slack)
            if ph.plant_index not in exclude]
    by_index = {p.plant_index: p for p in plan}

    real = target_cells(world, terrains)
    real_blocks = split_blocks(real, block_order)
    extra_blocks = {pi: [] for pi in block_order}

    sol = solution.Solution()

    # -- optional generation-1 burn -----------------------------------------
    if burn:
        t = 0
        for (r, c) in real:
            while sol.free_slots(t) == 0:
                t += 1
            sol.plant(t, plants.GRASS, r, c)

    # -- reserve the late-phase ticks ---------------------------------------
    late_ticks, lowest_late = _late_windows(plan, early_tick, last_tick)
    early_order = [pi for pi in block_order if by_index[pi].mode == "early"]
    early_capacity = (lowest_late - early_tick) * PLANTS_PER_TICK

    # -- speculative extra cells, split by leftover capacity ----------------
    if hedge_unlisted:
        spare = {pi: len(late_ticks[pi]) - len(real_blocks[pi])
                 for pi in late_ticks}
        spare_early = early_capacity - sum(len(real_blocks[pi]) for pi in early_order)
        for i, pi in enumerate(early_order):
            spare[pi] = (spare_early // len(early_order)
                         + (1 if i < spare_early % len(early_order) else 0))
        pool, cursor = unlisted_cells(world), 0
        for pi in block_order:                 # deterministic order
            take = max(0, min(spare.get(pi, 0), len(pool) - cursor))
            extra_blocks[pi] = pool[cursor:cursor + take]
            cursor += take

    # -- assign ticks: real cells first, then speculative -------------------
    assigned = {pi: [] for pi in block_order}   # plant_index -> [(tick,r,c)]

    # LATE species: earliest tick in their window is the oldest, so real cells
    # take those first.
    for pi, ticks in late_ticks.items():
        cells = list(real_blocks[pi]) + list(extra_blocks[pi])
        for tick, (r, c) in zip(ticks, cells):
            assigned[pi].append((tick, r, c))

    # EARLY species: interleave so every species' real cells are placed before
    # anybody's speculative cells.
    queue = _interleave(early_order, {pi: real_blocks[pi] for pi in early_order})
    queue += _interleave(early_order, {pi: extra_blocks[pi] for pi in early_order})
    t = early_tick
    used = 0
    for pi, (r, c) in queue:
        if t >= lowest_late:
            break                              # out of safe ticks; stop
        assigned[pi].append((t, r, c))
        used += 1
        if used % PLANTS_PER_TICK == 0:
            t += 1

    # -- emit, sorted by (tick, species, row, col) => deterministic ----------
    emit = sorted((tick, pi, r, c)
                  for pi, items in assigned.items() for (tick, r, c) in items)
    for tick, pi, r, c in emit:
        sol.plant(tick, pi, r, c)

    if verbose:
        print("listed cells targeted : %d   speculative extra : %d"
              % (len(real), sum(len(v) for v in extra_blocks.values())))
        for pi in block_order:
            p = plants.get(pi)
            ticks = sorted(t for t, _, _ in assigned[pi])
            if not ticks:
                continue
            real_n = len(real_blocks[pi])
            real_ticks = sorted(t for t, _, _ in assigned[pi][:real_n]) or ticks
            print("  %-16s listed=%4d (+%4d spec)  ticks %3d..%3d  "
                  "listed age at T = %3d..%3d   [%s]"
                  % (p.name, real_n, len(ticks) - real_n, ticks[0], ticks[-1],
                     T - real_ticks[-1], T - real_ticks[0],
                     by_index[pi].mode))
        print("total actions         : %d" % sol.total_actions())
    return sol
