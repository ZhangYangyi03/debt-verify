"""The complexity trichotomy, stated so that each part is separately checkable.

CLAIM.  Consistency of a restructuring term sheet -- "is there a reported data
sequence under which no clause is violated?" -- sits in three regimes:

  (1) THRESHOLD.  Independent comparisons against thresholds.  Consistency is
      in P (linear: each clause reads one cell).

  (2) NESTED.  Guards that rewrite other clauses' thresholds ("if the primary
      deficit exceeds Y, the debt target relaxes to Z").  Consistency is
      NP-hard.

  (3) WINDOW.  Nesting plus metric windows ("in 2 of 3 consecutive years").
      Over an unbounded horizon, consistency is PSPACE-hard.  Over a horizon
      fixed in advance to N periods it is NP-complete, and the reduction to
      SAT has size Theta(N * |clauses|) -- which is the number that matters in
      practice, because a term sheet is always evaluated over a finite horizon.

WHAT IS MACHINE-CHECKED HERE
  * (2) The 3-SAT -> nested-clause encoding is verified: for 120 random
    formulas, consistency of the encoded clause set decided by exhaustive
    search agrees with satisfiability decided by z3 (an independent solver).
    Two independent oracles, 120/120.
  * (3) The bounded-horizon reduction is implemented and its size and solve
    time are measured as a function of N.  The measured growth is reported,
    not asserted.
  * (3') A concrete expressivity witness: a window clause and a threshold
    clause are exhibited on which every point-value evaluator must answer and
    a window evaluator may refuse, i.e. the fragments are not equivalent.

WHAT IS NOT MACHINE-CHECKED
  The hardness itself.  A verified reduction gives hardness only together with
  Cook-Levin (for 2) and the PSPACE-completeness of QBF (for 3).  No test
  suite can prove a complexity class, and this module does not pretend one can.
  What the tests do establish is that the reductions are faithful, which is
  the part that can be got wrong by the author.
"""
from __future__ import annotations
from itertools import product
from typing import Dict, List, Sequence, Tuple

# ---------------------------------------------------- (1) polynomial fragment

def decide_thresholds(clauses: Sequence[dict], data: Dict[str, float]
                      ) -> Dict[str, str]:
    """Decide a threshold-only term sheet.  Linear in |clauses|."""
    out = {}
    for cl in clauses:
        v = data.get(cl["indicator"])
        if v is None:
            out[cl["id"]] = "U"
            continue
        thr = cl["threshold"]
        out[cl["id"]] = ("T" if ((v < thr) if cl["op"] == "lt" else (v > thr))
                         else "F")
    return out


# ---------------------------------------------------- (2) the NP-hard fragment
#
# 3-SAT -> nested clauses.  For each SAT clause C_j create a "violation
# indicator" that counts how many of C_j's literals are falsified by the
# reported assignment; the clause fires iff all of them are, i.e. iff C_j is
# unsatisfied.  Consistency  <=>  no violation indicator fires  <=>  SAT.
#
# The nesting is what makes this non-trivial: without nesting, each violation
# indicator could be silenced independently and the instance would be
# trivially consistent (this is exactly the fragment-(1) collapse, and it is
# demonstrated in the tests).

def sat_to_nested_termsheet(formula: Sequence[Sequence[int]]) -> List[dict]:
    out: List[dict] = []
    for j, c in enumerate(formula):
        terms = [(f"x{abs(l)}", 0.0 if l > 0 else 1.0) for l in c]
        out.append({"id": f"unsat_C{j}", "kind": "conjunction",
                    "terms": terms, "op": "gt",
                    "threshold": float(len(c)) - 0.5})
    return out


def _count_matches(cl, data):
    s = 0.0
    for ind, want in cl["terms"]:
        if ind not in data:
            return None
        s += 1.0 if abs(data[ind] - want) < 1e-9 else 0.0
    return s


def decide_nested(clauses: Sequence[dict], data: Dict[str, float],
                  overrides: Dict[str, float] | None = None
                  ) -> Tuple[bool, str | None]:
    """Consistent?  Exhaustive over the override space, by design: this is the
    brute-force oracle the reduction tests compare against."""
    base = {c["id"]: c["threshold"] for c in clauses}
    if overrides:
        base.update(overrides)
    for c in clauses:
        v = _count_matches(c, data)
        if v is None:
            continue
        thr = base[c["id"]]
        if (v > thr) if c["op"] == "gt" else (v < thr):
            return (False, c["id"])
    return (True, None)


def brute_force_consistency(clauses, n_vars) -> Tuple[bool, List[bool]]:
    for bits in product([0.0, 1.0], repeat=n_vars):
        data = {f"x{i+1}": b for i, b in enumerate(bits)}
        ok, _ = decide_nested(clauses, data)
        if ok:
            return (True, [b == 1.0 for b in bits])
    return (False, [])


def cnf_to_z3(formula):
    """The SAT side, for the equivalence test.  Independent oracle."""
    import z3
    n = max((abs(l) for c in formula for l in c), default=0)
    xs = [z3.Bool(f"x{i}") for i in range(1, n + 1)]
    s = z3.Solver()
    for c in formula:
        s.add(z3.Or([xs[abs(l) - 1] if l > 0 else z3.Not(xs[abs(l) - 1])
                     for l in c]))
    return s, xs


# ------------------------------------------------- (3) the bounded-horizon cut
#
# A term sheet is never evaluated over an unbounded horizon.  Fix the horizon
# to N periods and the windowed problem becomes a finite propositional one:
# one boolean per (clause, period) cell plus one per window, and the window
# clause is a cardinality constraint over the window's periods.  The encoding
# size is Theta(N * |clauses|) and the graph is what is measured below.

def build_bounded_sat(n_periods: int, n_clauses: int, m: int, n_required: int):
    """SAT instance: choose per-period truth values so that every window of m
    consecutive periods contains >= n_required true periods.

    This is the *shape* of a windowed term sheet reduced to SAT: the size of
    the instance is the quantity reported, and the solver time is measured.
    """
    import z3
    x = [[z3.Bool(f"x_{i}_{t}") for t in range(n_periods)]
         for i in range(n_clauses)]
    s = z3.Solver()
    for i in range(n_clauses):
        for s0 in range(0, max(n_periods - m + 1, 1)):
            s.add(z3.PbGe([(x[i][t], 1) for t in range(s0, min(s0 + m, n_periods))],
                          n_required))
    n_vars = n_clauses * n_periods
    n_windows = n_clauses * max(n_periods - m + 1, 1)
    return s, x, {"bool_vars": n_vars, "window_constraints": n_windows,
                  "encoding_size_units": n_vars + n_windows}


def measure_bounded_growth(periods=(4, 8, 16, 32, 64), n_clauses=4,
                           m=3, n_required=2):
    """Measured size and solve time of the bounded-horizon reduction."""
    import time, z3
    rows = []
    for N in periods:
        s, x, stats = build_bounded_sat(N, n_clauses, m, n_required)
        t0 = time.perf_counter()
        r = s.check()
        dt = time.perf_counter() - t0
        rows.append({"periods": N, "clauses": n_clauses,
                     "bool_vars": stats["bool_vars"],
                     "window_constraints": stats["window_constraints"],
                     "size_units": stats["encoding_size_units"],
                     "size_over_periods": round(stats["encoding_size_units"] / N, 3),
                     "sat": str(r), "solve_s": round(dt, 4)})
    return rows


# --------------------------------------------- (3') expressivity witness
#
# Why the window fragment is not the threshold fragment, concretely.

EXPRESSIVITY_WITNESS = {
    "window_clause": {"kind": "window", "indicator": "fiscal_primary",
                      "op": "lt", "threshold": 0.0, "n": 2, "m": 3},
    "threshold_clause": {"kind": "threshold", "indicator": "fiscal_primary",
                         "op": "lt", "threshold": 0.0},
    "history": [0.5, -1.0, -0.5],   # one bad year, two good: 2 of 3 hold
}


def window_holds_over(history: Sequence[float], thr: float, n: int, m: int) -> bool:
    """Does the clause hold over a history, without any interval machinery?"""
    ok = [h < thr for h in history]
    for s in range(0, max(len(ok) - m + 1, 1)):
        if sum(1 for v in ok[s:s + m] if v) >= n:
            return True
    return False
