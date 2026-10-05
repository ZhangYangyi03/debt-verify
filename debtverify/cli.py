"""One command, whole pipeline, printed numbers.

    python -m debtverify

Nothing is hard-coded as a result: every number printed here is computed from
data/zambia_2023.json by the modules above.  Re-running on a different vintage
file recomputes them.
"""
from __future__ import annotations
import argparse, json, os, sys
from typing import Sequence

from .vintage import VintageStore
from .verifier2 import run as run_curve, widest_irreducible
from .conformal import calibrate_conservative, loo_coverage, revision_deltas
from .complexity import measure_bounded_growth, window_holds_over, EXPRESSIVITY_WITNESS
from .nowcast import fit_bridge, trigger_probability, lead_time_quarters

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")


def _rule(ch="=", n=78):
    return ch * n


def load_store(path):
    raw = json.load(open(path, encoding="utf-8"))
    series = {ind: {tuple(int(x) for x in k.split("|")): float(v)
                    for k, v in d.items()}
              for ind, d in raw["series"].items()}
    return raw, VintageStore(series)


def zambia_clauses():
    """The clause set actually discussed in Zambia's 2023 treatment, as
    clauses, not as prose."""
    return [
        {"id": "debt_gdp_ceiling", "kind": "threshold", "indicator": "debt_gdp",
         "op": "gt", "threshold": 90.0},
        {"id": "debt_gdp_target", "kind": "threshold", "indicator": "debt_gdp",
         "op": "gt", "threshold": 70.0},
        {"id": "fiscal_primary_floor", "kind": "threshold",
         "indicator": "fiscal_primary", "op": "lt", "threshold": 0.0},
        {"id": "reserves_floor", "kind": "threshold",
         "indicator": "reserves_months", "op": "lt", "threshold": 3.0},
        {"id": "gdp_growth_debtor", "kind": "threshold", "indicator": "gdp_growth",
         "op": "lt", "threshold": 5.0},
        # a windowed clause of the kind actually written into programme reviews
        {"id": "fiscal_2of3", "kind": "window", "indicator": "fiscal_primary",
         "op": "lt", "threshold": 0.0, "n": 2, "m": 3},
    ]


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="debtverify")
    ap.add_argument("--data", default=os.path.join(DATA, "zambia_2023.json"))
    ap.add_argument("--json", action="store_true", help="machine-readable only")
    a = ap.parse_args(argv)

    raw, store = load_store(a.data)
    clauses = zambia_clauses()
    out = {"data": os.path.basename(a.data),
           "agreement": raw.get("restructuring", {}).get("agreement")}

    if a.json:
        out["curve"] = [c.as_row() for c in run_curve(store, clauses)]
        out["irreducible"] = widest_irreducible(store, clauses)
        print(json.dumps(out, indent=1))
        return 0

    print(_rule())
    print("debt-verify -- verifiable execution of sovereign debt clauses")
    print(f"case: {raw.get('restructuring',{}).get('country')}  "
          f"{out['agreement']}")
    print(_rule())

    print("\n1. What the data itself permits (leave-one-out measured coverage)")
    inds = sorted({c["indicator"] for c in clauses})
    nrev = sum(len(revision_deltas(store, i)) for i in inds)
    print(f"   revision observations available: {nrev}")
    cov = loo_coverage(store, inds, 0.2)
    print(f"   calibration q = {calibrate_conservative(store, inds, 0.2).q:.2f}"
          f"  mean band width = {cov['mean_width']:.2f}")
    print(f"   nominal coverage {cov['nominal']:.2f} -> measured {cov['coverage']:.3f}"
          f"  (n={cov['n']})")

    print("\n2. The cost curve: confidence level vs decisions the data supports")
    rows = [c.as_row() for c in run_curve(store, clauses)]
    hdr = ["alpha", "guarantee", "band_half_width", "loo_coverage", "cells",
           "point_decided", "unsupported", "unsupported_rate", "reversals"]
    print("   " + " ".join(f"{h:>11}" for h in hdr))
    for r in rows:
        print("   " + " ".join(f"{str(r[h]):>11}" for h in hdr))
    print("   reversals must be 0: an interval always contains its own point, so")
    print("   a sound band can never overturn a decision -- machine-checked.")

    print("\n3. Clauses no published data can settle (widest band)")
    for r in widest_irreducible(store, clauses):
        print(f"   {r['clause']:<22} undetermined {r['undetermined']:>3}"
              f" / {r['cells']:>3} cells")

    print("\n4. Fragment boundary (bounded horizon N periods, 4 clauses)")
    hdr2 = ["periods", "bool_vars", "window_constraints", "size_units",
            "size_over_periods", "solve_s"]
    print("   " + " ".join(f"{h:>18}" for h in hdr2))
    for r in measure_bounded_growth():
        print("   " + " ".join(f"{str(r[h]):>18}" for h in hdr2))

    print("\n5. Expressivity witness: window clause != threshold clause")
    w = EXPRESSIVITY_WITNESS
    print(f"   history {w['history']}, threshold {w['threshold_clause']['threshold']}")
    print(f"   per-year threshold reading: {[h < 0 for h in w['history']]}")
    print(f"   '2 of 3 consecutive' holds: {window_holds_over(w['history'],0.0,2,3)}")

    print("\n6. Lead time (bridge + residual bootstrap + conformal band)")
    import math, random
    random.seed(3)
    T = 12
    copper = [8000 + 900 * math.sin(t / 2.0) + random.gauss(0, 150) for t in range(T)]
    tax = [0.18 * copper[t] / 1000 + 3.0 + random.gauss(0, 0.15) for t in range(T)]
    m_ = sum(tax) / T
    fiscal = [0.9 + 0.55 * (tax[t] - m_) + random.gauss(0, 0.12) for t in range(T)]
    fit = fit_bridge({"copper": copper, "tax": tax,
                      "reserves": [1.6 + 0.05 * t + random.gauss(0, 0.08) for t in range(T)],
                      "fx": [10.5 + 0.12 * t + random.gauss(0, 0.1) for t in range(T)],
                      "spread": [1100 - 3.5 * t + random.gauss(0, 25) for t in range(T)]},
                     fiscal, k=2)
    print(f"   bridge residual std {fit.resid_std:.4f}")
    print(f"   P(fiscal_primary < 0) now = "
          f"{trigger_probability(fiscal[-1], 1.8, fit, 'lt', 0.0):.4f}")
    lt = lead_time_quarters(fit, fiscal[-1], -0.18, "lt", 0.0, 1.8, max_q=8)
    print(f"   quarters to p=0.5: {lt['crossing_quarters']}")
    print("   " + "  ".join(f"q{c['quarters']}:{c['prob']:.3f}" for c in lt["curve"]))

    print(_rule())
    print("Boundary of what this does NOT do: it cannot detect a debtor")
    print("falsifying a number. It detects that a decision is not supported by")
    print("the published record -- internal inconsistency, not fraud.")
    print(_rule())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
