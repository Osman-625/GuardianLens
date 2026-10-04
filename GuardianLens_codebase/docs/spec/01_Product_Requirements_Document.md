# GuardianLens: Product Requirements Document (PRD)

**Status:** Working draft for supervisor review. Derived from frozen sources; see the Verification Register (document 00) for the source of every claim.
**Derivation rule:** No feature in this PRD is invented. Every feature traces to a requirement ID in Chapter 3 (Tables 3.3 to 3.5) or a scope statement in Documentation I. Anything not traceable is listed under Out of scope or Rejected, with its source.

---

## 1. Project overview

GuardianLens is a multimodal, explainable fraud-risk assessment web application for buyers on Malaysian consumer-to-consumer (C2C) marketplaces, specifically Mudah.my and Carousell, covering product listings only. A buyer submits a listing's images and details through a web form. The system analyses three independent signals (visual, textual, behavioural), fuses them with a trained late-fusion meta-classifier, and returns a calibrated risk score from 0 to 100 with a risk band (Low, Moderate, High), a plain-language per-signal explanation generated from SHAP contributions, notices for any unavailable signal, and suggested manual checks. GuardianLens is decision support. It never issues a buy or do-not-buy command and never claims certainty about a listing (NFR-10, UR-05).

The FYP2 deliverable is a research prototype evaluated at two levels: technical performance of the individual and fused models (RQ1 to RQ3) and a controlled user study measuring whether the explained result improves buyer accuracy over unaided judgement (RQ4).

### 1.1 Target audience

| Audience | Description | Evidence |
| --- | --- | --- |
| Primary: everyday Malaysian C2C buyers | Non-expert buyers assessing an individual listing before paying, with little recourse after a loss. The requirements survey sample skewed 18 to 24 (78.6%) and Mudah.my-dominant; no respondent was 35 or older, a stated generalisability limit. | Doc I s.1.5; Ch3 Table 3.3a and s.3.1.7 |
| Secondary: fraud-detection researchers | An evaluation of multimodal fusion and explainability in the understudied Malaysian C2C context, plus a reusable, auditable labelling protocol. | Doc I s.1.5 |
| Tertiary: platforms and consumer bodies | A worked example of buyer-facing (not analyst-facing) explainable risk communication. | Proposal target-audience slide |
| Internal: project administrator (researcher) | Manages model versions, reference corpus, anonymised records, and evaluation exports through a restricted view. | UR-07, Screen 7 |

### 1.2 Working personas (survey-grounded, for design use only)

These personas summarise the survey sample. They are design aids, not population claims.

- **Aina, 21, student, occasional Mudah.my buyer.** Checks seller ratings and account age when she remembers, has come close to losing money once, wants plain-language reasons more than a number, and says she would weigh any score against her own judgement.
- **Danish, 27, early-career, buys electronics on Carousell a few times a year.** Compares prices and reverse-image searches suspicious photos, worries more about missing a fraud than about a false alarm, expects a result within seconds.

---

## 2. Problem statement and value proposition

### 2.1 Problem

Two national data series frame the problem. They are separate series and must never be merged. In 2024, Malaysia recorded 35,368 cybercrime cases with RM1.58 billion in reported losses (Ministry of Digital Malaysia, 2025, citing PDRM figures). In the 2023 data year, e-commerce accounted for 33.2% of online crime (DOSM, 2024).

At the individual level, the requirements survey (usable n = 66) found that 32.9% of respondents had lost money to C2C fraud and a further 22.9% had come close, so just under 56% had direct financial exposure. Buyers currently rely on manual spot checks: seller ratings (64.1%), account age (53.1%), price comparison (48.4%), and reverse-image search (43.8%). Their top concerns map directly onto the three GuardianLens signals: brand-new or review-less accounts (80.0%, behavioural), reused or stock photos (65.7%, visual), and off-platform payment pressure (50.0%).

Existing detection research and tooling is dominated by single-signal methods, transaction-time (post-checkout) fraud framing, analyst-facing outputs, and English-language text. There is no accessible, pre-purchase, buyer-facing, explained assessment for the Malay and mixed Malay-English listings typical of the Malaysian C2C context (Doc I Chapter 2 gap analysis).

### 2.2 Value proposition

GuardianLens gives a buyer a structured second opinion at the moment it matters, before payment. Value comes from four properties working together, each tied to a requirement:

1. **Multimodal coverage** where single signals fail alone (FR-03 to FR-05, FR-07): a convincing photo with a fraudulent price pattern, or clean text on a brand-new account, is caught by the signals in combination.
2. **Calibrated, banded output** (FR-08) instead of a raw probability, in the score format 57.4% of surveyed buyers asked for.
3. **Plain-language, per-signal explanation** (FR-09), the single most requested output (80.9% of n = 47), designed to support judgement rather than replace it; 78.8% of respondents said they would weigh the score with their own judgement, which the design deliberately preserves.
4. **Honest uncertainty** (FR-06, NFR-04, NFR-10): missing signals are surfaced, never silently treated as safe, and the disclaimer is always visible.

### 2.3 What GuardianLens is not

Not a verdict engine, not a takedown or monitoring system, not a platform integration, not a seller-reputation database, and not an official PDRM tool. Semak Mule (the PDRM/NSRC account-check service) appears only as a suggested manual check the buyer performs independently; no claim of affiliation or integration is made.

---

## 3. Core features

Priorities are the MoSCoW classes fixed in Chapter 3 Table 3.4. "Source" is the requirement ID; the FYP2 phase refers to the Engineering Plan (document 06).

### 3.1 Must-have

| Feature | Description | Source | FYP2 phase |
| --- | --- | --- | --- |
| Listing submission | Web form accepting image files and structured listing details: title, description, price, category, and optional visible seller information. Manual entry only; no URL fetching (platform terms prohibit automated retrieval). | FR-01, UR-02 | D |
| Input validation | Mandatory-field, file-type, file-size, numeric-price, and safe-text-length checks before processing; Chinese-language text flagged unsupported at this step. | FR-02, FR-04 | D |
| Visual analysis | CLIP image-description consistency plus SSCD copy similarity against the approved reference corpus; matches explained strictly as reuse within that corpus. | FR-03 | B |
| Textual analysis | Fine-tuned XLM-RoBERTa classification of Malay, English, and mixed listing text. | FR-04 | B |
| Behavioural analysis | XGBoost over available structured seller and listing features with explicit missingness representation. | FR-05 | B |
| Missing-signal handling | Available signals processed; unavailable signals marked; missing data never treated as safe. | FR-06 | B, D |
| Fusion | Trained late-fusion meta-classifier (logistic-regression baseline) over component probabilities plus availability indicators. | FR-07 | C |
| Calibration | Sigmoid-calibrated 0 to 100 score with a Low / Moderate / High band; band boundaries fixed during evaluation, not before. | FR-08 | C |
| Explanation generation | Per-signal SHAP contributions converted to short buyer-facing explanations. | FR-09 | C |
| Result display | Overall score, band, three signal cards, uncertainty and missing-data notices, suggested checks, permanent disclaimer. | FR-10, UR-03 to UR-05 | D |
| Assessment storage | Only anonymised assessment metadata needed for evaluation and reproducibility is stored. | FR-11, NFR-05 | D |
| Export | Administrator export of anonymised model outputs and user-study data. | FR-14, UR-07 | D, E |

### 3.2 Should-have

| Feature | Description | Source | FYP2 phase |
| --- | --- | --- | --- |
| Feedback | Buyer marks a result helpful, unclear, or potentially incorrect. | FR-12, UR-06 | D |
| Session history | Review listings checked during the current session (70% survey preference). Session-scoped only; cross-login history is future work. | FR-13 | D |

### 3.3 Could-have and rejected (do not build)

| Item | Status | Source |
| --- | --- | --- |
| Platform integration with Mudah.my or Carousell | Future work, out of FYP2 scope | Ch3 s.3.1.7 |
| Browser extension | Future work, out of FYP2 scope | Ch3 s.3.1.7 |
| Saved history across logins | Future work, out of FYP2 scope | Ch3 s.3.1.7 |
| URL-paste ingestion or screenshot OCR | Not a committed requirement. The survey recorded preference for these input modes, but FR-01 commits to image files plus structured details, and automated URL retrieval conflicts with platform terms. Any revisit requires a supervisor-approved scope change. | Survey Table 3.3c vs FR-01 |
| Community fraud reporting | Rejected outright: undermines decision-support framing | Ch3 s.3.1.7 |
| Guaranteed fraud confirmation | Rejected outright: impossible claim, over-reliance hazard | Ch3 s.3.1.7 |
| Real-time monitoring, takedown, audio/video analysis, production deployment | Out of scope | Doc I s.1.3 |
| Facebook Marketplace as a platform or data source | Out of scope | Project decision record |

---

## 4. Success measures

Success is defined by evidence produced against the fixed evaluation design, not by hitting an invented numeric target. No baseline exists for this dataset, so pre-committing to an F1 number would be unsupportable; the commitments below are the ones Chapter 3 actually makes.

| Area | Measure | Definition of success | Source |
| --- | --- | --- | --- |
| RQ1 component performance | Precision, recall, F1, confusion matrix per signal on the single-use held-out test set; threshold fixed on validation first | Metrics reported per protocol with the clean-subset check for the visual signal | Ch3 s.3.3.9 |
| RQ2 fusion benefit | Fused vs best single signal on identical held-out records; bootstrap confidence interval where feasible | Comparison reported with uncertainty; direction and size stated honestly either way | Ch3 Table 3.8 |
| RQ2 calibration | Brier score and reliability plot | Reported; band boundaries then fixed and documented | Ch3 s.3.3.8 to 3.3.9 |
| RQ3 ablation | Seven configurations (V, T, B, V+T, V+B, T+B, V+T+B) on the same test set | Full ablation table reported; findings feed the final fusion configuration | Ch3 Table 3.8 |
| RQ4 human benefit | Within-subjects study, minimum 20 participants; primary outcome per-participant accuracy; Wilcoxon signed-rank; Cohen's d; over-reliance rate | Study executed per protocol and analysed; a null or negative result is a reportable finding, not a project failure | Ch3 s.3.3.9 |
| Product quality | NFR-01 to NFR-10 verified by the methods in Table 3.9 (usability tasks, 10-second performance test, viewport checks, privacy and security audits, repeatability test, accessibility audit, disclaimer check) | Each audit executed with recorded results | Ch3 Table 3.9 |

**Anti-goals for the metrics:** accuracy is never headlined (imbalance makes it misleading; it is supplementary only), and statistical significance in the user study is never promised as an acceptance criterion.

---

## 5. Constraints and assumptions

| Type | Statement |
| --- | --- |
| Constraint | Manual data collection only; both platforms' terms prohibit automated scraping and bots. |
| Constraint | Free-tier compute: Colab free T4 (primary) and Kaggle (backup) for XLM-RoBERTa fine-tuning; single developer; roughly 13-week FYP2 window (exact dates: open item O-2). |
| Constraint | Class imbalance: fraud is the minority class; handled with class weighting, resampling where appropriate, and imbalance-aware metrics. |
| Constraint | No public benchmark for Malaysian C2C listing fraud exists; the dataset is self-collected and self-labelled, and reported metrics measure agreement with the labelling protocol, not absolute ground truth. |
| Assumption (flagged) | The pilot will yield enough fraud-positive listings with independent evidence to proceed; if not, the Tier C escalation path to Dr. Rajabi applies before any target is silently lowered. |
| Assumption (flagged) | A second annotator will be secured (open item O-1). The inter-annotator agreement claim collapses without one. |

---

## 6. Traceability

Every FR and NFR in Chapter 3 maps to at least one feature in section 3 of this PRD and to at least one task in the Engineering Plan (document 06, s.8 coverage check). Any future feature request must first be written as a new requirement, classified, and approved before it enters the plan.
