"""
Level file ingestion: grid geometry, soil/terrain, season schedule.

The level file lists only 1,060 of the 2,500 cells.  Whether the other 1,440
are void or default dirt is SimConfig.unlisted_is_void (UNKNOWN #2).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import SimConfig

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

SOIL_NAMES = {0: "Dirt", 1: "Mud", 2: "Clay", 3: "Burnt"}
SEASONS = ("Spring", "Summer", "Autumn", "Winter")
# HYPOTHESIS: level1.json's first season command is at tick 100 (Summer), so
# ticks 0-99 must already be some season.  Spring is the natural predecessor of
# Summer in the listed cycle.  Nothing in Level 1 depends on this: the only
# season-sensitive rule is no_winter_spread, and Winter is explicitly declared.
INITIAL_SEASON = "Spring"


@dataclass(frozen=True)
class World:
    rows: int
    cols: int
    ticks: int
    animals_enabled: bool
    terrain: list[list[int | None]]   # None = cell absent from the level file
    soil: list[list[int | None]]
    season_changes: dict[int, str]    # tick -> season name
    events: dict[int, str]            # tick -> event name (empty in Level 1)
    source: Path

    # ------------------------------------------------------------------ API
    @property
    def total_cells(self) -> int:
        """C_max in the scoring function = N x M, INCLUDING void cells."""
        return self.rows * self.cols

    def in_bounds(self, r: int, c: int) -> bool:
        return 0 <= r < self.rows and 0 <= c < self.cols

    def cell_terrain(self, r: int, c: int, cfg: SimConfig) -> int | None:
        t = self.terrain[r][c]
        if t is None:
            return None if cfg.unlisted_is_void else 0
        return t

    def cell_soil(self, r: int, c: int, cfg: SimConfig) -> int | None:
        s = self.soil[r][c]
        if s is None:
            return None if cfg.unlisted_is_void else 0
        return s

    def season_at(self, tick: int) -> str:
        season = INITIAL_SEASON
        for t in sorted(self.season_changes):
            if t <= tick:
                season = self.season_changes[t]
        return season

    def plantable_cells(self, cfg: SimConfig) -> list[tuple[int, int]]:
        """Cells whose terrain permits a plant at all (soil type still filters
        per-species via preferred_soil)."""
        out = []
        for r in range(self.rows):
            for c in range(self.cols):
                t = self.cell_terrain(r, c, cfg)
                if t is not None and t in cfg.plantable_terrains:
                    out.append((r, c))
        return out

    def cells_for_plant(self, plant, cfg: SimConfig) -> list[tuple[int, int]]:
        """Cells this specific species can legally occupy (terrain AND soil)."""
        return [
            (r, c)
            for (r, c) in self.plantable_cells(cfg)
            if self.cell_soil(r, c, cfg) in plant.preferred_soil
        ]


def load(path: str | Path = DATA_DIR / "level1.json") -> World:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows, cols = raw["rows"], raw["cols"]
    terrain: list[list[int | None]] = [[None] * cols for _ in range(rows)]
    soil: list[list[int | None]] = [[None] * cols for _ in range(rows)]
    for cell in raw["cells"]:
        terrain[cell["row"]][cell["col"]] = cell["terrain"]
        soil[cell["row"]][cell["col"]] = cell["soil"]

    season_changes, events = {}, {}
    for cmd in raw.get("commands", ()):
        if cmd["type"] == "season":
            season_changes[cmd["tick"]] = cmd["season"]
        else:                      # no non-season commands exist in Level 1
            events[cmd["tick"]] = cmd.get("event", cmd["type"])

    return World(
        rows=rows,
        cols=cols,
        ticks=raw["ticks"],
        animals_enabled=raw.get("animals_enabled", False),
        terrain=terrain,
        soil=soil,
        season_changes=season_changes,
        events=events,
        source=path,
    )


def describe(world: World, cfg: SimConfig) -> str:
    from collections import Counter

    listed = Counter()
    for r in range(world.rows):
        for c in range(world.cols):
            if world.terrain[r][c] is not None:
                listed[(world.terrain[r][c], world.soil[r][c])] += 1
    lines = [
        f"world       : {world.rows}x{world.cols} = {world.total_cells} cells, "
        f"{world.ticks} ticks, animals={world.animals_enabled}",
        f"seasons     : {world.season_at(0)} then "
        + ", ".join(f"{t}->{s}" for t, s in sorted(world.season_changes.items())),
        f"events      : {world.events or 'none'}",
        "listed cells:",
    ]
    for (t, s), n in sorted(listed.items()):
        lines.append(f"              terrain={t} soil={s} ({SOIL_NAMES[s]:5s}) x {n}")
    lines.append(f"              unlisted x {world.total_cells - sum(listed.values())}")
    lines.append(f"plantable terrain {cfg.plantable_terrains}: "
                 f"{len(world.plantable_cells(cfg))} cells")
    return "\n".join(lines)
