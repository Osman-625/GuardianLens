// Per-platform CSS selectors that refine the generic extraction in listing.ts.
//
// The generic strategies (structured data, meta tags, headings, "RM" prices, breadcrumb links)
// are tried first for every field; the selectors here are tried NEXT, in order, for the pages
// that need them. Each list starts empty and is filled only where a real page proved a
// selector necessary, using docs/SPIKE_NOTES.md ("Description and category selectors") and the
// real-fixture tests. Keep each selector short and prefer stable attributes (data-testid, ARIA
// labels, itemprop) over generated class names, which change with every site release.
//
// Example (illustrative): description: ["[data-testid='listing-description']"].
import type { Platform } from "@guardianlens/shared";

/** The selectors tried, in order, for each field. An empty list means "generic strategies only". */
export interface PlatformSelectors {
  title: string[];
  description: string[];
  price: string[];
  category: string[];
}

/** Selectors per marketplace. */
export const PLATFORM_SELECTORS: Record<Platform, PlatformSelectors> = {
  mudah: { title: [], description: [], price: [], category: [] },
  carousell: { title: [], description: [], price: [], category: [] },
};
