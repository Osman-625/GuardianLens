// The listing adapter: reads ONE marketplace listing from the page's DOM.
//
// Every field is read by trying several strategies in order and taking the first that yields a
// value:
//   title        heading (h1) > platform selectors > structured data name > Mudah ad data > og:title
//   description  Mudah ad data > structured data > platform selectors > og:description > meta
//                description (the two meta tags are NOT used on Mudah, where they are a generated
//                sentence rather than the seller's words)
//   price        Mudah ad data (final when present) > structured data price (never a low/high
//                range) > price meta tags > platform selectors > price elements > visible "RM ..."
//                text, which counts only when the page shows ONE distinct amount (other ads on the
//                page carry their own prices)
//   category     Mudah ad data > structured data > breadcrumb data > breadcrumb links > platform
//                selectors
//   photos       Mudah ad data photos (full size first), or structured data photos, then large
//                gallery images (images.ts), then og:image
// "Mudah ad data" is the ad record in the page's embedded __NEXT_DATA__ script (see readMudahAd);
// Mudah's visible page does not show the ad's own price as text, so the generic strategies cannot
// read it. Nothing here guesses. A field no strategy can read is reported as "not_found", and the
// buyer fills it in during the Review step. Pages that are blocked (captcha, login wall, removed
// listing) are reported through `pageState` and not read further; only titles, headings, banners,
// and nearly empty pages decide that, never the seller's own description.
//
// Code here runs inside the injected capture script on the buyer's click. It must stay free of
// network calls and of anything that changes the page.
import { matchTrainedCategory, type Platform } from "@guardianlens/shared";
import { classifyListingUrl, classifySellerUrl } from "./classify";
import { selectGalleryImages, type ImageCandidate } from "./images";
import { PLATFORM_SELECTORS, type PlatformSelectors } from "./selectors";
import {
  ADAPTER_VERSION,
  type BlockedState,
  type CapturedField,
  type CapturedListing,
  type PageState,
} from "./types";
import { normalizeText, parsePriceRm, parsePriceValue, textOf } from "./values";

// A parsed JSON object whose values have not been checked yet.
type JsonObject = Record<string, unknown>;

// Headings that are page chrome rather than a listing title.
const GENERIC_HEADINGS = new Set([
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

/** Wraps a value as a captured field, or as a not-found field when it is null. */
function field<T>(value: T | null): CapturedField<T> {
  return value === null ? { status: "not_found", value: null } : { status: "captured", value };
}

/** Returns the first non-null result of the strategies, trying them in order. */
function firstOf<T>(...strategies: Array<() => T | null>): T | null {
  for (const strategy of strategies) {
    const value = strategy();
    if (value !== null) return value;
  }
  return null;
}

/** A non-empty, whitespace-normalised string, or null for anything else. */
function clean(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const text = normalizeText(value);
  return text === "" ? null : text;
}

// ---- Structured data (JSON-LD) -------------------------------------------------------------

/** The `@type` values of a JSON-LD node, lower-cased and stripped of any namespace prefix. */
function typesOf(node: JsonObject): string[] {
  const raw = node["@type"];
  const list = Array.isArray(raw) ? raw : [raw];
  return list
    .filter((type): type is string => typeof type === "string")
    .map((type) => type.toLowerCase().split(/[/#]/).pop() ?? "");
}

/**
 * Visits every object in a parsed JSON-LD value. `budget` caps how many nodes are visited and
 * `depth` how deep, so a huge or hostile page cannot stall the capture.
 */
function walk(
  value: unknown,
  visit: (node: JsonObject) => void,
  budget: { left: number },
  depth: number,
): void {
  if (budget.left <= 0 || depth > 8 || value === null || typeof value !== "object") return;
  budget.left -= 1;
  if (Array.isArray(value)) {
    for (const item of value) walk(item, visit, budget, depth + 1);
    return;
  }
  const node = value as JsonObject;
  visit(node);
  for (const child of Object.values(node)) walk(child, visit, budget, depth + 1);
}

/** The Product and BreadcrumbList nodes found in the page's JSON-LD scripts. */
function readStructuredData(doc: Document): {
  products: JsonObject[];
  breadcrumbs: JsonObject[];
} {
  const products: JsonObject[] = [];
  const breadcrumbs: JsonObject[] = [];
  const budget = { left: 2000 };
  // Files each visited node under products or breadcrumbs according to its @type.
  const visit = (node: JsonObject): void => {
    const types = typesOf(node);
    if (types.includes("product")) products.push(node);
    if (types.includes("breadcrumblist")) breadcrumbs.push(node);
  };
  for (const script of Array.from(doc.querySelectorAll('script[type="application/ld+json"]'))) {
    try {
      walk(JSON.parse(script.textContent ?? ""), visit, budget, 0);
    } catch {
      // Malformed JSON-LD is ignored: the other strategies still run.
    }
  }
  return { products, breadcrumbs };
}

/** The photo URLs a Product node names (absolute, resolved against the page URL). */
function productPhotos(product: JsonObject | undefined, baseUrl: string): string[] {
  const urls: string[] = [];
  // Collects URLs from an image value that may be a string, an object with a url, or a list of
  // either, looking at most four levels deep and at most 20 list entries.
  const add = (value: unknown, depth: number): void => {
    if (depth > 4) return;
    if (Array.isArray(value)) {
      value.slice(0, 20).forEach((item) => add(item, depth + 1));
    } else if (value && typeof value === "object") {
      const node = value as JsonObject;
      add(node.url ?? node.contentUrl, depth + 1);
    } else if (typeof value === "string") {
      try {
        urls.push(new URL(value, baseUrl).href);
      } catch {
        // A value that is not a URL is skipped.
      }
    }
  };
  add(product?.image, 0);
  return urls;
}

/**
 * The price in a Product's offers, or null. Only a stated `price` counts: an AggregateOffer's
 * lowPrice and highPrice are a range, and taking one end would show an invented price as Captured.
 */
function productPrice(product: JsonObject | undefined): number | null {
  const offers = product?.offers;
  const list = Array.isArray(offers) ? offers : offers ? [offers] : [];
  for (const offer of list) {
    if (!offer || typeof offer !== "object") continue;
    const node = offer as JsonObject;
    const value = parsePriceValue(node.price as string | number | undefined);
    if (value !== null) return value;
  }
  return null;
}

/**
 * The category from a breadcrumb trail in structured data: the last entry whose name is not the
 * listing title (some sites end the trail with the listing itself).
 */
function breadcrumbCategory(breadcrumbs: JsonObject[], title: string | null): string | null {
  for (const crumb of breadcrumbs) {
    const items = Array.isArray(crumb.itemListElement)
      ? (crumb.itemListElement as JsonObject[])
      : [];
    const names = [...items]
      .sort((a, b) => Number(a.position ?? 0) - Number(b.position ?? 0))
      .map((item) => {
        const nested =
          item.item && typeof item.item === "object" ? (item.item as JsonObject).name : null;
        return clean(item.name) ?? clean(nested);
      })
      .filter(
        (name): name is string => name !== null && name.toLowerCase() !== title?.toLowerCase(),
      );
    const last = names.pop();
    if (last) return last;
  }
  return null;
}

// ---- Mudah embedded ad data (__NEXT_DATA__) ---------------------------------------------------

/** What a Mudah page's own ad record says. Each field is null when the record does not give it. */
interface MudahAd {
  title: string | null;
  description: string | null;
  priceText: string | null;
  category: string | null;
  imageUrls: string[];
}

/**
 * Turns the ad body (HTML such as "FOR SALE <br>Phone<br>64GB &amp; box") into plain text with one
 * line per line break. DOMParser builds an inert document, so nothing in the body can run.
 */
function adBodyText(html: unknown): string | null {
  if (typeof html !== "string") return null;
  const parsed = new DOMParser().parseFromString(
    html.replace(/<br\s*\/?>/gi, "\n").replace(/<\/p>/gi, "\n"),
    "text/html",
  );
  const lines = (parsed.body.textContent ?? "")
    .split("\n")
    .map((line) => normalizeText(line))
    .filter((line) => line !== "");
  return lines.length > 0 ? lines.join("\n") : null;
}

/** The absolute http(s) URLs in a list of strings; anything else in the list is skipped. */
function urlList(value: unknown, baseUrl: string): string[] {
  if (!Array.isArray(value)) return [];
  const urls: string[] = [];
  for (const item of value.slice(0, 20)) {
    if (typeof item !== "string") continue;
    try {
      const url = new URL(item, baseUrl);
      if (url.protocol === "https:" || url.protocol === "http:") urls.push(url.href);
    } catch {
      // A value that is not a URL is skipped.
    }
  }
  return urls;
}

/**
 * Finds this listing's ad record in the page's embedded __NEXT_DATA__ script.
 *
 * Why: a live Mudah page keeps the ad's real title, body, price, category, and photos in this
 * JSON. The visible page does not show the ad's own price as text, its JSON-LD has no Product, and
 * its meta description is a generated sentence, so the generic strategies cannot read these.
 * The record is an object with type "ad" and an id equal to the listing id in the URL; related
 * ads carry records of the same shape with other ids, and are never used. The record appears in
 * camelCase and snake_case copies, so both spellings are read.
 *
 * @returns The ad's fields, or null when the script is missing, is not JSON, or holds no record
 *          for this listing id.
 */
function readMudahAd(doc: Document, listingId: string, baseUrl: string): MudahAd | null {
  const raw = doc.getElementById("__NEXT_DATA__")?.textContent;
  if (!raw) return null;
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  // A deeper and larger budget than the JSON-LD walk: this document is one big page-state tree.
  let record: JsonObject | null = null;
  const budget = { left: 60000 };
  // Keeps the attributes of the first node that is this listing's own ad record.
  const visit = (node: JsonObject): void => {
    if (
      record === null &&
      node.type === "ad" &&
      String(node.id) === listingId &&
      node.attributes &&
      typeof node.attributes === "object"
    ) {
      record = node.attributes as JsonObject;
    }
  };
  // Walks the whole page-state tree, stopping at the first match or when the node budget or the
  // depth limit runs out.
  const visitAll = (value: unknown, depth: number): void => {
    if (
      record !== null ||
      budget.left <= 0 ||
      depth > 20 ||
      value === null ||
      typeof value !== "object"
    )
      return;
    budget.left -= 1;
    if (Array.isArray(value)) {
      for (const item of value) visitAll(item, depth + 1);
      return;
    }
    visit(value as JsonObject);
    for (const child of Object.values(value as JsonObject)) visitAll(child, depth + 1);
  };
  visitAll(data, 0);
  const ad = record as JsonObject | null;
  if (ad === null) return null;

  const params = Array.isArray(ad.categoryParams ?? ad.category_params)
    ? ((ad.categoryParams ?? ad.category_params) as JsonObject[])
    : [];
  const subcategory = clean(
    params.find((param) => clean(param?.label)?.toLowerCase() === "subcategory")?.value,
  );
  const categoryName = clean(adBodyText(ad.categoryName ?? ad.category_name));
  const images = urlList(ad.imageHd ?? ad.image_hd, baseUrl);
  return {
    title: clean(ad.subject),
    description: adBodyText(ad.body),
    priceText: typeof ad.price === "string" ? ad.price : null,
    // A sub-category that names a trained category ("Phones") is more specific than the
    // top-level name ("Mobile Phones & Gadgets"); otherwise the platform's own wording is kept.
    category:
      subcategory !== null && matchTrainedCategory(subcategory) !== null
        ? subcategory
        : (categoryName ?? subcategory),
    imageUrls: images.length > 0 ? images : urlList(ad.image, baseUrl),
  };
}

// ---- DOM and meta strategies ----------------------------------------------------------------

/** The content of the first meta tag matching `selector`, or null. */
function metaContent(doc: Document, selector: string): string | null {
  return clean(doc.querySelector<HTMLMetaElement>(selector)?.content);
}

/** The text of the first element matched by any of `selectors`, tried in order. */
function firstText(doc: Document, selectors: string[]): string | null {
  for (const selector of selectors) {
    const text = clean(textOf(doc.querySelector(selector)));
    if (text) return text;
  }
  return null;
}

/** The first h1 that reads like a listing title rather than page chrome. */
function headingTitle(doc: Document): string | null {
  for (const heading of Array.from(doc.querySelectorAll("h1"))) {
    const text = textOf(heading);
    if (text.length >= 3 && text.length <= 500 && !GENERIC_HEADINGS.has(text.toLowerCase()))
      return text;
  }
  return null;
}

// A site name is separated from the title by "|", a hyphen, an en dash (character code 0x2013), or an
// em dash (0x2014). The dashes are built from their character codes so this source stays plain ASCII.
// The hyphen goes last inside the character class so it is read as a literal hyphen, not a range.
const SITE_NAME_SEPARATORS = `|${String.fromCharCode(0x2013, 0x2014)}-`;
// Matches a trailing site name, such as " - Carousell Malaysia" or " | Mudah.my", at the end of a title.
const SITE_NAME_SUFFIX = new RegExp(
  `\\s*[${SITE_NAME_SEPARATORS}]\\s*(?:Carousell|Mudah)[^|]*$`,
  "i",
);

/** Removes a trailing " - Carousell Malaysia" / " | Mudah.my" style site name from a title. */
function withoutSiteName(text: string | null): string | null {
  if (text === null) return null;
  return clean(text.replace(SITE_NAME_SUFFIX, ""));
}

/** The last breadcrumb link that is not the listing title. */
function domBreadcrumbCategory(doc: Document, title: string | null): string | null {
  const links = Array.from(
    doc.querySelectorAll('nav[aria-label*="readcrumb" i] a, [class*="readcrumb" i] a'),
  )
    .map((link) => clean(textOf(link)))
    .filter((name): name is string => name !== null && name.toLowerCase() !== title?.toLowerCase());
  return links.pop() ?? null;
}

/** A price from elements matched by the platform's own price selectors. */
function priceFromSelectors(doc: Document, selectors: string[]): number | null {
  for (const selector of selectors) {
    const value = parsePriceRm(textOf(doc.querySelector(selector)));
    if (value !== null) return value;
  }
  return null;
}

/**
 * A price from elements that look like prices.
 *  1. Meta/itemprop tags with a `content` attribute (a bare number) are authoritative: the first
 *     one wins.
 *  2. Otherwise the amounts shown as text are collected: elements marked as prices, and any
 *     element whose own text is just "RM ...", inside the main content.
 * A page usually also shows OTHER ads ("You may also like") and may show a range as two separate
 * elements or an old price beside the new one. Taking the first amount would then present a
 * different price as Captured, so the text amounts count only when they are all the SAME amount;
 * more than one distinct amount is ambiguous and returns null (the buyer types the price).
 */
function priceFromDom(doc: Document): number | null {
  for (const node of Array.from(
    doc.querySelectorAll(
      'meta[itemprop="price"][content], meta[property="product:price:amount"][content]',
    ),
  )) {
    const value = parsePriceValue(node.getAttribute("content"));
    if (value !== null) return value;
  }

  const amounts = new Set<number>();
  for (const node of Array.from(
    doc.querySelectorAll('[itemprop="price"], [data-testid*="price" i], [class*="price" i]'),
  )) {
    const value = parsePriceRm(textOf(node));
    if (value !== null) amounts.add(value);
  }
  const scope = doc.querySelector("main, [role='main']") ?? doc.body;
  const leaves = Array.from(scope?.querySelectorAll("span, strong, p, div") ?? []).slice(0, 2000);
  for (const node of leaves) {
    if (node.childElementCount !== 0) continue;
    const text = textOf(node);
    if (/^(?:RM|MYR)\s*\d[\d,.]*$/i.test(text)) {
      const value = parsePriceRm(text);
      if (value !== null) amounts.add(value);
    }
  }
  const [only] = amounts;
  return amounts.size === 1 && only !== undefined ? only : null;
}

// ---- Photos ---------------------------------------------------------------------------------

/** True when the browser reports the element as not displayed. Tolerates documents with no window. */
function isHidden(element: Element): boolean {
  try {
    const style = globalThis.getComputedStyle(element);
    return style.display === "none" || style.visibility === "hidden";
  } catch {
    // A document without a browsing context (as in tests) has no computed style: treat as visible.
    return false;
  }
}

/**
 * The images in the page's gallery area with the size they were rendered at.
 * In a real page the layout rectangle is the size. Fixtures recorded for tests carry the size as
 * width/height attributes instead (jsdom has no layout engine), so the attribute is the fallback.
 */
function collectImageCandidates(doc: Document, baseUrl: string): ImageCandidate[] {
  const scoped = Array.from(
    doc.querySelectorAll<HTMLImageElement>(
      'main img, [role="main"] img, [data-testid*="gallery" i] img, [class*="gallery" i] img',
    ),
  );
  const pool = scoped.length > 0 ? scoped : Array.from(doc.images);
  const viewportHeight = globalThis.innerHeight || 768;
  const candidates: ImageCandidate[] = [];
  for (const img of pool) {
    if (isHidden(img)) continue;
    const raw = img.currentSrc || img.getAttribute("src") || "";
    if (!raw || raw.startsWith("data:")) continue;
    let url: string;
    try {
      url = new URL(raw, baseUrl).href;
    } catch {
      continue;
    }
    const rect = img.getBoundingClientRect();
    // Images far below the fold (related listings) are not the listing's photos.
    if (rect.top > viewportHeight * 3) continue;
    candidates.push({
      url,
      width: rect.width || img.width,
      height: rect.height || img.height,
    });
  }
  return candidates;
}

/** The og:image URL as a one-item list, or an empty list. */
function ogImage(doc: Document, baseUrl: string): string[] {
  const content = metaContent(doc, 'meta[property="og:image"]');
  if (!content) return [];
  try {
    return [new URL(content, baseUrl).href];
  } catch {
    return [];
  }
}

// ---- Page state -----------------------------------------------------------------------------

// A page nearly this short (in characters of visible text) is a challenge or error page, not a
// listing: real listing pages carry a header, a description, related ads, and a footer.
const SHORT_PAGE_CHARS = 600;

// Elements whose text may announce a blocked page: headings and alert-style banners.
const BANNER_SELECTOR = "h1, h2, h3, [role='alert'], [role='alertdialog'], [role='status']";

// A heading or banner that says, as a whole, that the listing is gone ("This item has been sold.").
// Anchored to the whole text on purpose: a TITLE such as "Item sold as is Samsung S21" is a live
// listing and must not match.
const GONE_HEADING =
  /^(?:this |the )?(?:listing|item|ad|advert|page|product)(?: is| has been| was)(?: no longer available| unavailable| deleted| removed| expired| sold| not found)(?: by the seller| anymore)?[.!]?$/;

// The same idea anywhere in a nearly empty page, where the sentence may sit among other words.
const GONE_ANYWHERE =
  /listing (?:is |has been )?(?:unavailable|deleted|removed|expired)|item (?:is |has been )?(?:unavailable|deleted|removed|sold)|(?:listing|item|ad) (?:is|has been|was) no longer available|page (?:does not exist|not found)/;

/**
 * Detects pages the extension must not read: a CAPTCHA, an access-denied block, a login wall, or
 * a removed listing. The checks mirror the Data Collector's, which detects (and never bypasses)
 * the same pages.
 *
 * Only the title, headings, alert-style banners, and, for a nearly empty page, the whole body are
 * read. A normal listing is long and holds the seller's own free text ("item sold as is"), and
 * many sites show a reCAPTCHA notice in the footer; neither may decide the page state.
 * @returns The blocked state, or null for an ordinary page.
 */
export function detectPageState(doc: Document, pathname: string): BlockedState | null {
  const banners = [
    doc.title,
    ...Array.from(doc.querySelectorAll(BANNER_SELECTOR)).map((element) => textOf(element)),
  ]
    .map((text) => normalizeText(text).toLowerCase())
    .filter((text) => text !== "");
  const body = normalizeText(textOf(doc.body)).toLowerCase();
  // What a challenge or error page says: its banners, plus its whole text when it is short.
  const readable = body.length < SHORT_PAGE_CHARS ? [...banners, body] : banners;
  // True when any readable text matches the pattern.
  const said = (pattern: RegExp): boolean => readable.some((text) => pattern.test(text));
  const path = pathname.toLowerCase();

  if (said(/captcha|verify (?:that )?you are human|complete the security check/)) {
    return "captcha";
  }
  if (
    said(/access denied|request blocked|checking your browser|just a moment/) ||
    doc.querySelector("[data-ray], #cf-challenge-running, .cf-browser-verification")
  ) {
    return "access_denied";
  }
  if (
    /\/(?:login|signin|sign-in)(?:\/|$)/.test(path) ||
    said(/(?:log|sign) in (?:is )?required|(?:log|sign) in to (?:continue|view)/)
  ) {
    return "login_required";
  }
  if (
    banners.some((text) => GONE_HEADING.test(text)) ||
    (body.length < SHORT_PAGE_CHARS && GONE_ANYWHERE.test(body))
  ) {
    return "listing_unavailable";
  }
  return null;
}

/**
 * The link to the seller's profile on a listing page, or null. Only a link to a seller page of the
 * SAME marketplace counts (Carousell and Mudah profiles are /u/<name>); real Carousell listing
 * pages carry one almost every time, real Mudah ones mostly do not.
 */
function findSellerUrl(doc: Document, baseUrl: string, platform: Platform): string | null {
  for (const anchor of Array.from(doc.querySelectorAll<HTMLAnchorElement>("a[href]"))) {
    try {
      const absolute = new URL(anchor.getAttribute("href") ?? "", baseUrl).href;
      if (classifySellerUrl(absolute)?.platform === platform) return absolute;
    } catch {
      // Not a URL (for example "javascript:"); keep looking.
    }
  }
  return null;
}

// ---- Public entry point ---------------------------------------------------------------------

/** Options for captureListing. `selectors` lets tests supply their own platform selectors. */
export interface CaptureOptions {
  selectors?: Record<Platform, PlatformSelectors>;
}

/**
 * Reads a listing page.
 * @param doc The listing page's document.
 * @param url The page's URL (it must be a supported listing URL).
 * @param options Optional overrides, used by tests.
 * @returns The captured fields, the photo candidates, and the page state.
 * @throws Error when `url` is not a supported marketplace listing page.
 */
export function captureListing(
  doc: Document,
  url: string,
  options: CaptureOptions = {},
): CapturedListing {
  const ref = classifyListingUrl(url);
  if (!ref) throw new Error("captureListing needs a supported marketplace listing URL");
  const selectors = (options.selectors ?? PLATFORM_SELECTORS)[ref.platform];
  const { products, breadcrumbs } = readStructuredData(doc);
  const product = products[0];
  // Mudah keeps the ad's real data in an embedded script; Carousell does not (see readMudahAd).
  const mudahAd = ref.platform === "mudah" ? readMudahAd(doc, ref.listingId, url) : null;

  const title = firstOf(
    () => headingTitle(doc),
    () => firstText(doc, selectors.title),
    () => clean(product?.name),
    () => mudahAd?.title ?? null,
    () => withoutSiteName(metaContent(doc, 'meta[property="og:title"]')),
  );
  const description = firstOf(
    () => mudahAd?.description ?? null,
    () => clean(product?.description),
    () => firstText(doc, selectors.description),
    // Mudah's meta descriptions are a generated sentence (title, category, place), not the seller's
    // words, so they are never offered as the description there.
    () => (ref.platform === "mudah" ? null : metaContent(doc, 'meta[property="og:description"]')),
    () => (ref.platform === "mudah" ? null : metaContent(doc, 'meta[name="description"]')),
  );
  // When Mudah's own ad record is present, its price is final. The page's other "RM" amounts
  // belong to related ads, so the DOM strategies are not tried: an ad with no stated price stays
  // "not found" and the buyer types it.
  const price = mudahAd
    ? parsePriceRm(mudahAd.priceText)
    : firstOf(
        () => productPrice(product),
        () =>
          parsePriceValue(
            metaContent(doc, 'meta[property="product:price:amount"], meta[itemprop="price"]'),
          ),
        () => priceFromSelectors(doc, selectors.price),
        () => priceFromDom(doc),
      );
  const category = firstOf(
    () => mudahAd?.category ?? null,
    () => clean(product?.category),
    () => breadcrumbCategory(breadcrumbs, title),
    () => domBreadcrumbCategory(doc, title),
    () => firstText(doc, selectors.category),
  );

  // The ad record names the ad's own photos; scanning the DOM would also pick up related ads.
  const gallery =
    mudahAd && mudahAd.imageUrls.length > 0
      ? mudahAd.imageUrls
      : selectGalleryImages(collectImageCandidates(doc, url), productPhotos(product, url));
  const imageUrls = gallery.length > 0 ? gallery : ogImage(doc, url);

  const blocked = detectPageState(doc, new URL(url).pathname);
  const pageState: PageState =
    blocked ?? (title !== null && price !== null && imageUrls.length > 0 ? "ready" : "incomplete");

  return {
    adapterVersion: ADAPTER_VERSION,
    platform: ref.platform,
    platformHost: ref.host,
    marketplaceListingId: ref.listingId,
    title: field(title),
    description: field(description),
    price: field(price),
    category: field(category),
    imageUrls,
    sellerUrl: findSellerUrl(doc, url, ref.platform),
    pageState,
  };
}
