#!/usr/bin/env python3
"""
Build one submission ZIP per level.

Each ZIP is SELF-CONTAINED and LEVEL-SPECIFIC: it holds only that level's
level file and that level's solution, plus the shared plant/animal reference
data and the code needed to regenerate it.  Nothing from another level is
included.

    py package.py            # builds level1_code.zip .. level3_code.zip
    py package.py 2          # just Level 2
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT.parent

# Shared reference data every level needs in order to run.
SHARED_DATA = ["plant_dataset.json", "plant_unlock_conditions.json",
               "classifications.json", "animals.json"]

CODE = [
    "photospheria/__init__.py", "photospheria/config.py", "photospheria/plants.py",
    "photospheria/world.py", "photospheria/solution.py", "photospheria/scoring.py",
    "photospheria/simulator.py", "photospheria/unlocks.py",
    "photospheria/fastsim.py", "photospheria/rules.py",
    "strategies/__init__.py", "strategies/phased_paint.py",
    "strategies/territory.py", "strategies/balanced.py",
    "strategies/bands3.py", "sweep3.py", "calib2.py",
    "generate_solution.py", "validate_solution.py", "simulate_solution.py",
    "bench.py", "sweep.py", "build_all.py", "package.py",
]

LEVELS = {
    n: {"level": "data/level%d.json" % n,
        "solution": "out/solution.json" if n == 1
                    else "out/solution_level%d.json" % n,
        "strategy": "strategies/balanced.py",
        "cmd": "py build_all.py --levels %d" % n}
    for n in (1, 2, 3, 4)
}

README = """# Photospheria - Level {n}

Python 3.13, standard library only.  Deterministic: the same command always
produces a byte-identical solution file.

Regenerate:

    {cmd}

Validate:

    py validate_solution.py {sol} --level {lvl}

Estimate the score locally (our own reading of the spec, not the official
solver):

    py simulate_solution.py {sol} --level {lvl}

Contents: only this level's level file and solution, the shared plant/animal
reference data, and the code that produces them.
"""


def build(n):
    spec = LEVELS[n]
    files = list(CODE) + [spec["strategy"], spec["level"], spec["solution"]]
    files += ["data/" + d for d in SHARED_DATA]

    out = OUT_DIR / ("level%d_code.zip" % n)
    if out.exists():
        out.unlink()
    missing = [f for f in files if not (ROOT / f).exists()]
    if missing:
        raise SystemExit("missing: %s" % missing)

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(set(files)):
            z.write(ROOT / f, f)
        z.writestr("README.md", README.format(
            n=n, cmd=spec["cmd"], sol=spec["solution"], lvl=spec["level"]))
    print("level%d_code.zip  %2d files  %6.1f KB   (solution: %s)"
          % (n, len(set(files)) + 1, out.stat().st_size / 1024, spec["solution"]))


if __name__ == "__main__":
    wanted = [int(a) for a in sys.argv[1:]] or sorted(LEVELS)
    for n in wanted:
        build(n)
