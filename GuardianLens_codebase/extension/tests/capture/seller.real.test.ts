// Checks the seller parsers against seller pages recorded from the live sites.
// These pages are git-ignored, so on a machine without them the whole file skips itself.
// A value of null in expected.json means "the page does not show it"; only shown values are compared.
import { describe, expect, it } from "vitest";
import { parseSellerPage } from "../../lib/capture/seller";
import { listRealFixtures, parseHtml, readFixtureHtml } from "../helpers/realFixtures";

// Every recorded fixture found on this machine (empty when none were recorded).
const fixtures = listRealFixtures();
// A well-formed seller page URL per platform; the parser only needs it to resolve listing links.
const BASE = {
  carousell: "https://www.carousell.com.my/u/seller/",
  mudah: "https://www.mudah.my/seller/shop",
} as const;

describe.skipIf(fixtures.length === 0)("seller parsing on locally recorded real pages", () => {
  for (const fixture of fixtures) {
    const html = readFixtureHtml(fixture, "seller");
    it.skipIf(html === null)(`${fixture.platform}/${fixture.slug}`, () => {
      const today = new Date(`${fixture.expected.recordedOn}T00:00:00Z`);
      const parsed = parseSellerPage(
        parseHtml(html as string),
        fixture.platform,
        BASE[fixture.platform],
        today,
      );
      const shown = fixture.expected.seller;
      if (shown.accountAgeDays !== null) expect(parsed.accountAgeDays).toBe(shown.accountAgeDays);
      if (shown.rating !== null) expect(parsed.rating).toBe(shown.rating);
      if (shown.reviewCount !== null) expect(parsed.reviewCount).toBe(shown.reviewCount);
      if (shown.activeListingCount !== null)
        expect(parsed.activeListingCount).toBe(shown.activeListingCount);
    });
  }
});
