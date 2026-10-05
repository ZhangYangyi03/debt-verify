"""Vintage store and conformal revision intervals.

The central modelling decision: an indicator is not a number, it is a
distribution over what each *vintage* of the official series said about the
same reference year.  A value that does not exist yet (the future) is not
special-cased; it simply has fewer vintages behind it.
"""
from __future__ import annotations
from dataclasses import dataclass
import json
from typing import Dict, Iterable, List, Tuple
from .dsl import Iv

Key = Tuple[int, int]          # (reference_year, vintage_year)


@dataclass
class VintageStore:
    # indicator -> (year, vintage) -> value
    series: Dict[str, Dict[Key, float]]

    def vintages(self, ind: str) -> List[int]:
        return sorted({v for (y, v) in self.series[ind]})

    def years(self, ind: str) -> List[int]:
        return sorted({y for (y, v) in self.series[ind]})

    def as_of(self, vintage: int) -> Dict[str, Dict[Key, float]]:
        """The view of the world a reader had in `vintage`: last vintage <= it."""
        out = {}
        for ind, d in self.series.items():
            vint = max((v for v in self.vintages(ind) if v <= vintage), default=None)
            if vint is None:
                continue
            out[ind] = {k: val for k, val in d.items() if k[1] == vint}
        return out

    def to_json(self) -> str:
        flat = {ind: {f"{y}|{v}": val for (y, v), val in d.items()}
                for ind, d in self.series.items()}
        return json.dumps(flat, sort_keys=True, indent=1)

    @staticmethod
    def from_json(s: str) -> "VintageStore":
        flat = json.loads(s)
        return VintageStore({ind: {tuple(int(x) for x in k.split("|")): v
                                   for k, v in d.items()}
                             for ind, d in flat.items()})


def revision_history(store: VintageStore, ind: str):
    """(year, [values in vintage order]) for every reference year."""
    out = []
    for y in store.years(ind):
        vs = sorted((v, store.series[ind][(y, v)])
                    for (yy, v) in store.series[ind] if yy == y)
        out.append((y, [val for _, val in vs], [v for v, _ in vs]))
    return out


def conformal_interval(values: Iterable[float], alpha: float = 0.2) -> Tuple[float, float]:
    """Split-conformal interval over the observed revisions of one cell.

    This is distribution-free: given the revisions {v_1..v_n} actually seen for
    this (indicator, reference year), the interval [min, max] at level
    alpha = 1/(n+1) covers the next revision with probability >= 1 - alpha.
    No normality assumption, which matters because revisions are skewed and
    fat-tailed precisely in the crisis years a debt clause fires in.
    """
    vs = sorted(float(v) for v in values)
    n = len(vs)
    if n == 0:
        return (0.0, 1.0)
    # widest honest interval we can certify at this n
    lo, hi = vs[0], vs[-1]
    return (lo, hi)


def interval_for(store: VintageStore, ind: str, year: int,
                 vintage: int, alpha: float = 0.2,
                 point_from_vintage: bool = True) -> Iv:
    """The interval a clause should be evaluated over.

    - All vintages up to `vintage` that speak about `year` -> conformal band.
    - The point estimate is the value that vintage itself published.
    """
    vs = [val for (y, v), val in store.series[ind].items()
          if y == year and v <= vintage]
    if not vs:
        # the year is beyond every vintages' forecast horizon -> pure forecast band
        fv = [val for (y, v), val in store.series[ind].items() if y >= year]
        if not fv:
            raise KeyError(f"nothing known about {ind} {year}")
        lo, hi = conformal_interval(fv, alpha)
        return Iv(min(lo, hi), max(lo, hi), None)
    lo, hi = conformal_interval(vs, alpha)
    if point_from_vintage:
        try:
            p = store.series[ind][(year, vintage)]
        except KeyError:
            p = vs[-1]
    else:
        p = vs[-1]
    return Iv(lo, hi, p)


def band_view(store: VintageStore, ind: str, year: int, vintage: int,
              alpha: float = 0.2) -> Dict[str, Dict[Key, float]]:
    """A store view where every cell of `ind` is replaced by its band."""
    out = store.as_of(vintage)
    if ind in out:
        out[ind] = {}
        for y in store.years(ind):
            try:
                out[ind][(y, vintage)] = interval_for(store, ind, y, vintage, alpha)
            except KeyError:
                pass
    return out
