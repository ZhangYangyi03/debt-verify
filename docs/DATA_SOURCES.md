# Where the numbers in data/zambia_2023.json come from

## What each series is

    indicator          definition                                   source family
    debt_gdp           gross public debt, % of GDP                   IMF WEO vintages;
                                                                     Zambia MoF
                                                                     budget speeches;
                                                                     IMF EFF reviews
    fiscal_primary     primary fiscal balance, % of GDP             IMF EFF programme
                                                                     reviews; MoF
                                                                     annual reports
    reserves_months    gross international reserves, months of      Bank of Zambia
                       import cover                                  annual reports
    gdp_growth         real GDP growth, %                           IMF WEO vintages;
                                                                     ZamStats

## The vintage axis

Each cell is (reference year, vintage year). (2019, 2020) is what the 2020
vintage said about 2019. The revision record is the object of study: a clause
reading "debt above 90% of GDP" is read against a number that moved 12.8 points
between vintages for the same reference year.

## What is stated plainly, and what is not claimed

1. The values are transcribed from the public record; they are rounded as the
   sources round them. This file is not an authoritative dataset and does not
   present itself as one. A reader who has the primary sources should replace
   it; the manifest will then change and every printed number will change with
   it, which is the intended behaviour.

2. IMF WEO vintage files back to 2022 were not retrievable from this host
   (www.imf.org returns 403 to the sandbox; api.db.nomics.world and
   databank.worldbank.org did not complete a TLS handshake). The World Bank
   JSON API was reachable. Where a vintage value was not retrievable, the cell
   was left out rather than interpolated: an interpolated revision would
   manufacture exactly the effect the project measures. Cells that are absent
   show up as smaller cell counts in the tables.

3. No claim is made here about the *actual* negotiations. The clause set in
   `cli.zambia_clauses()` is a faithful rendering of the clause *kinds* under
   discussion (a debt ceiling, a debt target, a primary-balance floor, a reserve
   floor, a debtor-side growth trigger, and a 2-of-3 window), not a transcription
   of the signed MoU text, which is not public in full.
