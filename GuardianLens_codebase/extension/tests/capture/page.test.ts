// Pins the entry point of the injected capture script: given the page it was injected into, decide
// whether it is a listing, a seller page, or something else, and return the right capture result.
import { describe, expect, it } from "vitest";
import { captureCurrentPage } from "../../lib/capture/page";
import { loadSynthetic, parseHtml } from "../helpers/realFixtures";

// "Today" for the seller join-date calculations, so the tests do not depend on the real clock.
const NOW = new Date(Date.UTC(2026, 9, 5));

describe("captureCurrentPage", () => {
  it("captures a listing page", () => {
    const result = captureCurrentPage(
      loadSynthetic("carousell-jsonld"),
      "https://www.carousell.com.my/p/used-laptop-1234567890/",
      NOW,
    );
    expect(result.kind).toBe("listing");
    if (result.kind === "listing")
      expect(result.listing.title.value).toBe("Used laptop in good condition");
  });

  it("captures a seller page into captured and not-found fields", () => {
    const doc = parseHtml(`<body>
      <p>Joined 8 months ago</p>
      <h2>Listings</h2>
      <article><a href="/p/phone-111/">Phone</a></article>
    </body>`);
    const result = captureCurrentPage(doc, "https://www.carousell.com.my/u/someone/", NOW);
    expect(result.kind).toBe("seller");
    if (result.kind === "seller") {
      // The panel compares this with the seller link the listing page offered.
      expect(result.url).toBe("https://www.carousell.com.my/u/someone/");
      expect(result.seller.accountAgeDays).toEqual({
        status: "captured",
        value: 240,
      });
      expect(result.seller.activeListingCount).toEqual({
        status: "captured",
        value: 1,
      });
      // The page says nothing about reviews, so they are "not found", never 0 or suspicious.
      expect(result.seller.reviewCount).toEqual({
        status: "not_found",
        value: null,
      });
      expect(result.seller.rating).toEqual({
        status: "not_found",
        value: null,
      });
      expect(result.pageState).toBe("ready");
    }
  });

  it("reports a blocked seller page", () => {
    const doc = parseHtml("<body><p>Please verify that you are human.</p></body>");
    const result = captureCurrentPage(doc, "https://www.carousell.com.my/u/someone/", NOW);
    expect(result.kind === "seller" && result.pageState).toBe("captcha");
  });

  it("says a marketplace page that is neither listing nor seller is not a listing", () => {
    const result = captureCurrentPage(
      parseHtml("<body></body>"),
      "https://www.carousell.com.my/categories/phones/",
      NOW,
    );
    expect(result).toEqual({ kind: "unsupported", reason: "not_a_listing" });
  });

  it("says another site is unsupported", () => {
    const result = captureCurrentPage(parseHtml("<body></body>"), "https://example.com/", NOW);
    expect(result).toEqual({ kind: "unsupported", reason: "unsupported_site" });
  });
});
