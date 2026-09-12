# Photospheria — Entelect Hack\<IT\> 2026

Solution for the Entelect Hack\<IT\> 2026 challenge (12 September 2026).

You are an ecologist on the planet Photospheria. Plants interact based on where
they are placed: some combinations unlock new species, others make it harder for
plants to survive. The garden is an *N×M* grid, time is discrete (ticks), and on
each tick you may place up to twenty plants. **Only the final state of the garden
is scored**, on species diversity first and longevity second.

Python 3.13, standard library only. No dependencies, no network, no randomness.

## Quick start

```bash
cd level1
py generate_solution.py     # writes out/solution.json
py validate_solution.py     # schema + constraint check
py simulate_solution.py     # local score estimate
py optimise_all.py          # parameter sweep across all four levels
```

## Layout

```
level1/
  data/              level1–4 level files + the four shared resource files
  photospheria/      world, plants, simulator, scoring, solution I/O, config
  strategies/        phased_paint, seed_spread, level2_ladder
  out/               generated solutions and optimiser reports
  submitted/         the solutions actually submitted
  generate_solution.py  validate_solution.py  simulate_solution.py
  optimise.py  optimise_all.py  optimise_levels.py  package.py
resources/           plant/animal datasets, classifications, unlock conditions
problem-statement.txt  extracted text of the official problem statement
rca.txt                extracted text of the Root Cause Analysis briefing
```

Despite the folder name, `level1/` holds the engine and strategies for **all
four levels** — the level files live side by side in `level1/data/`.

## Approach

The full write-up, including the reasoning behind the strategy and the local
score estimates, is in [level1/README.md](level1/README.md). In short:

- **Level 1 has no unlock game.** `animals_enabled` is false and there are no
  event commands, so every locked species' unlock chain is unreachable. Five
  species are available and the entire problem is *where* and *when* to place
  them.
- **The nutrient clock forces late planting.** A cell holds 100 nutrient points
  and loses 1/tick while occupied, so nothing planted before tick 401 survives
  to tick 500. The scored garden is painted in the final 99 ticks.
- **Equal blocks maximise entropy.** Diversity peaks at uniform proportions, so
  plantable cells split into five equal contiguous blocks — contiguous so a
  species can only lose ground along a single boundary.

Several rules are ambiguous in the problem statement (the terrain enum, whether
unlisted cells are void, CrossHatch geometry, and others). These are modelled as
explicit switches in `photospheria/config.py` rather than baked-in guesses, and
the strategy was checked to score flat across all of them.

## Note on `.zip` files

The packaged submission archives (`level*_code.zip`) are build output and are
gitignored — regenerate them with `level1/package.py`.
