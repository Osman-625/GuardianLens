# CSV Batch Replay Operator Guide

CSV Batch Replay opens only the individual Carousell Malaysia or Mudah listing URLs that
you provide. It does not search marketplaces, discover URLs, follow recommendations, or
approve records. Manual extension capture remains available.

Both input modes keep the same evidence and review pipeline. Replay deliberately separates
the viewable URL manifest, URL capture, and pictures/AI preprocessing:

```text
Manual extension capture ───────────────┐
                                       ├─> captured checkpoint -> pictures + preprocessing -> human review -> export
CSV/pasted URLs -> Stage 1 CSV -> capture pass (once) ┘
```

## 1. One-time setup

From the project root on Windows:

```powershell
.\setup.bat
```

Copy `.env.example` to `.env`, select `AI_PROVIDER`, and set only that provider's API key.
Do not put an AI provider key in the extension or a CSV file.

Start GuardianLens:

```powershell
.\run.bat
```

Open `http://127.0.0.1:8770`, then load `extension/` as an unpacked Chrome extension. Copy
the **Chrome extension token** from the dashboard into the extension and save its settings.

For unattended CSV/pasted-URL screenshots, open the extension popup and click **Enable queued
capture**. Chrome requires the optional `<all_urls>` grant for `captureVisibleTab` on windows
opened without a direct click. GuardianLens does not claim a queue item until the grant exists,
and its code still accepts only exact Carousell Malaysia or Mudah listing URLs. The popup can
revoke the grant at any time. Manual capture continues to use `activeTab` and does not need it.

## 2. Manual capture is still available

For the original workflow, open an individual supported listing yourself and click
**Capture Current Listing**. If required, open its seller/profile page and click
**Capture Seller Behaviour**. Process manually captured backlog records with the existing
duration/item-limit batch controls.

## 3. Prepare a CSV

GuardianLens accepts `url`, `source_url`, `listing_url`, or `product_url` as the URL header.
`platform` and `category` are optional.

```csv
platform,category,url
carousell,Phones,https://www.carousell.com.my/p/example-123456/
mudah,Cameras,https://www.mudah.my/example-654321.htm
```

If `platform` is absent, it is inferred from the exact hostname. If `category` is absent,
GuardianLens leaves it for the existing extraction pipeline. Supported text encodings are
UTF-8, UTF-8 with BOM, and Windows-1252; supported delimiters are comma, semicolon, and tab.
Default limits are 10,000 non-blank rows and 5 MiB.

Every non-blank row is accounted for. Invalid URLs, unsupported domains, in-file duplicates,
and listings already present in GuardianLens appear in the import summary and queue history.

## 4. Import and run the three stages

1. Open **Data collection** on the dashboard.
2. Drop a CSV in the upload area or click it to choose a file.
3. Alternatively, expand **Prefer manual URL input?** and paste one URL per line.
4. Optionally enter a batch name.
5. Click **Import CSV** or **Import pasted URLs**.
6. Check Rows, Valid URLs, Invalid rows, Duplicates, Already captured, and Queued.
7. Open or download the generated Stage 1 file from the dashboard. Its path is
   `data/private/replay_batches/<batch_id>/stage_1_urls.csv` in production or the matching
   isolated soft-test runtime path. Treat this normalized/validated manifest as view-only.
8. Click **Start capture pass from Stage 1 file** only after the summary and file are correct.
9. Keep GuardianLens and Chrome open. Confirm **Queued screenshot permission: Enabled** in the
   popup; the extension then claims one URL at a time.
10. Monitor Stage 2 in the dashboard or extension popup. Every result is written to the capture
   checkpoint log. A failure is left terminal while later URLs continue.
11. When capture reaches **Completed**, click **Process next 50 · 1 hour**. Stage 3 then downloads
    product pictures and runs extraction, privacy checks, duplicate checks, and validation.
12. Repeat **Process next 50 · 1 hour** while **Ready to preprocess** is greater than zero.
13. Open **Review Queue** and review every successful processed record before approval.

Provide either a CSV or pasted URLs in one import, not both. Importing does not automatically
start collection, and replay never automatically approves a record.

## 5. Controls

- **Pause** lets the current listing safely finish/checkpoint and prevents another claim.
- **Resume** continues the same durable queue.
- **Stop** retains completed records and marks untouched pending rows skipped.
- **Retry capture failures** is available only after the current capture pass finishes. It
  requeues eligible capture failures up to `MAX_CAPTURE_ATTEMPTS`.
- **Process next 50 · 1 hour** starts a processing run scoped to this replay batch. It does not
  mix in rows from a different replay batch.
- **Retry selected eligible failures** is for AI/image/processing failures and is unavailable
  until the current processing run finishes. Retried records wait for the next processing run.
- **Check queue** in the extension triggers an immediate poll instead of waiting for
  its next automatic check.
- **Enable queued capture** grants Chrome's optional screenshot permission. Until it is granted,
  the service worker deliberately claims no URL, so missing permission cannot fail an entire batch.
- **Revoke queued capture permission** stops new unattended captures without disabling manual
  capture.

Refreshing the dashboard does not lose either queue. After a backend or Chrome restart, start
GuardianLens and reopen Chrome with the configured extension. Completed capture checkpoints are
never repeated. A capture interrupted before it committed evidence is recorded as a failure and
requires an explicit retry after the pass; untouched pending URLs continue in order. Committed
captures are reconciled even if the browser acknowledgement was lost. Completed processing records
are not processed again; only a non-durable in-flight record is recovered.

## 6. Failure statuses

GuardianLens records, rather than bypasses, conditions such as:

```text
login_required
captcha
blocked
access_denied
listing_unavailable
capture_timeout
capture_failed
invalid_listing_page
```

One failed URL does not stop later URLs, and no failed URL is automatically retried inside the
same pass. Correct authentication, network, page, or provider problems first, finish the current
pass/run, and then request the appropriate capture or processing retry.

## 7. Human review and provenance

CSV records enter the same review interface and retain **Approve**, **Edit + Approve**,
**Reject**, **Skip**, and **Flag**. The record detail shows `csv_batch`, batch ID, CSV row,
original filename, and source category. CSV category is used only as a fallback when the
existing extractor leaves category empty.

## 8. Recommended live validation

Before a large collection, use `GUARDIANLENS_MODE=soft_test` and verify:

1. one manual Carousell and one manual Mudah capture;
2. one mixed Stage 1 CSV containing 5 random Carousell and 5 random Mudah listing URLs;
3. Stage 2 reaches 10 resolved capture checkpoints before Stage 3 starts;
4. processing stops at its configured record/time limit and can continue in a later run;
5. all successful records reach the normal review interface with screenshots, product images,
   seller fields where visible, warnings, histories, and correct provenance;
6. capture and processing failures remain stopped until explicitly retried after their pass/run;
7. human correction and approval work; and
8. the security and data-integrity audits pass.

Offline tests cannot certify the current marketplace DOM, login state, provider account,
quota, or network path.

## 9. Verification commands

```powershell
python -m compileall -q src\guardianlens tests
python -m pytest -p no:cacheprovider --basetemp=.tmp\pytest-verification
node --check extension\background.js
node --check extension\popup.js
python scripts\self_test.py
python scripts\mock_integration_check.py
python scripts\reset_soft_test.py
python scripts\soft_test_csv_pipeline.py
```

See `docs/VERIFICATION.md` for dataset audits and release-package verification.
