// Builders for the test data used across the panel tests: a captured listing, a captured seller,
// and a finished API result. Each takes overrides so a test can change only what it cares about.
import type { AssessmentResult } from "@guardianlens/shared";
import type { CapturedListing, CapturedSeller } from "../../lib/capture/types";

/** Four photo URLs on an allowed host. All four are selected by default (the limit is 10). */
export const PHOTOS = [
  "https://media.karousell.com/media/photos/products/1/a.jpg",
  "https://media.karousell.com/media/photos/products/1/b.jpg",
  "https://media.karousell.com/media/photos/products/1/c.jpg",
  "https://media.karousell.com/media/photos/products/1/d.jpg",
];

/** `count` distinct photo URLs on an allowed host, for tests about the photo limit. */
export function manyPhotos(count: number): string[] {
  return Array.from(
    { length: count },
    (_unused, index) =>
      `https://media.karousell.com/media/photos/products/1/photo-${index + 1}.jpg`,
  );
}

/** A fully captured Carousell listing. */
export function sampleListing(overrides: Partial<CapturedListing> = {}): CapturedListing {
  return {
    adapterVersion: "1",
    platform: "carousell",
    platformHost: "www.carousell.com.my",
    marketplaceListingId: "1234567890",
    title: { status: "captured", value: "Used laptop in good condition" },
    description: { status: "captured", value: "Original unit. COD available." },
    price: { status: "captured", value: 1250 },
    category: { status: "captured", value: "Computers and Tech > Laptops" },
    imageUrls: PHOTOS,
    sellerUrl: null,
    pageState: "ready",
    ...overrides,
  };
}

/** A fully captured seller page. */
export function sampleSeller(overrides: Partial<CapturedSeller> = {}): CapturedSeller {
  return {
    accountAgeDays: { status: "captured", value: 1155 },
    rating: { status: "captured", value: 4.8 },
    reviewCount: { status: "captured", value: 17 },
    activeListingCount: { status: "captured", value: 4 },
    ...overrides,
  };
}

/** A finished assessment result (development stub, moderate band, three available signals). */
export function sampleResult(overrides: Partial<AssessmentResult> = {}): AssessmentResult {
  // One available signal card with a fixed probability and the given summary.
  const card = (signal: "visual" | "textual" | "behavioural", summary: string) => ({
    signal,
    probability: 0.4,
    available: true,
    status_word: "clear",
    summary,
    reasons: [],
    scope_note: null,
  });
  return {
    assessment_id: "a1",
    title: "Used laptop in good condition",
    score: 58,
    band: "moderate",
    signal_cards: [
      card("visual", "No strong warning signs in the photos."),
      card("textual", "The wording looks ordinary."),
      card("behavioural", "The seller details look ordinary."),
    ],
    missing_data_notices: [],
    suggested_checks: [
      "Compare the price with similar listings on the same marketplace.",
      "Verify account or bank details independently using the official Semak Mule service.",
    ],
    disclaimer: "Decision support only. Verify the seller independently before paying.",
    model_bundle_label: "dev-stub-unvalidated",
    created_at: "2026-10-05T10:00:00Z",
    total_latency_ms: 120,
    development_stub: true,
    ...overrides,
  };
}
