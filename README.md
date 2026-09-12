# Photospheria — Entelect Hack\<IT\> 2026

Solution for the Entelect Hack\<IT\> 2026 challenge (12 September 2026).

You are an ecologist on the planet Photospheria. Plants interact based on where
they are placed: some combinations unlock new species, others make it harder for
plants to survive. The garden is an *N×M* grid, time is discrete (ticks), and on
each tick you may place up to twenty plants. **Only the final state of the garden
is scored**, on species diversity first and longevity second.

Python 3.13, standard library only. No dependencies, no network, no randomness.

## Quick start

Each level folder runs standalone:

```bash
cd level2
py generate_solution.py     # writes out/solution_level2.json
py validate_solution.py     # schema + constraint check
py simulate_solution.py     # local score estimate
```

Same three commands in `level3/` and `level4/`.

## Layout

```
level1/   working directory: engine, strategies, experiments, all four level files
level2/   self-contained level 2 submission
level3/   self-contained level 3 submission
level4/   self-contained level 4 submission
resources/             plant/animal datasets, classifications, unlock conditions
problem-statement.txt  extracted text of the official problem statement
rca.txt                extracted text of the Root Cause Analysis briefing
```

`level2/`, `level3/` and `level4/` are each a complete, standalone submission —
their own `data/level*.json`, `photospheria/` engine, `strategies/`, and the
generated `out/solution_level*.json`. They share most of their code, so they are
deliberately duplicated rather than cross-referenced; each folder runs on its
own with nothing else present.

`level1/` is the working directory the others were built from. It holds all four
level files side by side in `level1/data/`, plus the calibration and parameter
sweep experiments.

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
