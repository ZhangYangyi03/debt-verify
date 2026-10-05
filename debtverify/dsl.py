"""Clause DSL with interval (three-valued) semantics.

A sovereign debt restructuring clause is, operationally, a guarded state
transition whose guard is a comparison against an economic indicator.
The indicator is never known as a point: it is known as a *vintage series*,
and different vintages disagree.  So the guard is evaluated over an interval.

Semantics is Kleene's strong three-valued logic K3 over the value set
{T, F, U} (true / false / undetermined).  U is a first-class output, not an
error: "the published data does not decide this clause" is the honest answer
and it is the answer a negotiating table actually needs.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Iterable

T, F, U = "T", "F", "U"


def k_not(a):
    return {T: F, F: T, U: U}[a]


def k_and(*xs):
    if any(x == F for x in xs):
        return F
    return U if any(x == U for x in xs) else T


def k_or(*xs):
    if any(x == T for x in xs):
        return T
    return U if any(x == U for x in xs) else F


@dataclass(frozen=True)
class Iv:
    """A closed interval of reals, plus the point estimate it came from."""
    lo: float
    hi: float
    point: float | None = None

    def __post_init__(self):
        if self.lo > self.hi:
            raise ValueError(f"empty interval {self.lo}>{self.hi}")

    def __add__(self, o):
        o = o if isinstance(o, Iv) else Iv(o, o, o)
        return Iv(self.lo + o.lo, self.hi + o.hi)

    def __sub__(self, o):
        o = o if isinstance(o, Iv) else Iv(o, o, o)
        return Iv(self.lo - o.hi, self.hi - o.lo)

    def __mul__(self, o):
        o = o if isinstance(o, Iv) else Iv(o, o, o)
        c = (self.lo * o.lo, self.lo * o.hi, self.hi * o.lo, self.hi * o.hi)
        return Iv(min(c), max(c))

    def __truediv__(self, o):
        o = o if isinstance(o, Iv) else Iv(o, o, o)
        if o.lo <= 0.0 <= o.hi:
            # division by an interval containing zero is not a real interval
            raise ZeroDivisionError("divisor interval straddles zero")
        c = (self.lo / o.lo, self.lo / o.hi, self.hi / o.lo, self.hi / o.hi)
        return Iv(min(c), max(c))

    def cut(self, thr: float, op: str) -> str:
        """Compare an interval against a threshold -> K3."""
        if op == "lt":
            if self.hi < thr:
                return T
            if self.lo >= thr:
                return F
            return U
        if op == "gt":
            if self.lo > thr:
                return T
            if self.hi <= thr:
                return F
            return U
        raise ValueError(op)


# ---------------------------------------------------------------- clause kinds
# threshold   : ind OP thr
# ratio       : ind_a / ind_b OP thr
# delta       : (ind[t] - ind[t-k]) / ind[t-k] OP thr
# window      : base predicate evaluated over n of m consecutive periods
# nested      : IF antecedent THEN the target clause's threshold is overridden

def _get(series, ind, year, vintage):
    """Fetch one cell.  A cell may be a float (point vintage) or an Iv (band)."""
    try:
        v = series[ind][(year, vintage)]
    except KeyError:
        # a band view keys every reference year under the same vintage label
        cand = [val for (y, vv), val in series[ind].items() if y == year]
        if not cand:
            raise KeyError(f"no observation {ind!r} at year={year} vintage={vintage!r}")
        v = cand[-1]
    return v if isinstance(v, Iv) else Iv(float(v), float(v), float(v))


def eval_ratio(clause, series, year, vintage, thr_override=None):
    a = _get(series, clause["numerator"], year, vintage)
    b = _get(series, clause["denominator"], year, vintage)
    thr = clause["threshold"] if thr_override is None else thr_override
    try:
        return (a / b).cut(thr, clause["op"])
    except ZeroDivisionError:
        return U


def eval_delta(clause, series, year, vintage, thr_override=None):
    k = clause.get("lag", 1)
    now = _get(series, clause["indicator"], year, vintage)
    then = _get(series, clause["indicator"], year - k, vintage)
    thr = clause["threshold"] if thr_override is None else thr_override
    try:
        return ((now - then) / then).cut(thr, clause["op"])
    except ZeroDivisionError:
        return U


def eval_threshold(clause, series, year, vintage, thr_override=None):
    iv = _get(series, clause["indicator"], year, vintage)
    thr = clause["threshold"] if thr_override is None else thr_override
    return iv.cut(thr, clause["op"])


def _base_holds(clause, series, year, vintage, thr_override=None):
    kind = clause.get("kind", "threshold")
    if kind == "threshold":
        return eval_threshold(clause, series, year, vintage, thr_override)
    if kind == "ratio":
        return eval_ratio(clause, series, year, vintage, thr_override)
    if kind == "delta":
        return eval_delta(clause, series, year, vintage, thr_override)
    raise ValueError(f"{kind!r} is not a base predicate")


def eval_window(clause, series, year, vintage):
    """`n of m consecutive periods` over the base predicate.

    All-TRUE -> T, any-FALSE with the TRUE count already failing -> F,
    otherwise U.  This aggregation is exactly where interval data and
    point data give different answers.
    """
    n, m = clause["n"], clause["m"]
    years = [year - m + 1 + i for i in range(m)]
    # the window's period predicate is a threshold/ratio/delta over the same
    # indicator; the wrapper itself is not a base predicate, so build one.
    base = {k: v for k, v in clause.items() if k not in ("n", "m", "kind")}
    base["kind"] = clause.get("base_kind", "threshold")
    try:
        st = [_base_holds(base, series, y, vintage, clause.get("threshold"))
              for y in years]
    except KeyError:
        return U
    t = st.count(T)
    f = st.count(F)
    if t >= n:
        return T
    if len(st) - f < n:
        return F
    return U


def eval_clause(clause, series, year, vintage, threshold_override=None):
    kind = clause.get("kind", "threshold")
    if kind == "window":
        return eval_window(clause, series, year, vintage)
    if kind == "nested":
        ant = clause["antecedent"]
        a = eval_clause(ant, series, year, vintage)
        base = clause["base_threshold"]
        over = clause["override_threshold"]
        if a == T:
            return eval_clause(clause["target"], series, year, vintage, over)
        if a == F:
            return eval_clause(clause["target"], series, year, vintage, base)
        # antecedent undetermined: evaluate under both readings and degrade
        r1 = eval_clause(clause["target"], series, year, vintage, over)
        r2 = eval_clause(clause["target"], series, year, vintage, base)
        return r1 if r1 == r2 else U
    return _base_holds(clause, series, year, vintage, threshold_override)
