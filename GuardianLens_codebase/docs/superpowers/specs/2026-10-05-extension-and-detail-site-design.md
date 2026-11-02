# GuardianLens: Browser Extension and Detail Site Design

> Note (2026-10-15): the admin page and Supabase mentioned below were removed. See `docs/CHANGES_FROM_SPEC.md`.

**Date:** 2026-10-05
**Status:** Draft for review. Brainstormed with the developer; the four design sections below were each approved in conversation.
**Revision (same day):** the developer directed that the trained models in `GuardianLens_Training` be used and that useful work from the Data Collector and URL Crawler be reused inside this codebase. Section 8 (model serving) is new, and sections 2, 3, 5, 9, 10, 11, and 12 changed accordingly.
**Scope change:** The PRD (section 3.3) and Chapter 3 (s.3.1.7) list a browser extension as future work and out of FYP2 scope. The developer reports that the supervisor approved the extension on 2026-10-05, and that documentation updates wait until implementation is finished. The PRD, flow, and design documents in `docs/spec/` are therefore stale on this point and are updated in the documentation phase, not here.

---

## 1. Goal and success criteria

**Goal.** A buyer viewing a Mudah.my or Carousell listing clicks the GuardianLens extension icon. The extension captures that one listing, lets the buyer review it, runs the existing assessment pipeline, and shows the result in a side panel. A website carries the detailed explanation and acts as the fallback and study entry through its manual form.

**Success criteria**
1. From a supported listing page, a buyer reaches a score, band, three signal cards, and the disclaimer in two clicks (icon, then Check listing) with no re-typing.
2. Every captured field is visible to the buyer, labelled Captured or Not found, and editable before submission.
3. "See full explanation" opens the same assessment on the website without a login.
4. The manual form still works end to end for pasted or stored listings.
5. All binding rules from `docs/spec/04_Design_Brief_UI_UX.md` section 1 hold on both surfaces (text plus number plus icon for risk, visible uncertainty, integer score, disclaimer wherever a score shows, retention note beside the submit control, errors never discard input, WCAG 2.1 AA).
6. Until real models are served, every score carries the existing development-stub warning.

## 2. Decisions fixed in brainstorming

| Decision | Choice | Reason |
|---|---|---|
| Website role | Detail site plus manual fallback | Frozen hold-out study listings cannot be captured live, and capture can fail on a layout change |
| Hosting | Developer laptop now, API base URL configurable, hosted later | Models stay warm, zero cost; hosting decided at the end of the build (TDD s.6 option A, then B if needed) |
| Capture approach | DOM adapters per platform plus a Review step | Free, instant, user-controlled; the Review step stops a wrong selector from becoming a silently wrong score |
| Buyer identity | Anonymous opaque session token; no buyer accounts | Spec requirement (proposal P-3); accounts add personal data, ethics, and retention burden |
| Database | In-memory repository first, Supabase for study and deployment | Matches TDD s.7 topology A (API-mediated) |
| Admin auth | Supabase Auth with `profiles.role = 'admin'` replaces the dev token | Existing spec commitment |
| Language | English UI only | Existing design brief scoping statement |
| Capture boundary | On the buyer's click only, one listing, no crawling, no background scraping | Carried from the pinned scope note |
| Models served | The frozen run `20261002_062026_colab_v3_noMeta` from `GuardianLens_Training` (V, T, B, fusion, calibrator, bands) | These are the evaluated models; section 8 |
| Reuse from Collector and Crawler | Port, never import: DOM heuristics, seller-field conventions, and listing-URL patterns | Real-page-tested logic and train/serve feature parity; the crawl, pagination, and LLM-extraction code stays out |
| Categories | Free text. The 12 categories the models were trained on are suggestions only, and any other category is accepted | Developer decision: no category limiter. The behavioural model degrades gracefully on an unseen category (section 8.4). This deliberately overrides the Design Brief's Choice Overload row, which called for a curated list with no free-text taxonomy. |
| Model run served | The latest run in `GuardianLens_Training/runs`, `20261002_062026_colab_v3_noMeta` | Chosen after reviewing every run (section 8.1) |

## 3. Architecture and data flow

```
 Mudah / Carousell tab                 Extension (MV3)                      Local backend
 +---------------------+   click   +--------------------------+        +-------------------+
 | listing page        |---------->| Side panel (React)       | fetch  | FastAPI :8000     |
 | adapter runs here   |<--capture-| Idle>Review>Check>Result |------->| /api/v1/assess... |
 +---------------------+ (on click)| Service worker (thin)    |        | in-memory repo    |
                                   | runs adapter, opens panel|        | (Supabase later)  |
                                   +-----------+--------------+        +-------------------+
                                               | "See full explanation"           ^
                                               v  (session handoff)               |
                                   +--------------------------+                   |
                                   | Website (Next.js :3000)  |-------------------+
                                   | landing, detail, history,|
                                   | manual form, admin       |
                                   +--------------------------+
        shared/ = types + API client + design tokens + ScoreDial / BandChip / SignalCard
```

### 3.1 Repository layout

```text
GuardianLens_codebase/
  extension/   WXT + React + TypeScript, Manifest V3, side panel, adapters
  frontend/    existing Next.js site, repurposed
  shared/      types, API client, design tokens, presentational components
  api/         existing FastAPI service with additive changes
```

WXT is the intended extension framework. Its current documentation, and the Chrome side panel and host-permission behaviour assumed below, are confirmed against the docs when the implementation plan is written.

### 3.2 Units and boundaries

| Unit | Purpose | Interface | Depends on |
|---|---|---|---|
| Listing URL classifier | Decide whether the active tab is a supported listing page and extract its platform and marketplace listing id | `classify(url) -> { platform, listingId } or null`; patterns ported from `URL_Crawler/url_utils.py` (Carousell `/p/<slug>-<id>`, Mudah `<slug>-<id>.htm`) | Nothing |
| Platform adapter (`mudah`, `carousell`) | Read one listing from the live DOM | `capture(document) -> CapturedListing`; each field is `{ status: "found" or "not_found", value }`; heuristics ported from the Collector's `extension/background.js` (h1 title, JSON-LD and price nodes, visible gallery images, seller links, block-page detection) | The page DOM only |
| Seller parsers | Turn seller text into the numeric fields the behavioural model was trained on, using the Collector's conventions (section 8) | `parseSeller(text) -> { accountAgeDays, rating, reviewCount, activeListingCount }` | Nothing |
| Capture runner | Inject the adapter on click and return its result | `runCapture(tabId) -> CapturedListing` | `activeTab`, `scripting` |
| Image preparer | Fetch up to 3 photos and re-encode to JPEG of 5 MB or less | `preparePhotos(urls) -> File[]` | Host permission for image CDNs |
| Side panel app | State machine: not-on-listing, review, checking, result, error | Renders from `shared/` components | API client, capture runner |
| Service worker | Open the panel, run capture; no long-lived state | Message handlers | Capture runner |
| API client (`shared/`) | Typed calls to `/api/v1`, header or cookie transport | `createClient({ baseUrl, transport })` | `fetch` |
| Website | Landing, manual form, detail pages, history, admin | Next.js routes | `shared/` |

### 3.3 Click-to-result flow

1. The buyer opens a supported listing and clicks the icon; the panel opens and the adapter is injected through `activeTab` plus `scripting`, never as a static content script.
2. The adapter returns the captured fields and photo URLs. The panel shows the Review state.
3. The buyer edits as needed and presses Check listing. The image preparer fetches and re-encodes up to 3 photos.
4. The panel sends `POST /api/v1/assess` with the session token header, then polls `/status` through the five stages.
5. On completion the panel fetches `/result` and shows the summary.
6. "See full explanation" opens the website on the same assessment (section 4.2).

### 3.4 Open items for the real-page spike (slice 0)

The spike resolves these against real pages before adapter code is trusted:

- Which fields each platform exposes on the listing page.
- Which image CDN hosts the extension needs host permission for.
- Whether the listing page carries any seller card text. The Collector's extraction contract takes account age, rating, review count, and active-listing count from the seller profile page, not the listing page, so the working assumption is that they are only on the profile page (see the optional second capture in section 5).
- Whether Carousell route changes keep the `activeTab` grant, and what the panel shows when the grant lapses.

## 4. Backend changes (small and additive)

Current behaviour: a session is a UUID in an httpOnly cookie, created lazily on the first `POST /assess`; ownership compares it to the assessment's session; CORS allows only `Content-Type` and `X-Admin-Token`.

### 4.1 API additions

| Change | Detail |
|---|---|
| `POST /api/v1/session` | Creates a session and returns `{ session_token }`. Used by the extension on first run. |
| Session transport | `parse_session` reads `X-Session-Token`, falling back to the cookie. The ownership rule is unchanged. |
| `POST /api/v1/session/claim` | Accepts a token in the body and sets the httpOnly cookie for that session. Returns 204. Unknown tokens return the generic not-found envelope. |
| `POST /assess` fields | Optional `source` (`extension` or `manual`, default `manual`) and `capture_meta` (JSON: per-field status of captured, edited, or not found; adapter version; platform host). `capture_meta` never feeds the score. |
| CORS | Allow the `X-Session-Token` header for the website. The extension reaches the API through its host permission. |

`capture_meta` stores the platform host only, never the listing URL, so the "anonymised metadata only" retention promise holds. Photos continue through the existing re-encode that strips metadata.

### 4.2 Session handoff to the website

"See full explanation" opens `/assess/{id}/explanation#st=<token>`. The page reads the URL fragment (which never reaches server logs) and removes it at once with `history.replaceState`. It then asks the visitor to confirm linking this browser to the extension's session, and only after a yes calls `/session/claim`. The confirmation exists because anyone can craft a link with their own token; claiming silently would move the visitor into the sender's session (session fixation). From then on the website uses the cookie as it does today. The extension and the website share one session, so History lists checks from both. On the server, `/session/claim` and every cookie-authenticated write (`/assess`, cancel, feedback) refuse a browser request whose `Origin` is not one of the configured website origins, so a page on another site cannot bypass the confirmation by calling the API directly.

If the backend restarts, in-memory sessions disappear. The extension treats a `not_found` response as a signal to mint a new session, not as a user-facing error.

### 4.3 Known limitation

`POST /session` needs no authentication and is not throttled, and the rate limiter is keyed by session, so every freshly minted session gets a fresh allowance. In effect the per-session rate limit does not bound a determined client at all. A client can submit as fast as it can mint (measured: 15 submissions with 15 fresh tokens all accepted), which costs the server image processing and memory (the in-memory repository keeps up to 3 re-encoded images per submission), fills the research records with arbitrary content, and grows the limiter's own bookkeeping without bound. This already holds for the cookie flow and is acceptable only while the API runs on the developer's laptop. Before any hosted deployment add a coarse per-IP limit or a global cap on minting and submission, expire idle sessions and limiter entries, and mint a session only after a submission validates. Session tokens are long-lived bearer secrets with no expiry or revocation; a hosted store should keep only a hash of each token. The `source` and `capture_meta` fields are asserted by the client, so they are self-reported telemetry for the research export, not proof of how a record was captured. See `docs/superpowers/audits/2026-10-extension-security-review.md`.

## 5. Extension UI (side panel)

A single column about 360 to 420 px wide, using the existing design tokens and the same components as the website.

| State | Content |
|---|---|
| Not on a listing | Wordmark, "Open a Mudah.my or Carousell listing, then click the icon." Links to This session and the website, then a short list of what the three checks look at. |
| Review | Up to 3 photo thumbnails (removable, swappable if more were found); editable title, price, description, platform, and category. Category is a free-text combobox prefilled with the platform's own category text, with the 12 trained categories (Phones, Gaming, Home Appliances, Laptops, Fashion, Audio, Cameras, Sports, Wearables, Tablets, Collectibles, Other) offered as suggestions and no restriction on what can be typed. When the category is not one of the trained 12, a plain note says the price is compared with the overall average rather than the category average. Each field is labelled Captured or Not found in text. A collapsed "Seller information (optional)" group states that missing seller fields are treated as unknown, not suspicious. It offers an **Add seller details** action: if the buyer opens the seller's profile page and clicks the icon there, the panel reads the seller fields from that page and merges them into the draft. This stays click-only, with no automatic navigation, and a second listing is never captured. The retention notice sits beside the sticky Check listing button. The panel states "Captured from this page when you clicked." |
| Checking | Five labelled stages in a polite live region, a Cancel text button, an honest "taking longer than usual" line after a threshold, no percentages. |
| Result | One bounded region holds the score, band chip, and disclaimer. Below: three compact signal cards, any missing-data notice, and the single most protective check ("Verify the seller independently, for example with Semak Mule"). Then a Was this helpful? prompt. Primary action: See full explanation. Secondary: Check another listing. |
| Errors | Unsupported language appears as a field error in Review with input kept. Unreachable service: "Can't reach the GuardianLens service. Is the local server running?" with Retry. Failed or partial capture: Review with fields marked Not found plus a link to the website form. Rate limit: a plain message. |

**Rules carried from the design brief:** integer score; risk shown by text, number, and icon; the disclaimer is content inside the result region, not a banner; unavailable signals use the fixed sentence "Not enough information. Treated as unknown, not as suspicious."; reduced-motion respected.

**Verification widths:** 360 and 420 px for the panel; 375, 768, and 1440 px for the website.

## 6. Website changes

| Area | Change |
|---|---|
| Landing | Install-first: "Get the extension" with load-unpacked steps for the demo, then the three explainer blocks. "Enter a listing manually" is secondary. |
| `/assess` | Unchanged. Fallback and study entry. Sends `source=manual`. |
| Result and explanation pages | The detail surface for both sources. All suggested checks, evidence scope notes, reasons beyond the top three, feedback. They perform the session claim. |
| History | Lists extension and manual checks of the shared session. |
| Admin | Unchanged for now. Records and exports gain a `source` column. |
| Deferred | Study mode that loads a stored hold-out listing. Needed for the user study, not for the first slice. |

## 7. Database and auth plan

1. Build and demo against the in-memory repository.
2. Implement `api/repositories/supabase.py`, after applying `db/migrations` to a disposable Supabase project and verifying every table, policy, trigger, and private bucket.
3. Replace `X-Admin-Token` with Supabase JWT verification in FastAPI plus a `profiles.role = 'admin'` check.
4. Buyers never authenticate. The extension and website talk only to FastAPI, so neither holds a Supabase key.

## 8. Model serving (slice 6 in detail)

### 8.1 What exists

Every run in `GuardianLens_Training/runs` was reviewed (read from each run's `run.json` and `validation_metrics.json`):

| Run | Created | T signal | V signal | Fusion validation AUC | Test used | Status |
|---|---|---|---|---|---|---|
| `20261001_133604_colab` (v1) | 2026-10-01 13:36 | XLM-R fine-tune (collapsed, single-signal AUC 0.53) | plain | 0.658 | no | Superseded |
| `20261001_143328_colab_v2` | 2026-10-01 14:33 | text cues | plus image metadata | 0.791 | no | Superseded: the training audit found part of this score came from dataset-only features |
| `20261002_060742_colab_v3` | 2026-10-02 06:07 | text cues | plus image metadata, audit-fixed | 0.701 | no | Superseded: the metadata added nothing measurable |
| `20261002_062026_colab_v3_noMeta` | 2026-10-02 06:20 | text cues | plain | 0.706 | yes (once) | **Latest, served** |

The latest run exists in two local copies. `runs/final_test_results/20261002_062026_colab_v3_noMeta` is the later state (it includes `test_metrics.json` and `test_predictions.csv`) and is the reference copy; `runs/run_results_v3/20261002_062026_colab_v3_noMeta` is the pre-test copy. Choosing the latest also happens to be the methodologically sound choice, because the higher v2 score is not comparable.

The latest run's config, seed 42, and library versions are recorded in its `run.json`.

| Component | What it is |
|---|---|
| V (visual) | CLIP ViT-B/32 photo-title consistency plus SSCD copy detection against a train-only reference corpus, logistic head. Plain V, no image-metadata features. |
| T (textual) | TF-IDF plus text cues, logistic. It replaces the XLM-R fine-tune, which collapsed (validation AUC 0.53). This is a documented deviation that needs supervisor sign-off. |
| B (behavioural) | XGBoost on price, price-to-category ratio, account age, rating, review count, active listings, and missingness flags. TreeSHAP for reasons. |
| Fusion | Logistic regression on out-of-fold V, T, B scores plus availability flags (C = 0.3), then sigmoid calibration. |
| Bands | Low below 0.163, Moderate from 0.163, High from 0.467 (calibrated probability; validation-derived in `fusion.json`). |

Recorded results: fusion ROC AUC 0.706 on validation and 0.799 on the sealed test split (evaluated once, entry in the ledger). The labels are AI-annotated risk (suspicious or scam), not confirmed fraud.

### 8.2 Where run results are stored

| Location | Holds | Evidence |
|---|---|---|
| Google Drive, `MyDrive/GuardianLens_runs/<run_id>/` | The full run: `models/B.joblib`, `V.joblib`, `T.joblib`, `fusion.joblib`, reports, figures | The Colab notebooks symlink `runs/` to this folder, and `GuardianLens_Colab_final.ipynb` asserts these four files exist before it scores the sealed test |
| Google Drive, `MyDrive/GuardianLens_cache` | The feature cache, including the V signal's CLIP and SSCD features. `V.joblib` holds only the head and rebuilds features from this cache. | Notebook setup cells; `gl/pipeline.py` |
| Google Drive, `MyDrive/GuardianLens_runs/_evaluations` | The sealed-test ledger | Notebook setup cells |
| `GuardianLens_Training/runs/` (this laptop) | Downloaded copies without the model files: predictions, reports, figures | Every notebook's download step excludes `models`, `*.joblib`, and `xlmr` |

So the fitted artifacts for the latest run existed on Drive when the sealed test ran on 2026-10-02, but they are not on this laptop. A search of `cusmanka121@gmail.com`'s Drive through the connector found no `GuardianLens_runs` folder or joblib files, so Colab was probably run under a different Google account, or the folder was moved or deleted.

### 8.3 Plan

1. **Recover the original artifacts from Drive first.** The developer checks `MyDrive/GuardianLens_runs/20261002_062026_colab_v3_noMeta/` (and `GuardianLens_cache`) in the Google account Colab ran under, and downloads `models/` and `fusion.joblib`. Recovered originals are the evaluated model exactly, so the recorded test result (AUC 0.799) applies with no further check beyond verifying their hashes and the golden test in section 10.
   **Fallback: regenerate on Colab** only if the originals are gone, using the frozen config, seed, and library versions from `run.json`. Regeneration trains no new variant and never reads test labels; the sealed test is not re-run. Colab, not the laptop, because the project's training rule is Colab only.
   **Acceptance check for a refit.** Its validation predictions are compared with the frozen run's local `val_predictions.csv` and `oof_predictions.csv`, with the tolerance written down before the run. If they match, the refit is the frozen model and the recorded test result applies. If they differ, the difference is reported, and the refit is a new candidate that cannot inherit the sealed-test result or be described as the evaluated model.
2. **Add an export step in the training workspace** (which owns the `gl` code) that writes a self-contained bundle: the four joblibs, the SSCD descriptor matrix and group ids of the train reference corpus, the category price baselines, the calibrator, the band boundaries, the config, and a manifest with SHA-256 hashes and library versions. The `ml/` bundle schema in this codebase currently names an XLM-R checkpoint and is amended to describe the text-cue model.
3. **Serving adapter** in `api/services`, behind the existing stage interfaces in `ml/contracts.py`. It scores one in-memory listing (title, description, price, category, platform, up to 3 images, seller fields) with no dependency on the dataset folder.
4. **Explanations** reuse `gl/explain.py` (SHAP, CLIP, and SSCD results to buyer-facing sentences), mapped onto `SignalCard.reasons`. Any wording that names XLM-R is replaced.
5. **Latency and environment.** Measure all stages on the laptop CPU against the 10-second budget with 1 to 3 images. First run downloads CLIP weights (Hugging Face) and the SSCD TorchScript file once. Pin scikit-learn and xgboost to the training versions, because the artifacts are pickles, and load only artifacts we created.
6. **Remove the stub banner** only when the bundle loads, its hashes verify, and the band boundaries are present.

### 8.4 Feature parity

The behavioural and text models were trained on fields that an LLM extracted under the Collector's contract. The extension has no LLM, so deterministic parsers must reproduce the same conventions or the models see inputs unlike their training data:

- Account age in days: 1 year = 365 days and 1 month = 30 days from a stated duration, or days between a stated join date and today.
- "No reviews yet" gives review count 0 and rating 0.0.
- Active listings is the count of non-SOLD entries under the Listings section; a Listings header with no entries is 0.
- Price is a number parsed from RM text; platform is `mudah` or `carousell`.
- Category is free text. The behavioural model computes its price ratio against a per-category median fitted on the training split, and a category it has not seen falls back to the overall median (`BehaviouralFeatures.transform` in `gl/features.py`), so any category is accepted without an error. The adapter prefills the platform's own category text and matches it to a trained category with a small keyword table (new code; the Collector has no such table, because its categories came from its crawl plan). Unmatched categories are passed through unchanged. The V and T signals do not use category.

Parser tests use the Collector's recorded examples and the real-page fixtures from slice 0.

### 8.5 Interface copy constraints

- The score is a calibrated probability of annotated risk, not confirmed fraud, and the "what this means" text must say so.
- The Moderate band is wide: at the frozen boundaries it flagged about 72 to 74 percent of listings (precision about 0.33), while High flagged about 9 to 11 percent (precision about 0.60 to 0.64). Moderate copy must not read as a strong warning, and Low must never read as safe.
- Text-signal wording must describe text cues, not XLM-R, until the supervisor decides how the deviation is reported.

## 9. Build order

| # | Slice | Done when |
|---|---|---|
| 0 | Real-page spike (section 3.4) and sanitised HTML fixtures | Adapter notes and fixtures exist |
| 1 | `shared/` package, extension skeleton, `/session` and `/session/claim` | Panel opens, token round-trips, pytest passes |
| 2 | Adapters and the Review state, tested against fixtures | Fields captured or marked Not found on fixtures |
| 3 | Check, Checking, Result against the stub API, plus error states | Click-to-score works end to end |
| 4 | Website: landing, handoff, detail pages, history, `source` in admin | See full explanation opens the same result |
| 5 | Supabase repository, verified migrations, admin JWT auth | Persistent, study-grade storage |
| 6 | Real inference: Colab export of the frozen bundle, serving adapter, explanations, latency check (section 8). The Colab export has no dependency on slices 1 to 4 and starts as soon as the artifact recovery in section 8.3 step 1 is settled. | Stub banner removed, bundle hashes verified |
| 7 | Hardening: security review, UX-laws and WCAG re-run at panel widths, latency check, packaged extension | Audits recorded |

**Planning split.** This spec records the whole roadmap, but the first implementation plan covers slices 0 to 4 only (the extension, the handoff, and the website, all running on the stub API). Slice 5 (persistence and admin auth) and slice 6 (real inference) are independent subsystems with their own dependencies, so each gets its own short brief and plan. Slice 7 runs after them, with a first pass on slices 0 to 4 before slices 5 and 6 begin.

## 10. Testing

- Backend: the existing pytest suite plus new tests for session header transport, claim, and ownership (including cross-session denial and unknown tokens).
- Adapters and shared code: vitest against the HTML fixtures, including missing-field cases.
- UI: Playwright loads the unpacked extension and opens the side-panel page directly in a tab (Playwright cannot click the toolbar icon), and covers the website flows.
- Manual smoke on three to five live listings per platform.
- The `security-reviewer` agent reviews the session and claim endpoints before slice 4 completes.
- Model serving: a golden test scores a handful of frozen validation listings through the serving adapter and compares the result with the training run's `val_predictions.csv`; parser tests per section 8.4.

## 11. Risks

1. **The fitted model artifacts are not on this laptop** (section 8.2). They should be on the Google Drive Colab ran under, so recovery comes first. Only if they are gone are they regenerated on Colab from the frozen config, which costs one Colab session and must not read test labels. Pickle compatibility needs matching library versions. Supervisor decisions still pending (text cues instead of XLM-R, the annotated-risk target) affect how the result is described, not what is served. Until the bundle loads, every score is a labelled stub.
2. **Seller fields come from the seller profile page**, by the Collector's own contract, so a listing-page capture alone leaves the behavioural signal mostly unknown. The optional Add seller details action (section 5) addresses this, and the real-page spike confirms whether any seller text is on the listing page.
3. **Platform terms of service.** Click-only, single-listing capture with a visible Review step is the defensible boundary. Confirm the supervisor's approval covers it and record his wording for the report.
4. **Layout changes** on either platform break an adapter. Fixtures detect it in tests and the manual form is the fallback.
5. **OneDrive sync** of `node_modules` and build output may slow installs; keep build output out of synced paths where practical.

## 12. Out of scope

URL-paste ingestion, screenshot OCR, crawling or background capture (the Crawler's pagination, show-more, and overlay logic is not reused), LLM-based field extraction in the buyer path, platform integration, community reporting, buyer accounts, cross-login history, Facebook Marketplace, Malay UI, Chrome Web Store publication, and the hosted deployment (decided at the end of the build).

*Updated 2026-11-02: the panel's wording, names and look follow `.impeccable.md` and `docs/CHANGES_FROM_SPEC.md`; a captured field shows no status line (only "Edited by you" or "Not found" do), and the three checks are Photos, Wording and Seller and price.*
