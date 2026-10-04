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

  chrome.storage.local.get(['guardianlensServer', 'guardianlensToken', 'guardianlensLastListingId'], values => {
    server.value = normalizeServer(values.guardianlensServer) || 'http://127.0.0.1:8765';
    token.value = values.guardianlensToken || '';
    listingId.value = values.guardianlensLastListingId || '';
  });

  document.getElementById('save').addEventListener('click', async () => {
    const normalized = normalizeServer(server.value);
    if (!normalized) {
      statusBox.textContent = 'Server must be an exact localhost URL with port 1–65535, for example http://127.0.0.1:8765';
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
      await chrome.runtime.sendMessage({type: 'guardianlens.pollReplay'}).catch(() => null);
      statusBox.textContent = 'Settings saved locally in Chrome. CSV queue check requested.';
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
    await chrome.storage.local.set({guardianlensServer: normalized, guardianlensToken: cleanToken});
    const response = await chrome.runtime.sendMessage({type: 'guardianlens.pollReplay'});
    statusBox.textContent = response?.ok
      ? 'CSV queue check requested. Follow progress on the GuardianLens dashboard.'
      : 'Could not request a CSV queue check.';
  });
}
