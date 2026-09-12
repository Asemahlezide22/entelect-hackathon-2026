"""
Simulation configuration.

Everything in this file that is marked UNKNOWN is a rule that the official
problem statement does NOT pin down.  Rather than betting on one reading, each
one is a switch.  `run_experiments.py` sweeps strategies across every
combination of these switches, so we can pick a strategy that scores well no
matter which reading the official solver uses.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import product
from typing import Iterator


@dataclass(frozen=True)
class SimConfig:
    # ---------------------------------------------------------------- MAP ---
    # UNKNOWN #1: the level file gives every cell a `terrain` (0/1/2) but the
    # PDF never defines the terrain enum.  Terrain 0 is certainly plantable
    # soil.  Terrain 1 (the 180 "D" cells) and terrain 2 (the 160 wall cells)
    # are unknown.  Walls look like Stone/Path => uninhabitable.
    plantable_terrains: tuple[int, ...] = (0,)

    # RESOLVED by the official evaluation logs: Level 1 finished with
    # C = 1800 occupied cells while the level file lists only ~700 plantable
    # ones, so the cells the level file omits ARE plantable (plain dirt).
    unlisted_is_void: bool = False

    # ------------------------------------------------------------ NUTRIENTS ---
    nutrient_start: float = 100.0
    nutrient_max: float = 100.0
    drain_normal: float = 1.0           # CONFIRMED p.6: 1 point / tick
    # UNKNOWN #3: p.8 says a plant moving into a dead-matter cell drains at
    # 0.5/tick.  Set == drain_normal to test the pessimistic reading where the
    # bonus does not apply to *planted* (as opposed to spread) plants.
    drain_dead_matter: float = 0.5
    regen_dead_matter: float = 1.0      # CONFIRMED p.8: +1 / tick while empty

    # UNKNOWN #3b: does the dead-matter flag survive being re-occupied?
    # If False, a cell's 0.5/tick bonus is consumed by the first re-plant.
    dead_matter_persists: bool = True

    # ------------------------------------------------------------- SPREAD ---
    # UNKNOWN #4: p.6 says higher invasiveness_rank displaces the current
    # occupant; p.13 says whoever spreads in last wins because neither is
    # mature.  These contradict.  If False, spread can only fill EMPTY cells.
    spread_displaces_established: bool = True

    # RESOLVED by the logs: the official solver logs
    #   "Placement denied for plant N at (r, c): plant already occupies cell"
    # 2,907 times across our submissions.  A PLAYER planting action on an
    # occupied cell is REFUSED - it does NOT replace the occupant, contrary to
    # problem-statement.pdf p.5.  This invalidated our entire "paint over the
    # garden" strategy: most of those actions silently did nothing.
    planting_replaces_occupant: bool = False

    # UNKNOWN #5: "CrossHatch" is described only as "structured multi-axis
    # expansion".  'diagonal' = X shape; 'star' = X plus the N/S/E/W axes.
    crosshatch_shape: str = "diagonal"

    # VonNeumann at range r: 'diamond' = Manhattan distance <= r;
    # 'axes' = only the 4 axis directions out to r.
    vonneumann_shape: str = "diamond"

    # ------------------------------------------------------------ SCORING ---
    # UNKNOWN #7: "N = total number of species types in the game".  31 is the
    # size of the full catalogue; 5 would be the Level-1 subset.  Affects the
    # printed number only, never the ranking of two strategies.
    entropy_base_species: int = 31   # CONFIRMED by the logs
    alpha: float = 1.0   # CONFIRMED = 1 exactly (density_factor = C/Cmax)
    k: float = 1.0       # CONFIRMED = 1 by fitting longevity_score

    # UNKNOWN #6: p.3 contradicts itself about the final tick.  We simulate
    # `ticks` steps (0..ticks-1) and score the state afterwards.  Strategies
    # keep a safety margin so an off-by-one cannot kill the garden.
    score_after_tick: int | None = None  # None => after the last simulated tick


DEFAULT = SimConfig()

#: The pessimistic corner: smallest map, no dead-matter bonus, spread eats you.
PESSIMISTIC = SimConfig(
    plantable_terrains=(0,),
    unlisted_is_void=True,
    drain_dead_matter=1.0,
    dead_matter_persists=False,
    spread_displaces_established=True,
)

#: The optimistic corner: every listed cell plantable, dead-matter bonus works.
OPTIMISTIC = SimConfig(
    plantable_terrains=(0, 1, 2),
    unlisted_is_void=True,
    drain_dead_matter=0.5,
    dead_matter_persists=True,
    spread_displaces_established=False,
)


def sweep() -> Iterator[tuple[str, SimConfig]]:
    """Every combination of the switches we genuinely cannot resolve locally."""
    axes = {
        "terrain": [(0,), (0, 1), (0, 1, 2)],
        "deadmatter": [0.5, 1.0],
        "displace": [True, False],
        "crosshatch": ["diagonal", "star"],
    }
    keys = list(axes)
    for combo in product(*(axes[k] for k in keys)):
        opts = dict(zip(keys, combo))
        cfg = replace(
            DEFAULT,
            plantable_terrains=opts["terrain"],
            drain_dead_matter=opts["deadmatter"],
            spread_displaces_established=opts["displace"],
            crosshatch_shape=opts["crosshatch"],
        )
        name = (
            f"terrain={'/'.join(map(str, opts['terrain']))} "
            f"dm={opts['deadmatter']} "
            f"displace={int(opts['displace'])} "
            f"xh={opts['crosshatch'][:4]}"
        )
        yield name, cfg
