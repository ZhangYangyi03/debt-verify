"""Tests.  Each one is written so it can fail for a specific reason.

Four claims, in the order the README makes them:

  conformal   the band is a distribution-free interval with measured coverage
  semantics   evaluation is monotone in band width, and an interval always
              contains its own point
  soundness   therefore the reversal count is identically zero
  reductions  the complexity encodings agree with an independent solver
"""
import json
import math
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from debtverify.dsl import Iv, T, F, U, k_and, k_or, k_not, eval_clause
from debtverify.vintage import VintageStore
from debtverify.conformal import (conformal_quantile, revision_deltas,
                                  loo_coverage)
from debtverify.verifier2 import run as run_curve, widest_irreducible, _band_view
from debtverify.complexity import (sat_to_nested_termsheet, brute_force_consistency,
                                   cnf_to_z3, measure_bounded_growth,
                                   window_holds_over, EXPRESSIVITY_WITNESS,
                                   decide_thresholds)
from debtverify.concurrent_guard import assert_single_writer, release
from debtverify.provenance import manifest, verify_manifest, tamper
from debtverify.nowcast import fit_bridge, trigger_probability, lead_time_quarters
from debtverify.cli import zambia_clauses

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "debtverify", "data", "zambia_2023.json")


def load():
    raw = json.load(open(DATA, encoding="utf-8"))
    series = {ind: {tuple(int(x) for x in k.split("|")): float(v)
                    for k, v in d.items()}
              for ind, d in raw["series"].items()}
    return raw, VintageStore(series)


def toy():
    s = VintageStore({"g": {}, "d": {}})
    for y, vals in {2020: [3.0, 3.2, 3.1], 2021: [-1.0, -0.4, -0.2]}.items():
        for i, v in enumerate(vals):
            s.series["g"][(y, 2020 + i)] = v
    for y, vals in {2020: [80.0, 85.0, 83.0], 2021: [95.0, 101.0, 99.0]}.items():
        for i, v in enumerate(vals):
            s.series["d"][(y, 2020 + i)] = v
    return s


# --------------------------------------------------------------- conformal

def test_conformal_quantile_is_the_ceil_index():
    assert conformal_quantile([0.1, 0.5, 0.9, 2.0], 0.2) == 2.0


def test_conformal_quantile_is_infinite_when_too_few_scores():
    assert conformal_quantile([0.1, 0.2], 0.1) == float("inf")


def test_quantile_is_monotone_in_alpha():
    s = [0.1, 0.3, 0.6, 1.2, 2.4, 5.0]
    qs = [conformal_quantile(s, a) for a in (0.05, 0.1, 0.2, 0.3, 0.5)]
    assert all(a >= b for a, b in zip(qs, qs[1:]))


def test_measured_coverage_meets_nominal_on_toy():
    store = toy()
    for a in (0.2, 0.3):
        c = loo_coverage(store, ["g", "d"], a)
        assert c["coverage"] >= c["nominal"] - 1e-9, (a, c)


def test_revision_deltas_only_compare_same_reference_year():
    d = revision_deltas(toy(), "g")
    assert all(x >= 0 for x in d)
    assert len(d) == 4


def test_measured_coverage_on_the_real_case_is_reported_not_assumed():
    _, store = load()
    inds = sorted({c["indicator"] for c in zambia_clauses()})
    c = loo_coverage(store, inds, 0.2)
    assert c["n"] >= 30
    assert c["coverage"] >= c["nominal"] - 1e-9, c


# --------------------------------------------------------------- semantics

def test_k3_truth_tables():
    assert k_and(T, T) == T and k_and(T, U) == U and k_and(F, U) == F
    assert k_or(F, F) == F and k_or(F, U) == U and k_or(T, U) == T
    assert k_not(U) == U


def test_interval_comparison_is_kleene_faithful():
    assert Iv(1.0, 2.0).cut(3.0, "lt") == T
    assert Iv(4.0, 5.0).cut(3.0, "lt") == F
    assert Iv(2.0, 4.0).cut(3.0, "lt") == U


def test_interval_multiplication_contains_every_endpoint_combination():
    r = Iv(-1.0, 2.0) * Iv(3.0, 5.0)
    for x in (-1.0, 2.0):
        for y in (3.0, 5.0):
            assert r.lo - 1e-9 <= x * y <= r.hi + 1e-9


def test_division_by_an_interval_straddling_zero_is_refused():
    with pytest.raises(ZeroDivisionError):
        Iv(1.0, 2.0) / Iv(-1.0, 1.0)


def test_undetermined_count_is_monotone_in_band_width():
    store = toy()
    cl = {"id": "c", "kind": "threshold", "indicator": "d",
          "op": "gt", "threshold": 90.0}
    prev = None
    for q in (5.0, 2.0, 1.0, 0.5, 0.0):
        n_u = 0
        for v in sorted({u for (_, u) in store.series["d"]}):
            band = _band_view(store, "d", q, v)
            for y in store.years("d"):
                try:
                    if eval_clause(cl, band, y, v) == U:
                        n_u += 1
                except KeyError:
                    pass
        if prev is not None:
            assert n_u <= prev, (q, n_u, prev)
        prev = n_u


def test_window_clause_is_not_a_threshold_clause():
    w = EXPRESSIVITY_WITNESS
    per_year = [h < w["threshold_clause"]["threshold"] for h in w["history"]]
    assert any(per_year) and not all(per_year)
    assert window_holds_over(w["history"], 0.0, 2, 3) is True
    assert window_holds_over([0.5, 0.5, 0.5], 0.0, 2, 3) is False


def test_window_clause_decides_on_a_real_vintage_series():
    _, store = load()
    cl = {"id": "w", "kind": "window", "indicator": "fiscal_primary",
          "op": "lt", "threshold": 0.0, "n": 2, "m": 3}
    from debtverify.verifier2 import _band_view
    got = None
    for v in sorted({u for (_, u) in store.series["fiscal_primary"]}):
        for y in store.years("fiscal_primary"):
            try:
                r = eval_clause(cl, _band_view(store, "fiscal_primary", 0.4, v), y, v)
            except (KeyError, ZeroDivisionError):
                continue
            got = r
            assert r in (T, F, U)
    assert got is not None


def test_nested_clause_uses_the_override_only_when_the_antecedent_holds():
    series = {"x": {(2020, 1): Iv(1.0, 1.0, 1.0),
                    (2021, 1): Iv(5.0, 5.0, 5.0)}}
    cl = {"kind": "nested",
          "antecedent": {"kind": "threshold", "indicator": "x", "op": "gt",
                         "threshold": 3.0},
          "base_threshold": 10.0, "override_threshold": 2.0,
          "target": {"kind": "threshold", "indicator": "x", "op": "gt"}}
    assert eval_clause(cl, series, 2021, 1) == T
    assert eval_clause(cl, series, 2020, 1) == F


def test_nested_clause_degrades_to_undetermined_when_the_antecedent_is_unknown():
    series = {"x": {(2020, 1): Iv(2.0, 4.0, 3.0)}}
    cl = {"kind": "nested",
          "antecedent": {"kind": "threshold", "indicator": "x", "op": "gt",
                         "threshold": 3.0},
          "base_threshold": 3.5, "override_threshold": 3.2,
          "target": {"kind": "threshold", "indicator": "x", "op": "gt"}}
    assert eval_clause(cl, series, 2020, 1) == U


# --------------------------------------------------------------- soundness

def test_reversals_are_identically_zero():
    _, store = load()
    for c in run_curve(store, zambia_clauses()):
        assert c.reversals == 0, c


def test_unsupported_count_is_non_increasing_as_the_band_widens():
    _, store = load()
    uns = [c.as_row()["unsupported"] for c in run_curve(store, zambia_clauses())]
    assert all(a >= b for a, b in zip(uns, uns[1:])), uns


def test_the_point_appraiser_hides_at_least_ten_percent_of_its_decisions():
    """The headline.  If this fails the project has no finding."""
    _, store = load()
    rows = [c.as_row() for c in run_curve(store, zambia_clauses())]
    r90 = next(r for r in rows if abs(r["alpha"] - 0.1) < 1e-9)
    assert r90["unsupported_rate"] >= 0.10, r90


def test_widest_band_uses_a_per_indicator_revision_not_a_pooled_one():
    _, store = load()
    by = {r["clause"]: r for r in widest_irreducible(store, zambia_clauses())}
    assert by["debt_gdp_ceiling"]["widest_revision"] == 12.8
    assert by["fiscal_primary_floor"]["widest_revision"] == 0.4


# --------------------------------------------------------------- reductions

def test_nested_reduction_agrees_with_an_independent_solver():
    import z3
    random.seed(1234)
    agree = 0
    for _ in range(60):
        n = random.randint(3, 5)
        m = random.randint(2, 5)
        f = []
        for _ in range(m):
            c = random.sample(range(1, n + 1), min(3, n))
            f.append([v if random.random() < 0.5 else -v for v in c])
        a, _ = brute_force_consistency(sat_to_nested_termsheet(f), n)
        b = (cnf_to_z3(f)[0].check() == z3.sat)
        agree += (a == b)
    assert agree == 60, agree


def test_known_satisfiable_instance_stays_satisfiable():
    tl = sat_to_nested_termsheet([[1, 2], [-1, 2], [1, -2]])
    assert brute_force_consistency(tl, 2)[0] is True


def test_known_unsatisfiable_instance_is_reported_unsatisfiable():
    tl = sat_to_nested_termsheet([[1], [-1]])
    assert brute_force_consistency(tl, 1)[0] is False


def test_bounded_horizon_encoding_grows_linearly_in_periods():
    rows = measure_bounded_growth(periods=(8, 16, 32), n_clauses=4)
    per = [r["size_over_periods"] for r in rows]
    assert all(p > 0 for p in per)
    assert abs(rows[-1]["size_over_periods"] - 7.75) < 0.01, rows[-1]


def test_threshold_fragment_decides_without_search():
    cls = [{"id": "a", "indicator": "x", "op": "lt", "threshold": 1.0},
           {"id": "b", "indicator": "x", "op": "gt", "threshold": 1.0}]
    assert decide_thresholds(cls, {"x": 0.5}) == {"a": "T", "b": "F"}


# --------------------------------------------------------------- nowcast

def test_bridge_recovers_a_known_linear_relation():
    random.seed(5)
    T = 24
    copper = [8000 + 900 * math.sin(t / 2.0) + random.gauss(0, 150) for t in range(T)]
    tax = [0.18 * copper[t] / 1000 + 3.0 + random.gauss(0, 0.05) for t in range(T)]
    m_ = sum(tax) / T
    fiscal = [0.9 + 0.55 * (tax[t] - m_) + random.gauss(0, 0.05) for t in range(T)]
    fit = fit_bridge({"copper": copper, "tax": tax}, fiscal, k=1)
    assert fit.resid_std < 0.15, fit.resid_std


def test_trigger_probability_is_monotone_in_distance_to_the_threshold():
    random.seed(6)
    x = [random.gauss(0, 1) for _ in range(20)]
    y = [0.8 * x[t] + random.gauss(0, 0.3) for t in range(20)]
    fit = fit_bridge({"x": x}, y, k=1)
    assert trigger_probability(10.0, 0.5, fit, "lt", 0.0) < \
           trigger_probability(-0.2, 0.5, fit, "lt", 0.0)


def test_lead_time_returns_a_monotone_curve_not_a_single_number():
    random.seed(7)
    x = [random.gauss(0, 1) for _ in range(20)]
    y = [0.8 * x[t] + random.gauss(0, 0.3) for t in range(20)]
    fit = fit_bridge({"x": x}, y, k=1)
    lt = lead_time_quarters(fit, 1.0, -0.2, "lt", 0.0, 0.5, max_q=6)
    assert len(lt["curve"]) == 6
    probs = [c["prob"] for c in lt["curve"]]
    assert all(a <= b + 1e-9 for a, b in zip(probs, probs[1:]))


# ------------------------------------------------------- guard and provenance

def test_single_writer_guard_refuses_a_second_concurrent_writer():
    assert_single_writer("test-case", "owner-A")
    try:
        with pytest.raises(RuntimeError):
            assert_single_writer("test-case", "owner-B")
        assert_single_writer("test-case", "owner-A")
    finally:
        release("test-case", "owner-A")


def test_manifest_detects_a_wrong_hash():
    m = manifest(DATA)
    assert verify_manifest(DATA, m) is True
    bad = dict(m)
    bad["sha256"] = "0" * 64
    assert verify_manifest(DATA, bad) is False


def test_tampering_with_one_number_is_detected():
    m = manifest(DATA)
    assert tamper(DATA, m) is False


def test_manifest_covers_the_code_not_only_the_data():
    m = manifest(DATA)
    assert "conformal.py" in m["code"] and "verifier2.py" in m["code"]
