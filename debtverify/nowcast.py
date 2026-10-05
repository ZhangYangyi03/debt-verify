"""Trigger lead time: from "is the clause violated" to "how long have we got".

A verifier that only says whether a clause holds today is of limited use at a
negotiating table.  What both sides need is the forward view: given the
high-frequency indicators already published, what is the probability the
clause fires within h quarters, and how wide is that estimate.

Method, kept deliberately transparent because the point of this module is not
to beat the IMF's own forecasting:

  1. BRIDGE.  Extract the leading factors from monthly proxies (tax revenue,
     reserve cover, copper price, exchange rate, sovereign spread) by PCA;
     regress the annual target indicator on those factors by OLS.  This is a
     bridge equation, the standard nowcasting device.
  2. RESIDUAL BOOTSTRAP.  Resample the bridge residuals to form a predictive
     distribution of the target.  No distributional assumption beyond the
     residual sample being representative of what has not happened yet.
  3. PUSH THROUGH THE CLAUSE.  Evaluate the clause against every bootstrap
     draw and report the fraction that fires.  The result is a probability of
     triggering, not a point forecast, which is the only form in which the
     answer is honest given the revision widths measured in conformal.py.

The convolution with the conformal band from conformal.py is the part that
matters: the band says how wrong a *published* number may be, the bootstrap
says how wrong a *not-yet-published* number may be.  A clause decision is
exposed to both, and reporting them separately is the difference between a
forecast and a verification.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple
import math
import random


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


@dataclass
class BridgeFit:
    scores: List[List[float]]        # k_factors x T  (the factor time series)
    coef: List[float]                # k_factors -> target
    intercept: float
    resid: List[float]
    loadings: List[List[float]] = None   # k_factors x n_proxies

    @property
    def resid_std(self) -> float:
        return _std(self.resid)


def _standardise(cols: List[List[float]]):
    mus, sds = [], []
    out = []
    for c in cols:
        m, s = _mean(c), _std(c) or 1.0
        mus.append(m)
        sds.append(s)
        out.append([(v - m) / s for v in c])
    return out, mus, sds


def _pca_factors(cols: List[List[float]], k: int) -> Tuple[List[List[float]],
                                                          List[List[float]]]:
    """Power-iteration PCA.  Returns (scores, loadings).

    Dimensions matter here and were got wrong once:
      X is (n_proxies x T).  Power iteration runs on the proxy-domain
      covariance X X^T, so the eigenvector u has length n_proxies; the score
      (the time series a forecaster actually uses) is f = X^T u, length T.
      Deflation subtracts u f^T from X.

    No numpy on purpose: the whole stack is standard library plus z3, so a
    fresh clone runs on any machine with Python and no wheels.
    """
    X = [row[:] for row in cols]
    nprox = len(X)
    T = len(X[0]) if nprox else 0
    scores: List[List[float]] = []
    loadings: List[List[float]] = []
    for _ in range(k):
        # power iteration on C = X X^T  (nprox x nprox)
        u = [random.random() - 0.5 for _ in range(nprox)]
        for _ in range(200):
            Xu = [sum(X[p][t] * u[p] for p in range(nprox)) for t in range(T)]
            Cu = [sum(X[p][t] * Xu[t] for t in range(T)) for p in range(nprox)]
            nrm = math.sqrt(sum(x * x for x in Cu)) or 1.0
            u = [x / nrm for x in Cu]
        f = [sum(X[p][t] * u[p] for p in range(nprox)) for t in range(T)]
        # orient deterministically: largest-magnitude loading positive
        j = max(range(nprox), key=lambda i: abs(u[i]))
        if u[j] < 0:
            u = [-x for x in u]
            f = [-x for x in f]
        loadings.append(u)
        scores.append(f)
        for p in range(nprox):
            X[p] = [X[p][t] - u[p] * f[t] for t in range(T)]
    return scores, loadings


def fit_bridge(proxies: Dict[str, Sequence[float]], target: Sequence[float],
               k: int = 2) -> BridgeFit:
    names = sorted(proxies)
    cols, _, _ = _standardise([list(proxies[n]) for n in names])
    F, loadings = _pca_factors(cols, k)
    T = len(target)
    # OLS of target on the factors, with intercept, solved by normal equations
    rows = [[1.0] + [F[j][t] for j in range(k)] for t in range(T)]
    p = k + 1
    A = [[sum(rows[t][i] * rows[t][j] for t in range(T)) for j in range(p)]
         for i in range(p)]
    b = [sum(rows[t][i] * target[t] for t in range(T)) for i in range(p)]
    # gaussian elimination
    for i in range(p):
        piv = max(range(i, p), key=lambda r: abs(A[r][i]))
        A[i], A[piv] = A[piv], A[i]
        b[i], b[piv] = b[piv], b[i]
        if abs(A[i][i]) < 1e-12:
            continue
        for r in range(p):
            if r == i:
                continue
            f = A[r][i] / A[i][i]
            for c in range(i, p):
                A[r][c] -= f * A[i][c]
            b[r] -= f * b[i]
    coef = [(b[i] / A[i][i]) if abs(A[i][i]) > 1e-12 else 0.0 for i in range(p)]
    intercept, coef = coef[0], coef[1:]
    pred = [intercept + sum(coef[j] * F[j][t] for j in range(k))
            for t in range(T)]
    resid = [target[t] - pred[t] for t in range(T)]
    return BridgeFit(F, coef, intercept, resid, loadings)


def trigger_probability(point: float, band_half_width: float, fit: BridgeFit,
                        op: str, threshold: float, n_draws: int = 2000,
                        seed: int = 0) -> float:
    """P(clause fires), folding together publication revision and forecast error.

    Two independent sources of error, both sampled:
      * the forecast error of the not-yet-published value (bridge residual),
      * the publication revision of a value that is published (conformal band).
    """
    rng = random.Random(seed)
    sd = fit.resid_std
    hit = 0
    for _ in range(n_draws):
        v = point + rng.gauss(0.0, sd) + rng.uniform(-band_half_width,
                                                     band_half_width)
        fires = (v < threshold) if op == "lt" else (v > threshold)
        hit += 1 if fires else 0
    return hit / n_draws


def lead_time_quarters(fit: BridgeFit, point_now: float, drift_per_quarter: float,
                       op: str, threshold: float, band_half_width: float,
                       max_q: int = 12, p_star: float = 0.5,
                       n_draws: int = 800, seed: int = 0) -> Dict[str, object]:
    """First horizon at which P(trigger) crosses p_star, with the whole curve."""
    curve = []
    for q in range(1, max_q + 1):
        pt = point_now + drift_per_quarter * q
        p = trigger_probability(pt, band_half_width, fit, op, threshold,
                                n_draws, seed + q)
        curve.append({"quarters": q, "prob": round(p, 4)})
    cross = next((c["quarters"] for c in curve if c["prob"] >= p_star), None)
    return {"crossing_quarters": cross, "p_star": p_star, "curve": curve}
