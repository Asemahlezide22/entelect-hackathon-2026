"""
Submission file construction and validation.

Format (problem-statement.pdf p.4):

    { "actions": [ { "tick": 1,
                     "plants": [ {"plant_index": 6, "row": 0, "col": 0}, ... ] },
                   ... ] }

Constraints enforced here (p.5):
  * tick is an integer in [0, T-1]
  * row/col inside the grid
  * plant_index exists in the catalogue
  * at most 20 plants per tick  (the solver silently drops the rest; we refuse
    to emit such a file at all)
"""
from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path

from .plants import catalogue

MAX_PLANTS_PER_TICK = 20


class Solution:
    """An ordered, deterministic collection of planting actions."""

    def __init__(self):
        # tick -> list of (plant_index, row, col), insertion-ordered
        self._by_tick = OrderedDict()

    # ------------------------------------------------------------------ build
    def plant(self, tick: int, plant_index: int, row: int, col: int) -> None:
        bucket = self._by_tick.setdefault(tick, [])
        if len(bucket) >= MAX_PLANTS_PER_TICK:
            raise ValueError(
                "tick %d already has %d actions; the solver would drop this one"
                % (tick, MAX_PLANTS_PER_TICK)
            )
        bucket.append((plant_index, row, col))

    def free_slots(self, tick: int) -> int:
        return MAX_PLANTS_PER_TICK - len(self._by_tick.get(tick, ()))

    def total_actions(self) -> int:
        return sum(len(v) for v in self._by_tick.values())

    def as_actions(self) -> dict:
        """The dict form the simulator consumes."""
        return {t: list(v) for t, v in self._by_tick.items()}

    # ------------------------------------------------------------------- io
    def to_json_obj(self) -> dict:
        # Ticks sorted ascending, actions in insertion order => byte-identical
        # output for identical inputs.
        return {
            "actions": [
                {
                    "tick": tick,
                    "plants": [
                        {"plant_index": pi, "row": r, "col": c}
                        for (pi, r, c) in self._by_tick[tick]
                    ],
                }
                for tick in sorted(self._by_tick)
                if self._by_tick[tick]
            ]
        }

    def write(self, path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_json_obj(), indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        return path


def load(path) -> dict:
    """Read a submission file back into the simulator's actions dict."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    actions = {}
    for entry in raw["actions"]:
        actions.setdefault(entry["tick"], []).extend(
            (p["plant_index"], p["row"], p["col"]) for p in entry["plants"]
        )
    return actions


def validate(path, world) -> list:
    """Structural validation of a written submission.  Returns a list of
    problems; an empty list means the file satisfies every documented
    constraint in the problem statement."""
    problems = []
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:                        # noqa: BLE001
        return ["file is not valid JSON: %s" % exc]

    if not isinstance(raw, dict) or "actions" not in raw:
        return ["top level must be an object with an 'actions' key"]
    if not isinstance(raw["actions"], list):
        return ["'actions' must be an array"]

    known = set(catalogue())
    seen_ticks = set()
    for i, entry in enumerate(raw["actions"]):
        where = "actions[%d]" % i
        if not isinstance(entry, dict) or "tick" not in entry or "plants" not in entry:
            problems.append("%s: must have 'tick' and 'plants'" % where)
            continue
        tick = entry["tick"]
        if not isinstance(tick, int) or isinstance(tick, bool):
            problems.append("%s: tick must be an integer, got %r" % (where, tick))
            continue
        if not (0 <= tick <= world.ticks - 1):
            problems.append(
                "%s: tick %d outside [0, %d]" % (where, tick, world.ticks - 1)
            )
        if tick in seen_ticks:
            problems.append("%s: tick %d appears more than once" % (where, tick))
        seen_ticks.add(tick)

        plants = entry["plants"]
        if not isinstance(plants, list):
            problems.append("%s: 'plants' must be an array" % where)
            continue
        if len(plants) > MAX_PLANTS_PER_TICK:
            problems.append(
                "%s: %d plants on tick %d exceeds the limit of %d"
                % (where, len(plants), tick, MAX_PLANTS_PER_TICK)
            )
        occupied_this_tick = set()
        for j, p in enumerate(plants):
            w2 = "%s.plants[%d]" % (where, j)
            if not isinstance(p, dict) or not {"plant_index", "row", "col"} <= set(p):
                problems.append("%s: needs plant_index, row, col" % w2)
                continue
            pi, r, c = p["plant_index"], p["row"], p["col"]
            if pi not in known:
                problems.append("%s: unknown plant_index %r" % (w2, pi))
            if not world.in_bounds(r, c):
                problems.append("%s: (%r,%r) outside the %dx%d grid"
                                % (w2, r, c, world.rows, world.cols))
            if (r, c) in occupied_this_tick:
                problems.append("%s: (%d,%d) planted twice in tick %d" % (w2, r, c, tick))
            occupied_this_tick.add((r, c))
    return problems
