const INDIVIDUAL_LISTING_ERROR =
  "Capture rejected: This does not appear to be an individual listing page.";
const TAB_CHANGED_ERROR =
  "The active tab changed during capture. Return to the listing and try again.";

function detectPlatform(url) {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:") return null;
    const host = parsed.hostname.toLowerCase();
    if (host === "carousell.com.my" || host === "www.carousell.com.my")
      return "carousell";
    if (host === "mudah.my" || host === "www.mudah.my") return "mudah";
  } catch (_) {}
  return null;
}

function normalizeLocalServer(value) {
  const match = /^http:\/\/(127\.0\.0\.1|localhost):(\d{1,5})\/?$/i.exec(
    String(value || "").trim(),
  );
  if (!match) return null;
  const port = Number(match[2]);
  if (!Number.isInteger(port) || port < 1 || port > 65535) return null;
  return `http://${match[1].toLowerCase()}:${port}`;
}

async function hasQueuedCapturePermission() {
  if (typeof chrome === "undefined" || !chrome.permissions?.contains)
    return false;
  return chrome.permissions.contains({ origins: ["<all_urls>"] });
}

function tabSnapshotMatches(candidate, original, expectedUrl) {
  if (
    !candidate ||
    candidate.id !== original.id ||
    candidate.windowId !== original.windowId
  )
    return false;
  try {
    return new URL(candidate.url).href === new URL(expectedUrl).href;
  } catch (_) {
    return false;
  }
}

function safeApiErrorDetail(detail, fallback) {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail.slice(0, 5).map((item) => {
      const field = Array.isArray(item?.loc)
        ? item.loc.filter((part) => part !== "body").join(".")
        : "";
      const message =
        typeof item?.msg === "string" ? item.msg : "invalid value";
      return field ? `${field}: ${message}` : message;
    });
    if (messages.length) return messages.join("; ");
  }
  return fallback;
}

function listingIdFromUrl(platform, url) {
  try {
    const parsed = new URL(url);
    if (
      parsed.protocol !== "https:" ||
      parsed.username ||
      parsed.password ||
      parsed.port
    )
      return null;
    const path = decodeURIComponent(parsed.pathname);
    const match =
      platform === "carousell"
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
    const lastSlash = parsed.pathname.lastIndexOf("/");
    const directory =
      lastSlash >= 0
        ? parsed.pathname.slice(0, lastSlash + 1)
        : parsed.pathname;
    return `${parsed.hostname.toLowerCase()}${directory}`;
  } catch (_) {
    return null;
  }
}

function collectPageData() {
  const normalizeText = (value) => (value || "").replace(/\s+/g, " ").trim();
  const genericHeadings = new Set([
    "browse",
    "carousell",
    "categories",
    "category",
    "home",
    "login",
    "mudah",
    "profile",
    "search",
    "search results",
    "sign in",
    "sign up",
  ]);
  const h1Text =
    [...document.querySelectorAll("h1")]
      .map((node) => normalizeText(node.innerText || node.textContent))
      .find(
        (text) =>
          text.length >= 3 &&
          text.length <= 500 &&
          !genericHeadings.has(text.toLowerCase()),
      ) || null;

  let hasProductStructuredData = false;
  let hasOfferSignal = false;
  let structuredNodeCount = 0;
  const structuredImageUrls = [];

  const addStructuredImage = (value, depth = 0) => {
    if (depth > 4) return;
    if (Array.isArray(value)) {
      value.slice(0, 20).forEach((item) => addStructuredImage(item, depth + 1));
      return;
    }
    if (value && typeof value === "object") {
      addStructuredImage(value.url || value.contentUrl, depth + 1);
      return;
    }
    if (typeof value !== "string") return;
    try {
      const parsed = new URL(value, location.href);
      if (parsed.protocol === "https:") structuredImageUrls.push(parsed.href);
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
    if (typeof value !== "object") return;
    const rawTypes = Array.isArray(value["@type"])
      ? value["@type"]
      : [value["@type"]];
    const types = rawTypes
      .filter(Boolean)
      .map((type) => String(type).toLowerCase().split(/[\/#]/).pop());
    const isProduct = types.includes("product");
    if (isProduct) {
      hasProductStructuredData = true;
      addStructuredImage(value.image);
      if (value.offers) hasOfferSignal = true;
    }
    if (types.includes("offer") || types.includes("aggregateoffer"))
      hasOfferSignal = true;
    for (const item of Object.values(value)) {
      if (structuredNodeCount >= 2000) break;
      inspectStructuredData(item, depth + 1);
    }
  };

  document
    .querySelectorAll('script[type="application/ld+json"]')
    .forEach((script) => {
      try {
        inspectStructuredData(JSON.parse(script.textContent));
      } catch (_) {}
    });

  const semanticPriceNodes = [
    ...document.querySelectorAll(
      'meta[itemprop="price"][content], meta[property="product:price:amount"][content], [itemprop="price"], [data-testid*="price" i], [class*="price" i]',
    ),
  ];
  const hasSemanticPriceSignal = semanticPriceNodes.some((node) => {
    const value = normalizeText(
      node.content ||
        node.getAttribute("content") ||
        node.innerText ||
        node.textContent,
    );
    if (!value) return false;
    if (
      node.matches(
        'meta[itemprop="price"], meta[property="product:price:amount"], [itemprop="price"]',
      )
    ) {
      return /\d/.test(value);
    }
    return /(?:RM|MYR)\s*\d[\d,.]*/i.test(value);
  });
  const priceScope =
    document.querySelector('main, [role="main"]') || document.body;
  const hasVisiblePriceSignal = [
    ...priceScope.querySelectorAll("span, strong, p, div"),
  ]
    .slice(0, 2000)
    .some(
      (node) =>
        node.childElementCount === 0 &&
        /^(?:RM|MYR)\s*\d[\d,.]*$/i.test(
          normalizeText(node.innerText || node.textContent),
        ),
    );
  const hasPriceSignal = hasSemanticPriceSignal || hasVisiblePriceSignal;

  const scopedImages = [
    ...document.querySelectorAll(
      'main img, [role="main"] img, [data-testid*="gallery" i] img, [class*="gallery" i] img',
    ),
  ];
  const imagePool = scopedImages.length ? scopedImages : [...document.images];

  // Duplicated from the top-level imageDirectoryKey: chrome.scripting's func-injection serializes
  // only this function's own body (closures over background.js's other top-level helpers are
  // dropped), so everything collectPageData needs must be defined inside it. Keep both in sync.
  const imageDirectoryKey = (url) => {
    try {
      const parsed = new URL(url);
      const lastSlash = parsed.pathname.lastIndexOf("/");
      const directory =
        lastSlash >= 0
          ? parsed.pathname.slice(0, lastSlash + 1)
          : parsed.pathname;
      return `${parsed.hostname.toLowerCase()}${directory}`;
    } catch (_) {
      return null;
    }
  };

  const imageCandidates = imagePool
    .filter((img) => {
      const style = getComputedStyle(img);
      if (style.display === "none" || style.visibility === "hidden")
        return false;
      const rect = img.getBoundingClientRect();
      return rect.bottom >= 0 && rect.top <= innerHeight * 3;
    })
    .map((img) => {
      const raw = img.currentSrc || img.src;
      const rect = img.getBoundingClientRect();
      let url = null;
      if (raw && !/\.svg(?:[?#]|$)/i.test(raw)) {
        try {
          const resolved = new URL(raw, location.href);
          if (resolved.protocol === "https:") url = resolved.href;
        } catch (_) {}
      }
      return { url, width: rect.width, height: rect.height };
    })
    .filter((item) => item.url);

  const largeImages = imageCandidates.filter(
    (item) => item.width >= 160 && item.height >= 160,
  );
  const galleryDirectories = new Set(
    largeImages.map((item) => imageDirectoryKey(item.url)).filter(Boolean),
  );
  // A product gallery commonly renders every photo except the one currently selected as a small
  // thumbnail well under 160px. Only trust those small images when they share a CDN directory with
  // an already-qualified full-size photo, so stray icons or unrelated thumbnails elsewhere on the
  // page (e.g. a "related listings" strip) are not swept in by lowering the size floor everywhere.
  const thumbnailImages = galleryDirectories.size
    ? imageCandidates.filter(
        (item) =>
          item.width >= 48 &&
          item.height >= 48 &&
          !(item.width >= 160 && item.height >= 160) &&
          galleryDirectories.has(imageDirectoryKey(item.url)),
      )
    : [];
  const domImageUrls = [...largeImages, ...thumbnailImages].map(
    (item) => item.url,
  );

  const imageUrls = [
    ...new Set([...structuredImageUrls, ...domImageUrls]),
  ].slice(0, 12);
  // Server-side max is 250,000 chars; truncated here too so an oversized page never gets
  // rejected wholesale by the API after the user already sat through a capture.
  const visibleText =
    normalizeText(document.body ? document.body.innerText : "").slice(
      0,
      240000,
    ) || null;
  const pageSample = `${document.title || ""}\n${visibleText || ""}`
    .slice(0, 120000)
    .toLowerCase();
  const path = location.pathname.toLowerCase();
  let pageState = "candidate";
  if (
    document.querySelector(
      'iframe[src*="recaptcha" i], [class*="captcha" i], [id*="captcha" i]',
    ) ||
    /captcha|verify (?:that )?you are human|complete the security check/.test(
      pageSample,
    )
  ) {
    pageState = "captcha";
  } else if (
    /access denied|request blocked|checking your browser|just a moment/.test(
      pageSample,
    ) ||
    document.querySelector(
      "[data-ray], #cf-challenge-running, .cf-browser-verification",
    )
  ) {
    pageState = "access_denied";
  } else if (
    /\/(?:login|signin|sign-in)(?:\/|$)/.test(path) ||
    /(?:log|sign) in (?:is )?required|(?:log|sign) in to (?:continue|view)/.test(
      pageSample,
    )
  ) {
    pageState = "login_required";
  } else if (
    /listing (?:is |has been )?(?:unavailable|deleted|removed|expired)|item (?:is |has been )?(?:unavailable|deleted|removed|sold)|page (?:does not exist|not found)/.test(
      pageSample,
    )
  ) {
    pageState = "listing_unavailable";
  }

  const pageHost = location.hostname.toLowerCase();
  const marketplaceHosts =
    pageHost === "mudah.my" || pageHost === "www.mudah.my"
      ? new Set(["mudah.my", "www.mudah.my"])
      : new Set(["carousell.com.my", "www.carousell.com.my"]);
  const sellerCandidates = [...document.querySelectorAll("a[href]")]
    .map((anchor) => {
      try {
        const url = new URL(anchor.href, location.href);
        if (
          url.protocol !== "https:" ||
          !marketplaceHosts.has(url.hostname.toLowerCase()) ||
          url.href === location.href
        )
          return null;
        const candidatePath = url.pathname.toLowerCase();
        if (
          /^\/p\//.test(candidatePath) ||
          /-[1-9]\d*\.htm\/?$/.test(candidatePath)
        )
          return null;
        const text = normalizeText(
          anchor.innerText ||
            anchor.textContent ||
            anchor.getAttribute("aria-label"),
        ).toLowerCase();
        let score = 0;
        if (/^\/u\//.test(candidatePath)) score += 8;
        if (/\/(?:seller|profile|user|shop|dealer)(?:\/|$)/.test(candidatePath))
          score += 6;
        if (/seller|profile|visit shop|view shop|view account/.test(text))
          score += 4;
        return score ? { url: url.href, score } : null;
      } catch (_) {
        return null;
      }
    })
    .filter(Boolean)
    .sort((a, b) => b.score - a.score);
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
    visible_text: visibleText,
    page_state: pageState,
    seller_url: sellerCandidates[0]?.url || null,
  };
}

// Seller/profile pages have no listing-shaped evidence to check, so this stays a separate,
// deliberately minimal extraction: just the ground-truth URL and the page's visible text.
function collectVisibleText() {
  const normalizeText = (value) => (value || "").replace(/\s+/g, " ").trim();
  const visibleText =
    normalizeText(document.body ? document.body.innerText : "").slice(
      0,
      240000,
    ) || null;
  const sample = `${document.title || ""}\n${visibleText || ""}`
    .slice(0, 120000)
    .toLowerCase();
  const path = location.pathname.toLowerCase();
  let pageState = "candidate";
  if (
    document.querySelector(
      'iframe[src*="recaptcha" i], [class*="captcha" i], [id*="captcha" i]',
    ) ||
    /captcha|verify (?:that )?you are human|complete the security check/.test(
      sample,
    )
  )
    pageState = "captcha";
  else if (
    /access denied|request blocked|checking your browser|just a moment/.test(
      sample,
    ) ||
    document.querySelector(
      "[data-ray], #cf-challenge-running, .cf-browser-verification",
    )
  )
    pageState = "access_denied";
  else if (
    /\/(?:login|signin|sign-in)(?:\/|$)/.test(path) ||
    /(?:log|sign) in to (?:continue|view)/.test(sample)
  )
    pageState = "login_required";
  return {
    source_url: location.href,
    visible_text: visibleText,
    page_state: pageState,
  };
}

function capturePageState(page, expectedPlatform) {
  if (!page) return "invalid_listing_page";
  if (
    [
      "captcha",
      "access_denied",
      "login_required",
      "listing_unavailable",
    ].includes(page.page_state)
  ) {
    return page.page_state;
  }
  if (detectPlatform(page.source_url) !== expectedPlatform)
    return "invalid_listing_page";
  const evidence = page.listing_evidence;
  const ready =
    listingIdFromUrl(expectedPlatform, page.source_url) &&
    evidence?.h1_text &&
    (evidence.has_price_signal ||
      evidence.has_product_structured_data ||
      evidence.has_offer_signal) &&
    page.image_urls?.length;
  return ready ? "ready" : "candidate";
}

function classifyCaptureFailure(error) {
  const explicit = error?.captureStatus;
  if (explicit) return { status: explicit, error_type: explicit };
  const message = String(error?.message || error || "Capture failed");
  if (/timed? out|timeout/i.test(message))
    return { status: "capture_timeout", error_type: "capture_timeout" };
  if (/captcha|human verification/i.test(message))
    return { status: "captcha", error_type: "captcha" };
  if (/access denied|request blocked|cloudflare/i.test(message))
    return { status: "access_denied", error_type: "access_denied" };
  if (/log.?in|required.*account|sign.?in/i.test(message))
    return { status: "login_required", error_type: "login_required" };
  if (/unavailable|deleted|removed|not found/i.test(message))
    return { status: "listing_unavailable", error_type: "listing_unavailable" };
  if (/individual listing|listing page/i.test(message))
    return {
      status: "invalid_listing_page",
      error_type: "invalid_listing_page",
    };
  return { status: "capture_failed", error_type: "capture_failed" };
}

class ReplayCaptureError extends Error {
  constructor(status, message) {
    super(message);
    this.captureStatus = status;
  }
}

async function requestJson(serverOrigin, path, token, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("X-GuardianLens-Token", token);
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch(new URL(path, serverOrigin).href, {
    ...options,
    headers,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(
      safeApiErrorDetail(
        body.detail,
        `Local server returned HTTP ${response.status}`,
      ),
    );
  }
  return body;
}

const wait = (milliseconds) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

async function readListingPage(tabId) {
  const [injected] = await chrome.scripting.executeScript({
    target: { tabId },
    func: collectPageData,
  });
  return injected?.result || null;
}

async function waitForTabComplete(tabId, timeoutSeconds) {
  const current = await chrome.tabs.get(tabId);
  if (current.status === "complete") return current;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      reject(
        new ReplayCaptureError(
          "capture_timeout",
          "Timed out waiting for the listing page to load.",
        ),
      );
    }, timeoutSeconds * 1000);
    const listener = (updatedTabId, changeInfo, tab) => {
      if (updatedTabId !== tabId || changeInfo.status !== "complete") return;
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(listener);
      resolve(tab);
    };
    chrome.tabs.onUpdated.addListener(listener);
  });
}

async function waitForCapturablePage(tabId, expectedPlatform, timeoutSeconds) {
  const deadline = Date.now() + timeoutSeconds * 1000;
  let lastPage = null;
  while (Date.now() < deadline) {
    try {
      lastPage = await readListingPage(tabId);
      const state = capturePageState(lastPage, expectedPlatform);
      if (state === "ready") return lastPage;
      if (state !== "candidate") {
        const labels = {
          captcha:
            "The marketplace presented a CAPTCHA or human-verification page.",
          access_denied:
            "The marketplace denied access or presented a bot-check page.",
          login_required: "The listing requires a signed-in browser session.",
          listing_unavailable:
            "The listing is deleted, sold, expired, or unavailable.",
          invalid_listing_page:
            "The queued URL did not resolve to an individual listing page.",
        };
        throw new ReplayCaptureError(
          state,
          labels[state] || "Listing page is not capturable.",
        );
      }
      if (!listingIdFromUrl(expectedPlatform, lastPage?.source_url)) {
        throw new ReplayCaptureError(
          "invalid_listing_page",
          "The queued URL did not resolve to an individual listing page.",
        );
      }
    } catch (error) {
      if (error?.captureStatus) throw error;
    }
    await wait(1000);
  }
  throw new ReplayCaptureError(
    "capture_timeout",
    lastPage
      ? "Listing loaded, but required title, price, and product-image evidence did not become available."
      : "Timed out before GuardianLens could inspect the listing page.",
  );
}

async function waitForSellerUrl(tabId, expectedPlatform, timeoutSeconds) {
  const deadline = Date.now() + timeoutSeconds * 1000;
  let lastPage = null;
  while (Date.now() < deadline) {
    try {
      lastPage = await readListingPage(tabId);
      const state = lastPage?.page_state || "invalid_listing_page";
      if (
        [
          "captcha",
          "access_denied",
          "login_required",
          "listing_unavailable",
        ].includes(state)
      ) {
        throw new ReplayCaptureError(
          state,
          `Seller link could not be derived because the listing page reported ${state.replace("_", " ")}.`,
        );
      }
      if (
        detectPlatform(lastPage?.source_url) !== expectedPlatform ||
        !listingIdFromUrl(expectedPlatform, lastPage?.source_url)
      ) {
        throw new ReplayCaptureError(
          "invalid_listing_page",
          "The saved listing URL did not resolve to its original Mudah listing page.",
        );
      }
      if (
        lastPage.seller_url &&
        detectPlatform(lastPage.seller_url) === expectedPlatform
      ) {
        return lastPage.seller_url;
      }
    } catch (error) {
      if (error?.captureStatus) throw error;
    }
    await wait(1000);
  }
  throw new ReplayCaptureError(
    "seller_url_not_found",
    lastPage
      ? "The listing loaded, but no seller/profile link appeared before the retry timed out."
      : "The listing could not be inspected to derive its seller/profile link.",
  );
}

async function waitForSellerPage(tabId, expectedPlatform, timeoutSeconds) {
  const deadline = Date.now() + timeoutSeconds * 1000;
  let lastPage = null;
  while (Date.now() < deadline) {
    try {
      const [injected] = await chrome.scripting.executeScript({
        target: { tabId },
        func: collectVisibleText,
      });
      lastPage = injected?.result || null;
      if (
        !lastPage ||
        detectPlatform(lastPage.source_url) !== expectedPlatform
      ) {
        throw new ReplayCaptureError(
          "invalid_seller_page",
          "Seller page redirected outside the listing marketplace.",
        );
      }
      if (lastPage.page_state !== "candidate") {
        throw new ReplayCaptureError(
          lastPage.page_state,
          `Seller page could not be captured: ${lastPage.page_state.replace("_", " ")}.`,
        );
      }
      if (lastPage.visible_text && lastPage.visible_text.length >= 20)
        return lastPage;
    } catch (error) {
      if (error?.captureStatus) throw error;
    }
    await wait(1000);
  }
  throw new ReplayCaptureError(
    "capture_timeout",
    lastPage
      ? "Seller page loaded without enough visible behavioural evidence."
      : "Timed out before GuardianLens could inspect the seller page.",
  );
}

async function captureListingTab(tab, serverOrigin, token, options = {}) {
  const platform = options.platform || detectPlatform(tab.url);
  if (!platform)
    throw new ReplayCaptureError(
      "invalid_listing_page",
      INDIVIDUAL_LISTING_ERROR,
    );
  const page = options.page || (await readListingPage(tab.id));
  const state = capturePageState(page, platform);
  if (state !== "ready") {
    throw new ReplayCaptureError(
      state === "candidate" ? "invalid_listing_page" : state,
      INDIVIDUAL_LISTING_ERROR,
    );
  }
  const marketplaceListingId = listingIdFromUrl(platform, page.source_url);
  await chrome.tabs.update(tab.id, { active: true });
  if (options.requireActive) {
    const [active] = await chrome.tabs.query({
      active: true,
      windowId: tab.windowId,
    });
    if (!tabSnapshotMatches(active, tab, page.source_url))
      throw new Error(TAB_CHANGED_ERROR);
  } else {
    const before = await chrome.tabs.get(tab.id);
    if (!tabSnapshotMatches(before, tab, page.source_url))
      throw new Error(TAB_CHANGED_ERROR);
  }
  const screenshot = await chrome.tabs.captureVisibleTab(tab.windowId, {
    format: "jpeg",
    quality: 88,
  });
  const after = await chrome.tabs.get(tab.id);
  if (!tabSnapshotMatches(after, tab, page.source_url))
    throw new Error(TAB_CHANGED_ERROR);
  const {
    page_state: _pageState,
    seller_url: _sellerUrl,
    ...capturePage
  } = page;
  const payload = {
    platform,
    ...capturePage,
    marketplace_listing_id: marketplaceListingId,
    screenshot_data_url: screenshot,
    capture_source: options.batchItemId ? "csv_batch" : "extension",
    batch_item_id: options.batchItemId || null,
  };
  const body = await requestJson(serverOrigin, "/api/capture", token, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return { ...body, page, platform };
}

async function captureSellerTab(
  tab,
  sellerUrl,
  listingId,
  platform,
  serverOrigin,
  token,
  timeoutSeconds,
) {
  await chrome.tabs.update(tab.id, { url: sellerUrl, active: true });
  const loaded = await waitForTabComplete(tab.id, timeoutSeconds);
  if (detectPlatform(loaded.url) !== platform) {
    throw new ReplayCaptureError(
      "invalid_seller_page",
      "Seller page redirected outside the listing marketplace.",
    );
  }
  // A completed navigation can still precede client-rendered profile text or a delayed
  // anti-bot interstitial. Poll the page state briefly instead of taking the first DOM frame.
  const page = await waitForSellerPage(tab.id, platform, timeoutSeconds);
  await chrome.tabs.update(tab.id, { active: true });
  const before = await chrome.tabs.get(tab.id);
  if (!tabSnapshotMatches(before, tab, page.source_url))
    throw new Error(TAB_CHANGED_ERROR);
  const screenshot = await chrome.tabs.captureVisibleTab(tab.windowId, {
    format: "jpeg",
    quality: 88,
  });
  const after = await chrome.tabs.get(tab.id);
  if (!tabSnapshotMatches(after, tab, page.source_url))
    throw new Error(TAB_CHANGED_ERROR);
  return requestJson(
    serverOrigin,
    `/api/capture/${encodeURIComponent(listingId)}/seller`,
    token,
    {
      method: "POST",
      body: JSON.stringify({
        seller_url: page.source_url,
        visible_text: page.visible_text,
        screenshot_data_url: screenshot,
      }),
    },
  );
}

async function updateReplayItem(serverOrigin, token, itemId, update) {
  return requestJson(
    serverOrigin,
    `/api/replay/items/${encodeURIComponent(itemId)}`,
    token,
    {
      method: "POST",
      body: JSON.stringify(update),
    },
  );
}

async function updateSellerRetryItem(
  serverOrigin,
  token,
  itemId,
  leaseToken,
  update,
) {
  return requestJson(
    serverOrigin,
    `/api/seller-retry/items/${encodeURIComponent(itemId)}`,
    token,
    {
      method: "POST",
      body: JSON.stringify({ lease_token: leaseToken, ...update }),
    },
  );
}

async function runSellerRetryItem(item, serverOrigin, token) {
  let retryWindow = null;
  let evidenceRequestStarted = false;
  try {
    retryWindow = await chrome.windows.create({
      url: "about:blank",
      focused: false,
      type: "normal",
      width: 1280,
      height: 900,
    });
    const tab =
      retryWindow.tabs?.[0] ||
      (await chrome.tabs.query({ windowId: retryWindow.id }))[0];
    if (!tab?.id) throw new Error("Chrome did not create a seller retry tab.");

    let sellerUrl = item.seller_url || null;
    if (!sellerUrl) {
      await chrome.tabs.update(tab.id, { url: item.source_url, active: true });
      const loaded = await waitForTabComplete(
        tab.id,
        item.page_timeout_seconds,
      );
      if (detectPlatform(loaded.url) !== item.platform) {
        throw new ReplayCaptureError(
          "invalid_listing_page",
          "Saved listing URL redirected outside its supported marketplace.",
        );
      }
      sellerUrl = await waitForSellerUrl(
        tab.id,
        item.platform,
        item.page_timeout_seconds,
      );
      // Persist the derived URL before the profile navigation. A blocked visit or browser
      // restart can then retry the seller directly without loading the listing again.
      await updateSellerRetryItem(
        serverOrigin,
        token,
        item.retry_item_id,
        item.lease_token,
        {
          status: "opening_seller",
          status_message:
            "Seller URL recovered; waiting before the paced profile visit",
          seller_url: sellerUrl,
        },
      );
    }

    const navigationDelay = Math.max(
      0,
      Number(item.navigation_delay_seconds) || 0,
    );
    if (navigationDelay) await wait(navigationDelay * 1000);
    evidenceRequestStarted = true;
    const sellerCapture = await captureSellerTab(
      tab,
      sellerUrl,
      item.listing_id,
      item.platform,
      serverOrigin,
      token,
      item.page_timeout_seconds,
    );
    await updateSellerRetryItem(
      serverOrigin,
      token,
      item.retry_item_id,
      item.lease_token,
      {
        status: "captured",
        status_message:
          "Seller behaviour evidence captured; listing queued for later AI extraction",
        seller_url: sellerCapture.seller_url,
      },
    );
  } catch (error) {
    const classification = classifyCaptureFailure(error);
    try {
      await updateSellerRetryItem(
        serverOrigin,
        token,
        item.retry_item_id,
        item.lease_token,
        {
          status: "failed",
          status_message: evidenceRequestStarted
            ? "Paced seller profile capture did not complete"
            : "Seller profile URL could not be prepared",
          error_type: classification.error_type,
          error_message: String(error?.message || error).slice(0, 2000),
        },
      );
    } catch (_) {
      // If seller evidence committed before the acknowledgement was lost, backend lease
      // recovery reconciles the staging/screenshot checkpoint instead of recapturing it.
    }
  } finally {
    if (retryWindow?.id) {
      try {
        await chrome.windows.remove(retryWindow.id);
      } catch (_) {}
    }
  }
}

async function runReplayItem(item, serverOrigin, token) {
  let replayWindow = null;
  try {
    replayWindow = await chrome.windows.create({
      url: item.source_url,
      focused: false,
      type: "normal",
      width: 1280,
      height: 900,
    });
    const tab =
      replayWindow.tabs?.[0] ||
      (await chrome.tabs.query({ windowId: replayWindow.id }))[0];
    if (!tab?.id) throw new Error("Chrome did not create a replay tab.");
    await waitForTabComplete(tab.id, item.page_timeout_seconds);
    const loadedTab = await chrome.tabs.get(tab.id);
    const platform = detectPlatform(loadedTab.url);
    if (platform !== item.platform) {
      throw new ReplayCaptureError(
        "invalid_listing_page",
        "Queued URL redirected outside its supported marketplace.",
      );
    }
    const page = await waitForCapturablePage(
      tab.id,
      platform,
      item.page_timeout_seconds,
    );
    await updateReplayItem(serverOrigin, token, item.batch_item_id, {
      status: "capturing",
      status_message: "Capturing listing text, screenshot, and product images",
    });
    const result = await captureListingTab(loadedTab, serverOrigin, token, {
      platform,
      page,
      batchItemId: item.batch_item_id,
    });
    if (result.duplicate) {
      await updateReplayItem(serverOrigin, token, item.batch_item_id, {
        status: "duplicate",
        status_message: "Existing GuardianLens listing detected during capture",
        listing_id: result.listing_id,
        error_type: "already_captured",
        error_message: `Existing listing status: ${result.status}`,
      });
      return;
    }

    let sellerError = null;
    if (result.page.seller_url) {
      try {
        await captureSellerTab(
          loadedTab,
          result.page.seller_url,
          result.listing_id,
          platform,
          serverOrigin,
          token,
          item.page_timeout_seconds,
        );
      } catch (error) {
        sellerError = `Seller behaviour capture failed: ${error.message}`;
      }
    } else {
      sellerError =
        "No seller/profile link was available on the listing page; existing validation will flag missing behavioural fields.";
    }
    await updateReplayItem(serverOrigin, token, item.batch_item_id, {
      status: "captured",
      status_message: sellerError
        ? "Listing captured; seller evidence needs attention"
        : "Full listing and seller evidence captured",
      listing_id: result.listing_id,
      error_type: sellerError ? "seller_capture_incomplete" : null,
      error_message: sellerError,
    });
  } catch (error) {
    const classification = classifyCaptureFailure(error);
    try {
      await updateReplayItem(serverOrigin, token, item.batch_item_id, {
        status: classification.status,
        status_message: "Browser capture did not complete",
        error_type: classification.error_type,
        error_message: String(error?.message || error).slice(0, 2000),
      });
    } catch (_) {
      // The persistent opening/capturing checkpoint is recovered by the backend after a restart.
    }
  } finally {
    if (replayWindow?.id) {
      try {
        await chrome.windows.remove(replayWindow.id);
      } catch (_) {}
    }
  }
}

let browserCaptureActive = false;

async function withBrowserCaptureLock(callback) {
  // Set the shared lock before the first await. Both durable browser queues use the same Chrome
  // session and captureVisibleTab permission, so even simultaneous alarms cannot open two items.
  if (browserCaptureActive) return { busy: true };
  browserCaptureActive = true;
  try {
    return await callback();
  } finally {
    browserCaptureActive = false;
  }
}

async function queuedCaptureConnection() {
  // Chrome grants activeTab only after a direct user gesture. Queue-created tabs require the
  // separately granted optional permission. Never claim durable work before that permission.
  if (!(await hasQueuedCapturePermission()))
    return { permission_required: true };
  const values = await chrome.storage.local.get([
    "guardianlensServer",
    "guardianlensToken",
  ]);
  const serverOrigin = normalizeLocalServer(values.guardianlensServer);
  const token = String(values.guardianlensToken || "").trim();
  if (!serverOrigin || !token) return { unconfigured: true };
  return { serverOrigin, token };
}

async function pollReplayQueueUnlocked(serverOrigin, token) {
  const response = await requestJson(serverOrigin, "/api/replay/claim", token, {
    method: "POST",
  });
  if (!response.item) return false;
  await runReplayItem(response.item, serverOrigin, token);
  return true;
}

async function pollSellerRetryQueueUnlocked(serverOrigin, token) {
  const response = await requestJson(
    serverOrigin,
    "/api/seller-retry/claim",
    token,
    { method: "POST" },
  );
  if (!response.item) return false;
  await runSellerRetryItem(response.item, serverOrigin, token);
  return true;
}

async function pollReplayQueue() {
  return withBrowserCaptureLock(async () => {
    try {
      const connection = await queuedCaptureConnection();
      if (connection.permission_required || connection.unconfigured)
        return connection;
      const processedItem = await pollReplayQueueUnlocked(
        connection.serverOrigin,
        connection.token,
      );
      return { permission_required: false, processed_item: processedItem };
    } catch (_) {
      return { permission_required: false, processed_item: false };
    }
  });
}

async function pollSellerRetryQueue() {
  return withBrowserCaptureLock(async () => {
    try {
      const connection = await queuedCaptureConnection();
      if (connection.permission_required || connection.unconfigured)
        return connection;
      const processedItem = await pollSellerRetryQueueUnlocked(
        connection.serverOrigin,
        connection.token,
      );
      return { permission_required: false, processed_item: processedItem };
    } catch (_) {
      return { permission_required: false, processed_item: false };
    }
  });
}

async function pollCaptureQueues() {
  return withBrowserCaptureLock(async () => {
    try {
      const connection = await queuedCaptureConnection();
      if (connection.permission_required || connection.unconfigured)
        return connection;
      // A backend transaction also enforces mutual exclusion. Checking the paced seller queue
      // first prevents a normal replay claim from delaying a seller visit whose not-before time
      // has already arrived.
      const sellerProcessed = await pollSellerRetryQueueUnlocked(
        connection.serverOrigin,
        connection.token,
      );
      if (sellerProcessed) {
        return {
          permission_required: false,
          processed_item: true,
          queue: "seller_retry",
        };
      }
      const replayProcessed = await pollReplayQueueUnlocked(
        connection.serverOrigin,
        connection.token,
      );
      return {
        permission_required: false,
        processed_item: replayProcessed,
        queue: replayProcessed ? "replay" : null,
      };
    } catch (_) {
      // Dashboard polling exposes backend state; the next 30-second alarm retries connectivity.
      return { permission_required: false, processed_item: false };
    }
  });
}

if (typeof module !== "undefined") {
  module.exports = {
    capturePageState,
    classifyCaptureFailure,
    collectVisibleText,
    detectPlatform,
    imageDirectoryKey,
    listingIdFromUrl,
    hasQueuedCapturePermission,
    normalizeLocalServer,
    pollCaptureQueues,
    pollReplayQueue,
    pollSellerRetryQueue,
    runSellerRetryItem,
    safeApiErrorDetail,
    tabSnapshotMatches,
    waitForSellerUrl,
  };
}

if (typeof chrome !== "undefined") {
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg?.type !== "guardianlens.pollReplay") return;
    pollCaptureQueues()
      .then((result) => sendResponse({ ok: true, ...(result || {}) }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  });

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg?.type !== "guardianlens.capture") return;
    (async () => {
      const serverOrigin = normalizeLocalServer(msg.server);
      if (!serverOrigin)
        throw new Error("Invalid local GuardianLens server URL.");
      const [tab] = await chrome.tabs.query({
        active: true,
        currentWindow: true,
      });
      if (!tab?.id || !tab.url) throw new Error("No active browser tab found.");
      const result = await captureListingTab(tab, serverOrigin, msg.token, {
        requireActive: true,
      });
      sendResponse({
        ok: true,
        ...result,
        page: undefined,
        platform: undefined,
      });
    })().catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  });

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg?.type !== "guardianlens.captureSeller") return;
    (async () => {
      const serverOrigin = normalizeLocalServer(msg.server);
      if (!serverOrigin)
        throw new Error("Invalid local GuardianLens server URL.");
      const listingId = String(msg.listingId || "").trim();
      if (!listingId)
        throw new Error("Enter the listing ID from a previous capture first.");
      const [tab] = await chrome.tabs.query({
        active: true,
        currentWindow: true,
      });
      if (!tab?.id || !tab.url) throw new Error("No active browser tab found.");
      const platform = detectPlatform(tab.url);
      if (!platform)
        throw new Error(
          "Open the seller or profile page on Carousell Malaysia or Mudah, then click Capture Seller Behaviour.",
        );
      const result = await captureSellerTab(
        tab,
        tab.url,
        listingId,
        platform,
        serverOrigin,
        msg.token,
        45,
      );
      sendResponse({ ok: true, ...result });
    })().catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  });

  const replayAlarm = "guardianlens-replay-poll";
  chrome.runtime.onInstalled.addListener(() => {
    chrome.alarms.create(replayAlarm, { periodInMinutes: 0.5 });
    pollCaptureQueues();
  });
  chrome.runtime.onStartup.addListener(() => {
    chrome.alarms.create(replayAlarm, { periodInMinutes: 0.5 });
    pollCaptureQueues();
  });
  chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === replayAlarm) pollCaptureQueues();
  });
  chrome.alarms.create(replayAlarm, { periodInMinutes: 0.5 });
  setTimeout(pollCaptureQueues, 250);
}
