// Types for what the capture script reads from a page, and the one message that triggers it.
// Mostly type definitions plus two constants, so every part of the extension (the injected
// script, the service worker, and the side panel) agrees on the same shapes.
import type { Platform, PlatformHost } from "@guardianlens/shared";

/**
 * Version of the extraction logic. Bump it whenever the adapters change in a way that could
 * change what is captured, so research records can tell which logic produced a capture.
 */
export const ADAPTER_VERSION = "2";

/** Message type the service worker sends to the injected capture script to request a capture. */
export const CAPTURE_MESSAGE = "guardianlens:capture";

/** Pages the extension refuses to read, with the reason. */
export type BlockedState = "captcha" | "access_denied" | "login_required" | "listing_unavailable";

/**
 * "ready": title, price, and at least one photo were found.
 * "incomplete": the page was read but one of those is missing (the buyer fills it in).
 * The remaining values mean the page was blocked and was not read.
 */
export type PageState = "ready" | "incomplete" | BlockedState;

/** One value read from a page: "captured" with a value, or "not_found" (value is null). */
export interface CapturedField<T> {
  status: "captured" | "not_found";
  value: T | null;
}

/** What the capture script read from a listing page. */
export interface CapturedListing {
  adapterVersion: string;
  platform: Platform;
  platformHost: PlatformHost;
  /** The marketplace's numeric listing id. Kept for debugging; never sent to the API. */
  marketplaceListingId: string;
  title: CapturedField<string>;
  description: CapturedField<string>;
  /** Price in ringgit. */
  price: CapturedField<number>;
  /** The platform's own category text, before any mapping to a trained category. */
  category: CapturedField<string>;
  /** Candidate photo URLs (up to 12), best first. */
  imageUrls: string[];
  /**
   * The seller's profile page, when the listing page links to it (Carousell and Mudah profile
   * pages are /u/<name>). The panel offers it as "Open seller page" for the second capture. Kept
   * in the panel only; never sent to the API.
   */
  sellerUrl: string | null;
  pageState: PageState;
}

/** What the capture script read from a seller / profile page. */
export interface CapturedSeller {
  accountAgeDays: CapturedField<number>;
  rating: CapturedField<number>;
  reviewCount: CapturedField<number>;
  activeListingCount: CapturedField<number>;
}

/** The result of one capture click. */
export type CaptureResult =
  | { kind: "listing"; listing: CapturedListing }
  | {
      kind: "seller";
      platform: Platform;
      /** The page that was read, so the panel can check it is the seller the listing linked to. */
      url: string;
      seller: CapturedSeller;
      pageState: PageState;
    }
  | { kind: "unsupported"; reason: "not_a_listing" | "unsupported_site" };
