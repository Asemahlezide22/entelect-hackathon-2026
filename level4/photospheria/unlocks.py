"""
Unlock condition trees (p.18-21) and animal presence (animals.json).

Used by the simulator so that a planting action for a species that is not yet
unlocked is IGNORED, exactly as the problem statement says (p.5), and by the
generator so it knows which species are actually available at which tick.

Coverage denominator: p.8 - "if the world had 100 cells, at least 8 of them
must contain Lavender" - so coverage is measured against rows*cols, including
cells that are not plantable.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .plants import catalogue

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

STARTERS = ("Grass", "Rose Bush", "Lavender", "Dwarf Sunflower", "Oak Tree")

_OPS = {
    ">":  lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<":  lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
}


@lru_cache(maxsize=1)
def _load():
    unlocks = json.loads((DATA_DIR / "plant_unlock_conditions.json").read_text("utf-8"))
    animals = json.loads((DATA_DIR / "animals.json").read_text("utf-8"))
    classes = json.loads((DATA_DIR / "classifications.json").read_text("utf-8"))
    return unlocks, animals, classes


class WorldState:
    """The slice of simulator state the condition trees need."""

    def __init__(self, counts_by_name, total_cells, dead_matter, events_seen):
        self.counts = counts_by_name          # plant name -> cells occupied
        self.total_cells = total_cells        # rows * cols
        self.dead_matter = dead_matter        # number of dead-matter cells
        self.events = events_seen             # set of event names seen so far

    def count(self, name):
        return self.counts.get(name, 0)

    def coverage(self, name):
        return self.count(name) / self.total_cells if self.total_cells else 0.0


class Tracker:
    """Recomputes which species are plantable, and which animals are present."""

    def __init__(self, animals_enabled=True, total_cells=0):
        self.unlocks, self.animals, self.classes = _load()
        self.animals_enabled = animals_enabled
        self.total_cells = total_cells
        self.by_name = {p.name: p.index for p in catalogue().values()}
        self.present_animals = set()
        self.unlocked = {self.by_name[n] for n in STARTERS}

    # ------------------------------------------------------------- helpers
    def _expand(self, group):
        """A species_group entry may name a classification or a species."""
        names = [group] if isinstance(group, str) else list(group)
        out = []
        for n in names:
            out.extend(self.classes.get(n, [n]))
        return out

    # ------------------------------------------------- animal requirements
    def _animal_cond(self, node, st):
        t = node.get("type")
        if t in ("AND", "OR"):
            f = all if t == "AND" else any
            return f(self._animal_cond(c, st) for c in node.get("conditions", ()))
        op = _OPS.get(node.get("operator", ">="))
        if t == "coverage":
            total = sum(st.coverage(n) for n in self._expand(node["species"]))
            return op(total, node["threshold"])
        if t == "group_coverage":
            total = sum(st.coverage(n) for n in self._expand(node["species_group"]))
            return op(total, node["threshold"])
        if t == "count":
            key = node.get("species") or node.get("species_group")
            total = sum(st.count(n) for n in self._expand(key))
            return op(total, node["threshold"])
        if t == "dominance":
            tot = sum(st.counts.values())
            if not tot:
                return False
            top = max(st.counts.values())
            return op(top / tot, node["threshold"])
        return False

    # -------------------------------------------------- plant unlock trees
    def _plant_cond(self, node, st):
        if "op" in node:
            if node["op"] == "AND":
                return all(self._plant_cond(c, st) for c in node["children"])
            if node["op"] == "OR":
                return any(self._plant_cond(c, st) for c in node["children"])
            if node["op"] == "NOT":
                return not self._plant_cond(node["child"], st)
        t = node["type"]
        if t == "species_present":
            return node["species"].lower() in self.present_animals
        if t == "species_absent":
            return node["species"].lower() not in self.present_animals
        if t == "event":
            return node["event"] in st.events
        op = _OPS.get(node.get("operator", ">"))
        if t == "coverage":
            return op(st.coverage(node["plant"]), node["value"])
        if t == "count":
            return op(st.count(node["plant"]), node["value"])
        if t == "feature_count":
            if node["feature"] == "dead_matter":
                value = node["value"]
                measured = (st.dead_matter / st.total_cells
                            if value <= 1 else st.dead_matter)
                return op(measured, value)
            return False
        return False

    # ------------------------------------------------------------- update
    def update(self, counts_by_index, dead_matter, events_seen):
        """Recompute animals + unlocked species.  Unlocks are STICKY: once a
        species has been unlocked we keep it unlocked (the PDF never says an
        unlock is revoked, only that animals come and go)."""
        by_name = {}
        for idx, n in counts_by_index.items():
            by_name[catalogue()[idx].name] = n
        st = WorldState(by_name, self.total_cells, dead_matter, events_seen)

        if self.animals_enabled:
            self.present_animals = {
                a["id"] for a in self.animals
                if self._animal_cond(a["requirements"], st)
            }
        else:
            self.present_animals = set()

        for entry in self.unlocks:
            idx = self.by_name.get(entry["plant"])
            if idx is None or idx in self.unlocked:
                continue
            if self._plant_cond(entry["unlock"], st):
                self.unlocked.add(idx)
        return self.unlocked
