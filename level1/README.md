# Photospheria — Level 1 (Greenhouse Study)

Python 3.13, standard library only. No dependencies, no network, no randomness.

```bash
py generate_solution.py     # writes out/solution.json
py validate_solution.py     # schema + constraint check
py simulate_solution.py     # local score estimate
py optimise.py              # parameter sweep (a few seconds)
```

## The finding that defines Level 1

`level1.json` sets `animals_enabled: false` and contains **no event commands** —
only four `season` commands. Evaluating every unlock tree in
`plant_unlock_conditions.json` under those conditions gives a fixed point of:

```
REACHABLE:   Grass, Rose Bush, Lavender, Dwarf Sunflower, Oak Tree   (5)
UNREACHABLE: the other 26 species
```

Every locked species' unlock chain bottoms out in a `species_present` (animal)
or `event` leaf. **There is no unlock game in Level 1.** The whole problem is
where and when to place the five starter species.

## The map

1,060 of 2,500 cells are listed. Six planting beds inside vertical walls:

| terrain | soil | count | notes |
|---|---|---|---|
| 0 | 1 Mud | 360 | certainly plantable |
| 0 | 2 Clay | 360 | **unusable** — no Level-1 species has soil 2 in `preferred_soil` |
| 1 | 0 Dirt | 180 | terrain enum undefined in the PDF |
| 2 | 0 Dirt | 160 | vertical walls at cols 10/20/30/40 |
| — | — | 1,440 | absent from the level file entirely |

## Strategy

1. **The nutrient clock (p.6).** A cell holds 100 points and loses 1/tick while
   occupied. Nothing planted before tick 401 is alive at tick 500, so the scored
   garden must be painted in the last 99 ticks.
2. **Budget (p.5).** 99 ticks × 20 = 1,980 slots for ~700 cells. We never need
   natural spreading for coverage, so spreading is a liability, not a tool.
3. **Two phases, split by invasiveness (p.6).**
   - **Early (tick 401+)** — Grass (rank 1, can overwrite nothing), Rose Bush and
     Lavender (both rank 2, cannot overwrite each other). These reach age 79–99
     and carry the longevity score.
   - **Late (ticks 480–499)** — Oak Tree and Dwarf Sunflower. Packed against the
     final tick so they never reach `time_to_maturity + spread_rate`, and Oak
     never reaches the age where its shade radius 4 would kill Grass.
4. **Equal counts (p.9).** Entropy peaks at uniform proportions, so the listed
   cells split into five equal contiguous blocks — contiguous because a species
   can only lose cells to spread along its block boundary.

### Two free hedges

An illegal planting action is silently **ignored** (p.5), never rejected, and we
have spare slots. So we also aim at cells that *might* be plantable:

- terrain 1 and 2 cells (the PDF never defines the terrain enum);
- the 1,440 cells the level file omits.

Definitely-plantable cells are always scheduled first and keep the best ticks,
so the hedges only consume slots that would otherwise go unused.

## Local score estimates

From our own simulator (`photospheria/simulator.py`) — **not** the official
solver. α = k = 1.

| Scenario | C | H | mean age | FINAL |
|---|---|---|---|---|
| listed cells, terrain 0/1/2 (most likely) | 700 | 0.4687 (ceiling) | 58.0 | **0.11148** |
| listed cells, terrain 0 only (worst map) | 360 | 0.4683 | 58.7 | 0.05733 |
| unlisted cells also plantable (upside) | 2,140 | 0.4359 | 50.1 | **0.31570** |
| no dead-matter bonus | 700 | 0.4687 | 58.0 | 0.11148 |
| spread cannot displace | 700 | 0.4687 | 58.0 | 0.11148 |
| CrossHatch = star | 700 | 0.4687 | 58.0 | 0.11148 |

The result is **flat across every unresolved rule** except the map size, which we
cannot control. H sits exactly on its ceiling for 5 species, `log₃₁(5) = 0.4687`.

## Unresolved rules (SimConfig switches, not guesses)

| # | Unknown | Where |
|---|---|---|
| 1 | terrain enum (which of 0/1/2 is plantable) | `plantable_terrains` |
| 2 | are unlisted cells void or plain dirt | `unlisted_is_void` |
| 3 | does the dead-matter 0.5/tick drain apply to planted plants | `drain_dead_matter` |
| 4 | p.6 (rank wins) vs p.13 (last spreader wins) | `spread_displaces_established` |
| 5 | CrossHatch geometry | `crosshatch_shape` |
| 6 | is scoring at tick 499 or 500 | strategy keeps a safety margin |
| 7 | entropy log base N = 31 or 5 | `entropy_base_species` |

## Layout

```
data/           level1.json + the four resource files
photospheria/   world, plants, simulator, scoring, solution I/O, config
strategies/     phased_paint.py — the strategy, heavily commented
generate_solution.py  validate_solution.py  simulate_solution.py  optimise.py
out/solution.json     the submission file
```
