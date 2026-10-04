# Dataset Split Safety

**No train/validation/test split is created in this workspace.** GuardianLens is at
the annotation-preparation stage -- labels don't exist yet, so a split would be
premature. This document exists so a *future* split (once real annotations/final
labels exist) avoids leaking information between train and test.

## Leakage risks identified in this dataset (from the independent validation audit)

1. **Cross-listing near-duplicate images** -- `reports/dataset_validation_report.md`
   lists 174 groups of images that are perceptually near-identical *across different
   listings* (265 distinct listings touched). If two listings share reused images and
   end up split across train/test, a model could learn to recognize the specific
   image rather than the underlying signal. **Recommendation:** when splitting, keep
   every listing in a cross-listing near-duplicate group in the *same* split.
2. **Possible repost candidates** -- `reports/dataset_validation_report.md` lists 6
   groups of listings sharing the same platform+title+price (heuristic, not
   confirmed reposts). Same recommendation: keep grouped listings together.
3. **Same-seller groupings** -- the exported `listings.csv` deliberately does **not**
   carry a seller-identity field (no raw seller name/contact is exported at all, per
   the PII/data-boundary policy). If a future export adds a seller-linking key, treat
   it the same way: group by seller before splitting, don't split a seller's
   listings across train/test.
4. **Duplicated descriptions** -- not found as exact duplicates in this dataset (the
   source DB already enforces uniqueness on marketplace ID / URL / metadata
   signature at approval time, independently re-verified in this audit -- 0 hits).
   Still worth a fuzzy-text-similarity check before any future split, since exact
   dedup doesn't catch near-identical descriptions with minor edits.

## Recommended approach for a future split

Use **grouped/stratified splitting**, keyed on a `group_id` you'd derive at split
time by union-finding: (a) cross-listing near-duplicate image groups, (b) possible
repost candidate groups, (c) any seller-identity key if one exists by then. Assign
whole groups to a single split (e.g. via `GroupShuffleSplit`/`GroupKFold` keyed on
`group_id`), stratified by `label` (once real labels exist) and `platform`/`category`
to keep class balance reasonable across splits.

Do not split on `listing_id` directly without first computing `group_id` -- doing so
risks placing near-duplicate/repost listings on both sides of the split.
