const tokenElement =
  document.getElementById("token") ||
  document.querySelector('input[name="token"]');
const GL_TOKEN = tokenElement
  ? String(
      "value" in tokenElement ? tokenElement.value : tokenElement.textContent,
    ).trim()
  : "";

function setText(id, value) {
  const element = document.getElementById(id);
  if (element) element.textContent = String(value ?? "");
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (GL_TOKEN) headers.set("X-GuardianLens-Token", GL_TOKEN);
  const response = await fetch(path, { ...options, headers });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail =
      typeof body.detail === "string"
        ? body.detail
        : `Request failed (${response.status})`;
    throw new Error(detail);
  }
  return body;
}

function appendCell(row, value) {
  const cell = document.createElement("td");
  cell.textContent = value ?? "—";
  row.appendChild(cell);
  return cell;
}

function listingLabel(item) {
  return item.title || item.page_title || item.listing_id;
}

function appendRecordLink(cell, item) {
  cell.textContent = "";
  const link = document.createElement("a");
  link.href = `/records/${encodeURIComponent(item.listing_id)}`;
  link.textContent = listingLabel(item);
  cell.appendChild(link);
}

const ACTIVE_PROCESSING_COMMANDS = new Set(["running", "paused", "stopping"]);
let latestReplayBatchId = null;
let latestReplayBatchName = null;
let latestReplayQueued = 0;
let latestProcessingControl = "idle";
let latestPendingCount = 0;
let latestBatchStatus = null;

function selectedProcessingLimits() {
  const durationValue = document.getElementById("duration")?.value ?? "";
  const limitValue = document.getElementById("limit")?.value ?? "";
  return {
    duration_minutes: durationValue ? Number(durationValue) : null,
    item_limit: limitValue ? Number(limitValue) : null,
  };
}

function durationLabel(minutes) {
  if (minutes === null) return "unlimited";
  if (minutes === 60) return "1 hour";
  if (minutes === 120) return "2 hours";
  return `${minutes} minutes`;
}

function processingLimitLabel(limits = selectedProcessingLimits()) {
  const records =
    limits.item_limit === null ? "all pending" : `next ${limits.item_limit}`;
  return `${records} · ${durationLabel(limits.duration_minutes)}`;
}

function updateProcessingControls() {
  const active = ACTIVE_PROCESSING_COMMANDS.has(latestProcessingControl);
  const queueReady = latestPendingCount > 0;
  const start = document.getElementById("batchStart");
  if (start) {
    start.disabled = active || !queueReady;
    start.title = active
      ? "Finish or stop the current processing run first."
      : queueReady
        ? `Start processing: ${processingLimitLabel()}.`
        : "No captured records are ready to process.";
  }

  document.querySelectorAll("[data-batch-command]").forEach((button) => {
    const command = button.dataset.batchCommand;
    button.disabled = !(
      (command === "pause" && latestProcessingControl === "running") ||
      (command === "resume" && latestProcessingControl === "paused") ||
      (command === "stop" &&
        ["running", "paused"].includes(latestProcessingControl))
    );
  });
  ["duration", "limit"].forEach((id) => {
    const control = document.getElementById(id);
    if (control) control.disabled = active;
  });
}

function renderBatch(status) {
  if (!status?.control) throw new Error("Processing status is unavailable.");
  latestBatchStatus = status;
  latestProcessingControl = status.control?.command || "idle";
  latestPendingCount = Number(status.pending_count || 0);
  const details = document.getElementById("batchStatus");
  if (details) details.textContent = JSON.stringify(status, null, 2);

  const run = status.latest_run;
  const fill = document.getElementById("progressFill");
  const label = document.getElementById("progressLabel");
  const progressbar = fill ? fill.parentElement : null;
  if (!fill || !label) return;

  if (!run) {
    fill.style.width = "0%";
    if (progressbar) progressbar.setAttribute("aria-valuenow", "0");
    label.textContent = "Idle — no processing run yet.";
    [
      "cAttempted",
      "cSuccessful",
      "cAttention",
      "cAiFail",
      "cImgFail",
      "cDup",
    ].forEach((id) => setText(id, 0));
    updateProcessingControls();
    return;
  }

  const complete = !["running", "paused", "stopping"].includes(run.status);
  const percent = run.item_limit
    ? Math.min(100, Math.round((100 * run.attempted) / run.item_limit))
    : complete && run.attempted > 0
      ? 100
      : 0;
  fill.style.width = `${percent}%`;
  if (progressbar) progressbar.setAttribute("aria-valuenow", String(percent));
  const command = complete ? run.status : status.control?.command || run.status;
  label.textContent = `${command} — run ${run.run_id.slice(0, 8)} — ${run.attempted}/${run.item_limit || "all"} attempted`;
  setText("cAttempted", run.attempted ?? "No data");
  setText("cSuccessful", run.successful ?? "No data");
  setText("cAttention", run.needs_attention ?? "No data");
  setText("cAiFail", run.ai_failures ?? "No data");
  setText("cImgFail", run.image_failures ?? "No data");
  setText("cDup", run.duplicates ?? "No data");
  updateProcessingControls();
}

let lastReplayAttempts = null;

function renderReplay(snapshot) {
  const workspace = document.getElementById("replayWorkspace");
  if (!workspace) return;
  const batch = snapshot?.batch;
  const summary = snapshot?.import_summary || {};
  const progress = snapshot?.progress || {};
  const processing = snapshot?.processing || {};
  const stageFile = snapshot?.stage_file;
  latestReplayBatchId = batch?.batch_id || null;
  latestReplayBatchName = batch?.name || null;
  latestReplayQueued = Number(processing.queued || 0);
  workspace.classList.toggle("is-empty", !batch);

  setText("replayBatchName", batch?.name || "No batch imported");
  setText(
    "replayBatchMeta",
    batch
      ? `${batch.original_filename || "Pasted URLs"} · created ${batch.created_at}`
      : "Import a source above to begin.",
  );
  setText("replayBatchStatus", batch?.status || "idle");
  const replayStatus = document.getElementById("replayBatchStatus");
  if (replayStatus) replayStatus.dataset.state = batch?.status || "idle";
  setText(
    "replayStageFileState",
    stageFile?.exists
      ? "Ready to inspect"
      : batch
        ? "File missing"
        : "Waiting for import",
  );
  setText(
    "replayStageFilePath",
    stageFile?.relative_path || "A validated CSV will be created after import.",
  );
  const stageView = document.getElementById("replayStageFileView");
  const stageDownload = document.getElementById("replayStageFileDownload");
  if (stageView) {
    stageView.hidden = !stageFile?.exists;
    stageView.href = stageFile?.view_url || "#";
  }
  if (stageDownload) {
    stageDownload.hidden = !stageFile?.exists;
    stageDownload.href = stageFile?.download_url || "#";
  }
  setText("rRows", batch ? (summary.rows ?? "No data") : 0);
  setText("rValid", batch ? (summary.valid_urls ?? "No data") : 0);
  setText("rInvalid", batch ? (summary.invalid_rows ?? "No data") : 0);
  setText(
    "rImportDuplicates",
    batch ? (summary.duplicates_in_import ?? "No data") : 0,
  );
  setText(
    "rAlreadyCaptured",
    batch ? (summary.already_captured ?? "No data") : 0,
  );
  setText("rQueued", batch ? (summary.queued ?? "No data") : 0);
  setText("rCaptured", batch ? (progress.captured ?? "No data") : 0);
  setText("rFailed", batch ? (progress.failed ?? "No data") : 0);
  setText("rBlocked", batch ? (progress.blocked ?? "No data") : 0);
  setText("rRemaining", batch ? (progress.remaining ?? "No data") : 0);
  setText("rProcessingQueued", batch ? (processing.queued ?? "No data") : 0);
  setText(
    "rProcessingResolved",
    batch ? (processing.resolved ?? "No data") : 0,
  );
  setText("rProcessingFailed", batch ? (processing.failed ?? "No data") : 0);

  const percent = progress.total
    ? Math.min(
        100,
        Math.round((100 * (progress.processed || 0)) / progress.total),
      )
    : 0;
  const fill = document.getElementById("replayProgressFill");
  const progressbar = fill?.parentElement;
  if (fill) fill.style.width = `${percent}%`;
  if (progressbar) progressbar.setAttribute("aria-valuenow", String(percent));
  setText(
    "replayProgressLabel",
    batch
      ? `${progress.resolved || 0} / ${progress.total || 0} capture rows resolved · ${progress.captured || 0} captured · ${progress.failed || 0} failed · ${progress.remaining || 0} remaining`
      : "No replay batch is active.",
  );

  const stagingCard = document.getElementById("stagingPhaseCard");
  const captureCard = document.getElementById("capturePhaseCard");
  const processingCard = document.getElementById("processingPhaseCard");
  const stagingState = !batch
    ? "waiting"
    : stageFile?.exists
      ? "complete"
      : "attention";
  const captureState = !batch
    ? "waiting"
    : ["running", "paused", "stopping"].includes(batch.status)
      ? batch.status
      : batch.status === "draft"
        ? "ready"
        : "complete";
  const processingActive =
    ACTIVE_PROCESSING_COMMANDS.has(latestProcessingControl) &&
    (processing.queued || 0) + (processing.active || 0) > 0;
  const processingState =
    !batch || ["draft", "running", "paused", "stopping"].includes(batch.status)
      ? "locked"
      : processingActive
        ? latestProcessingControl
        : (processing.queued || 0) > 0
          ? "ready"
          : (processing.failed || 0) > 0
            ? "attention"
            : (processing.total || 0) > 0
              ? "complete"
              : "empty";
  if (stagingCard) stagingCard.dataset.state = stagingState;
  if (captureCard) captureCard.dataset.state = captureState;
  if (processingCard) processingCard.dataset.state = processingState;
  setText(
    "stagingPhaseState",
    stagingState[0].toUpperCase() + stagingState.slice(1),
  );
  setText(
    "stagingPhaseDetail",
    stageFile?.exists
      ? `${summary.rows || 0} source row(s) stored in ${stageFile.relative_path}.`
      : batch
        ? "The Stage 1 file is unavailable; capture is blocked."
        : "Import, normalize, and validate URLs into a viewable file.",
  );
  setText(
    "capturePhaseState",
    captureState[0].toUpperCase() + captureState.slice(1),
  );
  setText(
    "capturePhaseDetail",
    batch
      ? `${progress.resolved || 0}/${progress.total || 0} checkpointed; completed URLs are never captured again.`
      : "Validate and capture each queued URL once.",
  );
  setText(
    "processingPhaseState",
    processingState[0].toUpperCase() + processingState.slice(1),
  );
  setText(
    "processingPhaseDetail",
    processingActive
      ? `Batch processor is running — ${processing.queued || 0} of this batch's records still queued.`
      : processingState === "locked"
        ? "Starts only after the capture pass finishes."
        : `${processing.queued || 0} queued · ${processing.resolved || 0} resolved · ${processing.failed || 0} failed.`,
  );

  const current = snapshot?.current;
  const currentBox = document.getElementById("replayCurrent");
  currentBox?.classList.toggle("is-active", Boolean(current));
  setText(
    "replayCurrentCategory",
    current?.category ||
      (current
        ? `${current.platform} · row ${current.row_number}`
        : "Waiting for a queued URL"),
  );
  setText(
    "replayCurrentStatus",
    current?.status_message ||
      (batch?.status === "running"
        ? "Waiting for the GuardianLens extension to claim the next URL."
        : batch
          ? `Batch is ${batch.status}.`
          : "The extension checks the queue while Chrome is open."),
  );
  const currentUrl = document.getElementById("replayCurrentUrl");
  if (currentUrl) {
    currentUrl.hidden = !current?.source_url;
    currentUrl.textContent = current?.source_url || "";
    if (current?.source_url) currentUrl.href = current.source_url;
    else currentUrl.removeAttribute("href");
  }

  document.querySelectorAll("[data-replay-command]").forEach((button) => {
    const command = button.dataset.replayCommand;
    const enabled =
      Boolean(batch) &&
      ((command === "start" &&
        batch.status === "draft" &&
        stageFile?.exists &&
        (summary.queued || 0) > 0) ||
        (command === "pause" && batch.status === "running") ||
        (command === "resume" && batch.status === "paused") ||
        (command === "stop" && ["running", "paused"].includes(batch.status)) ||
        (command === "retry-failed" &&
          ["completed", "stopped"].includes(batch.status) &&
          (progress.failed || 0) > 0 &&
          latestProcessingControl === "idle"));
    button.disabled = !enabled;
  });
  updateProcessingControls();

  const attemptRows = document.getElementById("replayAttemptRows");
  if (attemptRows) {
    const attempts = snapshot?.recent_attempts || [];
    const signature = JSON.stringify(attempts);
    if (signature === lastReplayAttempts) return;
    lastReplayAttempts = signature;
    attemptRows.textContent = "";
    if (!attempts.length) {
      const row = document.createElement("tr");
      const cell = appendCell(row, "No capture attempts in the latest batch.");
      cell.colSpan = 7;
      attemptRows.appendChild(row);
    } else {
      attempts.forEach((attempt) => {
        const row = document.createElement("tr");
        appendCell(row, attempt.row_number);
        appendCell(row, attempt.platform || "—");
        const urlCell = appendCell(row, "");
        if (/^https?:\/\//i.test(attempt.source_url || "")) {
          const link = document.createElement("a");
          link.href = attempt.source_url;
          link.target = "_blank";
          link.rel = "noreferrer";
          link.textContent = attempt.source_url;
          urlCell.appendChild(link);
        } else {
          urlCell.textContent = attempt.source_url || "—";
        }
        appendCell(row, attempt.status);
        appendCell(
          row,
          attempt.error_message ||
            (attempt.status === "captured"
              ? "Capture checkpoint committed"
              : "In progress"),
        );
        appendCell(row, attempt.attempt_number || 0);
        appendCell(row, attempt.finished_at || "In progress");
        attemptRows.appendChild(row);
      });
    }
  }
}

function renderAiStatus(status) {
  document.querySelectorAll(".provider-pill").forEach((button) => {
    const active = button.dataset.provider === status.active;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
    button.textContent = button.dataset.provider;
  });
  const provider = status.providers.find((candidate) => candidate.active);
  setText(
    "providerModel",
    provider
      ? `Active model: ${provider.model}`
      : "No active provider is configured.",
  );
}

function renderRecommendations(recommendations) {
  const container = document.getElementById("recommendations");
  if (!container) return;
  container.textContent = "";
  if (!recommendations.length) {
    const message = document.createElement("p");
    message.textContent =
      "Configured targets are currently covered by approved and pending records.";
    container.appendChild(message);
    return;
  }
  recommendations.forEach((recommendation) => {
    const article = document.createElement("article");
    const title = document.createElement("b");
    title.textContent = `${recommendation.platform[0].toUpperCase()}${recommendation.platform.slice(1)} → ${recommendation.category}`;
    const detail = document.createElement("small");
    detail.textContent = `Estimated remaining ${recommendation.remaining}`;
    article.append(title, detail);
    container.appendChild(article);
  });
}

function renderCategories(categories) {
  const body = document.getElementById("categoryRows");
  if (!body) return;
  body.textContent = "";
  categories.forEach((category) => {
    const row = document.createElement("tr");
    appendCell(row, category.name);
    appendCell(row, category.approved);
    appendCell(row, category.pending);
    appendCell(row, category.target);
    appendCell(row, category.remaining);
    body.appendChild(row);
  });
}

let lastOperationalQueueSignature = null;

function renderOperationalQueue(items) {
  const body = document.getElementById("operationalQueueRows");
  if (!body) return;
  const signature = JSON.stringify(
    items.map((item) => [
      item.listing_id,
      item.status,
      item.updated_at,
      item.title,
      item.page_title,
      item.ai_error,
      item.status_reason,
    ]),
  );
  if (signature === lastOperationalQueueSignature) return;
  lastOperationalQueueSignature = signature;
  const active = document.activeElement;
  const focusedRow = active?.closest?.("tr");
  const focusedListingId = focusedRow?.dataset.listingId || null;
  const focusedSelector = active?.classList?.contains("retry-listing")
    ? ".retry-listing"
    : active?.tagName === "A"
      ? "a"
      : null;
  const selected = new Set(
    [...body.querySelectorAll(".retry-listing:checked")].map(
      (input) => input.value,
    ),
  );
  body.textContent = "";
  if (!items.length) {
    const row = document.createElement("tr");
    const cell = appendCell(
      row,
      "No captured, processing, failed, or duplicate-blocked records.",
    );
    cell.colSpan = 6;
    body.appendChild(row);
    if (focusedListingId) document.getElementById("retrySelected")?.focus();
    return;
  }
  const retryable = new Set(["processing_failed", "ai_failed", "image_failed"]);
  items.forEach((item) => {
    const row = document.createElement("tr");
    row.dataset.listingId = item.listing_id;
    const selection = document.createElement("td");
    if (retryable.has(item.status)) {
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = "retry-listing";
      checkbox.value = item.listing_id;
      checkbox.checked = selected.has(item.listing_id);
      checkbox.setAttribute(
        "aria-label",
        `Select ${listingLabel(item)} for retry`,
      );
      selection.appendChild(checkbox);
    }
    row.appendChild(selection);
    appendCell(
      row,
      `${item.platform[0].toUpperCase()}${item.platform.slice(1)}`,
    );
    appendRecordLink(appendCell(row, ""), item);
    const statusCell = appendCell(row, "");
    const status = document.createElement("span");
    status.className = "status";
    status.textContent = item.status;
    statusCell.appendChild(status);
    appendCell(row, item.ai_error || item.status_reason || "—");
    appendCell(row, item.captured_at);
    body.appendChild(row);
  });
  if (focusedListingId && focusedSelector) {
    const replacement = [...body.rows]
      .find((row) => row.dataset.listingId === focusedListingId)
      ?.querySelector(focusedSelector);
    (replacement || document.getElementById("retrySelected"))?.focus();
  }
}

let lastActivitySignature = null;

function renderActivity(items) {
  const body = document.getElementById("activityRows");
  if (!body) return;
  const signature = JSON.stringify(
    items.map((item) => [
      item.history_id,
      item.listing_id,
      item.timestamp,
      item.title,
      item.page_title,
      item.from_status,
      item.to_status,
      item.reason,
    ]),
  );
  if (signature === lastActivitySignature) return;
  lastActivitySignature = signature;
  const active = document.activeElement;
  const focusedRow = active?.closest?.("tr");
  const focusedHistoryId =
    active?.tagName === "A" ? focusedRow?.dataset.historyId : null;
  body.textContent = "";
  if (!items.length) {
    const row = document.createElement("tr");
    const cell = appendCell(row, "No lifecycle activity yet.");
    cell.colSpan = 4;
    body.appendChild(row);
    if (focusedHistoryId) document.getElementById("activity-heading")?.focus();
    return;
  }
  items.forEach((item) => {
    const row = document.createElement("tr");
    row.dataset.listingId = item.listing_id;
    row.dataset.historyId = item.history_id;
    appendCell(row, item.timestamp);
    appendRecordLink(appendCell(row, ""), item);
    appendCell(row, `${item.from_status || "new"} → ${item.to_status}`);
    appendCell(row, item.reason || "—");
    body.appendChild(row);
  });
  if (focusedHistoryId) {
    const replacement = [...body.rows]
      .find((row) => row.dataset.historyId === focusedHistoryId)
      ?.querySelector("a");
    (replacement || document.getElementById("activity-heading"))?.focus();
  }
}

function renderDashboard(snapshot) {
  if (
    !snapshot?.counts ||
    !snapshot.plan?.platforms ||
    !snapshot.review_stats ||
    !snapshot.batch?.control ||
    !snapshot.replay ||
    !snapshot.ai_status?.providers ||
    !Array.isArray(snapshot.operational_queue) ||
    !Array.isArray(snapshot.activity)
  ) {
    throw new Error("Collection status is incomplete.");
  }
  Object.entries(snapshot.counts).forEach(([status, count]) =>
    setText(`count-${status}`, count ?? "No data"),
  );
  setText("summaryReady", snapshot.counts.ready_for_review ?? "No data");
  setText("summaryAttention", snapshot.counts.needs_attention ?? "No data");
  setText("approvedTotal", snapshot.plan.approved_total);
  setText("datasetTarget", snapshot.plan.total_target);
  const carousell = snapshot.plan.platforms.carousell;
  const mudah = snapshot.plan.platforms.mudah;
  if (carousell) {
    setText("carousellApproved", carousell.approved);
    setText("carousellTarget", carousell.target);
    setText("carousellPending", carousell.pending);
  }
  if (mudah) {
    setText("mudahApproved", mudah.approved);
    setText("mudahTarget", mudah.target);
    setText("mudahPending", mudah.pending);
  }
  setText("reviewOpen", snapshot.review_stats.open_count);
  setText("reviewedToday", snapshot.review_stats.reviewed_today);
  setText("reviewTimezone", snapshot.review_stats.operator_timezone);
  const hasReviewHistory = snapshot.review_stats.completed_sessions > 0;
  setText(
    "reviewAverage",
    hasReviewHistory
      ? `${Math.round(snapshot.review_stats.average_seconds)} sec`
      : "Not enough history",
  );
  setText(
    "reviewEstimate",
    hasReviewHistory
      ? `${Math.floor(snapshot.review_stats.estimated_remaining_seconds / 60)} min`
      : "Not enough history",
  );
  setText(
    "unassignedCategoryPending",
    snapshot.plan.unassigned_category_pending,
  );
  setText(
    "unconfiguredCategoryApproved",
    snapshot.plan.unconfigured_category_approved,
  );
  renderRecommendations(snapshot.plan.recommendations);
  renderCategories(snapshot.plan.categories);
  renderOperationalQueue(snapshot.operational_queue);
  renderActivity(snapshot.activity);
  renderBatch(snapshot.batch);
  renderReplay(snapshot.replay);
  renderAiStatus(snapshot.ai_status);
}

let lastReviewQueueSignature = null;

function renderReviewQueueTabCounts(bucketCounts) {
  if (!bucketCounts) return;
  setText("tabCountReady", bucketCounts.ready);
  setText("tabCountAttention", bucketCounts.attention);
  setText("tabCountOther", bucketCounts.other);
  setText("tabCountAll", bucketCounts.all);
}

function renderReviewQueue(items, total = items.length) {
  const body = document.getElementById("reviewQueueRows");
  if (!body) return;
  setText("reviewQueueCount", total);
  setText("reviewQueueShown", items.length);
  const signature = JSON.stringify(
    items.map((item) => [
      item.listing_id,
      item.status,
      item.updated_at,
      item.title,
      item.category,
      item.price,
      item.currency,
    ]),
  );
  if (signature === lastReviewQueueSignature) return;
  lastReviewQueueSignature = signature;
  const active = document.activeElement;
  const focusedRow = active?.closest?.("tr");
  const focusedListingId = focusedRow?.dataset.listingId || null;
  const focusedSelector =
    active?.tagName === "A"
      ? "a"
      : active?.tagName === "BUTTON"
        ? "button"
        : null;
  body.textContent = "";
  const empty = document.getElementById("reviewQueueEmpty");
  if (empty) empty.hidden = total > 0;

  items.forEach((item) => {
    const row = document.createElement("tr");
    row.dataset.listingId = item.listing_id;
    appendCell(
      row,
      `${item.platform[0].toUpperCase()}${item.platform.slice(1)}`,
    );
    appendRecordLink(appendCell(row, ""), item);
    appendCell(row, item.category || "Not extracted");
    const price =
      item.price == null
        ? "Not extracted"
        : `${item.currency || "Not extracted"} ${Number(item.price).toFixed(2)}`;
    appendCell(row, price);
    const statusCell = appendCell(row, "");
    const status = document.createElement("span");
    status.className = "status";
    status.textContent = item.status;
    statusCell.appendChild(status);
    const actionCell = appendCell(row, "");
    const bucket = document.querySelector(".queue-tabs")?.dataset.bucket;
    const bucketQs =
      bucket && bucket !== "all" ? `?bucket=${encodeURIComponent(bucket)}` : "";
    if (item.status === "under_review") {
      const link = document.createElement("a");
      link.className = "button";
      link.href = `/review/${encodeURIComponent(item.listing_id)}${bucketQs}`;
      link.textContent = "Continue";
      actionCell.appendChild(link);
    } else {
      const form = document.createElement("form");
      form.method = "post";
      form.action = `/review/${encodeURIComponent(item.listing_id)}/begin${bucketQs}`;
      const hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.name = "token";
      hidden.value = GL_TOKEN;
      const button = document.createElement("button");
      button.type = "submit";
      button.textContent = "Begin review";
      form.append(hidden, button);
      actionCell.appendChild(form);
    }
    body.appendChild(row);
  });
  if (focusedListingId && focusedSelector) {
    const replacement = [...body.rows]
      .find((row) => row.dataset.listingId === focusedListingId)
      ?.querySelector(focusedSelector);
    (replacement || document.getElementById("reviewQueueHeading"))?.focus();
  }
}

let dashboardRefreshPending = false;

async function refreshDashboard() {
  if (dashboardRefreshPending) return;
  dashboardRefreshPending = true;
  const button = document.getElementById("refreshDashboard");
  const errorMessage = document.getElementById("dashboardRefreshError");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  if (button) button.disabled = true;
  try {
    renderDashboard(
      await api("/api/dashboard/status", { signal: controller.signal }),
    );
    if (errorMessage) errorMessage.hidden = true;
    setText(
      "dashboardFreshness",
      `Live stored data · updated ${new Date().toLocaleTimeString()}`,
    );
  } catch (error) {
    setText(
      "dashboardFreshness",
      "Updates disconnected · showing the last stored snapshot",
    );
    if (errorMessage) {
      errorMessage.textContent = `Dashboard refresh failed: ${error.message} Retrying automatically; you can also select Refresh now.`;
      errorMessage.hidden = false;
    }
  } finally {
    clearTimeout(timeout);
    dashboardRefreshPending = false;
    if (button) button.disabled = false;
  }
}

async function refreshReviewQueue() {
  const errorMessage = document.getElementById("reviewQueueError");
  try {
    const bucket = document.querySelector(".queue-tabs")?.dataset.bucket;
    const query =
      bucket && bucket !== "all" ? `?bucket=${encodeURIComponent(bucket)}` : "";
    const response = await api(`/api/review/queue${query}`);
    if (errorMessage) {
      errorMessage.hidden = true;
      errorMessage.textContent = "";
    }
    renderReviewQueue(response.rows, response.total);
    renderReviewQueueTabCounts(response.bucket_counts);
  } catch (error) {
    if (errorMessage) {
      errorMessage.hidden = false;
      errorMessage.textContent = `Review queue refresh failed: ${error.message}`;
    }
  }
}

async function startBatch() {
  const start = document.getElementById("batchStart");
  if (start) start.disabled = true;
  const limits = selectedProcessingLimits();
  setText("progressLabel", `Starting: ${processingLimitLabel(limits)}…`);
  try {
    await api("/api/batch/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(limits),
    });
    await refreshDashboard();
  } catch (error) {
    setText("progressLabel", `Could not start batch: ${error.message}`);
    await refreshDashboard();
  }
}

async function sendBatchCommand(command) {
  try {
    renderBatch(await api(`/api/batch/${command}`, { method: "POST" }));
  } catch (error) {
    setText("progressLabel", `Could not ${command} batch: ${error.message}`);
  }
}

function setReplayNotice(message, kind = "") {
  const notice = document.getElementById("replayNotice");
  if (!notice) return;
  notice.textContent = message;
  notice.classList.toggle("is-error", kind === "error");
  notice.classList.toggle("is-success", kind === "success");
}

async function importReplay(form, submitButton, sourceLabel) {
  if (!form || !submitButton) return;
  submitButton.disabled = true;
  setReplayNotice(`Validating ${sourceLabel}…`);
  try {
    const snapshot = await api("/api/replay/import", {
      method: "POST",
      body: new FormData(form),
    });
    renderReplay(snapshot);
    const summary = snapshot.import_summary;
    setReplayNotice(
      `Stage 1 file created with ${summary.rows} row(s): ${summary.queued} queued, ${summary.invalid_rows} invalid, ${summary.duplicates_in_import} duplicate in the import, ${summary.already_captured} already captured. Open the CSV to inspect it, then start capture.`,
      "success",
    );
  } catch (error) {
    setReplayNotice(`Import failed: ${error.message}`, "error");
  } finally {
    submitButton.disabled = false;
  }
}

async function sendReplayCommand(command) {
  if (!latestReplayBatchId) {
    setReplayNotice(
      "Import a CSV or paste URLs before using batch controls.",
      "error",
    );
    return;
  }
  setReplayNotice(`${command.replace("-", " ")} requested…`);
  try {
    let path;
    if (command === "start")
      path = `/api/replay/${encodeURIComponent(latestReplayBatchId)}/start`;
    else if (command === "retry-failed")
      path = `/api/replay/${encodeURIComponent(latestReplayBatchId)}/retry-failed`;
    else
      path = `/api/replay/${encodeURIComponent(latestReplayBatchId)}/command/${encodeURIComponent(command)}`;
    const snapshot = await api(path, { method: "POST" });
    renderReplay(snapshot);
    setReplayNotice(
      `Capture batch is now ${snapshot.batch.status}.`,
      "success",
    );
  } catch (error) {
    setReplayNotice(
      `Could not ${command.replace("-", " ")}: ${error.message}`,
      "error",
    );
  }
}

let modelRequestGeneration = 0;

async function switchProvider(provider) {
  const providerButtons = [...document.querySelectorAll(".provider-pill")];
  const previousDisabledStates = providerButtons.map(
    (button) => button.disabled,
  );
  providerButtons.forEach((button) => {
    button.disabled = true;
  });
  modelRequestGeneration += 1;
  try {
    const status = await api("/api/ai/provider", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider }),
    });
    renderAiStatus(status);
    const models = document.getElementById("providerModels");
    if (models) models.textContent = "";
  } catch (error) {
    setText("providerModel", `Could not switch provider: ${error.message}`);
  } finally {
    providerButtons.forEach((button, index) => {
      button.disabled = previousDisabledStates[index];
    });
  }
}

async function loadModels() {
  const active = document.querySelector(".provider-pill.active")?.dataset
    .provider;
  const list = document.getElementById("providerModels");
  if (!list || !active) return;
  const requestGeneration = ++modelRequestGeneration;
  list.textContent = "";
  const loading = document.createElement("li");
  loading.textContent = `Loading ${active} models…`;
  list.appendChild(loading);
  try {
    const response = await api(`/api/ai/models/${encodeURIComponent(active)}`);
    const currentProvider = document.querySelector(".provider-pill.active")
      ?.dataset.provider;
    if (
      requestGeneration !== modelRequestGeneration ||
      currentProvider !== active
    )
      return;
    list.textContent = "";
    response.models.forEach((model) => {
      const item = document.createElement("li");
      item.textContent = `${model}${model === response.configured_model ? " ← configured" : ""}`;
      list.appendChild(item);
    });
  } catch (error) {
    const currentProvider = document.querySelector(".provider-pill.active")
      ?.dataset.provider;
    if (
      requestGeneration !== modelRequestGeneration ||
      currentProvider !== active
    )
      return;
    list.textContent = "";
    const item = document.createElement("li");
    item.textContent = `Could not load models: ${error.message}`;
    list.appendChild(item);
  }
}

async function retrySelected() {
  const listingIds = [
    ...document.querySelectorAll(".retry-listing:checked"),
  ].map((input) => input.value);
  if (!listingIds.length) {
    setText(
      "progressLabel",
      "Select at least one eligible failed listing to retry.",
    );
    return;
  }
  try {
    const result = await api("/api/queue/retry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ listing_ids: listingIds }),
    });
    setText(
      "progressLabel",
      `Queued ${result.retried.length} listing(s) for retry${result.rejected.length ? `; ${result.rejected.length} rejected` : ""}.`,
    );
    await refreshDashboard();
  } catch (error) {
    setText("progressLabel", `Could not retry listings: ${error.message}`);
  }
}

async function exportApproved() {
  try {
    const result = await api("/api/export", { method: "POST" });
    setText("exportStatus", `Exported: ${result.files.join(", ")}`);
  } catch (error) {
    setText("exportStatus", `Export failed: ${error.message}`);
  }
}

document.getElementById("batchStart")?.addEventListener("click", startBatch);
["duration", "limit"].forEach((id) => {
  document
    .getElementById(id)
    ?.addEventListener("input", updateProcessingControls);
});
document.querySelectorAll("[data-batch-command]").forEach((button) => {
  button.addEventListener("click", () =>
    sendBatchCommand(button.dataset.batchCommand),
  );
});
document.querySelectorAll(".provider-pill").forEach((button) => {
  button.addEventListener("click", () =>
    switchProvider(button.dataset.provider),
  );
});
document
  .getElementById("loadProviderModels")
  ?.addEventListener("click", loadModels);
document
  .getElementById("retrySelected")
  ?.addEventListener("click", retrySelected);
document
  .getElementById("exportApproved")
  ?.addEventListener("click", exportApproved);
document
  .getElementById("csvImportForm")
  ?.addEventListener("submit", (event) => {
    event.preventDefault();
    importReplay(
      event.currentTarget,
      document.getElementById("csvImportButton"),
      "CSV",
    );
  });
document
  .getElementById("manualImportForm")
  ?.addEventListener("submit", (event) => {
    event.preventDefault();
    importReplay(
      event.currentTarget,
      document.getElementById("manualImportButton"),
      "pasted URLs",
    );
  });
document.querySelectorAll("[data-replay-command]").forEach((button) => {
  button.addEventListener("click", () =>
    sendReplayCommand(button.dataset.replayCommand),
  );
});

const csvFile = document.getElementById("csvFile");
const csvDropZone = document.getElementById("csvDropZone");
csvFile?.addEventListener("change", () => {
  setText("csvFileName", csvFile.files?.[0]?.name || "No file selected");
});
if (csvDropZone && csvFile) {
  ["dragenter", "dragover"].forEach((type) => {
    csvDropZone.addEventListener(type, (event) => {
      event.preventDefault();
      csvDropZone.classList.add("is-dragging");
    });
  });
  ["dragleave", "drop"].forEach((type) => {
    csvDropZone.addEventListener(type, (event) => {
      event.preventDefault();
      csvDropZone.classList.remove("is-dragging");
    });
  });
  csvDropZone.addEventListener("drop", (event) => {
    const [file] = event.dataTransfer?.files || [];
    if (!file) return;
    const transfer = new DataTransfer();
    transfer.items.add(file);
    csvFile.files = transfer.files;
    setText("csvFileName", file.name);
  });
}
document.getElementById("copyToken")?.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(GL_TOKEN);
    setText("exportStatus", "Extension token copied.");
  } catch (_error) {
    setText(
      "exportStatus",
      "Copy failed. Select the token and copy it manually.",
    );
  }
});

const reviewEditForm = document.getElementById("reviewEditForm");
if (reviewEditForm) {
  let reviewIsDirty = false;
  const approveUnchanged = document.getElementById("approveUnchanged");
  const unsavedNotice = document.getElementById("unsavedReviewNotice");
  const markDirty = () => {
    reviewIsDirty = true;
    if (approveUnchanged) approveUnchanged.disabled = true;
    if (unsavedNotice) unsavedNotice.hidden = false;
  };
  reviewEditForm.addEventListener("input", markDirty);
  reviewEditForm.addEventListener("submit", () => {
    reviewIsDirty = false;
  });
  document.querySelectorAll("[data-discard-edits]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (
        reviewIsDirty &&
        !window.confirm(
          "This outcome will discard your unsaved edits. Continue?",
        )
      ) {
        event.preventDefault();
        return;
      }
      reviewIsDirty = false;
    });
  });
  window.addEventListener("beforeunload", (event) => {
    if (!reviewIsDirty) return;
    event.preventDefault();
    event.returnValue = "";
  });
}

if (document.getElementById("dashboard-heading")) {
  // Use the same renderer for the server snapshot and subsequent live updates.
  // The JSON is escaped by Jinja's tojson filter and contains no executable code.
  try {
    renderDashboard(
      JSON.parse(document.getElementById("dashboardInitialState").textContent),
    );
  } catch (_error) {
    setText("dashboardFreshness", "Waiting for current collection status…");
  }
  document
    .getElementById("refreshDashboard")
    ?.addEventListener("click", refreshDashboard);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshDashboard();
  });
  // Persist disclosure choices separately from forms; polling never replaces them.
  document.querySelectorAll("[data-dashboard-section]").forEach((section) => {
    const key = `guardianlens.dashboard.${section.dataset.dashboardSection}`;
    try {
      const saved = sessionStorage.getItem(key);
      if (saved !== null) section.open = saved === "open";
    } catch (_error) {
      /* Disclosure still works when browser storage is blocked. */
    }
    section.addEventListener("toggle", () => {
      try {
        sessionStorage.setItem(key, section.open ? "open" : "closed");
      } catch (_error) {
        /* Native details remains usable without persistence. */
      }
    });
  });
  refreshDashboard();
  setInterval(() => {
    if (!document.hidden) refreshDashboard();
  }, 4000);
}

if (document.getElementById("reviewQueueRows")) {
  refreshReviewQueue();
  setInterval(() => {
    if (!document.hidden) refreshReviewQueue();
  }, 4000);
}
