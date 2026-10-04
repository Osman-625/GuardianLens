# GuardianLens Data Collection Guideline

**Status:** Draft for supervisor, ethics, and legal/platform approval

**Scope:** Mudah.my and Carousell Malaysia marketplace listings

**Primary task:** Classify a listing as `fraudulent`, `legitimate`, or `uncertain` using
independently verified outcomes, then train the GuardianLens text, image, behavioural,
and fusion models.

This is a research protocol, not permission to begin copying marketplace content. The
collection team must complete Gate 0 before storing listing text or images.

## 1. Recommended dataset size

There is no universal correct sample size for a machine-learning model. GuardianLens
should use a staged target and stop only after reviewing learning curves and class-level
metrics.

| Stage | Candidate records | Final adjudicated records | Purpose |
|---|---:|---:|---|
| Pilot | 60 | Expected 40-55 | Test the rubric, workflow, evidence yield, and annotator agreement |
| Minimum FYP dataset | About 800-900 | 600 | A defensible prototype if time or evidence access is limited |
| Recommended FYP dataset | About 1,000-1,200 | 800 | Better coverage for grouped model development and evaluation |
| Stretch target | About 1,250-1,500 | 1,000 | Use only if evidence quality and dual annotation remain consistent |

Candidate totals are higher because uncertain cases, duplicate clusters, unauthorized
content, out-of-scope listings, and records without independent evidence must be excluded
from the supervised dataset.

For the recommended 800-record final dataset, aim for:

- at least 320 independently evidenced fraudulent listings;
- at least 480 independently evidenced legitimate listings;
- approximately 1-3 authorized images per listing, where available; and
- a separate, authorized 500-1,000-image reference corpus for copy-similarity research.

These are pragmatic FYP targets, not a claim about the real prevalence of marketplace
fraud. The dataset is intentionally enriched with confirmed fraud cases. Report
population prevalence only from a separate probability sample.

If only 600 final records are feasible, seek at least 250 fraudulent and 350 legitimate
records. If either class falls below this floor, narrow the research claim and present
the work as a feasibility study.

### 1.1 Which data trains which GuardianLens component

| Component | Required data | Training role |
|---|---|---|
| XLM-RoBERTa text model | Scrubbed title, scrubbed description, language, final label | Fine-tune the pretrained multilingual encoder |
| XGBoost behavioural model | Price, category, account age, rating, review count, active-listing count, missing-value indicators, final label | Train supervised tabular classifier |
| CLIP consistency signal | Authorized listing images paired with their own title/description | Measure image-text consistency; do not train CLIP from scratch for the FYP |
| SSCD copy-similarity signal | Authorized listing images plus a separate, provenanced reference corpus | Retrieve likely copies/near duplicates; do not use a match as the label |
| Logistic-regression fusion | Out-of-fold scores from the text, behaviour, CLIP, and SSCD branches plus final label | Train the late-fusion risk score without leakage |
| Calibration/explanations | Validation predictions and final labels | Calibrate risk probabilities and evaluate explanations |

Try to obtain usable text for every final record, behavioural fields for at least 80%,
and one authorized image for at least 70%. Missing modalities should be recorded
explicitly, not imputed during collection. If image coverage is much lower, report the
image branch as a limited experiment rather than presenting it as equally validated.

## 2. Gate 0: authorization before collection

Do not store listing text, images, usernames, account links, phone numbers, chat messages,
or seller identifiers until all applicable items below are complete.

- [ ] Supervisor approves this protocol and the target population.
- [ ] University ethics review is approved or formally declared not required.
- [ ] A second independent annotator is confirmed.
- [ ] Written permission or a suitable data agreement is obtained from each platform,
      content owner, or authorized data provider.
- [ ] The permission explicitly covers the fields, images, research purpose, retention
      period, security controls, publication format, and trained-model use.
- [ ] A private evidence store and an access-control list are configured.
- [ ] A retention and deletion date is recorded.
- [ ] The team has a withdrawal/takedown process for contributed data.

Carousell's terms prohibit automated acquisition and restrict copying or collecting
information in ways that violate intellectual-property or privacy rights. Mudah's terms
also restrict copying and scraping without prior written consent. Therefore, manual
browsing is not by itself sufficient authorization.

If platform permission is not available, use one or more of these routes instead:

1. Obtain listings directly from consenting sellers and verified fraud victims.
2. Partner with a platform, enforcement body, consumer-protection organization, or
   university research group under a written agreement.
3. Use a public dataset whose licence explicitly permits the planned research and model
   use, while documenting its domain mismatch.
4. Use synthetic listings only for software testing and demonstrations. Never mix them
   into the primary training or evaluation dataset.

Do not bypass access controls, automate scraping, create deceptive accounts, bait
sellers, make transactions, or contact marketplace users without approved consent.

## 3. Population and sampling frame

### 3.1 Include

A candidate listing may enter the collection log when all of the following are true:

- it is within the approved data source or contribution route;
- it was active or verifiably archived during the approved collection period;
- it is a consumer-goods listing relevant to GuardianLens;
- its language is English, Malay, or a documented mixture of the two;
- it has enough authorized fields for at least one planned model branch; and
- it has a route to independent outcome evidence.

### 3.2 Exclude

Exclude Chinese-only listings, property, vehicles, services, jobs, audio-only material,
video-only material, records without reuse permission, and records whose provenance
cannot be verified. Also exclude a record from supervised training if its final outcome
cannot be independently established.

### 3.3 Sampling matrix

Use a sampling matrix so the model does not merely learn one platform, category, or
language. During the pilot, coverage is more important than exact balance. During
scaling, monitor these minimums:

| Dimension | Recommended coverage |
|---|---|
| Platform/source | No authorized primary source contributes more than 70% of final records |
| Language | English, Malay, and mixed-language each have at least 100 records at N=800 |
| Category | At least 60-80 records per retained category; merge or drop smaller categories |
| Label | At least 40% independently confirmed fraud in the enriched research set |
| Time | Collect in multiple dated batches, not a single day |
| Contributor | Avoid one victim, seller, or case source dominating a class |

Use neutral category/language/time quotas to choose candidates. Do not select a candidate
because the current model, a low price, suspicious wording, a new account, or a reused
image says it “looks fraudulent.” That would make the training sample circular.

Confirmed-case enrichment is allowed only when the case source provides independent
outcome evidence. Maintain a separate random or systematic stream, where permission
allows, to measure selection bias.

## 4. What to collect

The ML-ready listing export should contain only the minimum fields already defined in
`research/templates/listings_import.csv`:

- pseudonymous `listing_id`;
- authorized platform/source label and collection date;
- collector code;
- scrubbed title and description;
- approved category, price, language, and coarse location;
- account-age, rating, review-count, and active-listing-count features where authorized;
- non-identifying notes.

For images, use `research/templates/listing_images_import.csv`:

- `listing_id`;
- internal storage path;
- SHA-256 checksum;
- position within the listing.

Keep the following in a separate encrypted evidence register, never in the training CSV:

- original URL or platform listing identifier;
- username, telephone number, email, chat transcript, payment details, and report number;
- consent record and permission scope;
- source document for the independent label;
- access history and deletion date.

Generate public/research IDs independently of the marketplace identifier. If records must
be linked, use a keyed HMAC maintained in the restricted evidence environment; do not
publish the key or the mapping.

## 5. Human collection procedure

Work in batches of 50 candidates after the pilot.

1. Open only an approved source.
2. Check the sampling matrix for the next underrepresented stratum.
3. Confirm that reuse permission and evidence provenance cover the candidate.
4. Assign a new pseudonymous `listing_id`.
5. Copy only approved fields and immediately redact direct identifiers.
6. Download only explicitly authorized images; calculate their SHA-256 checksums.
7. Store the evidence reference separately from the ML-ready record.
8. Run a second-person PII check before releasing the record for annotation.
9. Record batch totals in `research/templates/collection_batch_log.csv`.
10. Lock the batch so annotators cannot see each other's work.

Never infer or fill a missing value. Leave it empty and distinguish “missing” from a real
zero during preprocessing.

## 6. Labeling protocol

Use `research/LABELLING_RUBRIC_V1.md`. Both annotators must complete calibration before
the pilot.

1. Annotator A1 labels every candidate independently.
2. Annotator A2 labels the same candidate without seeing A1's decision.
3. Both record label, evidence type, whether evidence is decisive, a short rationale, and
   confidence.
4. Compute raw agreement and Cohen's kappa for the pilot.
5. Send disagreements, uncertain labels, and low-confidence cases to adjudication.
6. The adjudicator may assign `fraudulent`, `legitimate`, or `excluded`.
7. A record enters supervised training only when the adjudication has independent,
   decisive evidence.

No model output, reverse-image result, price anomaly, account-age value, wording pattern,
or planned input feature may be decisive evidence for the label. These may be model
features later, but they cannot define ground truth.

## 7. Pilot and Gate A

Collect and dual-label 60 candidates before scaling.

Produce a pilot report containing:

- inclusion, exclusion, uncertainty, and duplicate counts;
- label counts by source, language, and category;
- raw agreement and Cohen's kappa;
- disagreements grouped by rubric rule;
- count of fraud labels with independent decisive evidence;
- count of legitimate labels with positive independent confirmation;
- average collection and annotation time per record;
- PII or permission incidents; and
- changes proposed for rubric version 1.1.

Suggested Gate A conditions, subject to supervisor approval:

- Cohen's kappa is at least 0.61;
- no unresolved permission or high-risk privacy incident exists;
- every included label has traceable independent evidence;
- both classes have a viable evidence-acquisition path; and
- exclusion/uncertainty rates are low enough to reach 600-800 final records.

If Gate A fails, revise the rubric or source strategy and repeat a smaller calibration
round. Do not compensate by allowing weak labels.

## 8. Scaling and weekly quality control

After Gate A, collect in 50-candidate batches. Each week:

- reconcile batch totals with the evidence register;
- inspect 10% of records for PII and permission compliance;
- inspect label and exclusion rates by collector and annotator;
- investigate a kappa drop greater than 0.10 from the pilot;
- check source, language, category, and class coverage;
- identify exact and near duplicates;
- record rubric changes as new versions rather than editing history; and
- back up the encrypted evidence register to an approved location.

Freeze the rubric before the final 200 candidates unless a safety or validity defect is
found. Any material rubric change requires re-review of earlier records.

## 9. Duplicate control and data splits

Create groups before splitting:

- all images and text belonging to one listing;
- listings from the same seller/contributor where linkage is authorized;
- exact duplicates using SHA-256 and normalized-text hashes;
- near-duplicate image clusters using perceptual similarity/SSCD; and
- near-duplicate text clusters.

Every group must remain entirely within one split. Do not allow images from one listing
to appear in train while its text or duplicate appears in validation or test.

For 800 final records, the current schema can use:

| Split | Share | Approximate records | Use |
|---|---:|---:|---|
| Train | 60% | 480 | Fit models and cross-validated out-of-fold fusion inputs |
| Validation | 15% | 120 | Tune thresholds and calibration |
| Test | 15% | 120 | One-time final comparison |
| Clean validation | 10% | 80 | Independently evidenced, leakage-audited diagnostic set |

Preserve class proportions where possible while keeping groups intact. Use a grouped,
stratified procedure such as `StratifiedGroupKFold` for cross-validation. Freeze and hash
the test and clean-validation manifests before model development. Do not repeatedly tune
against them.

If the schema is later changed so clean validation is a flag rather than an exclusive
split, use a 70/15/15 train/validation/test split and select the clean subset from records
not used to fit the model.

## 10. Image reference corpus

The SSCD copy-similarity branch needs a separate, provenanced reference corpus. It must
not silently reuse unlicensed marketplace images.

For each reference image record:

- record owner/source and licence or consent;
- record acquisition date and allowed use;
- retain the original file checksum;
- assign a reference-cluster ID;
- document transformations;
- keep near-duplicate families in the same evaluation group; and
- exclude it from label adjudication unless it is independent evidence approved by the
  rubric.

A reverse-image or SSCD match is a model signal, not proof that the listing is fraudulent.

## 11. Stop rule

After every additional 100 final records, plot learning curves for the text, behavioural,
and fusion models using grouped cross-validation.

Stop at the approved target only when:

- the minimum class and coverage floors are met;
- data-quality and authorization checks pass;
- adding the last 100 records produces little or no validated improvement; or
- the approved FYP resource limit is reached.

If the learning curve is still rising at 800 records, report that the model is
data-limited and treat 800 as a project constraint rather than “enough data.”

## 12. Evaluation and reporting

Because fraud detection is class-imbalanced, report precision, recall, F1, and
precision-recall AUC for each class. Also report:

- confusion matrices;
- performance by platform/source, language, and category;
- bootstrap confidence intervals at the grouped-record level;
- calibration/reliability and Brier score;
- ablations for text, image consistency, copy similarity, behaviour, and fusion;
- missing-modality performance;
- number and reason for every exclusion; and
- dataset limitations, enrichment strategy, and known selection bias.

Do not present accuracy as the main result. Do not claim production readiness or
population-wide fraud prevalence from this research dataset.

## 13. Suggested working schedule

| Work block | Output |
|---|---|
| Block 1 | Gate 0 approvals, data agreement, evidence store, annotator recruitment |
| Block 2 | Rubric calibration and 60-candidate pilot |
| Block 3 | Pilot analysis, Gate A decision, rubric freeze |
| Blocks 4-7 | Collection and dual labeling in 50-candidate batches |
| Block 8 | Final adjudication, PII audit, deduplication, manifests and hashes |
| Block 9 | Baselines and learning-curve review; decide whether to extend collection |

## 14. Required outputs

Before training, the research folder should contain:

- an approved protocol and rubric version;
- a permission/ethics decision record;
- collection and annotation data dictionaries;
- batch QA reports;
- a de-identified listings export;
- an authorized image manifest;
- dual annotations and final adjudications;
- grouped split manifests with hashes;
- a dataset card describing provenance, exclusions, risks, and intended use; and
- a deletion/retention log.

Actual research data belongs only under ignored, access-controlled directories such as
`research/data/` and `research/exports/`. Never commit raw marketplace identifiers,
participant contact data, or private evidence.

## References

- [Carousell Terms of Service](https://support.carousell.com/hc/en-us/articles/115011881808-Terms-of-Service)
- [Mudah Terms of Service](https://www.mudah.my/about/terms-of-service/)
- [Malaysia Personal Data Protection Department: Data Protection by Design Guideline (2026)](https://www.pdp.gov.my/ppdpv1/wp-content/uploads/2026/04/Data-Protection-By-Design-Guideline-DpbD.pdf)
- [scikit-learn: Learning curves](https://scikit-learn.org/stable/modules/learning_curve.html)
- [scikit-learn: StratifiedGroupKFold](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.StratifiedGroupKFold.html)
- [scikit-learn: Precision-Recall](https://scikit-learn.org/stable/auto_examples/model_selection/plot_precision_recall.html)
