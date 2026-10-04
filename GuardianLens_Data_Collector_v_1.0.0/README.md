# GuardianLens Data Collector v_1.0.0

Manual marketplace listing capture, CSV URL batch replay, AI-assisted field extraction, privacy processing, duplicate checks, product-image storage, human review, and approved-dataset export for GuardianLens FYP2.

This package implements **data collection only**. It intentionally does not contain fraud labels, train/validation/test splitting, model training, fraud scoring, calibrated AI confidence, or an unattended marketplace crawler.

Dashboard totals come from stored collection state and refresh automatically. Expand the
sections for detailed counts, capture logs, review history, provider settings, and local
tools. Expansion choices persist for the browser tab; a disconnected update is clearly
marked while the last stored snapshot remains visible. See the
[workspace cleanup report](docs/WORKSPACE_CLEANUP.md) for the repository map and verification.

## 1. Core rule

The collection boundary is deliberate. Manual and CSV modes converge at the existing capture request:

```text
         MANUAL MODE                         CSV REPLAY MODE
YOU choose and open a listing          YOU upload/paste listing URLs
YOU click Capture Current Listing      Stage 1 writes a viewable validated URL CSV
YOU capture seller behaviour           Stage 2 captures only rows from that file
                 \                         /
                  SAME CaptureRequest boundary
                              ↓
captured staging + durable checkpoints (no preprocessing during capture)
                              ↓
Stage 3 batch processor: default maximum 50 records / 60 minutes
        ↓
AI extraction: page text is the PRIMARY source (listing text -> product fields, seller text ->
account_age_days/seller_rating/review_count/active_listing_count); the screenshots are SECONDARY
proof only, never a data source (OpenAI, Anthropic, OmniRoute, or Gemini — set by AI_PROVIDER)
        ↓
PII scrub + validation + duplicate/image checks
        ↓
ready_for_review / needs_attention
        ↓
YOU review and correct
        ↓
approve / reject / skip / flag
        ↓
approved dataset
```

The extension never searches marketplaces, follows pagination, discovers listing URLs, or chooses products for you. Manual capture remains available. In CSV replay, it opens only the supplied URL and may follow that listing's seller/profile link solely to preserve the existing behavioural signal; it never follows recommendations or other listing links.

## 2. Dataset target

Collection is complete. Final approved dataset:

- Total approved listings: **2,209**
- Carousell Malaysia: **1,410 (64%)**
- Mudah.my: **799 (36%)**
- Only `approved` records count.
- Captured, processing, waiting-for-review, skipped, flagged, rejected, and failed records do not count toward the total.

The collector's original plan targeted 2,500 (1,500/1,000); that plan was scoped down once
collection stabilized at the counts above, which are now the project's final dataset size —
there is no further collection planned against a larger number.

Category targets are configurable in `config/categories.yaml`.

## 3. What is included

```text
GuardianLens_Data_Collector_v_1.0.0/
├── main.py                         # production server entry point
├── environment.yml                # Conda environment
├── requirements.txt               # pip mirror of runtime/test dependencies
├── .env.example                   # secret/config template
├── setup.bat                      # Windows Conda setup
├── run.bat                        # Windows production run
├── config/
│   ├── categories.yaml            # configurable category mix
│   └── platform_targets.yaml      # final dataset targets (2,209 / 1,410 / 799)
├── extension/
│   ├── manifest.json              # Chrome Manifest V3
│   ├── background.js              # shared manual + queued-browser capture
│   ├── popup.html
│   └── popup.js
├── src/guardianlens/
│   ├── app.py                     # FastAPI app and dashboard/review routes
│   ├── batch.py                   # start/pause/resume/stop + recovery
│   ├── capture.py                 # shared CaptureRequest staging boundary
│   ├── replay.py                  # CSV parsing, persistent queue, replay orchestration
│   ├── config.py
│   ├── db.py
│   ├── schema.sql
│   ├── states.py                  # listing state machine
│   ├── openai_extractor.py        # OpenAI screenshot extraction adapter
│   ├── anthropic_extractor.py     # Anthropic screenshot extraction adapter
│   ├── omniroute_extractor.py    # OmniRoute local gateway adapter
│   ├── gemini_extractor.py        # Gemini screenshot extraction adapter
│   ├── extraction_contract.py     # shared schema/prompt rules for all providers
│   ├── provider_info.py           # per-provider model listing
│   ├── errors.py                  # provider error classification (auth/quota/other)
│   ├── models.py                  # request/response Pydantic models
│   ├── security.py                # local collector token
│   ├── release.py                 # release-zip secret exclusion
│   ├── pii.py                     # PII scrub + residual checks
│   ├── images.py                  # validation, hashes, storage
│   ├── dedupe.py                  # URL/metadata/image duplicate helpers
│   ├── planner.py                 # platform/category recommendations
│   ├── processor.py               # post-capture processing pipeline
│   ├── review.py                  # human edit/actions + atomic approval
│   ├── exports.py                 # approved-only export
│   ├── annotation_dataset.py      # atomic annotation-handoff CSV views
│   ├── audit.py                   # security/data-integrity audit
│   ├── templates/                 # local dashboard and review UI
│   └── static/
├── scripts/
│   ├── init_db.py
│   ├── self_test.py
│   ├── run_tests.py
│   ├── run_soft_test_server.py
│   ├── reset_soft_test.py
│   ├── soft_test_csv_pipeline.py      # persistent isolated 5+5 staged-pipeline check
│   ├── mock_integration_check.py
│   ├── security_audit.py
│   ├── data_integrity_audit.py
│   ├── export_approved.py
│   ├── verify_approved_live.py        # verify approved records against live marketplace pages
│   ├── refresh_annotation_dataset.py
│   ├── manifest.py
│   ├── build_release_zip.py
│   └── verify_fresh_release.py
├── data/
│   ├── private/
│   │   ├── replay_batches/           # viewable Stage 1 URL files, one per batch
│   │   ├── screenshots/           # temporary/private evidence
│   │   └── staging/               # private staged capture info
│   ├── images/
│   │   ├── carousell/             # long-term dataset product images
│   │   └── mudah/
│   ├── temporary/
│   ├── exports/
│   ├── reports/
│   └── soft_test/                 # isolated soft-test DB + runtime assets
├── tests/
├── docs/
└── logs/
```

Empty runtime folders contain `.gitkeep` so the structure survives ZIP extraction and Git.

Every CSV upload and manual URL import creates:

```text
data/private/replay_batches/<batch_id>/stage_1_urls.csv
```

The dashboard provides **Open CSV** and **Download CSV** controls. This UTF-8 CSV contains
the normalized URL, detected platform, optional category, source row, validation outcome,
capture-ready flag, and durable queue item ID. Treat it as view-only: the collector verifies
it against SQLite before capture and refuses to proceed if it was edited. Existing batches
receive this file automatically when GuardianLens starts. In soft-test mode, the same artifact
is isolated under `data/soft_test/runtime/private/replay_batches/`.

---

# 4. Required software

Recommended Windows setup:

1. Windows 11
2. Miniconda or Anaconda
3. Google Chrome
4. Internet connection for AI processing and remote product-image download
5. An API key for at least one of: OpenAI, Anthropic, OmniRoute, Gemini. Pick the active one with `AI_PROVIDER` in `.env`; you can also switch it live from the dashboard.
6. Node.js is optional. It is used only by `scripts/self_test.py` to syntax-check extension JavaScript if installed.

Python is installed inside the Conda environment. You do not need to depend on your global Python installation.

---

# 5. First-time setup with Conda

Open **Anaconda Prompt** or a terminal where `conda` works.

```bat
cd path\to\GuardianLens_Data_Collector_v_1.0.0
setup.bat
```

The setup script does this:

```text
conda env update -f environment.yml --prune
copy .env.example .env      (only if .env does not already exist)
initialize SQLite
create/verify local collector token
run structural self-test
```

From PowerShell, run the same batch file as `.\setup.bat`. It does not require a
PowerShell execution-policy change.

## Manual Conda commands

If you prefer to see each command:

```powershell
conda env create -f environment.yml
conda activate guardianlens-collector
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python scripts/init_db.py
python scripts/self_test.py
python scripts/run_tests.py
```

If the environment already exists:

```powershell
conda env update -f environment.yml --prune
conda activate guardianlens-collector
```

---

# 6. Configure `.env`

Open `.env`, set `AI_PROVIDER` to the one you're using, and fill in only that provider's key
(the other three can stay blank):

```env
AI_PROVIDER=openai
OPENAI_API_KEY=your_real_key_here
OPENAI_MODEL=gpt-5.6-luna
OPENAI_PROMPT_VERSION=collector_v1
HOST=127.0.0.1
PORT=8770
OPERATOR_TIMEZONE=Asia/Kuala_Lumpur
SCREENSHOT_RETENTION=review_only
MAX_PRODUCT_IMAGES=12
MAX_IMAGE_BYTES=12582912
IMAGE_MIN_WIDTH=160
IMAGE_MIN_HEIGHT=160
REQUEST_TIMEOUT_SECONDS=45
MAX_CAPTURE_ATTEMPTS=2
CAPTURE_PAGE_TIMEOUT_SECONDS=45
CSV_IMPORT_MAX_ROWS=10000
CSV_IMPORT_MAX_BYTES=5242880
GUARDIANLENS_MODE=production
```

The `*_MODEL` defaults in `.env.example` are placeholders, not guaranteed-valid API model IDs —
verify (or change) them from the dashboard's **AI provider → View models for active provider**
before running a real batch, so the whole queue doesn't fail on a bad model name.

Rules:

- Keep every provider API key only in `.env`.
- Never paste any of them into the Chrome extension.
- Never commit `.env` to Git.
- Keep `HOST=127.0.0.1`.
- Set `OPERATOR_TIMEZONE` to the operator's IANA time-zone name. The supplied Malaysian default is `Asia/Kuala_Lumpur`.
- The server intentionally refuses `0.0.0.0` by default.
- The extension receives only the separate local collector token.

Every provider model and prompt version is configurable, so the collector is not tied to
one provider or model name.

### Use OmniRoute

Install [OmniRoute](https://github.com/diegosouzapw/OmniRoute), connect an upstream
provider, and set these values in `.env`:

```env
AI_PROVIDER=omniroute
OMNIROUTE_BASE_URL=http://127.0.0.1:20128/v1
OMNIROUTE_API_KEY=your_omniroute_endpoint_key
OMNIROUTE_MODEL=gemini/gemini-3.5-flash-lite
```

The model is an example: use the exact image-capable model ID available in your
OmniRoute dashboard. Connect its upstream provider in OmniRoute first. The endpoint
key belongs to OmniRoute; the upstream provider key stays in OmniRoute. Restart the
collector and select OmniRoute if a saved dashboard provider override is active.
The model-list button reads the configured gateway's catalog; custom catalogs are
not filtered for free pricing or image support. Provider quotas and charges still
apply. Begin with a small verified extraction before starting a batch.

`OMNIROUTE_BASE_URL` defaults to `http://127.0.0.1:20128/v1`.
The OpenAI, Anthropic, and Gemini adapters keep their existing
configuration. Reprocessing cannot supply seller evidence absent from the capture.

---

# 7. Run the production collector

## Windows (CMD, Anaconda Prompt, or PowerShell)

```bat
run.bat
```

From PowerShell, use `.\run.bat`.

## Activated Conda environment

```powershell
conda activate guardianlens-collector
python main.py
```

Then open:

```text
http://127.0.0.1:8770
```

Health endpoint:

```text
http://127.0.0.1:8770/health
```

The dashboard shows:

- approved total / 2,209 (final target)
- Carousell / 1,410
- Mudah / 799
- exact counts for every lifecycle/failure state
- pending/processing/attention and review queues with safe failure reasons
- searchable, paginated **All Records** history (including rejected, skipped, failed, and duplicates)
- category coverage
- collection recommendations
- CSV upload and pasted-URL import summaries
- two-stage replay progress, current URL, durable capture log, popup monitor, and explicit retries
- batch controls
- local extension token
- review timing in `OPERATOR_TIMEZONE`
- recent audited activity

---

# 8. Install the Chrome extension

The extension is loaded locally. It is not published to the Chrome Web Store.

1. Start GuardianLens first.
2. Open Chrome.
3. Go to `chrome://extensions`.
4. Enable **Developer mode**.
5. Click **Load unpacked**.
6. Select the project folder:

```text
GuardianLens_Data_Collector_v_1.0.0\extension
```

7. Pin **GuardianLens Data Collection** to the toolbar.
8. Open `http://127.0.0.1:8770`.
9. Copy the **Chrome extension token** shown on the dashboard.
10. Click the GuardianLens extension.
11. Keep the server URL as:

```text
http://127.0.0.1:8770
```

12. Paste the local token.
13. Click **Save settings**.

The token is stored in Chrome extension local storage. It is separate from every provider
API key.

---

## CSV batch replay

The dashboard keeps both input methods visible. Upload a CSV, or expand **Prefer manual URL input?** and paste one URL per line. Uploads support these URL headers:

For the complete operator procedure, controls, recovery behaviour, and live-test checklist,
see [`docs/CSV_BATCH_REPLAY.md`](docs/CSV_BATCH_REPLAY.md).

```text
url
source_url
listing_url
product_url
```

Optional CSV columns are `platform` and `category`. Platform is inferred from the exact Carousell Malaysia or Mudah hostname when omitted; an imported category is retained as provenance and used only if the existing extractor leaves category empty.

Example:

```csv
platform,category,url
carousell,Phones,https://www.carousell.com.my/p/example-123456/
mudah,Cameras,https://www.mudah.my/example-654321.htm
```

Import validates readable text, a supported URL header, HTTP/HTTPS URLs, exact supported hosts, blank rows, malformed rows, duplicates inside the import, and existing GuardianLens source duplicates. Nothing invalid is silently discarded. Review the summary, then use:

```text
Start capture pass · Pause · Resume · Stop · Retry capture failures
Process next 50 · 1 hour
```

Both queues and their logs are stored in SQLite. Refreshes and normal backend/browser restarts retain them. Completed capture checkpoints are never repeated. An interrupted uncommitted capture becomes a visible failure; untouched pending URLs continue, and any retry is explicit only after the pass finishes. Processing failures likewise remain stopped until the current processing run finishes and an operator requeues them.

Chrome must remain open with the extension configured during stage 1. The extension checks the local queue automatically (or click **Check queue**), opens one supplied URL at a time in a dedicated browser window, detects login/CAPTCHA/access-denied/unavailable pages without bypassing them, and submits successful evidence to the same `/api/capture` endpoint used by manual capture. Its popup monitors both stages and can start the scoped 50-record/60-minute processing run after capture completes.

Quick run:

1. Start GuardianLens with `.\run.bat` and confirm `http://127.0.0.1:8770` loads.
2. Load/configure the unpacked Chrome extension and save the dashboard token.
3. In **Data collection**, choose one CSV or paste one URL per line; do not provide both.
4. Click **Import CSV** or **Import pasted URLs** and inspect every import-summary count.
5. Click **Start capture pass** and keep Chrome open until every row has a checkpoint.
6. After capture completes, click **Process next 50 · 1 hour**; repeat while records remain queued.
7. Retry capture or processing failures only after the corresponding pass/run has finished.
8. Review and correct successful records in the existing **Review Queue**.

# 9. What the extension actually captures

For a manual click or a claimed CSV replay item, the shared capture operation collects:

- current URL
- detected platform
- page title
- one visible-tab screenshot
- up to 12 large visible product-image candidate URLs
- marketplace listing ID when a reliable numeric ID is visible in the URL
- capture timestamp on the backend

Before the request is accepted, the extension and backend both require an exact supported
marketplace host, an individual-listing URL shape, and listing-specific page evidence
(for example, a product heading plus price/product signals). Home, category, search,
seller-profile, malformed, deceptive-host, and tab-changed-during-capture requests are
rejected without creating a record.

Normalized visible page text is regex-scrubbed before it enters private staging; raw unsanitized page text is not written to disk. The scrubbed listing/seller text is the primary extraction source, while private screenshots remain secondary capture-time proof for review.

The extension does **not**:

- open marketplace pages that are not present in the persistent replay queue
- search products
- click pagination
- crawl seller profiles
- follow recommendation or other listing links
- discover URLs
- bypass CAPTCHA, login, Cloudflare, bot checks, or access controls

---

# 10. Required manual-and-replay soft test

Do this before real collection.

The soft test uses a separate database **and** a separate runtime asset tree:

```text
data/soft_test/collector_soft_test.sqlite3
data/soft_test/runtime/private/replay_batches/
data/soft_test/runtime/private/screenshots/
data/soft_test/runtime/images/
data/soft_test/runtime/exports/
```

It does not count toward the production dataset total and its screenshots/images do not enter the production asset folders.

## Start soft-test mode

Stop the production server first, then run:

```powershell
conda activate guardianlens-collector
python scripts/run_soft_test_server.py
```

The dashboard still uses:

```text
http://127.0.0.1:8770
```

## Validate both input modes with a controlled real trial

First validate the original manual path:

1. One manually selected Carousell Malaysia listing
2. One manually selected Mudah.my listing

For each listing:

```text
manually open listing
→ extension Capture Current Listing
→ verify it appears as captured
```

Then create a mixed CSV containing 5 random individual Carousell URLs and 5 random Mudah
URLs. Import it under **Data collection**, open the generated Stage 1 CSV, verify the summary,
click **Start capture pass from Stage 1 file**, and keep Chrome open until all 10 rows have
terminal capture checkpoints. Confirm Stage 3 did not start before Stage 2 capture completed,
then click **Process next 50 · 1 hour**. Confirm the dashboard and extension popup show the
three stages, checkpoint counts, failures, and `csv_batch` provenance.

## Process the manually captured pair

Dashboard → Batch processor:

```text
Minutes: 30
Max records: 2
Start
```

Expected flow:

```text
captured
→ processing
→ ai_extracted
→ validating
→ ready_for_review OR needs_attention
```

If something fails, the record should enter a named failure/attention state instead of silently disappearing.

## Human review

Open **Review Queue**.

For each successful manual or CSV record verify:

- title
- description
- category
- condition
- price
- state/city
- account age if visible
- seller rating if visible
- review count if visible
- active listing count if visible
- language
- private screenshot
- product images
- warnings
- AI provider/model/prompt provenance
- complete status and review history
- duplicate checks/warnings and image-integrity results
- a human edit is retained in the correction audit

Correct mistakes, save, then approve only when correct.

Approval requires at least one stored product image and the final integrity checks to pass.

After the representative records have been reviewed, use a second PowerShell window
to verify the isolated soft-test
dataset and produce its approved-only export:

```powershell
$env:GUARDIANLENS_MODE = 'soft_test'
python scripts/security_audit.py
python scripts/data_integrity_audit.py
python scripts/export_approved.py
```

Confirm that both audits pass, the approved count increases for every accepted record, the
planner updates, and the export is written only under `data/soft_test/runtime/exports/`.
Do not begin a larger collection campaign unless both manual and CSV replay paths complete
this checklist.

`GUARDIANLENS_MODE` remains set in that PowerShell window. Close it or run
`Remove-Item Env:GUARDIANLENS_MODE` before launching production. The collector token and
dashboard-selected provider override are intentionally shared between production and
soft-test modes; the databases and all collection assets/outputs are isolated.

## Reset soft test when needed

Stop the soft-test server first. This command deliberately deletes only the isolated
soft-test database and runtime asset/output tree; it never deletes production data.

```powershell
python scripts/reset_soft_test.py
```

Then restart `scripts/run_soft_test_server.py`.

---

# 11. Automated engineering integration check

This is different from the university soft test. It uses generated images and a deterministic mock extractor to verify the internal pipeline without spending API credits or using marketplace data.

```powershell
conda activate guardianlens-collector
python scripts/mock_integration_check.py
```

Expected:

```text
MOCK INTEGRATION CHECK: PASS
```

It creates exactly two synthetic records inside a disposable OS temporary directory and
checks capture → processing → review → approval. It does not write the production or
persistent soft-test database/assets.

Synthetic test records are not research data.

## Persistent 5+5 CSV soft test

To exercise the staged CSV pipeline with five random rows from each supplied crawler file,
stop the soft-test server and run:

```powershell
python scripts/reset_soft_test.py
python scripts/soft_test_csv_pipeline.py
python scripts/run_soft_test_server.py
```

The runner reads `../URL_Crawler/output/carousell_urls_full.csv` and
`../URL_Crawler/output/mudah_urls_full.csv`, creates the viewable Stage 1 CSV, writes ten
synthetic capture checkpoints, preprocesses ten synthetic product images with the mock
extractor, and leaves all ten records in the human review queue. It never writes production.
The auditable result is stored at
`data/soft_test/runtime/reports/csv_pipeline_5x5.json`. The URLs are real rows from the supplied
files, but the screenshot, page text, product image, and extraction evidence are synthetic;
this validates the collector pipeline, not the current live marketplace pages.

---

# 12. Daily collection workflow

## A. Check what is under target

Open the dashboard.

Example:

```text
What should I collect next?
Mudah → Cameras
Carousell → Sports
Mudah → Gaming
```

The planner uses approved plus pending records to avoid over-collecting one category while a large review queue is waiting.

## B. Choose an input mode

Manual mode example:

```text
Dashboard says: Mudah → Cameras
↓
YOU open Mudah
↓
YOU manually search Cameras
↓
YOU choose one listing
↓
YOU open it
```

CSV mode uses a prepared CSV or pasted URL list under **Data collection**. It replaces only
the repetitive opening-and-clicking step; it does not replace the pipeline or human review.

## C. Manual capture mode

Click:

```text
GuardianLens → Capture Current Listing
```

The request is accepted only for Carousell Malaysia or Mudah hosts and only with the local collector token.

You may repeat manual capture for several pages without waiting for AI processing. They
remain in `captured` status until you use the manual batch processor.

## D. CSV replay mode

Choose one CSV or paste one URL per line, import it, verify the summary, and click **Start
capture pass**. Keep Chrome open. Replay captures every supplied URL once and finishes stage 1
without invoking AI or product-image preprocessing. Then click **Process next 50 · 1 hour**
to start a scoped stage-2 run.

## E. Process manually captured backlog

Use the dashboard batch controls.

Example:

```text
Duration: 60 minutes
Maximum records: 50
Start
```

Processing stops when either limit is reached, the scoped queue is empty, or you request Stop.
CSV replay has its own durable capture controls and two-stage progress panel.

## F. Review

Open the review queue.

Human actions are:

```text
Approve
Edit + Approve
Reject
Skip
Flag
```

`approved` means accepted collection data. It does not mean legitimate or fraudulent.

---

# 13. Batch controls

## Manual captured-backlog controls

Supported controls:

- Start
- Pause
- Resume
- Stop

Stop is graceful at the queue level. The worker finishes or fails the current listing, then stops before starting another one.

The latest run stores:

- run ID
- start/end times
- duration limit
- item limit
- attempted/processed
- successful
- duplicates
- AI failures
- image failures
- failed count
- run status

Crash recovery runs on server startup:

- listings left in `processing` are returned to `captured`
- listings left in later intermediate processing states become visible `processing_failed` records
- interrupted review sessions are closed as `review_session_interrupted` and returned to their prior reviewable state; offline time is not counted as human review time
- unfinished batch runs become `interrupted`
- processor control returns to `idle`

## CSV replay controls

- Start capture pass
- Pause
- Resume
- Stop
- Retry capture failures
- Process next 50 · 1 hour

Replay opens one persisted user-supplied URL at a time. Pause safely checkpoints/finishes the
current row before another claim. Stop retains completed records and skips untouched rows.
Resume continues the durable queue. A failed capture is not retried inside the same pass;
**Retry capture failures** becomes available afterward and observes `MAX_CAPTURE_ATTEMPTS`.
Stage 2 is separately limited to 50 records or 60 minutes by default. Backend, dashboard, and
browser restarts do not discard either stored queue or their logs.

---

# 14. Listing state machine

Normal path:

```text
captured
→ processing
→ ai_extracted
→ validating
→ ready_for_review / needs_attention
→ under_review
→ approved / rejected / skipped / flagged
```

Failure states:

```text
capture_failed
processing_failed
ai_failed
image_failed
duplicate_blocked
```

Processing batches select only eligible `captured` rows and exclude every replay batch whose
capture pass is still running, paused, or stopping. Scoped replay processing selects only the
chosen replay's captured rows. Failed rows remain visible and are never retried during the
current pass/run; correct the problem and request an explicit retry afterward.

Every state transition is recorded in `status_history`.

---

# 15. AI role and provenance

AI is only an automatic form filler during this phase.

Primary input:

```text
scrubbed visible listing text
+ scrubbed visible seller/profile text when captured
+ platform
+ page title
+ configured category list
```

The private listing and seller screenshots are secondary capture-time evidence for review,
not exported dataset fields.

Output fields:

```text
title
description
category
condition
price
currency
location_state
location_city
account_age_days
seller_rating
review_count
active_listing_count
language
```

The model is instructed not to return seller identity, email, phone, bank details, contact handles, or exact street addresses.

There are deliberately **no AI confidence fields**.

Provenance retained:

```text
ai_extracted
ai_provider
ai_model
ai_prompt_version
ai extraction timestamp
structured extraction result
status/error
```

Human edits are written to `review_actions` with previous and updated values.

---

# 16. Screenshot privacy

Private screenshots are stored separately:

```text
data/private/screenshots/<platform>/<listing_id>/listing.jpg
data/private/screenshots/<platform>/<listing_id>/seller.jpg   (when available)
data/private/staging/<listing_id>.json                        (PII-scrubbed text + image URLs)
```

Before stage 2, the product-image URLs are only staged in that private JSON file; the
product image files have not been downloaded yet. The queue/checkpoint, source URL, and
listing record are stored in `data/collector.sqlite3`.

They are never included in normal dataset exports.

Default:

```env
SCREENSHOT_RETENTION=review_only
```

Supported values:

- `review_only`: delete screenshot after approval or rejection
- `retain_private`: keep screenshots privately
- `delete_after_approval`: delete only after approval

Private staging material, including the staged image-URL JSON, is removed after final approval/rejection.

---

# 17. Product images

Product images are dataset assets:

```text
data/images/carousell/<listing_id>/image_001_<unique-id>.jpg
data/images/mudah/<listing_id>/image_001_<unique-id>.jpg
```

Checks before storage:

```text
file exists/download succeeds
→ HTTPS-only public host and redirect validation
→ content type is image
→ supported format
→ maximum size
→ maximum decoded pixel count
→ minimum dimensions
→ image decode/verify
→ safe re-encode with EXIF/ancillary metadata removed
→ SHA-256 of the stored bytes
→ perceptual hash
→ exact duplicate check
→ near-duplicate warning
→ atomic file move
```

Supported formats:

- JPEG
- PNG
- WebP

Image metadata stored:

- image ID
- listing ID
- platform
- storage path
- SHA-256
- perceptual hash
- file size
- width/height
- source position
- primary flag
- source image URL without query parameters or fragments
- created timestamp

---

# 18. PII processing

The collection pipeline removes or flags patterns including:

- email addresses
- Malaysian phone numbers
- generic international phone-like numbers during residual checks
- obvious bank-account phrases
- contact-handle phrases such as WhatsApp/Telegram
- obvious exact street-address patterns

The collector keeps research-relevant seller behaviour such as account age, rating, review count, active listing count, and broad state/city.

Human review is still mandatory. Regex privacy checks are guardrails, not a replacement for checking the screenshot and extracted draft.

---

# 19. Duplicate handling

## Source duplicate

Uses canonical URL SHA-256.

Tracking query parameters and fragments are removed before hashing.

## Marketplace listing ID duplicate

Unique per platform when an ID is available.

## Metadata duplicate

Signature:

```text
platform
+ normalized title
+ normalized description
+ price
```

An exact match against an approved record blocks the duplicate draft/approval path.

## Exact image duplicate

Uses SHA-256.

## Near image duplicate

Uses a compact perceptual hash and Hamming distance.

Near duplicates create a warning for human review. They are not automatically rejected.

---

# 20. Atomic approval

Approval uses an SQLite `BEGIN IMMEDIATE` transaction.

Before commit GuardianLens checks:

1. current status is reviewable
2. title/category/price/currency exist
3. category is configured
4. at least one product image exists
5. residual PII check passes
6. source URL is not already approved
7. marketplace listing ID is not already approved
8. metadata signature is not already approved
9. approved timestamp and state history can be written together

If a check fails, the transaction rolls back.

There is no partial approval.

Screenshot/staging retention cleanup occurs after the database outcome commits because
SQLite cannot transactionally delete filesystem objects. If cleanup fails, GuardianLens
keeps the approved/rejected outcome, records and displays a cleanup warning, returns an
error to the operator, and makes the integrity audit fail until the private artifact is
resolved. It never silently reports cleanup success or rolls back only half of an approval.

---

# 21. SQLite database

Production DB:

```text
data/collector.sqlite3
```

Soft-test DB:

```text
data/soft_test/collector_soft_test.sqlite3
```

Core tables:

- `capture_batches`
- `capture_batch_items`
- `capture_batch_attempts`
- `listings`
- `images`
- `ai_extractions`
- `review_actions`
- `warnings`
- `status_history`
- `processing_runs`
- `processor_control`

SQLite uses foreign keys, WAL mode, and a busy timeout.

The schema is versioned. Before a legacy database is migrated, GuardianLens creates and
validates an online SQLite backup under:

```text
data/backups/schema_migrations/
```

Migration runs under a write lock, re-checks the durable schema version, preserves user
rows, and validates the schema, foreign keys, indexes, migration history, and
`PRAGMA quick_check` before commit.

No external database server is required for this collection phase.

---

# 22. Export approved data

Dashboard export endpoint exists, or run:

```powershell
conda activate guardianlens-collector
python scripts/export_approved.py
```

Files are created in:

```text
data/exports/
```

Outputs:

```text
approved_listings_<timestamp>.csv
approved_images_<timestamp>.jsonl
```

The listing export intentionally excludes:

- screenshots
- screenshot paths
- private staging material/path
- provider API keys
- local collector token
- AI confidence fields
- raw seller identity/contact details

## Auto-updating annotation handoff

GuardianLens also maintains a non-destructive, one-way research-data view under:

```text
data/exports/annotation_dataset/
```

It contains master CSVs for all imported source rows, captured listings, product-image
references, review/audit history, exact-status views, quality findings, and an
`annotation_test.csv` pilot containing only human-approved records. Product images stay in
their canonical `data/images/<platform>/<listing_id>/` directories and are referenced by
path; they are never copied or moved by the export.

The view refreshes after committed collection, processing, and human-review changes and on
application startup. SQLite remains authoritative: editing a generated CSV does not update
the database and the next refresh overwrites that edit. To recover from a failed automatic
refresh, run:

```powershell
python scripts/refresh_annotation_dataset.py
```

Only existing workflow statuses and collection categories are labels. `approved` means a
human accepted the collected record; it does not mean legitimate or fraudulent, and the
test CSV is not an ML train/test assignment. Missing source values remain empty rather than
being guessed or filled with placeholders. Private screenshots/staging data, secrets,
backups, and raw AI structured output never enter this handoff folder.

---

# 23. Run all automated tests

```powershell
conda activate guardianlens-collector
python scripts/run_tests.py
```

or:

```powershell
python -m pytest -q -p no:cacheprovider --basetemp=.tmp\pytest-manual
```

The automated suite covers core behaviour including:

- PII email removal
- phone removal
- simple false-positive check
- URL canonicalization
- URL duplicate detection
- metadata signatures
- image corruption/minimum-size checks
- exact image duplicate detection
- state transition enforcement
- private staging
- wrong-platform URL rejection
- mock AI extraction
- invalid AI shape rejection
- missing-image attention path
- human edit auditing
- PII scrub on human edits
- skip/flag/reject transitions
- atomic approval requirements
- screenshot cleanup
- planner 2,500 / 1,500 / 1,000 targets
- approved-only export field protection
- local-token creation
- non-local bind rejection
- security audit
- data-integrity audit baseline
- local API token enforcement
- batch start/pause/resume/stop
- crash recovery
- CSV aliases, invalid rows, blank rows, unsupported hosts, and in-file duplicates
- persistent replay ordering, pause/resume/stop, bounded retry, and crash/browser-lease recovery
- shared `CaptureRequest` provenance and per-URL failure isolation

---

# 24. Structural self-test

Run:

```powershell
python scripts/self_test.py
```

It checks:

- required folder structure
- category percentages sum to 100
- target total is 2,209 (final dataset size)
- Carousell target is 1,410
- Mudah target is 799
- Manifest V3 extension
- no always-on `<all_urls>` host permission; unattended queued screenshots use an explicit
  optional permission that the operator can grant or revoke in the popup
- JavaScript syntax when Node.js is available
- localhost-only bind configuration
- SQLite schema creation/readability in an OS temporary directory
- local token entropy without creating or changing the production token

The self-test does not initialize the production database or write runtime files into the project.

## Release-package verification

After all source changes are final, regenerate and verify the source manifest, build the strict-allowlist ZIP, then test a fresh temporary extraction:

```powershell
python scripts/manifest.py --generate
python scripts/manifest.py --verify
python scripts/build_release_zip.py
python scripts/verify_fresh_release.py
```

The release ZIP excludes databases and sidecars, logs, private screenshots/staging, captured product images, tokens, `.env`, caches, dependencies, and tool state. Its verifier checks the archive independently, scans allowed text for secret patterns, and requires the empty runtime directory structure.

---

# 25. Security audit

```powershell
python scripts/security_audit.py
```

Report:

```text
data/reports/security_audit.json
```

The runtime security report checks:

- localhost-only server binding
- absence of an always-on broad `<all_urls>` host permission; the broad screenshot grant is
  optional, operator-controlled, and checked before any replay URL is claimed
- absence of the configured provider key from extension files, active-mode exports, and logs

Separate self-test, regression-test, manifest, and release-verifier gates check the
collector-token location and entropy, mutation-token and same-origin protections,
wildcard CORS absence, source/ZIP secret patterns, and exclusion of `.env`, SQLite
files and sidecars, private evidence, collected assets, logs, caches, dependencies,
tool state, and tokens from the release ZIP.

The application deliberately does not enable wildcard CORS.

State-changing extension API requests require:

```http
X-GuardianLens-Token: <local token>
```

State-changing dashboard forms require the same local secret as a hidden form token;
review GET routes are read-only. Private evidence routes enforce same-origin requests,
loopback Host/client boundaries, path containment, and regular-file checks.

---

# 26. Data-integrity audit

```powershell
python scripts/data_integrity_audit.py
```

Report:

```text
data/reports/data_integrity_audit.json
```

Current checks include:

- SQLite quick-check and foreign-key integrity
- exact status/history consistency and legal lifecycle transitions
- stale/interrupted processing runs and review sessions
- approved records have required clean fields and no residual PII pattern
- source URL, marketplace ID, metadata, and exact-image SHA-256 duplicate integrity
- image row ownership, path containment, file existence, decodability, dimensions, byte size, SHA-256, and perceptual hash
- orphan image/screenshot/staging rows, files, and listing folders
- screenshot-retention and cleanup failures
- approved-only export prerequisites and soft-test path isolation

Run this periodically and again before declaring collection complete.

---

# 27. Collection completion rule

Collection is complete. The final approved dataset is:

```text
Approved total: 2,209
Carousell:      1,410
Mudah:            799
```

This is the project's dataset going forward — there is no larger number still being collected
toward. This section is kept for reference in case collection is ever reopened; if it is, restate
a new target explicitly in `config/platform_targets.yaml` rather than reusing an old one.

Then run:

```powershell
python scripts/security_audit.py
python scripts/data_integrity_audit.py
python scripts/export_approved.py
python scripts/verify_approved_live.py    # spot-check approved records against the live marketplace pages
```

The next phase should work from the exported/frozen approved dataset, not directly from captured drafts.

---

# 28. Troubleshooting

## `conda` is not recognized

Use **Anaconda Prompt**, or initialize Conda for PowerShell:

```powershell
conda init powershell
```

Close and reopen the terminal.

## Port 8770 is already in use

Check Windows:

```powershell
netstat -ano | findstr :8770
```

If you intentionally change `PORT` in `.env`, also change the local server URL in the extension popup.

## Extension says invalid token

1. Start GuardianLens.
2. Refresh the dashboard.
3. Copy the displayed local collector token.
4. Paste it into the extension.
5. Save settings.

The token file is private:

```text
data/private/local_token.txt
```

Do not put any provider API key there.

## Extension says open a Carousell or Mudah listing

The active tab hostname must be Carousell Malaysia or Mudah. The collector intentionally rejects unrelated sites.

## AI processing fails with a missing API key

Set `AI_PROVIDER` and only its matching key, for example:

```env
AI_PROVIDER=openai
OPENAI_API_KEY=...
```

Restart the server.

Neither manual capture nor replay **Start capture pass** requires an AI provider. You can
capture and checkpoint URLs first, then configure or verify the provider before stage 2.
**Process next 50 · 1 hour** requires a configured active provider.
Authentication, quota, unsupported-model, rate-limit, timeout, network, and invalid-response
failures appear with safe classifications on the dashboard; credentials are redacted.

## CSV replay has imported rows but does not move

1. Confirm GuardianLens is running and the batch status is `running`.
2. Confirm the extension has the current dashboard token and correct local server URL.
3. In the extension popup, click **Enable queued capture** and approve Chrome's one-time
   optional screenshot permission. Chrome labels it broadly because unattended tabs do not
   receive `activeTab`; GuardianLens still validates and captures only exact queued Carousell
   Malaysia or Mudah listing tabs.
4. Keep Chrome open and click **Check queue** in the extension.
5. If the batch is paused, click **Resume**.
6. Check the capture checkpoint log for permission, login, CAPTCHA, access, timeout, or
   unavailable-page status.
7. If capture is complete but preprocessing has not started, verify the active provider/model,
   then click **Process next 50 · 1 hour**.

## CSV import is rejected

Provide either one CSV or pasted URLs, not both. Ensure the file has a supported URL header,
contains individual Carousell Malaysia or Mudah listings, and remains within the configured
row/byte limits. Invalid and duplicate data rows are shown in the import result rather than
silently removed.

## `ai_failed`

The capture stays in the database. Fix the API/network/model configuration, then process the queue again.

## `image_failed`

One of the selected product-image resources could not be downloaded or validated. The record is not silently accepted. Reopen the listing, verify the images, then retry/re-capture as appropriate.

## `needs_attention`

Open the review record. Typical reasons:

- missing product images
- missing required field
- category outside configured list
- residual PII pattern
- exact image duplicate
- visually similar image

## `duplicate_blocked`

The collector found an exact duplicate condition that should not enter the approved dataset unchanged.

---

# 29. What was deliberately left out

Do not add these to this collector unless the research design changes:

- automatic marketplace listing discovery
- search crawling
- pagination crawling
- unattended seller crawling
- fraud/legitimate labels
- fraud score
- model confidence score
- AI confidence score
- annotation/adjudication tables
- train/validation/test split
- ML training/evaluation

Those are later GuardianLens phases.

---

# 30. Recommended first real run

After the automated tests pass:

```text
1. setup Conda environment
2. set `AI_PROVIDER` and the matching provider key in `.env`
3. run production server once and inspect dashboard
4. install Chrome extension
5. copy local token into extension
6. stop production server
7. start soft-test server
8. manually capture exactly 1 Carousell listing
9. manually capture exactly 1 Mudah listing
10. import a mixed smoke-test CSV with 10 random listings from each platform
11. verify the import summary and start the CSV capture pass, then its processing run
12. process the two manual captures with max records 2
13. review all successful manual and CSV captures
14. correct AI mistakes
15. approve only clean records
16. inspect the soft-test database/dashboard and provenance
17. run soft-test security and data-integrity audits
18. reset the soft-test database if desired
19. start the production server
20. use manual capture, CSV replay, or both as your supplied-input workflow requires
21. use controlled batch/replay limits
22. review every record
23. audit and export only approved records
```

That is the intended operating procedure for this package.
# GuardianLens_Data_Collector
