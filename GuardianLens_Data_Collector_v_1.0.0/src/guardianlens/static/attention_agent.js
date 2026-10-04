(() => {
  const panel = document.getElementById("attentionPanel");
  if (!panel) return;

  const activeStates = new Set(["running", "paused", "stopping"]);
  const terminalStates = new Set(["completed", "stopped", "failed"]);
  const form = document.getElementById("attentionForm");
  let attention = null;
  let recovery = null;
  let busy = false;
  let polling = false;
  let connected = false;

  const element = (id) => document.getElementById(id);
  const readable = (value) => String(value ?? "").replaceAll("_", " ");
  const setText = (id, value) => {
    element(id).textContent = String(value ?? "");
  };
  const valueText = (value) =>
    value === null || value === undefined
      ? "Not extracted"
      : typeof value === "object"
        ? JSON.stringify(value)
        : String(value);

  async function request(path, payload) {
    const headers = new Headers();
    const options = { headers };
    if (payload !== undefined) {
      headers.set("Content-Type", "application/json");
      headers.set(
        "X-GuardianLens-Token",
        element("token")?.textContent.trim() || "",
      );
      options.method = "POST";
      options.body = JSON.stringify(payload);
    }
    const response = await fetch(path, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = Array.isArray(data.detail)
        ? data.detail
            .map(
              (issue) =>
                `${issue.loc?.slice(1).join(".") || "Input"}: ${issue.msg}`,
            )
            .join("; ")
        : data.detail;
      throw new Error(
        typeof detail === "string"
          ? detail
          : `Request failed (${response.status})`,
      );
    }
    return data;
  }

  function reportError(message = "") {
    setText("attentionError", message);
    element("attentionError").hidden = !message;
  }

  function cell(row, content) {
    const td = document.createElement("td");
    td.textContent = content ?? "";
    row.append(td);
    return td;
  }

  let lastItems = null;

  function renderItems(items) {
    const signature = JSON.stringify(items || []);
    if (signature === lastItems) return;
    lastItems = signature;
    const rows = element("attentionItemRows");
    rows.replaceChildren();
    for (const item of items || []) {
      const row = document.createElement("tr");
      const link = document.createElement("a");
      link.href = `/review/${encodeURIComponent(item.listing_id)}`;
      link.textContent = item.title || item.listing_id;
      cell(row).append(link);
      cell(row, readable(item.outcome));
      const findings = cell(row);
      if (item.findings?.length) {
        const list = document.createElement("ul");
        for (const finding of item.findings) {
          const li = document.createElement("li");
          li.textContent = `${finding.message || readable(finding.code)}${finding.action ? ` Next: ${readable(finding.action)}.` : ""}`;
          list.append(li);
        }
        findings.append(list);
      } else {
        findings.textContent =
          item.outcome === "pending" || item.outcome === "inspecting"
            ? "Waiting for inspection."
            : "No remaining findings recorded.";
      }
      cell(
        row,
        item.changes?.length
          ? item.changes
              .map(
                (change) =>
                  `${readable(change.field)}: ${valueText(change.before)} → ${valueText(change.after)}`,
              )
              .join("; ")
          : "No fields changed",
      );
      rows.append(row);
    }
    if (!rows.children.length) {
      const row = document.createElement("tr");
      cell(row, "No inspection results yet.").colSpan = 4;
      rows.append(row);
    }
  }

  function renderControls() {
    const run = attention?.run;
    const state = run?.status;
    const recoveryState = recovery?.batch?.status;
    const active = activeStates.has(state);
    const recoveryActive = activeStates.has(recoveryState);
    const blocked = busy || !connected;
    for (const control of form.querySelectorAll(
      'input, select, textarea, button[type="submit"]',
    )) {
      control.disabled = blocked || active || recoveryActive;
    }
    for (const button of panel.querySelectorAll("[data-attention-command]")) {
      const command = button.dataset.attentionCommand;
      const allowed =
        command === "pause"
          ? state === "running"
          : command === "resume"
            ? state === "paused"
            : state === "running" || state === "paused";
      button.disabled = blocked || !allowed;
    }
    element("attentionRecoverSellers").disabled =
      blocked ||
      active ||
      recoveryActive ||
      !terminalStates.has(state) ||
      !(attention?.progress?.awaiting_capture > 0);
    element("attentionProcessRecovered").disabled =
      blocked ||
      active ||
      !terminalStates.has(recoveryState) ||
      !(recovery?.progress?.succeeded > 0);
    for (const button of panel.querySelectorAll(
      "[data-attention-recovery-command]",
    )) {
      const command = button.dataset.attentionRecoveryCommand;
      const allowed =
        command === "pause"
          ? recoveryState === "running"
          : command === "resume"
            ? recoveryState === "paused"
            : recoveryState === "running" || recoveryState === "paused";
      button.disabled = blocked || !allowed;
    }
  }

  function renderAttention() {
    const run = attention?.run;
    setText("attentionRunStatus", readable(run?.status || "idle"));
    for (const key of [
      "total",
      "inspected",
      "changed",
      "ready",
      "awaiting_capture",
      "awaiting_human",
      "failed",
      "skipped",
      "pending",
    ]) {
      setText(`attentionCount-${key}`, attention?.progress?.[key] || 0);
    }
    setText(
      "attentionNotice",
      run
        ? `${readable(run.mode)} · ${readable(run.status)}${run.watch ? " · watching for changed records" : ""} · ${run.api_calls || 0} / ${run.api_call_limit ?? 0} AI calls${run.status_reason ? ` · ${run.status_reason}` : ""}`
        : "Choose Inspect all to check the bucket, or Start repair to fill supported values.",
    );
    renderItems(attention?.items);
    renderControls();
  }

  function renderRecovery() {
    const batch = recovery?.batch;
    const progress = recovery?.progress || {};
    setText(
      "attentionRecoveryNotice",
      batch
        ? `${batch.name || "Seller recovery"} · ${readable(batch.status)} · ${progress.succeeded || 0} captured · ${progress.remaining || 0} remaining · ${progress.failed || 0} failed${recovery.retry_after_seconds ? ` · next attempt in ${recovery.retry_after_seconds} seconds` : ""}`
        : "No seller recovery is active.",
    );
    renderControls();
  }

  function limits() {
    return {
      item_limit: element("attentionLimit").value
        ? Number(element("attentionLimit").value)
        : null,
      time_limit_minutes: Number(element("attentionMinutes").value),
      api_call_limit: Number(element("attentionApiLimit").value),
    };
  }

  async function mutate(path, payload = {}, kind = "attention") {
    if (busy) return;
    busy = true;
    reportError();
    renderControls();
    try {
      const result = await request(path, payload);
      if (kind === "recovery") {
        recovery = result;
        renderRecovery();
      } else {
        attention = result;
        renderAttention();
      }
    } catch (error) {
      reportError(error.message);
    } finally {
      busy = false;
      renderControls();
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const mode = event.submitter?.value === "repair" ? "repair" : "inspect";
    const ids = [
      ...new Set(
        element("attentionListingIds")
          .value.split(/[\s,]+/)
          .filter(Boolean),
      ),
    ];
    if (ids.length > 10000 || ids.some((id) => id.length > 64)) {
      reportError(
        "Choose at most 10,000 listing IDs, each no more than 64 characters.",
      );
      return;
    }
    mutate("/api/attention/start", {
      ...limits(),
      mode,
      item_limit: mode === "inspect" ? null : limits().item_limit,
      listing_ids: ids.length ? ids : null,
      platform: element("attentionPlatform").value || null,
      reason: element("attentionReason").value || null,
      watch: element("attentionWatch").checked,
    });
  });

  for (const button of panel.querySelectorAll("[data-attention-command]")) {
    button.addEventListener("click", () => {
      if (attention?.run?.run_id)
        mutate(
          `/api/attention/${encodeURIComponent(attention.run.run_id)}/command/${button.dataset.attentionCommand}`,
        );
    });
  }
  element("attentionRecoverSellers").addEventListener("click", () => {
    if (attention?.run?.run_id)
      mutate(
        `/api/attention/${encodeURIComponent(attention.run.run_id)}/recover-sellers`,
        {},
        "recovery",
      );
  });
  for (const button of panel.querySelectorAll(
    "[data-attention-recovery-command]",
  )) {
    button.addEventListener("click", () => {
      if (recovery?.batch?.retry_batch_id)
        mutate(
          `/api/seller-retry/${encodeURIComponent(recovery.batch.retry_batch_id)}/command/${button.dataset.attentionRecoveryCommand}`,
          {},
          "recovery",
        );
    });
  }
  element("attentionProcessRecovered").addEventListener("click", () => {
    if (!form.reportValidity() || !recovery?.batch?.retry_batch_id) return;
    mutate("/api/attention/start", {
      ...limits(),
      mode: "repair",
      recovery_batch_id: recovery.batch.retry_batch_id,
    });
  });

  async function refresh() {
    if (polling || busy || document.hidden) return;
    polling = true;
    try {
      const results = await Promise.allSettled([
        request("/api/attention/status"),
        request("/api/seller-retry/status"),
      ]);
      if (busy) return;
      connected = results.every((result) => result.status === "fulfilled");
      if (results[0].status === "fulfilled") {
        attention = results[0].value;
        renderAttention();
      }
      if (results[1].status === "fulfilled") {
        recovery = results[1].value;
        renderRecovery();
      }
      if (!connected)
        setText(
          "attentionNotice",
          "Cannot refresh agent status. Reconnecting…",
        );
      renderControls();
    } finally {
      polling = false;
    }
  }
  try {
    const initial = JSON.parse(element("dashboardInitialState").textContent);
    attention = initial.attention;
    recovery = initial.seller_retry;
    renderAttention();
    renderRecovery();
  } catch (_error) {
    setText("attentionNotice", "Waiting for stored agent status…");
  }
  renderControls();
  refresh();
  window.setInterval(refresh, 5000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refresh();
  });
})();
