"""The verifier: same clauses, two appraisers, compared cell by cell.

Appraiser A (vintage-point) reads what the official series said in a given
vintage and answers T or F.  This is what every existing workflow does.

Appraiser B (conformal-band) reads the whole set of vintages that speak about
the reference year, forms a distribution-free revision interval, and answers
T, F or U.

The comparison is the contribution.  Two counts come out of it:

  flips        -- cells where B's answer differs from A's *and A was
                  over-confident*: A says T/F, B says U.  These are the cells
                  where a point-value verifier reports a decision the data
                  does not support.
  reversals    -- cells where A and B both answer decisively but disagree.
                  Should be 0 for a sound interval construction; anything
                  non-zero is a bug in the band, and the test asserts it is 0.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple
from .dsl import T, F, U, eval_clause
from .vintage import VintageStore, interval_for, band_view


@dataclass
class Cell:
    clause_id: str
    reference_year: int
    vintage: int
    point_answer: str
    band_answer: str
    point_value: float | None
    band_lo: float
    band_hi: float
    decisive: bool          # A said T/F
    supported: bool         # B agrees A had the right to decide
    flips: bool             # A decisive, B undetermined
    reversal: bool          # both decisive, different answers


def evaluate(store: VintageStore, clauses: List[dict],
             vintages: List[int] | None = None,
             alpha: float = 0.2,
             primary_indicator_of=None) -> List[Cell]:
    """Evaluate every clause at every (reference year, vintage) cell."""
    if vintages is None:
        vintages = sorted({v for d in store.series.values() for (_, v) in d})
    point_view = {ind: {k: float(v) for k, v in d.items()}
                  for ind, d in store.series.items()}
    from .dsl import Iv
    point_view = {ind: {k: Iv(v, v, v) for k, v in d.items()}
                  for ind, d in point_view.items()}

    out: List[Cell] = []
    for cl in clauses:
        ind = primary_indicator_of(cl) if primary_indicator_of else _primary(cl)
        for v in vintages:
            band = band_view(store, ind, None, v, alpha) if False else \
                   _band_store(store, v, alpha)
            for y in store.years(ind):
                if y < min(vs for vs in vintages) - 0 and False:
                    continue
                try:
                    a = eval_clause(cl, point_view, y, v)
                    b = eval_clause(cl, band, y, v)
                except KeyError:
                    continue
                decisive = a in (T, F)
                fl = decisive and b == U
                rev = decisive and b in (T, F) and a != b
                try:
                    iv = interval_for(store, ind, y, v, alpha)
                    lo, hi = iv.lo, iv.hi
                except KeyError:
                    lo = hi = float("nan")
                out.append(Cell(cl.get("id", "?"), y, v, a, b,
                                float(iv.point) if iv.point is not None else None,
                                lo, hi, decisive, not fl, fl, rev))
    return out


def _primary(cl):
    k = cl.get("kind", "threshold")
    if k == "window":
        return _primary(cl)[0] if isinstance(_primary(cl), tuple) else cl["indicator"]
    if k == "nested":
        return _primary(cl["target"])
    if k == "ratio":
        return cl["numerator"]
    return cl["indicator"]


def _band_store(store: VintageStore, vintage: int, alpha: float):
    """Whole-store view at `vintage` with every cell replaced by its band."""
    view: Dict[str, Dict] = {}
    for ind in store.series:
        d = {}
        for (y, v), val in store.series[ind].items():
            try:
                d[(y, v)] = interval_for(store, ind, y, vintage, alpha)
            except KeyError:
                d[(y, v)] = val
        view[ind] = d
    return view


def summarise(cells: List[Cell]) -> dict:
    n = len(cells)
    dec = sum(1 for c in cells if c.decisive)
    flips = sum(1 for c in cells if c.flips)
    rev = sum(1 for c in cells if c.reversal)
    return {
        "cells": n,
        "point_decisive": dec,
        "unsupported_decisions": flips,
        "unsupported_rate_of_decisions": (flips / dec) if dec else 0.0,
        "unsupported_rate_of_cells": (flips / n) if n else 0.0,
        "reversals": rev,
    }


def by_clause(cells: List[Cell]) -> Dict[str, dict]:
    out = {}
    for c in cells:
        out.setdefault(c.clause_id, []).append(c)
    return {k: summarise(v) for k, v in out.items()}
