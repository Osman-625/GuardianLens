# CSV Batch Replay Operator Guide

CSV Batch Replay opens only the individual Carousell Malaysia or Mudah listing URLs that
you provide. It does not search marketplaces, discover URLs, follow recommendations, or
approve records. Manual extension capture remains available.

Both input modes use the same GuardianLens capture and processing path:

```text
Manual extension capture ─┐
                          ├─> CaptureRequest -> processing -> human review -> export
CSV/pasted URL replay ────┘
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

Open `http://127.0.0.1:8765`, then load `extension/` as an unpacked Chrome extension. Copy
the **Chrome extension token** from the dashboard into the extension and save its settings.

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

## 4. Import and run a replay batch

1. Open **Data collection** on the dashboard.
2. Drop a CSV in the upload area or click it to choose a file.
3. Alternatively, expand **Prefer manual URL input?** and paste one URL per line.
4. Optionally enter a batch name.
5. Click **Import URLs**.
6. Check Rows, Valid URLs, Invalid rows, Duplicates, Already captured, and Queued.
7. Click **Start** only after the summary is correct.
8. Keep GuardianLens and Chrome open. The extension claims one URL at a time.
9. Monitor the current category, URL, status, progress counters, and recent failures.
10. Open **Review Queue** and review every successful capture before approval.

Provide either a CSV or pasted URLs in one import, not both. Importing does not automatically
start collection, and replay never automatically approves a record.

## 5. Controls

- **Pause** lets the current listing safely finish/checkpoint and prevents another claim.
- **Resume** continues the same durable queue.
- **Stop** retains completed records and marks untouched pending rows skipped.
- **Retry Failed** requeues eligible failures up to `MAX_CAPTURE_ATTEMPTS`.
- **Check CSV Queue Now** in the extension triggers an immediate poll instead of waiting for
  its next automatic check.

Refreshing the dashboard does not lose the queue. After a backend or Chrome restart, start
GuardianLens, reopen Chrome with the configured extension, and resume the existing batch.
Committed captures are reconciled even if a browser acknowledgement was lost.

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

One failed URL does not stop later URLs. An obviously unavailable listing is not retried
forever. Correct authentication, network, page, or provider problems before retrying.

## 7. Human review and provenance

CSV records enter the same review interface and retain **Approve**, **Edit + Approve**,
**Reject**, **Skip**, and **Flag**. The record detail shows `csv_batch`, batch ID, CSV row,
original filename, and source category. CSV category is used only as a fallback when the
existing extractor leaves category empty.

## 8. Recommended live validation

Before a large collection, use `GUARDIANLENS_MODE=soft_test` and verify:

1. one manual Carousell and one manual Mudah capture;
2. one two-row CSV containing a different Carousell and Mudah listing;
3. all four records reach the normal review interface with screenshots, product images,
   seller fields where visible, warnings, histories, and correct provenance;
4. human correction and approval work; and
5. the security and data-integrity audits pass.

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
```

See `docs/VERIFICATION.md` for dataset audits and release-package verification.
