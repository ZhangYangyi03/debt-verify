# debt-verify

Verifiable execution of sovereign debt restructuring clauses.

A restructuring term sheet is a set of conditional obligations: *if* the primary
deficit exceeds Y *then* the debt target relaxes to Z; *if* growth falls below X
in 2 of 3 consecutive years *then* interest is halved. Those conditions are
checked, today, against published macroeconomic statistics. This project asks
what happens when the check is done properly, and reports the answer as a
number.

## The finding, in one paragraph

Take Zambia's 2023 treatment and evaluate six clauses of the kind actually
written into it, at every (reference year, vintage) cell a reader could have
read. A point-value verifier -- what every existing workflow does -- returns a
decisive answer at all 84 cells it can evaluate. Requiring the same answer to
survive the published revision record (a distribution-free conformal band at
the 90% level, calibrated on the 37 observed revisions) leaves 63 of those 84
decisions unsupported by the data that was actually published: 75%. The
disagreement is not in the reporting and not in the method; it is inside the
data itself. At the widest band each series has ever shown, four clauses are
still undetermined on some cells -- those are the clauses no amount of
published data settles, and they are the ones a term sheet should stop writing.

## What is measured, and what is asserted

    claim                                  how it is established
    the band covers the next revision      leave-one-out: nominal 0.80 ->
                                           measured 0.838, n=37
    the band never overturns a decision    reversal count is identically 0
                                           across all 5 confidence levels,
                                           asserted in the test suite
    the cost curve is monotone             unsupported count is non-increasing
                                           in band width, asserted
    the encodings are faithful             120 random 3-SAT instances, encoded
                                           as nested clauses, decided by
                                           exhaustive search AND by z3: 120/120
    the bounded-horizon reduction          measured: Theta(N * clauses),
                                           ~7.75 size units per period at 4
                                           clauses

## What it does NOT do

It cannot detect a debtor falsifying a number. It detects that a *decision* is
not supported by the published record -- internal inconsistency between the
clauses, the vintages and the thresholds, not fraud. Nothing here reads data
the debtor did not publish. A framework that claimed otherwise would be
claiming a cryptographic property it does not have, which is why the
zero-knowledge variant was considered and dropped: proving a statistic that is
itself revised by more than the clause threshold proves nothing.

## Run it

    git clone <repo> && cd debt-verify
    python -m debtverify

One command. The only dependency is `z3-solver`, used to check the complexity
reductions; if it is absent the report still runs and says which section is out. Every number printed is
computed from `debtverify/data/zambia_2023.json`; edit one value and the manifest test
fails.

    python -m pytest tests -q      # 31 tests

## The complexity trichotomy

Consistency of a term sheet -- is there a reported data sequence under which no
clause is violated -- sits in three regimes:

    fragment                     consistency       what it means for drafting
    threshold only               P, linear         safe: each clause reads one
                                                   cell, no interaction
    + nested guards              NP-hard           ambiguity is born here: a
                                                   conflict has no local witness
    + metric windows             PSPACE-hard       "2 of 3 consecutive years"
                                 unbounded;         is not a statement about the
                                 NP-complete        reported vector but about a
                                 at fixed horizon N set of sequences consistent
                                                   with it

The drafting consequence: keep the term sheet in the first fragment unless the
economic logic genuinely needs the third, and if it does, fix the horizon,
because that is what turns an unbounded-horizon problem into a finite one with
an encoding of size Theta(N * clauses).

What the tests check is the *reductions*, not the hardness. A verified reduction
gives hardness only together with Cook-Levin and the PSPACE-completeness of QBF.
No test suite can prove a complexity class and this one does not claim to.

## Lead time

A verifier that only says whether a clause holds today is of limited use at a
table. `nowcast.py` adds the forward view: bridge equation on monthly proxies
(copper, tax, reserve cover, FX, spread) -> PCA factors -> OLS -> residual
bootstrap -> push every draw through the clause. Two independent error sources
are sampled together: the forecast error of a not-yet-published value, and the
publication revision of a published one. The output is a probability curve over
horizons, not a point forecast, because a point forecast at these revision
widths would be false precision.

## Layout

    debtverify/dsl.py             clause DSL, three-valued (Kleene K3) semantics
    debtverify/vintage.py         vintage store: an indicator is a distribution
                                  over what each vintage said, not a number
    debtverify/conformal.py       split-conformal revision bands, LOO coverage
    debtverify/verifier2.py       the two appraisers, the cost curve, the
                                  per-indicator irreducible table
    debtverify/complexity.py      the trichotomy and the machine-checked
                                  reductions
    debtverify/nowcast.py         bridge + bootstrap + trigger probability
    debtverify/concurrent_guard.py  one writer per case, enforced
    debtverify/provenance.py      SHA-256 over data AND code; tamper test

## Provenance of the data

`debtverify/data/zambia_2023.json` holds, for each (indicator, reference year, vintage
year), the value that vintage published. See `docs/DATA_SOURCES.md` for what
each vintage is and, stated plainly, what could not be obtained. The file is
data, not evidence: the point of the project is the method's behaviour under
revision, and the revision record is what it is.

## License

Apache-2.0.

## Related work by the same author

The same claim -- *a number is meaningless until it is shown to survive its own
verification* -- is made and measured in other domains:

| repo | the number it refuses to trust |
| ---- | ---- |
| [autoforge](https://github.com/ZhangYangyi03/autoforge) | a tool's fitness, until an oracle outside the tool agrees |
| [agentic-eda](https://github.com/ZhangYangyi03/agentic-eda) | a circuit's area, until equivalence to the reference netlist is proven |
| [debt-verify](https://github.com/ZhangYangyi03/debt-verify) | a debt clause decision, until it survives the published revision record |
| [tool-market](https://github.com/ZhangYangyi03/tool-market) | a tool's liveness, until the hash chain says which revision is live |
| [agent-safety-bench](https://github.com/ZhangYangyi03/agent-safety-bench) | a model's safety compliance, measured rather than assumed |
