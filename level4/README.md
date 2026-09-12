# Photospheria - Level 4

Python 3.13, standard library only.  Deterministic: the same command always
produces a byte-identical solution file.

Regenerate:

    py build_all.py --levels 4

Validate:

    py validate_solution.py out/solution_level4.json --level data/level4.json

Estimate the score locally (our own reading of the spec, not the official
solver):

    py simulate_solution.py out/solution_level4.json --level data/level4.json

Contents: only this level's level file and solution, the shared plant/animal
reference data, and the code that produces them.
