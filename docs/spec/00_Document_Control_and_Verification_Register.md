# GuardianLens FYP2: Document Control and Verification Register

**Status:** Working draft for supervisor review. Not an assessed deliverable.
**Purpose:** Governs the six pre-implementation documents (01 to 06). Every claim in those documents is either (a) verified against a frozen project source, (b) an established project decision, or (c) a proposal explicitly marked as awaiting confirmation. Nothing in category (c) may be treated as settled.
**Scope note:** These are internal engineering and product documents for the FYP2 build. They must never contradict Documentation I or Chapter 3, which are frozen and authoritative. Where they add detail (database schema, design tokens, task plan), that detail is new engineering elaboration consistent with the locked architecture, not a change to it.
**House style:** British English. No em dashes or en dashes anywhere; ranges use "to". No first-person pronouns. Markdown structured for direct copy into Notion.

---

## 1. Document set

| # | File | Contents | Depends on |
| --- | --- | --- | --- |
| 01 | `01_Product_Requirements_Document.md` | Overview, audience, problem, value proposition, MoSCoW features, success measures | Doc I Ch1, Ch3 Tables 3.3 to 3.5, 3.8, 3.9 |
| 02 | `02_Technical_Design_Document.md` | Committed stack, architecture, API contract, model serving analysis, security, reproducibility | Doc I s.6 stack table, Ch3 s.3.3.7 to 3.3.8 |
| 03 | `03_App_Flow_and_User_Journeys.md` | Onboarding, journeys, screen-by-screen navigation map | Ch3 s.3.3.6 Table 3.6, FR table |
| 04 | `04_Design_Brief_UI_UX.md` | Look and feel, design tokens, component specs, UX-laws audit (Laws of UX, 30-law set) | Ch3 s.3.3.6, NFR-03, NFR-08, survey findings |
| 05 | `05_Backend_Schema.md` | Supabase (Postgres) tables, fields, constraints, relationships, RLS, ER diagram | Ch3 Table 3.7, FR-11 to FR-14, NFR-05 to NFR-07 |
| 06 | `06_Engineering_Plan.md` | Phased task breakdown, dependencies, gates, acceptance criteria, risk register | Doc I DSR phases, Ch3 s.3.3.9, FYP2 roadmap |

---

## 2. Verified facts and their sources

Facts below were checked against the project files in this session. "Ch3" = GuardianLens_Chapter_3.docx as mounted in the project space; if this predates the submitted v11, re-verify any cited line against v11 before relying on it externally. "Doc I" = I23023943_Osman_Documentation_I.docx / GuardianLens_Documentation_I_FINAL.docx. "Proposal" = I23023943_Osman_proposal.docx.

| Fact | Source |
| --- | --- |
| Requirements: UR-01 to UR-07, FR-01 to FR-14 with MoSCoW priorities, NFR-01 to NFR-10 with measures | Ch3 Tables 3.3, 3.4, 3.5 |
| Seven interface screens and their required content | Ch3 Table 3.6, s.3.3.6 |
| Client-server architecture: Next.js + TypeScript frontend, FastAPI orchestration backend, Supabase storage | Ch3 s.3.3.7; Proposal s.6 stack table |
| Visual signal: CLIP image-description consistency; SSCD copy detection against an approved reference corpus; corpus match explained only as reuse within that corpus | Ch3 s.3.3.8 |
| Textual signal: fine-tuned XLM-RoBERTa; Malay, English, mixed; class weights, early stopping, stratified validation; Chinese-language listings out of scope and flagged unsupported at input | Ch3 s.3.3.8, FR-04 |
| Behavioural signal: XGBoost; candidate features account age, seller rating, review count, active listing count, listing velocity, price deviation from category baseline, explicit missingness indicators; missingness never auto-read as suspicious | Ch3 s.3.3.8, FR-05, FR-06 |
| Fusion: logistic-regression meta-classifier preferred baseline; component probabilities generated out of fold via five-fold stratified cross-validation; availability indicators as fusion inputs | Ch3 s.3.3.8 |
| Calibration: sigmoid calibration via CalibratedClassifierCV; quality via reliability plot and Brier score; calibrated 0 to 100 score | Ch3 s.3.3.8, FR-08 |
| Risk bands: Low, Moderate, High; interface labels; final boundaries stated explicitly in the evaluation report, not fixed in advance | Ch3 s.3.3.8 |
| Explanation: per-signal SHAP contributions converted to short templates; decision support framing; over-reliance risk acknowledged (Bansal et al., 2021) | Ch3 s.3.3.8, FR-09, NFR-10 |
| Dataset field groups: listing identity, product information, images, seller/listing features, evidence metadata, model outputs | Ch3 Table 3.7 |
| Dataset exclusions: Chinese-language listings, property, vehicles, services, job advertisements, audio, video | Ch3 s.3.3.8 |
| Circular-labelling safeguard: labels only from evidence independent of model inputs; reverse-image matches recorded as non-decisive metadata; clean validation subset reserved | Doc I s.1.4 Phase 2; Ch3 s.3.3.8 |
| Metrics: precision, recall, F1 primary; accuracy supplementary; confusion matrices; classification threshold fixed on validation before a single-use test set; ablation over V, T, B, V+T, V+B, T+B, V+T+B; bootstrap confidence interval where feasible | Ch3 s.3.3.9, Tables 3.8, 3.9 |
| User study: within-subjects, counterbalanced; two matched sets of eight listings (four fraudulent, four legitimate); minimum 20 participants (10 per group); five-step session protocol; primary outcome per-participant accuracy; secondary outcomes decision time, confidence, perceived usefulness (5-point Likert), over-reliance rate; Wilcoxon signed-rank test; Cohen's d effect size; study listings drawn only from the hold-out set with independent fraud evidence | Ch3 s.3.3.9 |
| Performance target: assessment completes within 10 seconds from submission to result (survey-derived) | Ch3 NFR-02 |
| Responsiveness checkpoints: 375 px, 768 px, 1440 px | Ch3 Table 3.9 (NFR-03) |
| Accessibility: WCAG 2.1 AA contrast and label audit; risk never communicated through colour alone | Ch3 NFR-08, s.3.3.6 |
| Security: OWASP-based checklist, secret scanning, restricted admin functions, no secrets in source | Ch3 NFR-06, Table 3.9 |
| Privacy: no personal identifiers required for an assessment; pseudonymous identifiers; approved retention period; seller identifiers pseudonymised at collection; no financial or contact details retained | Ch3 NFR-05, s.3.3.9 |
| History is session-scoped (FR-13, Should); cross-login saved history was explicitly deferred as future work | Ch3 s.3.1.7, FR-13 |
| Rejected features: community fraud reporting, guaranteed fraud confirmation, platform integration, browser extension (future-work list) | Ch3 s.3.1.7 |
| DSR six phases (Peffers et al., 2007) mapped to the project | Doc I s.1.4; Ch3 Table 3.1 |
| Problem statistic A: 35,368 cybercrime cases and RM1.58 billion in reported losses, 2024 figures, Ministry of Digital Malaysia (2025) citing PDRM | Doc I / proposal problem statement; project statistics rule |
| Problem statistic B: e-commerce accounted for 33.2% of online crime, 2023 data year, DOSM (2024) | Doc I / proposal problem statement; project statistics rule |
| Survey findings used in these documents (Ch3 table values, not prose): direct exposure 32.9% lost money + 22.9% came close; top checks: ratings 64.1%, account age 53.1%, price comparison 48.4%, reverse-image 43.8%; top concerns: new account 80.0%, reused photos 65.7%, off-platform payment 50.0%; submission preference: photos 68.6%, screenshot 54.3%, URL 45.7%, manual 20.0%; plain-language reasons 80.9% of n=47; session history wanted by 70%; 78.8% would weigh the score with their own judgement; 48% more worried about missed fraud than false alarms; 54.2% expected a result within seconds | Ch3 Tables 3.3a to 3.3c and s.3.1.7 |
| Limitations register (dataset self-labelled, corpus-bounded visual recall, sparse behavioural features, class imbalance, small study sample, generalisability, free-tier compute) | Doc I s.1.3 Limitations |

**Statistics rule (non-negotiable):** the two problem statistics above are separate data series with different years, sources, definitions, and populations. They must never be merged, averaged, or cross-attributed in any document.

---

## 3. Established project decisions (binding, from the project decision record)

| Decision | Consequence for these documents |
| --- | --- |
| Both Mudah.my and Carousell Malaysia terms of service prohibit automated scraping, bots, and automated means. Manual collection is the required approach. | No scraper, crawler, or automated URL-fetch component appears anywhere in the architecture, schema, or plan. Listing data enters via the web form (FR-01) at inference time and via manual browsing plus the collection log tool during dataset building. |
| Facebook Marketplace is out of scope. | Not referenced as a data source or target platform. |
| Supabase is the committed database. "PostgreSQL or Supabase" phrasing is not acceptable. | Documents 02 and 05 name Supabase throughout. |
| A React-based collection log tool exists for the clerical side of manual data collection: structured intake, blind independent labelling per annotator, live Cohen's kappa, disagreement adjudication, CSV export. | The Engineering Plan treats collection as manual browsing plus this tool; it does not re-plan tool construction. |
| Pilot test gates the fraud-positive volume target. A Tier C shortfall scenario requires immediate escalation to Dr. Rajabi, not silent absorption. | Gate A in the Engineering Plan. |
| User study recruitment opens in weeks 1 to 2 of FYP2 regardless of pipeline progress. | Task GL-P0-05; status to confirm against the calendar (see s.5). |
| Chapter 4 is written incrementally per component. | Chapter 4 drafting tasks are embedded in each build phase. |
| XLM-RoBERTa fine-tuning runs on Google Colab free T4 as primary, Kaggle as backup; Drive checkpointing every epoch; Colab Pro only if real throttling occurs near a training deadline. | Reflected in 02 and 06. |
| Reproducibility is non-negotiable: fixed seeds, versioned notebooks, pinned dependencies, archived checkpoints per training run. | Global definition of done in 06; model registry in 02 and 05. |
| Second annotator identity is unresolved. | Recorded as the highest-priority open item; blocks the inter-annotator agreement claim. |

---

## 4. Proposals awaiting confirmation (not settled; owner: Maaney, confirmer: Dr. Rajabi unless stated)

| # | Proposal | Where it appears | Why it is not settled |
| --- | --- | --- | --- |
| P-1 | Model serving for FYP2: develop and demo the FastAPI service locally; deploy to a free CPU host only if the user study requires remote access. Options analysed in 02 s.6. | 02, 06 | Chapter 3 specifies FastAPI but not a hosting environment. |
| P-2 | All buyer-facing database access is mediated by FastAPI holding the Supabase service key server-side; the browser never queries buyer data directly. Alternative (Supabase anonymous sign-in with RLS) analysed in 05 s.7. | 02, 05 | Chapter 3 does not specify the auth topology for anonymous buyers. |
| P-3 | Guest sessions identified by a server-issued opaque session token (httpOnly cookie) to satisfy NFR-05 and FR-13 without accounts. | 03, 05 | Same as P-2. |
| P-4 | Inter-annotator agreement working target: Cohen's kappa at or above 0.61 (conventional "substantial" threshold, Landis and Koch, 1977), with the achieved value reported regardless. | 06 | Chapter 3 commits to reporting agreement but states no numeric threshold. A target must be agreed before the pilot is judged. |
| P-5 | API contract in 02 s.5 (submit, poll status, fetch result, feedback, admin endpoints). | 02, 03, 05 | New engineering detail; consistent with the sequence diagram intent but not specified in Ch3. |
| P-6 | Database schema in 05, including a separate `research` schema for the labelled dataset and study data. | 05 | Ch3 Table 3.7 defines field groups, not tables; the class diagram is a figure without extractable field lists. |
| P-7 | Design tokens (palette, type scale, spacing) in 04. | 04 | Ch3 fixes principles, not tokens. |
| P-8 | Relative-week schedule W1 to W13 in 06, anchored to DSR phases. | 06 | Official FYP4999 June 2026 session calendar dates not present in the project files read this session. |

---

## 5. Open items (must be resolved; failure to resolve is an examiner-level risk)

| # | Item | Blocks | Priority | Action |
| --- | --- | --- | --- | --- |
| O-1 | Second annotator identity and commitment | Pilot kappa, the entire inter-annotator agreement claim in Chapter 3, dataset scaling | Critical | Name a specific person, confirm availability across the collection window, record in the annotation log. Escalate to Dr. Rajabi if unresolved within one week. |
| O-2 | Official FYP2 calendar dates (session start, submission, presentation) | Converting W1 to W13 into dates; judging whether the weeks 1 to 2 recruitment window has already passed | Critical | Confirm against the FYP4999 June 2026 session calendar or with Ms. Sarasvathi. |
| O-3 | Whether INTI requires a formal ethics form or approval for the user study beyond supervisor sign-off | User study start | High | Ask Ms. Sarasvathi / Dr. Rajabi; the Documentation I brief lists ethics considerations but no approval workflow was located in the project files. |
| O-4 | Numeric value of the "approved retention period" referenced by NFR-05 | Privacy audit, retention notice text on Screen 1 and Screen 2 | High | Confirm with Dr. Rajabi and record the number; the documents use the placeholder "the approved retention period" until then. |
| O-5 | Licence terms of the pretrained model weights to be used (CLIP variant, SSCD weights, XLM-RoBERTa base) | Legitimate use in a university prototype; report acknowledgements | High | Verify each licence at the source repository before Phase B training begins; record in the model registry. No licence is asserted in these documents. |
| O-6 | Current Supabase free-tier limits (storage, row, bandwidth, project pausing behaviour) | Storage budgeting for images; study data safety | Medium | Check supabase.com/pricing at Phase D start; design assumes free tier but no specific quota figures are asserted. |
| O-7 | Risk band boundaries (Low / Moderate / High cut points) | Result screen copy | By design deferred | Fixed after calibration on validation data and stated in the evaluation report, per Ch3. Not to be invented earlier. |
| O-8 | Confirmation that supervisor sign-off on Ch3 sections 3.3.7 to 3.3.9 was recorded (the chapter notes those sections required confirmation before submission) | Record hygiene only | Low | One-line confirmation from Dr. Rajabi in writing. |

---

## 6. Errata awareness (frozen documents; do not silently correct, do not repeat)

| Location | Issue | Handling |
| --- | --- | --- |
| Ch3 s.3.3.7 | Text reads "calibrated to the 0 - 10 scale". Every other statement (FR-08, Objective 2, s.3.1.1, s.3.3.8) says 0 to 100. | 0 to 100 is authoritative in all new documents. Prepare a one-sentence viva answer acknowledging the typo if raised. |
| Ch3 s.3.1.7 prose | Percentages in prose occasionally disagree with the tables (differing n bases; a known item on the personal fix list for 3.1.7). | These documents cite table values only. |

---

## 7. Change control

Any change to a locked item (architecture, stack, requirements, methodology, statistics) requires Dr. Rajabi's agreement and a dated entry here before any document is edited. Proposals in s.4 convert to decisions only when a confirmation date and confirmer are recorded against them.
