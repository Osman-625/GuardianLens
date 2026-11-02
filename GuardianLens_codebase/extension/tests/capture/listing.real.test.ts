// Checks the listing adapter against listing pages recorded from the live sites.
// These pages are git-ignored, so on a machine without them the whole file skips itself.
// A null in expected.json means "the page does not show it", and only shown values are compared.
// The photo check also protects host_permissions: the first photos the adapter picks must be
// fetchable, otherwise a photo host is missing from lib/hosts.ts.
import { describe, expect, it } from "vitest";
import { captureListing } from "../../lib/capture/listing";
import { isFetchableImageUrl } from "../../lib/hosts";
import { listRealFixtures, parseHtml, readFixtureHtml } from "../helpers/realFixtures";

// Every recorded fixture found on this machine (empty when none were recorded).
const fixtures = listRealFixtures();
// Any well-formed listing URL for the platform: the adapter only needs the shape, not a real id.
const LISTING_URL = {
  carousell: "https://www.carousell.com.my/p/fixture-1000000001/",
  mudah: "https://www.mudah.my/fixture-1000000001.htm",
} as const;

describe.skipIf(fixtures.length === 0)("listing capture on locally recorded real pages", () => {
  for (const fixture of fixtures) {
    const html = readFixtureHtml(fixture, "listing");
    it.skipIf(html === null)(`${fixture.platform}/${fixture.slug}`, () => {
      const listing = captureListing(parseHtml(html as string), LISTING_URL[fixture.platform]);
      const shown = fixture.expected;
      if (shown.title !== null) expect(listing.title.value).toBe(shown.title);
      if (shown.priceRm !== null) expect(listing.price.value).toBe(shown.priceRm);
      if (shown.category !== null) {
        expect(listing.category.value?.toLowerCase()).toContain(shown.category.toLowerCase());
      }
      if (shown.descriptionStartsWith !== null) {
        expect(listing.description.value?.startsWith(shown.descriptionStartsWith)).toBe(true);
      }
      if (shown.imageCountAtLeast !== null) {
        expect(listing.imageUrls.length).toBeGreaterThanOrEqual(shown.imageCountAtLeast);
      }
      for (const url of listing.imageUrls.slice(0, 3)) expect(isFetchableImageUrl(url)).toBe(true);
    });
  }
});
