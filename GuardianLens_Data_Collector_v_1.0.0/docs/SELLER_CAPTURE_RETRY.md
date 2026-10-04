# Mudah seller-capture recovery

GuardianLens has a dedicated browser queue for historical Mudah listings whose listing evidence
was captured but whose seller/profile evidence failed. It does not reuse the URL replay attempt
counter and it never starts AI extraction automatically.

## Safety boundary

The queue selects a listing only while all three predicates remain true:

- `listings.platform = 'mudah'`
- `listings.status = 'needs_attention'`
- a linked `capture_batch_items` row still has
  `last_error_type = 'seller_capture_incomplete'`

Those predicates are checked when the batch is prepared, when an item is claimed, and again when
seller evidence is completed. A listing that has changed state is marked ineligible in the retry
ledger and is not transitioned or reprocessed.

Preparing or starting the queue is rejected while preprocessing or a URL replay pass is active.
Conversely, preprocessing and URL replay cannot start while a seller-retry batch is running,
paused, or stopping.

## Anti-bot controls

The defaults intentionally favor restraint over throughput:

- one browser item at a time across URL replay and seller retry;
- 90 seconds plus 0–60 seconds persisted jitter after every seller attempt;
- per-listing exponential retry delay of 15, 30, then 60 minutes (capped);
- a queue-wide 15, 30, then 60 minute cooldown after consecutive `access_denied`, `captcha`, or
  blocked responses;
- no more than three attempts per listing;
- backend leases and not-before timestamps remain authoritative if Chrome's Manifest V3 service
  worker sleeps or restarts.

The extension opens the saved seller URL directly when one exists. Otherwise it opens the saved
listing, waits specifically for a seller/profile link, and checkpoints that URL in the retry item
before visiting the profile. Historical blocked URLs were not persisted by the old pipeline, so
the first pass may need to re-derive the URL even when the original browser run found one.

## Operator procedure

Wait until `/api/batch/status` reports an idle processor and the current run is terminal. Then:

1. Stop and restart GuardianLens so schema migration 6 is applied. The migration creates an online
   SQLite backup before changing the production database.
2. Reload the unpacked Chrome extension so its seller-retry worker is active.
3. In the extension, save the local server/token and grant **Queued screenshot permission**.
4. Prepare one exact-scope retry batch:

   ```powershell
   $collectorToken = (Get-Content -Raw -LiteralPath 'data/private/local_token.txt').Trim()
   $headers = @{ 'X-GuardianLens-Token' = $collectorToken }
   $prepared = Invoke-RestMethod -Method Post `
     -Uri 'http://127.0.0.1:8770/api/seller-retry/prepare' `
     -Headers $headers -ContentType 'application/json' -Body '{}'
   $retryBatchId = $prepared.batch.retry_batch_id
   ```

5. Review `$prepared.progress.total`, then start it explicitly:

   ```powershell
   Invoke-RestMethod -Method Post `
     -Uri "http://127.0.0.1:8770/api/seller-retry/$retryBatchId/start" `
     -Headers $headers
   ```

6. Monitor without mutation:

   ```powershell
   Invoke-RestMethod -Method Get `
     -Uri "http://127.0.0.1:8770/api/seller-retry/status?retry_batch_id=$retryBatchId"
   ```

Pause, resume, or stop with
`POST /api/seller-retry/{retry_batch_id}/command/{pause|resume|stop}`. A stop lets the leased item
finish, then marks unvisited rows skipped.

On verified success, GuardianLens stores the seller screenshot and scrubbed visible text, clears
only the matching `seller_capture_incomplete` source error, and uses the state machine to move that
listing from `needs_attention` to `captured`. Start a separate AI preprocessing run only after the
seller-retry batch has completed or stopped.
