const INDIVIDUAL_LISTING_ERROR = 'Capture rejected: This does not appear to be an individual listing page.';
const TAB_CHANGED_ERROR = 'The active tab changed during capture. Return to the listing and try again.';

function detectPlatform(url) {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:') return null;
    const host = parsed.hostname.toLowerCase();
    if (host === 'carousell.com.my' || host === 'www.carousell.com.my') return 'carousell';
    if (host === 'mudah.my' || host === 'www.mudah.my') return 'mudah';
  } catch (_) {}
  return null;
}

function normalizeLocalServer(value) {
  const match = /^http:\/\/(127\.0\.0\.1|localhost):(\d{1,5})\/?$/i.exec(String(value || '').trim());
  if (!match) return null;
  const port = Number(match[2]);
  if (!Number.isInteger(port) || port < 1 || port > 65535) return null;
  return `http://${match[1].toLowerCase()}:${port}`;
}

function tabSnapshotMatches(candidate, original, expectedUrl) {
  if (!candidate || candidate.id !== original.id || candidate.windowId !== original.windowId) return false;
  try {
    return new URL(candidate.url).href === new URL(expectedUrl).href;
  } catch (_) {
    return false;
  }
}

function safeApiErrorDetail(detail, fallback) {
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail.slice(0, 5).map(item => {
      const field = Array.isArray(item?.loc) ? item.loc.filter(part => part !== 'body').join('.') : '';
      const message = typeof item?.msg === 'string' ? item.msg : 'invalid value';
      return field ? `${field}: ${message}` : message;
    });
    if (messages.length) return messages.join('; ');
  }
  return fallback;
}

function listingIdFromUrl(platform, url) {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:' || parsed.username || parsed.password || parsed.port) return null;
    const path = decodeURIComponent(parsed.pathname);
    const match = platform === 'carousell'
      ? path.match(/^\/p\/[^/]+-([1-9]\d*)\/?$/i)
      : path.match(/^\/[^/]+-([1-9]\d*)\.htm$/i);
    return match ? match[1] : null;
  } catch (_) {
    return null;
  }
}

// Groups an image URL by "host + directory" so a small gallery thumbnail can be matched back to
// a full-size photo served from the same CDN folder, without depending on any site's CSS classes.
function imageDirectoryKey(url) {
  try {
    const parsed = new URL(url);
    const lastSlash = parsed.pathname.lastIndexOf('/');
    const directory = lastSlash >= 0 ? parsed.pathname.slice(0, lastSlash + 1) : parsed.pathname;
    return `${parsed.hostname.toLowerCase()}${directory}`;
  } catch (_) {
    return null;
  }
}

function collectPageData() {
  const normalizeText = value => (value || '').replace(/\s+/g, ' ').trim();
  const genericHeadings = new Set([
    'browse', 'carousell', 'categories', 'category', 'home', 'login', 'mudah',
    'profile', 'search', 'search results', 'sign in', 'sign up',
  ]);
  const h1Text = [...document.querySelectorAll('h1')]
    .map(node => normalizeText(node.innerText || node.textContent))
    .find(text => text.length >= 3 && text.length <= 500 && !genericHeadings.has(text.toLowerCase())) || null;

  let hasProductStructuredData = false;
  let hasOfferSignal = false;
  let structuredNodeCount = 0;
  const structuredImageUrls = [];

  const addStructuredImage = (value, depth = 0) => {
    if (depth > 4) return;
    if (Array.isArray(value)) {
      value.slice(0, 20).forEach(item => addStructuredImage(item, depth + 1));
      return;
    }
    if (value && typeof value === 'object') {
      addStructuredImage(value.url || value.contentUrl, depth + 1);
      return;
    }
    if (typeof value !== 'string') return;
    try {
      const parsed = new URL(value, location.href);
      if (parsed.protocol === 'https:') structuredImageUrls.push(parsed.href);
    } catch (_) {}
  };

  const inspectStructuredData = (value, depth = 0) => {
    if (structuredNodeCount >= 2000 || depth > 8 || value == null) return;
    structuredNodeCount += 1;
    if (Array.isArray(value)) {
      for (const item of value) {
        if (structuredNodeCount >= 2000) break;
        inspectStructuredData(item, depth + 1);
      }
      return;
    }
    if (typeof value !== 'object') return;
    const rawTypes = Array.isArray(value['@type']) ? value['@type'] : [value['@type']];
    const types = rawTypes.filter(Boolean).map(type => String(type).toLowerCase().split(/[\/#]/).pop());
    const isProduct = types.includes('product');
    if (isProduct) {
      hasProductStructuredData = true;
      addStructuredImage(value.image);
      if (value.offers) hasOfferSignal = true;
    }
    if (types.includes('offer') || types.includes('aggregateoffer')) hasOfferSignal = true;
    for (const item of Object.values(value)) {
      if (structuredNodeCount >= 2000) break;
      inspectStructuredData(item, depth + 1);
    }
  };

  document.querySelectorAll('script[type="application/ld+json"]').forEach(script => {
    try {
      inspectStructuredData(JSON.parse(script.textContent));
    } catch (_) {}
  });

  const semanticPriceNodes = [...document.querySelectorAll(
    'meta[itemprop="price"][content], meta[property="product:price:amount"][content], [itemprop="price"], [data-testid*="price" i], [class*="price" i]'
  )];
  const hasSemanticPriceSignal = semanticPriceNodes.some(node => {
    const value = normalizeText(node.content || node.getAttribute('content') || node.innerText || node.textContent);
    if (!value) return false;
    if (node.matches('meta[itemprop="price"], meta[property="product:price:amount"], [itemprop="price"]')) {
      return /\d/.test(value);
    }
    return /(?:RM|MYR)\s*\d[\d,.]*/i.test(value);
  });
  const priceScope = document.querySelector('main, [role="main"]') || document.body;
  const hasVisiblePriceSignal = [...priceScope.querySelectorAll('span, strong, p, div')]
    .slice(0, 2000)
    .some(node => node.childElementCount === 0
      && /^(?:RM|MYR)\s*\d[\d,.]*$/i.test(normalizeText(node.innerText || node.textContent)));
  const hasPriceSignal = hasSemanticPriceSignal || hasVisiblePriceSignal;

  const scopedImages = [...document.querySelectorAll(
    'main img, [role="main"] img, [data-testid*="gallery" i] img, [class*="gallery" i] img'
  )];
  const imagePool = scopedImages.length ? scopedImages : [...document.images];

  // Duplicated from the top-level imageDirectoryKey: chrome.scripting's func-injection serializes
  // only this function's own body (closures over background.js's other top-level helpers are
  // dropped), so everything collectPageData needs must be defined inside it. Keep both in sync.
  const imageDirectoryKey = url => {
    try {
      const parsed = new URL(url);
      const lastSlash = parsed.pathname.lastIndexOf('/');
      const directory = lastSlash >= 0 ? parsed.pathname.slice(0, lastSlash + 1) : parsed.pathname;
      return `${parsed.hostname.toLowerCase()}${directory}`;
    } catch (_) {
      return null;
    }
  };

  const imageCandidates = imagePool.filter(img => {
    const style = getComputedStyle(img);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    const rect = img.getBoundingClientRect();
    return rect.bottom >= 0 && rect.top <= innerHeight * 3;
  }).map(img => {
    const raw = img.currentSrc || img.src;
    const rect = img.getBoundingClientRect();
    let url = null;
    if (raw && !/\.svg(?:[?#]|$)/i.test(raw)) {
      try {
        const resolved = new URL(raw, location.href);
        if (resolved.protocol === 'https:') url = resolved.href;
      } catch (_) {}
    }
    return {url, width: rect.width, height: rect.height};
  }).filter(item => item.url);

  const largeImages = imageCandidates.filter(item => item.width >= 160 && item.height >= 160);
  const galleryDirectories = new Set(largeImages.map(item => imageDirectoryKey(item.url)).filter(Boolean));
  // A product gallery commonly renders every photo except the one currently selected as a small
  // thumbnail well under 160px. Only trust those small images when they share a CDN directory with
  // an already-qualified full-size photo, so stray icons or unrelated thumbnails elsewhere on the
  // page (e.g. a "related listings" strip) are not swept in by lowering the size floor everywhere.
  const thumbnailImages = galleryDirectories.size ? imageCandidates.filter(item =>
    item.width >= 48 && item.height >= 48
    && !(item.width >= 160 && item.height >= 160)
    && galleryDirectories.has(imageDirectoryKey(item.url))
  ) : [];
  const domImageUrls = [...largeImages, ...thumbnailImages].map(item => item.url);

  const imageUrls = [...new Set([...structuredImageUrls, ...domImageUrls])].slice(0, 12);
  return {
    source_url: location.href,
    page_title: document.title,
    image_urls: imageUrls,
    listing_evidence: {
      h1_text: h1Text,
      has_price_signal: hasPriceSignal,
      has_product_structured_data: hasProductStructuredData,
      has_offer_signal: hasOfferSignal,
    },
  };
}

if (typeof module !== 'undefined') {
  module.exports = {
    detectPlatform,
    imageDirectoryKey,
    listingIdFromUrl,
    normalizeLocalServer,
    safeApiErrorDetail,
    tabSnapshotMatches,
  };
}

if (typeof chrome !== 'undefined') chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg?.type !== 'guardianlens.capture') return;
  (async () => {
    const serverOrigin = normalizeLocalServer(msg.server);
    if (!serverOrigin) throw new Error('Invalid local GuardianLens server URL.');
    const tabs = await chrome.tabs.query({active: true, currentWindow: true});
    const tab = tabs[0];
    if (!tab?.id || !tab.url) throw new Error('No active browser tab found.');
    const platform = detectPlatform(tab.url);
    if (!platform) throw new Error(INDIVIDUAL_LISTING_ERROR);
    const [injected] = await chrome.scripting.executeScript({target: {tabId: tab.id}, func: collectPageData});
    const page = injected?.result;
    if (!page || detectPlatform(page.source_url) !== platform) throw new Error(TAB_CHANGED_ERROR);
    const marketplaceListingId = page ? listingIdFromUrl(platform, page.source_url) : null;
    const evidence = page?.listing_evidence;
    if (
      !marketplaceListingId
      || !evidence?.h1_text
      || !(evidence.has_price_signal || evidence.has_product_structured_data || evidence.has_offer_signal)
      || !page.image_urls?.length
    ) {
      throw new Error(INDIVIDUAL_LISTING_ERROR);
    }
    const [beforeCapture] = await chrome.tabs.query({active: true, windowId: tab.windowId});
    if (!tabSnapshotMatches(beforeCapture, tab, page.source_url)) throw new Error(TAB_CHANGED_ERROR);
    const screenshot = await chrome.tabs.captureVisibleTab(tab.windowId, {format: 'jpeg', quality: 88});
    const [afterCapture] = await chrome.tabs.query({active: true, windowId: tab.windowId});
    if (!tabSnapshotMatches(afterCapture, tab, page.source_url)) throw new Error(TAB_CHANGED_ERROR);
    const payload = {
      platform,
      ...page,
      marketplace_listing_id: marketplaceListingId,
      screenshot_data_url: screenshot,
    };
    const response = await fetch(new URL('/api/capture', serverOrigin).href, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-GuardianLens-Token': msg.token},
      body: JSON.stringify(payload),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(
        safeApiErrorDetail(body.detail, `Local server returned HTTP ${response.status}`),
      );
    }
    sendResponse({ok: true, ...body});
  })().catch(error => sendResponse({ok: false, error: error.message}));
  return true;
});
