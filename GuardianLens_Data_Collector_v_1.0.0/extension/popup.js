function normalizeServer(value) {
  const match = /^http:\/\/(127\.0\.0\.1|localhost):(\d{1,5})\/?$/i.exec(String(value || '').trim());
  if (!match) return null;
  const port = Number(match[2]);
  if (!Number.isInteger(port) || port < 1 || port > 65535) return null;
  return `http://${match[1].toLowerCase()}:${port}`;
}

if (typeof module !== 'undefined') {
  module.exports = {normalizeServer};
}

if (typeof document !== 'undefined' && typeof chrome !== 'undefined') {
  const server = document.getElementById('server');
  const token = document.getElementById('token');
  const listingId = document.getElementById('listingId');
  const statusBox = document.getElementById('status');
  const processNextButton = document.getElementById('processNext');
  const processDuration = document.getElementById('processDuration');
  const processLimit = document.getElementById('processLimit');
  const queuedPermissionPanel = document.getElementById('queuedPermission');
  const queuedPermissionState = document.getElementById('queuedPermissionState');
  const enableQueuedCaptureButton = document.getElementById('enableQueuedCapture');
  const disableQueuedCaptureButton = document.getElementById('disableQueuedCapture');
  let latestMonitorBatchId = null;
  let queuedCapturePermissionGranted = false;

  const labelState = value => String(value || 'waiting')
    .replaceAll('_', ' ')
    .replace(/^./, character => character.toUpperCase());

  function selectedProcessingLimits() {
    return {
      duration_minutes: processDuration.value ? Number(processDuration.value) : null,
      item_limit: processLimit.value ? Number(processLimit.value) : null,
    };
  }

  function durationLabel(minutes) {
    if (minutes === null) return 'unlimited';
    if (minutes === 60) return '1 hour';
    if (minutes === 120) return '2 hours';
    return `${minutes} minutes`;
  }

  function updateProcessButtonLabel() {
    const limits = selectedProcessingLimits();
    const records = limits.item_limit === null ? 'all pending' : `next ${limits.item_limit}`;
    processNextButton.textContent = `Process ${records} · ${durationLabel(limits.duration_minutes)}`;
  }

  async function localRequest(path, options = {}) {
    const origin = normalizeServer(server.value);
    if (!origin) throw new Error('Save a valid local server URL first.');
    const cleanToken = token.value.trim();
    const headers = new Headers(options.headers || {});
    if (cleanToken) headers.set('X-GuardianLens-Token', cleanToken);
    const response = await fetch(new URL(path, origin).href, {...options, headers});
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(typeof body.detail === 'string' ? body.detail : `Local server returned HTTP ${response.status}`);
    }
    return body;
  }

  async function refreshQueuedCapturePermission() {
    queuedCapturePermissionGranted = await chrome.permissions.contains({origins: ['<all_urls>']});
    queuedPermissionPanel.dataset.state = queuedCapturePermissionGranted ? 'granted' : 'required';
    enableQueuedCaptureButton.hidden = queuedCapturePermissionGranted;
    disableQueuedCaptureButton.hidden = !queuedCapturePermissionGranted;
    queuedPermissionState.textContent = queuedCapturePermissionGranted
      ? 'Enabled. GuardianLens may now capture only its validated queued marketplace tabs.'
      : 'Required for automatic CSV/pasted-URL screenshots. Manual capture does not need it.';
    return queuedCapturePermissionGranted;
  }

  function setStage(prefix, state, percent, detail) {
    const stage = document.getElementById(`${prefix}Stage`);
    const fill = document.getElementById(`${prefix}StageFill`);
    const progress = fill?.parentElement;
    if (stage) stage.dataset.state = state;
    if (fill) fill.style.width = `${percent}%`;
    if (progress) progress.setAttribute('aria-valuenow', String(percent));
    const stateElement = document.getElementById(`${prefix}StageState`);
    const detailElement = document.getElementById(`${prefix}StageDetail`);
    if (stateElement) stateElement.textContent = labelState(state);
    if (detailElement) detailElement.textContent = detail;
  }

  function renderMonitor(snapshot, batchStatus) {
    const batch = snapshot?.batch;
    const capture = snapshot?.progress || {};
    const processing = snapshot?.processing || {};
    const batchLabel = document.getElementById('monitorBatch');
    latestMonitorBatchId = batch?.batch_id || null;
    if (batchLabel) {
      batchLabel.textContent = batch ? `${batch.name} · ${batch.status}` : 'No batch';
      batchLabel.title = batchLabel.textContent;
    }

    const capturePercent = capture.total
      ? Math.min(100, Math.round((100 * (capture.resolved || 0)) / capture.total))
      : 0;
    const captureNeedsPermission = batch
      && ['running', 'paused', 'stopping'].includes(batch.status)
      && !queuedCapturePermissionGranted;
    const captureState = !batch
      ? 'locked'
      : captureNeedsPermission
        ? 'attention'
      : ['running', 'paused', 'stopping'].includes(batch.status)
        ? batch.status
        : batch.status === 'draft'
          ? 'ready'
          : 'complete';
    const current = snapshot?.current;
    setStage(
      'capture',
      captureState,
      capturePercent,
      captureNeedsPermission
        ? 'Queue is waiting locally. Enable queued capture permission before checking the queue.'
        : current
        ? `Row ${current.row_number}: ${current.status_message || current.status}`
        : batch
          ? `${capture.resolved || 0}/${capture.total || 0} checkpointed · ${capture.failed || 0} failed · ${capture.remaining || 0} remaining`
          : 'Save settings, then import a queue on the dashboard.',
    );

    // Processing is one shared queue across every batch (see batch.py READY_TO_PROCESS_SQL),
    // so its running/idle state comes from the unified batch processor, not this batch alone.
    const run = batchStatus?.latest_run;
    const control = batchStatus?.control?.command || 'idle';
    const runActive = ['running', 'paused', 'stopping'].includes(control);
    const processingState = !batch || ['draft', 'running', 'paused', 'stopping'].includes(batch.status)
      ? 'locked'
      : runActive
        ? control
        : (processing.queued || 0) > 0
          ? 'ready'
          : (processing.failed || 0) > 0
            ? 'attention'
            : (processing.total || 0) > 0
              ? 'complete'
              : 'empty';
    const processingPercent = runActive && run?.item_limit
      ? Math.min(100, Math.round((100 * (run.attempted || 0)) / run.item_limit))
      : processing.total
        ? Math.min(100, Math.round((100 * (processing.resolved || 0)) / processing.total))
        : 0;
    setStage(
      'processing',
      processingState,
      processingPercent,
      runActive
        ? `Run ${run.run_id.slice(0, 8)} · ${run.attempted || 0}/${run.item_limit || 'all'} attempted (shared queue)`
        : `${processing.queued || 0} queued · ${processing.resolved || 0} resolved · ${processing.failed || 0} failed`,
    );
    const pendingCount = Number(batchStatus?.pending_count || 0);
    processNextButton.disabled = runActive || pendingCount === 0;
    processDuration.disabled = runActive;
    processLimit.disabled = runActive;
    updateProcessButtonLabel();
  }

  async function refreshMonitor() {
    try {
      await refreshQueuedCapturePermission();
      const [batchStatus, replaySnapshot] = await Promise.all([
        localRequest('/api/batch/status'),
        localRequest('/api/replay/status'),
      ]);
      renderMonitor(replaySnapshot, batchStatus);
    } catch (error) {
      latestMonitorBatchId = null;
      processNextButton.disabled = true;
      setStage('capture', 'attention', 0, `Monitor unavailable: ${error.message}`);
      setStage('processing', 'locked', 0, 'Waiting for the local GuardianLens server.');
    }
  }

  chrome.storage.local.get([
    'guardianlensServer',
    'guardianlensToken',
    'guardianlensLastListingId',
    'guardianlensProcessingDuration',
    'guardianlensProcessingLimit',
  ], values => {
    server.value = normalizeServer(values.guardianlensServer) || 'http://127.0.0.1:8770';
    token.value = values.guardianlensToken || '';
    listingId.value = values.guardianlensLastListingId || '';
    if (values.guardianlensProcessingDuration) {
      processDuration.value = values.guardianlensProcessingDuration;
    }
    if (values.guardianlensProcessingLimit) {
      processLimit.value = values.guardianlensProcessingLimit;
    }
    updateProcessButtonLabel();
    refreshMonitor();
  });

  processDuration.addEventListener('input', async () => {
    updateProcessButtonLabel();
    await chrome.storage.local.set({guardianlensProcessingDuration: processDuration.value});
  });
  processLimit.addEventListener('input', async () => {
    updateProcessButtonLabel();
    await chrome.storage.local.set({guardianlensProcessingLimit: processLimit.value});
  });

  enableQueuedCaptureButton.addEventListener('click', async () => {
    enableQueuedCaptureButton.disabled = true;
    statusBox.textContent = 'Waiting for Chrome permission…';
    try {
      const granted = await chrome.permissions.request({origins: ['<all_urls>']});
      await refreshQueuedCapturePermission();
      if (!granted) {
        statusBox.textContent = 'Queued capture permission was not granted. No queue URL was claimed.';
        return;
      }
      const response = await chrome.runtime.sendMessage({type: 'guardianlens.pollReplay'});
      statusBox.textContent = response?.ok
        ? 'Queued capture enabled. Queue check requested.'
        : `Queued capture enabled, but the queue check failed${response?.error ? `: ${response.error}` : '.'}`;
      await refreshMonitor();
    } catch (error) {
      statusBox.textContent = `ERROR: Could not enable queued capture: ${error.message}`;
    } finally {
      enableQueuedCaptureButton.disabled = false;
    }
  });

  disableQueuedCaptureButton.addEventListener('click', async () => {
    disableQueuedCaptureButton.disabled = true;
    try {
      const removed = await chrome.permissions.remove({origins: ['<all_urls>']});
      await refreshQueuedCapturePermission();
      statusBox.textContent = removed
        ? 'Queued capture permission revoked. Automatic capture is now idle; manual capture still works.'
        : 'Chrome did not remove the queued capture permission.';
      await refreshMonitor();
    } catch (error) {
      statusBox.textContent = `ERROR: Could not revoke queued capture permission: ${error.message}`;
    } finally {
      disableQueuedCaptureButton.disabled = false;
    }
  });

  document.getElementById('save').addEventListener('click', async () => {
    const normalized = normalizeServer(server.value);
    if (!normalized) {
      statusBox.textContent = 'Server must be an exact localhost URL with port 1–65535, for example http://127.0.0.1:8770';
      return;
    }
    const cleanToken = token.value.trim();
    server.value = normalized;
    token.value = cleanToken;
    try {
      await chrome.storage.local.set({
        guardianlensServer: normalized,
        guardianlensToken: cleanToken,
      });
      const hasPermission = await refreshQueuedCapturePermission();
      const response = hasPermission
        ? await chrome.runtime.sendMessage({type: 'guardianlens.pollReplay'}).catch(() => null)
        : null;
      statusBox.textContent = !hasPermission
        ? 'Settings saved. Enable queued capture before running CSV/pasted-URL screenshots.'
        : response?.ok
          ? 'Settings saved locally in Chrome. CSV queue check requested.'
          : 'Settings saved, but the background queue check could not be requested.';
      await refreshMonitor();
    } catch (error) {
      statusBox.textContent = `ERROR: Could not save settings: ${error.message}`;
    }
  });

  const captureButton = document.getElementById('capture');
  captureButton.addEventListener('click', async () => {
    if (captureButton.disabled) return;
    captureButton.disabled = true;
    statusBox.textContent = 'Capturing current tab…';
    try {
      const normalized = normalizeServer(server.value);
      if (!normalized) {
        statusBox.textContent = 'Invalid local server URL.';
        return;
      }
      const cleanToken = token.value.trim();
      if (!cleanToken) {
        statusBox.textContent = 'Paste the local collector token first.';
        return;
      }
      server.value = normalized;
      token.value = cleanToken;
      await chrome.storage.local.set({
        guardianlensServer: normalized,
        guardianlensToken: cleanToken,
      });
      const response = await chrome.runtime.sendMessage({
        type: 'guardianlens.capture',
        server: normalized,
        token: cleanToken,
      });
      if (!response?.ok) throw new Error(response?.error || 'Capture failed');
      if (response.listing_id) {
        listingId.value = response.listing_id;
        await chrome.storage.local.set({guardianlensLastListingId: response.listing_id});
      }
      statusBox.textContent = response.duplicate
        ? `Duplicate blocked. Existing record: ${response.listing_id}`
        : `Captured. Listing ID: ${response.listing_id}\nStatus: ${response.status}\nNow open the seller/profile page and capture their behaviour data.`;
    } catch (error) {
      statusBox.textContent = `ERROR: ${error.message}`;
    } finally {
      captureButton.disabled = false;
    }
  });

  const captureSellerButton = document.getElementById('captureSeller');
  captureSellerButton.addEventListener('click', async () => {
    if (captureSellerButton.disabled) return;
    captureSellerButton.disabled = true;
    statusBox.textContent = 'Capturing seller behaviour data…';
    try {
      const normalized = normalizeServer(server.value);
      if (!normalized) {
        statusBox.textContent = 'Invalid local server URL.';
        return;
      }
      const cleanToken = token.value.trim();
      if (!cleanToken) {
        statusBox.textContent = 'Paste the local collector token first.';
        return;
      }
      const cleanListingId = listingId.value.trim();
      if (!cleanListingId) {
        statusBox.textContent = 'Capture a listing first, or paste its listing ID above.';
        return;
      }
      server.value = normalized;
      token.value = cleanToken;
      listingId.value = cleanListingId;
      await chrome.storage.local.set({
        guardianlensServer: normalized,
        guardianlensToken: cleanToken,
        guardianlensLastListingId: cleanListingId,
      });
      const response = await chrome.runtime.sendMessage({
        type: 'guardianlens.captureSeller',
        server: normalized,
        token: cleanToken,
        listingId: cleanListingId,
      });
      if (!response?.ok) throw new Error(response?.error || 'Seller capture failed');
      statusBox.textContent = `Seller behaviour captured for listing ${cleanListingId}.\nSeller URL: ${response.seller_url}`;
    } catch (error) {
      statusBox.textContent = `ERROR: ${error.message}`;
    } finally {
      captureSellerButton.disabled = false;
    }
  });

  document.getElementById('syncReplay').addEventListener('click', async () => {
    const normalized = normalizeServer(server.value);
    const cleanToken = token.value.trim();
    if (!normalized || !cleanToken) {
      statusBox.textContent = 'Save a valid local server URL and collector token first.';
      return;
    }
    try {
      await chrome.storage.local.set({guardianlensServer: normalized, guardianlensToken: cleanToken});
      if (!(await refreshQueuedCapturePermission())) {
        statusBox.textContent = 'Enable queued capture permission first. No queue URL was claimed.';
        enableQueuedCaptureButton.focus();
        return;
      }
      const response = await chrome.runtime.sendMessage({type: 'guardianlens.pollReplay'});
      statusBox.textContent = response?.ok && !response.permission_required
        ? 'CSV capture queue check requested.'
        : 'Queued capture permission is required before checking the queue.';
      await refreshMonitor();
    } catch (error) {
      statusBox.textContent = `ERROR: Could not check the queue: ${error.message}`;
    }
  });

  processNextButton.addEventListener('click', async () => {
    if (processNextButton.disabled) return;
    const limits = selectedProcessingLimits();
    processNextButton.disabled = true;
    processDuration.disabled = true;
    processLimit.disabled = true;
    statusBox.textContent = `Starting pictures and preprocessing: ${processNextButton.textContent.replace(/^Process /, '')}…`;
    try {
      await localRequest('/api/batch/start', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(limits),
      });
      statusBox.textContent = 'Preprocessing run started. Failed records will remain stopped until you explicitly retry them after this run.';
      await refreshMonitor();
    } catch (error) {
      statusBox.textContent = `ERROR: ${error.message}`;
      await refreshMonitor();
    }
  });

  document.getElementById('openDashboard').addEventListener('click', async () => {
    const origin = normalizeServer(server.value);
    if (!origin) {
      statusBox.textContent = 'Save a valid local server URL first.';
      return;
    }
    try {
      await chrome.tabs.create({url: `${origin}/`});
    } catch (error) {
      statusBox.textContent = `ERROR: Could not open the dashboard: ${error.message}`;
    }
  });

  setInterval(refreshMonitor, 3000);
}
