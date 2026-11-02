// Entry point of the injected capture script's logic: given the page it runs in, decide whether it
// is a listing, a seller page, or something else, and return the matching capture result.
// Kept free of any browser-extension API so it can be tested in jsdom like any other function.
import { classifyListingUrl, classifySellerUrl, platformFromHost } from "./classify";
import { captureListing, detectPageState } from "./listing";
import { parseSellerPage, type SellerValues } from "./seller";
import type { CapturedField, CapturedSeller, CaptureResult } from "./types";

/** Wraps a nullable number as a captured / not-found field. */
function numberField(value: number | null): CapturedField<number> {
  return value === null ? { status: "not_found", value: null } : { status: "captured", value };
}

/** Converts parsed seller values to captured fields (null becomes "not found"). */
function toCapturedSeller(values: SellerValues): CapturedSeller {
  return {
    accountAgeDays: numberField(values.accountAgeDays),
    rating: numberField(values.rating),
    reviewCount: numberField(values.reviewCount),
    activeListingCount: numberField(values.activeListingCount),
  };
}

/** The hostname of a URL, or "" when it cannot be parsed. */
function hostnameOf(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return "";
  }
}

/**
 * Captures the current page.
 * @param doc The page's document.
 * @param url The page's URL.
 * @param now "Today", for seller join-date calculations.
 * @returns A listing capture, a seller capture, or an "unsupported" result with the reason.
 */
export function captureCurrentPage(doc: Document, url: string, now: Date): CaptureResult {
  if (classifyListingUrl(url)) {
    return { kind: "listing", listing: captureListing(doc, url) };
  }
  const seller = classifySellerUrl(url);
  if (seller) {
    const blocked = detectPageState(doc, new URL(url).pathname);
    return {
      kind: "seller",
      platform: seller.platform,
      url,
      seller: toCapturedSeller(parseSellerPage(doc, seller.platform, url, now)),
      pageState: blocked ?? "ready",
    };
  }
  return {
    kind: "unsupported",
    reason: platformFromHost(hostnameOf(url)) ? "not_a_listing" : "unsupported_site",
  };
}
