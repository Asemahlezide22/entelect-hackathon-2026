"""
The scoring function, transcribed from problem-statement.pdf pages 9-10.

    H            = -sum_i  p_i * log_N(p_i)            (0*log0 == 0)
    MainScore    = H * (C / C_max) ** alpha
    Longevity    = (1 / C_max) * sum_ij (l_ij / T) ** k
    FinalScore   = 0.8 * MainScore + 0.2 * Longevity

alpha and k are deliberately withheld by the organisers, so every number this
module prints is an ESTIMATE under the alpha/k in SimConfig.  Both terms are
monotonic in (diversity, coverage, lifespan), so the *ranking* of two
strategies is almost always stable across alpha/k - `score_grid` checks that.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .plants import get as get_plant


@dataclass
class Score:
    entropy: float          # H
    coverage: float         # C / C_max
    occupied: int           # C
    main: float             # H * (C/C_max)^alpha
    longevity: float
    final: float
    counts: dict
    mean_age: float
    alpha: float
    k: float

    def __str__(self) -> str:
        names = ", ".join(
            "%s=%d" % (get_plant(i).name, n) for i, n in sorted(self.counts.items())
        )
        return (
            "H=%.4f  C=%d (%.3f of grid)  main=%.4f  longevity=%.4f  "
            "FINAL=%.5f  [alpha=%g k=%g]\n    %s\n    mean age of living plants = %.1f"
            % (
                self.entropy, self.occupied, self.coverage, self.main,
                self.longevity, self.final, self.alpha, self.k, names, self.mean_age,
            )
        )


def entropy(counts, n_species_in_game: int) -> float:
    total = sum(counts.values())
    if total == 0 or n_species_in_game <= 1:
        return 0.0
    log_n = math.log(n_species_in_game)
    h = 0.0
    for n in counts.values():
        if n <= 0:
            continue
        p = n / total
        h -= p * (math.log(p) / log_n)
    return h


def score(result, alpha=None, k=None, n_species_in_game=None) -> Score:
    cfg = result.cfg
    alpha = cfg.alpha if alpha is None else alpha
    k = cfg.k if k is None else k
    n_species = cfg.entropy_base_species if n_species_in_game is None else n_species_in_game

    c_max = result.world.total_cells
    T = result.world.ticks

    h = entropy(result.counts, n_species)
    coverage = result.occupied / c_max
    main = h * (coverage ** alpha)

    ages = [a for a in result.age if a > 0]
    longevity = sum((a / T) ** k for a in ages) / c_max

    return Score(
        entropy=h,
        coverage=coverage,
        occupied=result.occupied,
        main=main,
        longevity=longevity,
        final=0.8 * main + 0.2 * longevity,
        counts=dict(result.counts),
        mean_age=(sum(ages) / len(ages)) if ages else 0.0,
        alpha=alpha,
        k=k,
    )


def score_grid(result, alphas=(0.5, 1.0, 1.5, 2.0), ks=(0.5, 1.0, 2.0)):
    """Score under several alpha/k so we never tune against one lucky guess."""
    return {(a, kk): score(result, alpha=a, k=kk).final for a in alphas for kk in ks}


def theoretical_max_entropy(n_available_species: int, n_species_in_game: int) -> float:
    """H when the available species are present in exactly equal numbers."""
    return entropy({i: 1 for i in range(n_available_species)}, n_species_in_game)
