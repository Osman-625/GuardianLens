// Decides what kind of page a URL is: a supported marketplace's LISTING page, its SELLER page,
// or neither. Pure string logic with no browser calls, so it is fast to test.
//
// Listing URL shapes follow URL_Crawler/url_utils.py and the Data Collector's extension. Seller URL
// shapes come from docs/SPIKE_NOTES.md ("Seller page URL shapes"); a seller page that is not
// recognised needs its pattern added here, with a test that uses a made-up slug.
import type { Platform, PlatformHost } from "@guardianlens/shared";

/** A recognised marketplace and the exact host the page was served from. */
export interface PlatformInfo {
  platform: Platform;
  host: PlatformHost;
}

/** A recognised listing page: the marketplace plus the listing's numeric id. */
export interface ListingRef extends PlatformInfo {
  listingId: string;
}

// The only four hosts the extension will ever act on. Matching is exact on purpose: a
// look-alike such as "www.carousell.com.my.evil.com" must never be treated as a marketplace.
const HOSTS: Record<string, PlatformInfo> = {
  "mudah.my": { platform: "mudah", host: "mudah.my" },
  "www.mudah.my": { platform: "mudah", host: "www.mudah.my" },
  "carousell.com.my": { platform: "carousell", host: "carousell.com.my" },
  "www.carousell.com.my": {
    platform: "carousell",
    host: "www.carousell.com.my",
  },
};

// Carousell listing: /p/<slug>-<numeric id>/        Mudah listing: /<slug>-<numeric id>.htm
// The id must start with 1-9 (no leading zero), matching the crawler's rule.
const CAROUSELL_LISTING = /^\/p\/[^/]+-([1-9]\d*)\/?$/i;
const MUDAH_LISTING = /^\/[^/]+-([1-9]\d*)\.htm$/i;

// Seller pages. Profiles on BOTH marketplaces are /u/<username> (the Data Collector's real captures:
// 1,469 on Carousell, 28 on Mudah). Elsewhere a path segment named seller, profile, user, shop,
// or dealer marks one (the same words the Collector scores seller links by).
const PROFILE_SELLER = /^\/u\/[^/]+\/?$/i;
const GENERIC_SELLER = /\/(?:seller|profile|user|shop|dealer)(?:\/|$)/i;

/** Looks up a hostname in the four known marketplace hosts (case-insensitive, exact match). */
export function platformFromHost(hostname: string): PlatformInfo | null {
  return HOSTS[hostname.toLowerCase()] ?? null;
}

/** Parses a URL, accepting only https; returns null for anything else or for invalid text. */
function parseHttps(url: string | undefined): URL | null {
  try {
    const parsed = new URL(url ?? "");
    return parsed.protocol === "https:" ? parsed : null;
  } catch {
    return null;
  }
}

/**
 * Recognises a marketplace listing page.
 * @returns The platform, host, and listing id, or null when the URL is not a listing page.
 */
export function classifyListingUrl(url: string | undefined): ListingRef | null {
  const parsed = parseHttps(url);
  if (!parsed) return null;
  const info = platformFromHost(parsed.hostname);
  if (!info) return null;
  const pattern = info.platform === "carousell" ? CAROUSELL_LISTING : MUDAH_LISTING;
  const listingId = pattern.exec(parsed.pathname)?.[1];
  return listingId ? { ...info, listingId } : null;
}

/** True when two URLs are the same page: same path, ignoring case and a trailing slash. */
export function samePage(a: string, b: string): boolean {
  try {
    const path = (url: string) => new URL(url).pathname.toLowerCase().replace(/\/+$/, "");
    return path(a) === path(b);
  } catch {
    return false;
  }
}

/**
 * Recognises a marketplace seller / profile page.
 * @returns The platform and host, or null when the URL is not a seller page. A listing page is
 *          never a seller page, even if its path contains one of the seller words.
 */
export function classifySellerUrl(url: string | undefined): PlatformInfo | null {
  const parsed = parseHttps(url);
  if (!parsed) return null;
  const info = platformFromHost(parsed.hostname);
  if (!info || classifyListingUrl(url)) return null;
  const isSeller = PROFILE_SELLER.test(parsed.pathname) || GENERIC_SELLER.test(parsed.pathname);
  return isSeller ? info : null;
}
