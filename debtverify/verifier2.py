"""Verifier v2: bands come from the conformal calibration, not from min-max.

The comparison is now a *curve*, not a number.  For each confidence level
1-alpha the band widens (that is what the guarantee costs) and the number of
point decisions the data does not actually support falls.  Reporting the
curve, rather than one point on it, is the honest form of the claim: there is
no setting at which the band is both tight and always decisive.

Three counts per level:

  unsupported   A decided (T/F), B says U under the same data
  reversal      A and B both decided and disagreed -- must be 0, machine-checked
  irreducible   B says U even at alpha -> 0, i.e. the widest band the data can
                justify still does not decide.  These are the clauses that
                NO amount of published data settles, and they are the ones a
                term sheet should stop writing.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Sequence
from .dsl import T, F, U, Iv, eval_clause
from .vintage import VintageStore, revision_history
from .conformal import Calibration, calibrate_conservative


@dataclass
class Curve:
    alpha: float
    q: float
    n_scores: int
    loo_coverage: float
    cells: int
    decided: int
    unsupported: int
    reversals: int
    irreducible: int

    def as_row(self) -> dict:
        return {
            "alpha": round(self.alpha, 3),
            "guarantee": round(1 - self.alpha, 3),
            "band_half_width": (round(self.q, 3) if self.q != float("inf") else None),
            "loo_coverage": (round(self.loo_coverage, 3)
                             if self.loo_coverage == self.loo_coverage else None),
            "cells": self.cells,
            "point_decided": self.decided,
            "unsupported": self.unsupported,
            "unsupported_rate": (round(self.unsupported / self.decided, 4)
                                 if self.decided else None),
            "reversals": self.reversals,
            "irreducible": self.irreducible,
        }


def _primary(cl):
    k = cl.get("kind", "threshold")
    if k == "window":
        return cl["indicator"]
    if k == "nested":
        return _primary(cl["target"])
    if k == "ratio":
        return cl["numerator"]
    return cl["indicator"]


def _band_view(store: VintageStore, ind: str, q: float, vintage: int):
    """As-of view: only cells a reader in `vintage` could actually have read.

    This is the constraint that makes the count honest.  A cell (y, u) with
    u > vintage is a value published *later*; letting the point appraiser see
    it would hand it the answer key and make the comparison meaningless.
    Every cell is (point - q, point + q); the point is what that vintage said.
    """
    view = {i: {} for i in store.series}
    for i, d in store.series.items():
        for (y, u), val in d.items():
            if u <= vintage:
                view[i][(y, u)] = Iv(float(val), float(val), float(val))
    for y in store.years(ind):
        vs = sorted((u, val) for (yy, u), val in store.series[ind].items()
                    if yy == y and u <= vintage)
        if not vs:
            continue                      # nothing published about this year yet
        p = float(vs[-1][1])
        if q == float("inf"):
            view[ind][(y, vintage)] = Iv(float("-inf"), float("inf"), p)
        else:
            view[ind][(y, vintage)] = Iv(p - q, p + q, p)
    return view


def run(store: VintageStore, clauses: Sequence[dict],
        alphas: Sequence[float] = (0.05, 0.1, 0.2, 0.3, 0.5)) -> List[Curve]:
    inds = sorted({_primary(c) for c in clauses})
    vintages = sorted({v for d in store.series.values() for (_, v) in d})
    out: List[Curve] = []
    for alpha in alphas:
        cal: Calibration = calibrate_conservative(store, inds, max(alpha, 1e-9))
        q = cal.q
        # leave-one-out coverage at this level (recomputed, not assumed)
        from .conformal import loo_coverage
        cov = loo_coverage(store, inds, max(alpha, 1e-9))
        cells = decided = unsup = rev = irr = 0
        for cl in clauses:
            ind = _primary(cl)
            for v in vintages:
                band = _band_view(store, ind, q, v)
                for y in store.years(ind):
                    try:
                        a = eval_clause(cl, band, y, v)   # banded evaluator
                    except (KeyError, ZeroDivisionError):
                        continue
                    # point answer under the same banded evaluator, width 0
                    try:
                        p = eval_clause(cl, _band_view(store, ind, 0.0, v), y, v)
                    except (KeyError, ZeroDivisionError):
                        continue
                    cells += 1
                    if p in (T, F):
                        decided += 1
                    if p in (T, F) and a == U:
                        unsup += 1
                    if p in (T, F) and a in (T, F) and a != p:
                        rev += 1
                    if a == U and q == float("inf"):
                        irr += 1
        out.append(Curve(alpha, q, cal.n_scores, cov["coverage"], cells, decided,
                         unsup, rev, irr))
    return out


def widest_irreducible(store: VintageStore, clauses: Sequence[dict],
                       alpha: float | None = None) -> List[dict]:
    """Clauses still undetermined under the widest band the data can justify.

    The band is calibrated PER INDICATOR, not pooled.  Pooling a debt-to-GDP
    revision (which moves 10+ points between vintages) into a reserves-cover
    band would swamp the second indicator and turn this table into an artefact
    of the widest series in the file -- which is exactly the mistake that makes
    a headline number worthless.  Per indicator, the band is the widest
    revision that series has ever shown; if a clause is undetermined even
    then, the disagreement is inside the data, not inside the method.
    """
    from .conformal import revision_deltas
    vintages = sorted({v for d in store.series.values() for (_, v) in d})
    rows = []
    for cl in clauses:
        ind = _primary(cl)
        sc = revision_deltas(store, ind)
        q = max(sc) if sc else 0.0
        n_u = n = 0
        for v in vintages:
            band = _band_view(store, ind, q, v)
            for y in store.years(ind):
                try:
                    a = eval_clause(cl, band, y, v)
                except (KeyError, ZeroDivisionError):
                    continue
                n += 1
                if a == U:
                    n_u += 1
        rows.append({"clause": cl.get("id"), "indicator": ind,
                     "widest_revision": round(q, 2),
                     "undetermined": n_u, "cells": n})
    return rows
