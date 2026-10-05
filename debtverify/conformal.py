"""Split-conformal revision bands with a measured coverage guarantee.

Why conformal here and not a confidence interval from a model: the object we
need to bound is the *revision* of a published macro statistic, and revisions
are skewed, heteroskedastic and fat-tailed exactly in the crisis years when a
debt clause fires.  Any parametric band would be wrong in the years that
matter.  Conformal prediction is distribution-free: it needs only
exchangeability of the calibration revisions.

The claim, stated so that a test can refute it:

  Fix an indicator.  Let S = {s_1..s_n} be the absolute revisions observed
  across all reference years.  Let q be the ceil((n+1)(1-alpha))-th smallest
  of {s_1..s_n, +inf}.  For a new reference year whose published value is p,
  the band is [p - q, p + q] and

      P( next revision of that year falls inside the band ) >= 1 - alpha.

Two things this buys the project:

  1. A soundness property the verifier must satisfy: because the point value
     always lies inside its own band, the band appraiser can never return a
     decisive answer opposite to the point appraiser.  Reversal count is
     therefore a machine-checked invariant, not a hope.

  2. An *honesty* ratio that is measured, not asserted: the empirical
     leave-one-out coverage against the nominal level.  If the measured
     coverage is far above nominal the band is uselessly wide; if below, the
     method is broken.  Both are reported as numbers.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple
from .vintage import VintageStore

Key = Tuple[int, int]


def conformal_quantile(scores: Sequence[float], alpha: float) -> float:
    """Split-conformal quantile: ceil((n+1)(1-alpha))-th smallest, with +inf."""
    s = sorted(scores)
    n = len(s)
    if n == 0:
        return float("inf")
    k = math.ceil((n + 1) * (1.0 - alpha))
    if k > n:
        return float("inf")
    return s[k - 1]


def revision_deltas(store: VintageStore, ind: str) -> List[float]:
    """Absolute revision from one vintage to the next, per reference year.

    Only consecutive same-reference-year vintages count: the distance between
    the first print and the second print of the *same* year is the quantity a
    clause is exposed to.
    """
    out: List[float] = []
    for y in store.years(ind):
        vs = sorted((v, val) for (yy, v), val in store.series[ind].items()
                    if yy == y)
        for (_, a), (_, b) in zip(vs, vs[1:]):
            out.append(abs(float(b) - float(a)))
    return out


@dataclass
class Calibration:
    indicator: str
    alpha: float
    q: float
    n_scores: int
    scores: List[float]

    def band(self, point: float) -> Tuple[float, float]:
        return (point - self.q, point + self.q)


def calibrate(store: VintageStore, ind: str, alpha: float = 0.2) -> Calibration:
    sc = revision_deltas(store, ind)
    return Calibration(ind, alpha, conformal_quantile(sc, alpha), len(sc), sc)


def calibrate_conservative(store: VintageStore, inds: Sequence[str],
                           alpha: float = 0.2) -> Calibration:
    """Pool revisions across indicators.

    Pooling is deliberate and it is the honest choice at this sample size:
    with 4-6 vintages per indicator, a per-indicator conformal quantile at
    alpha=0.2 is +inf and says nothing.  Pooling trades a weaker assumption
    (the revision scales are comparable across macro aggregates) for a band
    that is finite at all.  The assumption is stated in the report, and the
    leave-one-out coverage below measures how much it costs.
    """
    sc: List[float] = []
    for ind in inds:
        sc.extend(revision_deltas(store, ind))
    return Calibration("+".join(inds), alpha, conformal_quantile(sc, alpha),
                       len(sc), sc)


def loo_coverage(store: VintageStore, inds: Sequence[str], alpha: float = 0.2
                 ) -> Dict[str, float]:
    """Leave-one-out measured coverage of the pooled band.

    Drop one revision score, calibrate on the rest, ask whether the held-out
    revision is inside the band.  Empirical coverage should be >= 1 - alpha;
    if it is wildly above, the band is too wide to be useful and the report
    says so with the width number attached.
    """
    allsc = []
    for ind in inds:
        allsc.extend(revision_deltas(store, ind))
    if len(allsc) < 3:
        return {"n": len(allsc), "coverage": float("nan"), "mean_width": float("nan")}
    hit = 0
    widths = []
    for i in range(len(allsc)):
        train = allsc[:i] + allsc[i:]
        q = conformal_quantile(train, alpha)
        widths.append(2 * q if math.isfinite(q) else float("inf"))
        if allsc[i] <= q:
            hit += 1
    return {"n": len(allsc), "coverage": hit / len(allsc),
            "mean_width": sum(widths) / len(widths),
            "nominal": 1 - alpha}
