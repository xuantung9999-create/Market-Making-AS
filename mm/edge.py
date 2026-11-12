"""v2 Task 5: what is a fill worth, and should we quote?

Everything the agent learns is one number per fill, its NET EDGE:

    net_edge_bp = side * (mid 60 s after the fill - fill price) / fill price * 1e4 - maker fee

It already contains the spread we captured, the adverse selection we suffered (the mid moving
against us after the fill) and the fee. A positive average means quoting there makes money.

``EdgeTable`` keeps that average per (action, market state). The state is a small grid of
3 x 3 buckets: book imbalance seen from our side (against us / neutral / with us) times
volatility regime (calm / normal / fast). Each cell is an exponentially forgetting mean
(half-life in fills, so old regimes fade) and is shrunk toward the pooled mean of its action:
a cell with few fills borrows strength from all the others, a cell with many fills speaks
for itself. The shrinkage weight ``n0`` is "how many fills of its own a cell needs before
we trust it as much as the pool".

``EdgePolicy`` quotes a side only if the edge, minus ``z`` standard errors (caution), clears
a threshold that rises with inventory in the direction of that inventory (being long makes
buying harder and selling easier): ``e_min_bp +/- gamma_bp * q``.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from typing import Mapping

from mm.queue_sim import Action, MarketState

IMB_EDGES = (-0.33, 0.33)
VOL_EDGES = (1.5, 3.0)
N_MIN_POOLED = 20.0
_ACTIONS = (Action.JOIN, Action.BACK)


def net_edge_bp(side: int, fill_price: float, mid_later: float, fee_bps: float) -> float:
    return side * (mid_later - fill_price) / fill_price * 1e4 - fee_bps


def bucket_of(feat: Mapping[str, float], side: int) -> tuple[int, int]:
    imb = side * float(feat.get("book_imb", 0.0))
    vol = float(feat.get("vol_ratio", 1.0))
    return bisect_right(IMB_EDGES, imb), bisect_right(VOL_EDGES, vol)


def _upd(stat: list, x: float, decay: float) -> None:
    """Exponentially weighted count / mean / sum of squared deviations (weighted Welford)."""
    n, mean, m2 = stat
    n = n * decay + 1.0
    m2 *= decay
    delta = x - mean
    mean += delta / n
    m2 += delta * (x - mean)
    stat[0], stat[1], stat[2] = n, mean, m2


def _var(stat: list) -> float:
    n, _, m2 = stat
    return max(m2, 0.0) / (n - 1.0) if n > 1.0 else 0.0


class EdgeTable:
    def __init__(self, halflife_fills: float = 300.0, n0: float = 30.0):
        self.halflife_fills, self.n0 = float(halflife_fills), float(n0)
        self._decay = 0.5 ** (1.0 / self.halflife_fills)
        self._cells: dict[tuple[int, int, int], list] = {}
        self._pool: dict[int, list] = {}

    def update(self, action: Action, bucket: tuple[int, int], x: float) -> None:
        key = (int(action), int(bucket[0]), int(bucket[1]))
        _upd(self._cells.setdefault(key, [0.0, 0.0, 0.0]), float(x), self._decay)
        _upd(self._pool.setdefault(int(action), [0.0, 0.0, 0.0]), float(x), self._decay)

    def cell(self, action: Action, bucket: tuple[int, int]) -> tuple[float, float, float]:
        """(decayed count, mean, variance) of one cell."""
        s = self._cells.get((int(action), int(bucket[0]), int(bucket[1])), [0.0, 0.0, 0.0])
        return s[0], s[1], _var(s)

    def pooled(self, action: Action) -> tuple[float, float, float]:
        s = self._pool.get(int(action), [0.0, 0.0, 0.0])
        return s[0], s[1], _var(s)

    def estimate(self, action: Action, bucket: tuple[int, int]) -> tuple[float, float]:
        """(shrunk mean, standard error); (-1e9, 0) until the action has enough fills overall."""
        pn, pmean, pvar = self.pooled(action)
        if pn < N_MIN_POOLED:
            return -1e9, 0.0
        n, cmean, cvar = self.cell(action, bucket)
        mean = (n * cmean + self.n0 * pmean) / (n + self.n0)
        var = cvar if n >= 2.0 else pvar
        return mean, math.sqrt(var / max(n, 1.0))

    def to_dict(self) -> dict:
        return {"halflife_fills": self.halflife_fills, "n0": self.n0,
                "cells": [[a, i, j, *s] for (a, i, j), s in sorted(self._cells.items())],
                "pool": [[a, *s] for a, s in sorted(self._pool.items())]}

    @classmethod
    def from_dict(cls, d: dict) -> "EdgeTable":
        t = cls(d["halflife_fills"], d["n0"])
        t._cells = {(int(a), int(i), int(j)): [float(n), float(m), float(v)] for a, i, j, n, m, v in d["cells"]}
        t._pool = {int(a): [float(n), float(m), float(v)] for a, n, m, v in d["pool"]}
        return t


@dataclass
class EdgePolicy:
    table: EdgeTable
    e_min_bp: float = 0.0
    z: float = 1.0
    gamma_bp: float = 1.0
    name: str = "Edge"

    def _side(self, feat, side: int, q: int) -> Action:
        threshold = self.e_min_bp + side * self.gamma_bp * q
        bucket = bucket_of(feat, side)
        best, best_score = Action.OUT, 0.0
        for a in _ACTIONS:                       # JOIN first, so ties go to JOIN
            mean, se = self.table.estimate(a, bucket)
            score = mean - self.z * se - threshold
            if score > best_score:
                best, best_score = a, score
        return best

    def decide(self, st: MarketState, q: int) -> tuple[Action, Action]:
        return self._side(st.feat, 1, q), self._side(st.feat, -1, q)
