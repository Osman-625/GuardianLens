// Pins which photo URLs the extension will try to fetch.
// The extension downloads listing photos itself so it can upload them to the API, and a
// browser extension may only read another site's files for hosts named in the manifest's
// host_permissions. isFetchableImageUrl mirrors that list at run time, so a photo from an
// unlisted host is skipped cleanly instead of failing with a confusing network error.
// Matching must be EXACT on the host: a look-alike such as "mudah.my.evil.com" is never allowed.
import { describe, expect, it } from "vitest";
import { IMAGE_HOST_PATTERNS, isFetchableImageUrl, PAGE_HOST_PATTERNS } from "../lib/hosts";

describe("IMAGE_HOST_PATTERNS", () => {
  it("uses the manifest match-pattern shape https://<host>/*", () => {
    for (const pattern of IMAGE_HOST_PATTERNS) {
      expect(pattern).toMatch(/^https:\/\/(\*\.)?[a-z0-9.-]+\/\*$/);
    }
  });
});

describe("isFetchableImageUrl", () => {
  it("accepts an https photo on a listed host", () => {
    expect(isFetchableImageUrl("https://media.karousell.com/media/photos/products/1/a.jpg")).toBe(
      true,
    );
  });

  it("accepts Mudah's photo CDN (a different domain from the Mudah site), by subdomain and bare domain", () => {
    // Recorded from a live Mudah listing on 2026-10-06: photos come from rnudah.com, not mudah.my.
    expect(isFetchableImageUrl("https://cdn.rnudah.com/image_hd/plain/abc-123.jpg")).toBe(true);
    expect(isFetchableImageUrl("https://img.rnudah.com/grids/a.jpg")).toBe(true);
    expect(isFetchableImageUrl("https://rnudah.com/a.jpg")).toBe(true);
  });

  // The extension must have NO standing access to the marketplace sites themselves: it may read
  // them only through the buyer's click (activeTab). A photo pattern that also matched a
  // marketplace page host would silently grant that access in host_permissions.
  it.each([
    "https://www.mudah.my/a.jpg",
    "https://mudah.my/a.jpg",
    "https://cdn.mudah.my/a.jpg",
    "https://www.carousell.com.my/a.jpg",
    "https://carousell.com.my/a.jpg",
  ])("never covers the marketplace site %s", (url) => {
    expect(isFetchableImageUrl(url)).toBe(false);
  });

  it("never lets a photo pattern match a marketplace page host", () => {
    const pageHosts = ["www.mudah.my", "mudah.my", "www.carousell.com.my", "carousell.com.my"];
    for (const pattern of IMAGE_HOST_PATTERNS) {
      const allowed = /^https:\/\/([^/]+)\/\*$/.exec(pattern)?.[1] ?? "";
      for (const host of pageHosts) {
        const matches = allowed.startsWith("*.")
          ? host === allowed.slice(2) || host.endsWith(allowed.slice(1))
          : host === allowed;
        expect(matches, `${pattern} must not match ${host}`).toBe(false);
      }
    }
  });

  it.each([
    ["a look-alike host", "https://mudah.my.evil.com/a.jpg"],
    ["an unlisted host", "https://example.com/a.jpg"],
    ["plain http", "http://media.karousell.com/a.jpg"],
    ["a data URL", "data:image/png;base64,AAAA"],
    ["something that is not a URL", "not a url"],
    ["an empty string", ""],
  ])("rejects %s", (_label, url) => {
    expect(isFetchableImageUrl(url)).toBe(false);
  });
});

describe("PAGE_HOST_PATTERNS", () => {
  // These are optional permissions asked for from a click, so they must be exactly the four
  // marketplace hosts and never overlap the standing photo-host list.
  it("lists the four marketplace hosts and none of the photo hosts", () => {
    expect([...PAGE_HOST_PATTERNS].sort()).toEqual([
      "https://carousell.com.my/*",
      "https://mudah.my/*",
      "https://www.carousell.com.my/*",
      "https://www.mudah.my/*",
    ]);
    for (const pattern of PAGE_HOST_PATTERNS) expect(IMAGE_HOST_PATTERNS).not.toContain(pattern);
  });
});
