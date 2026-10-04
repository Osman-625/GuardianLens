# GuardianLens Labeling Rubric v1

**Status:** Draft; freeze only after supervisor approval and annotator calibration

**Version:** 1.0-draft

**Approved by:** ____________________

**Approval date:** ____________________

## Core rule

The ground-truth label must come from evidence independent of every planned GuardianLens
model input. A suspicious pattern is not an outcome.

## Labels

### `fraudulent`

Assign only when at least one approved independent source establishes that this specific
listing, transaction, or linked case involved deception or attempted deception.

Examples of potentially decisive evidence, subject to ethics and data-access approval:

- a verified victim or transaction outcome with consent and supporting records;
- a platform fraud determination specific to the listing/account;
- an official enforcement or consumer-protection case match;
- a court, police, or regulator record that can be reliably linked to the case; or
- another pre-approved independent source with an auditable chain of evidence.

### `legitimate`

Assign only when there is positive independent confirmation that the listing and seller
were genuine for the relevant event.

Examples of potentially decisive evidence:

- a consenting seller proves ownership and the genuine listing history;
- a consenting buyer provides a verified successful transaction outcome;
- the platform confirms the listing/account as genuine for the case; or
- another pre-approved source positively verifies legitimacy.

The absence of a complaint, report, reverse-image match, or suspicious feature is not
proof of legitimacy.

### `uncertain`

Assign when:

- no decisive independent evidence is available;
- evidence conflicts or cannot be linked to this specific listing;
- only model-visible suspicious cues are available;
- provenance or permission is incomplete; or
- the annotator cannot confidently apply the rubric.

Uncertain records may be retained for future investigation but must not enter supervised
training as positive or negative examples.

### `excluded`

Only the adjudicator assigns `excluded`. Use it for out-of-scope, unauthorized,
duplicate-only, corrupted, unverifiable, or permanently uncertain records.

## Evidence hierarchy

### Decisive when verified and approved

1. Specific official/platform case outcome.
2. Consented, documented transaction outcome.
3. Consented ownership and listing-history verification.
4. Another source named in the approved evidence-source register.

### Never decisive by itself

- unusually low or high price;
- new account, low rating, few reviews, or many active listings;
- urgent, emotional, grammatically unusual, or off-platform wording;
- missing product details;
- stock, reused, inconsistent, or reverse-matched images;
- CLIP, SSCD, XLM-R, XGBoost, fusion, or other model output;
- the collector's or annotator's intuition;
- a listing that disappeared, because it may have sold or been removed for another reason;
- an unverified social-media post, complaint, or screenshot; or
- absence from a complaint/report database.

These items may be recorded as non-decisive metadata only when authorized.

## Annotation procedure

1. Confirm the record is in scope and de-identified.
2. Review the approved evidence packet, not any model score.
3. Select `fraudulent`, `legitimate`, or `uncertain`.
4. Select the registered evidence type.
5. Mark `evidence_is_decisive=true` only when the evidence satisfies this rubric.
6. Write a short factual rationale without personal data.
7. Record confidence:
   - `high`: direct, specific evidence with clear linkage;
   - `medium`: evidence is sufficient but linkage or interpretation required care;
   - `low`: material ambiguity remains; normally label `uncertain`.
8. Submit without viewing the other annotator's label.

## Adjudication rules

- Review A1 and A2 only after both submissions are locked.
- Resolve disagreements by applying the rubric, not by majority intuition.
- Do not convert an uncertain case to fraud or legitimate merely to balance classes.
- Set `decisive_evidence_independent=true` only after checking the evidence source and
  listing linkage.
- Record the reason for every decision.
- Escalate a new evidence type to the supervisor before using it.

## Calibration set

Before the 60-candidate pilot, both annotators independently label the same 15-20
approved calibration cases. Discuss rule interpretation after labels are locked, revise
the draft if needed, then restart calibration on fresh cases.

The pilot may proceed when both annotators can explain:

- why suspicious cues are not labels;
- why “not known to be fraud” is not legitimate;
- how independent evidence links to one listing;
- when to use uncertain; and
- how to keep personal data out of annotation notes.

## Change control

Never silently edit a frozen rubric. Record:

- new version and date;
- exact rule changed;
- reason for the change;
- approving person;
- affected record IDs; and
- whether earlier annotations require review.
