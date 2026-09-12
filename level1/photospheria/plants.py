"""
Plant catalogue, loaded verbatim from data/plant_dataset.json.

Nothing here is invented: every field is read straight out of the supplied
dataset.  The only derived values are convenience booleans for the handful of
weakness/special rules that actually fire in Level 1.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# The five species with no entry in plant_unlock_conditions.json, i.e. the ones
# the PDF (p.6) says you start every level with.
STARTER_NAMES = ("Grass", "Rose Bush", "Lavender", "Dwarf Sunflower", "Oak Tree")

# Convenient aliases used throughout the strategies.
GRASS = 1
ROSE_BUSH = 2
DWARF_SUNFLOWER = 5
LAVENDER = 6
OAK_TREE = 12

#: The complete Level-1 roster.  See notes/level1_analysis.md - every other
#: species' unlock tree bottoms out in an animal or a weather event, both of
#: which are disabled in level1.json, so none of them is reachable.
LEVEL1_PLANT_INDICES = (GRASS, ROSE_BUSH, DWARF_SUNFLOWER, LAVENDER, OAK_TREE)


@dataclass(frozen=True)
class Plant:
    name: str
    index: int
    time_to_maturity: int
    spread_rate: int
    spread_mechanism: str
    spread_type: str
    spread_range: int
    root_type: str
    invasiveness_rank: int
    preferred_soil: frozenset[int]
    conditional_modifiers: tuple[dict, ...] = ()
    weaknesses: tuple[dict, ...] = ()
    specials: tuple[dict, ...] = ()

    # -- derived flags for the rules that can actually fire in Level 1 -------
    no_shade_survival: bool = field(default=False)
    no_shade_spread: bool = field(default=False)
    no_winter_spread: bool = field(default=False)
    die_if_isolated: bool = field(default=False)
    die_if_neighbors_gt: int | None = field(default=None)
    shade_radius: int = field(default=0)
    adjacent_shade_penalty: bool = field(default=False)
    shade_required: bool = field(default=False)
    must_be_burnt_soil: bool = field(default=False)
    no_adjacent_plants: bool = field(default=False)
    must_be_adjacent_to: str = field(default="")

    @property
    def risky(self) -> bool:
        """True when this species' survival depends on a rule the PDF states
        but never defines precisely - terrain adjacency, shade, burnt soil.
        Our simulator enforces a conservative reading, but the official solver
        may differ, so strategies can choose to avoid these species entirely
        rather than stake coverage on an interpretation."""
        return bool(self.shade_required or self.must_be_burnt_soil
                    or self.no_adjacent_plants or self.must_be_adjacent_to)

    def spread_rate_for_season(self, season: str) -> int:
        """Apply conditional_modifiers (p.13).  Only season_summer exists here."""
        rate = self.spread_rate
        for mod in self.conditional_modifiers:
            if mod.get("condition") == f"season_{season.lower()}":
                rate = mod.get("spread_rate", rate)
        return rate


def _build(raw: dict) -> Plant:
    g = raw["growth"]
    weaknesses = tuple(raw["rules"].get("weaknesses", ()))
    specials = tuple(raw["rules"].get("special", ()))
    wtypes = {w["type"] for w in weaknesses}
    by_type = {s["type"]: s for s in specials}
    neighbors_gt = next(
        (w["value"] for w in weaknesses if w["type"] == "die_if_neighbors_greater_than"),
        None,
    )
    return Plant(
        name=raw["plant"],
        index=raw["index"],
        time_to_maturity=g["time_to_maturity"],
        spread_rate=g["spread_rate"],
        spread_mechanism=g["spread_mechanism"],
        spread_type=g["spread_type"],
        spread_range=g["spread_range"],
        root_type=g["root_type"],
        invasiveness_rank=g["invasiveness_rank"],
        preferred_soil=frozenset(raw["preferred_soil"]),
        conditional_modifiers=tuple(g.get("conditional_modifiers", ())),
        weaknesses=weaknesses,
        specials=specials,
        no_shade_survival="no_shade_survival" in wtypes,
        no_shade_spread="no_shade_spread" in wtypes,
        no_winter_spread="no_winter_spread" in wtypes,
        die_if_isolated="die_if_isolated" in wtypes,
        die_if_neighbors_gt=neighbors_gt,
        shade_radius=by_type.get("shade_radius", {}).get("value", 0),
        adjacent_shade_penalty="adjacent_shade_penalty" in by_type,
        shade_required="shade_required" in wtypes,
        must_be_burnt_soil="must_be_burnt_soil" in wtypes,
        no_adjacent_plants="no_adjacent_plants" in wtypes,
        must_be_adjacent_to=next(
            (w.get("feature", "") for w in weaknesses
             if w["type"] == "must_be_adjacent_to"), ""),
    )


@lru_cache(maxsize=1)
def catalogue() -> dict[int, Plant]:
    raw = json.loads((DATA_DIR / "plant_dataset.json").read_text(encoding="utf-8"))
    return {p["index"]: _build(p) for p in raw}


def get(index: int) -> Plant:
    return catalogue()[index]


TOTAL_SPECIES_IN_GAME = 31  # len(catalogue()); the N in log_N for entropy
