// Pins how the extension decides what the current tab is.
// Getting this wrong has two costs: a real listing treated as "not a listing" blocks the buyer,
// and a look-alike site treated as a marketplace would get the capture script injected. So host
// matching is EXACT (no suffix tricks), only https counts, and the listing URL shapes are the
// ones the URL crawler and the Data Collector already use.
import { describe, expect, it } from "vitest";
import {
  classifyListingUrl,
  classifySellerUrl,
  platformFromHost,
} from "../../lib/capture/classify";

describe("platformFromHost", () => {
  it("knows the four marketplace hosts", () => {
    expect(platformFromHost("www.carousell.com.my")).toEqual({
      platform: "carousell",
      host: "www.carousell.com.my",
    });
    expect(platformFromHost("mudah.my")).toEqual({
      platform: "mudah",
      host: "mudah.my",
    });
  });

  it("is case-insensitive and rejects anything else", () => {
    expect(platformFromHost("WWW.MUDAH.MY")?.platform).toBe("mudah");
    expect(platformFromHost("example.com")).toBeNull();
  });
});

describe("classifyListingUrl", () => {
  it("recognises a Carousell listing", () => {
    expect(classifyListingUrl("https://www.carousell.com.my/p/iphone-13-1234567890/")).toEqual({
      platform: "carousell",
      host: "www.carousell.com.my",
      listingId: "1234567890",
    });
  });

  it("recognises a Mudah listing", () => {
    expect(classifyListingUrl("https://www.mudah.my/samsung-galaxy-s21-123456789.htm")).toEqual({
      platform: "mudah",
      host: "www.mudah.my",
      listingId: "123456789",
    });
  });

  it("ignores query strings and a missing trailing slash", () => {
    expect(
      classifyListingUrl("https://www.carousell.com.my/p/phone-99?ref=search")?.listingId,
    ).toBe("99");
  });

  it.each([
    ["plain http", "http://www.carousell.com.my/p/x-1/"],
    ["a category page", "https://www.carousell.com.my/categories/phones/"],
    ["an id that starts with zero", "https://www.carousell.com.my/p/x-0/"],
    ["another site", "https://example.com/p/x-1/"],
    ["a look-alike host (suffix trick)", "https://www.carousell.com.my.evil.com/p/x-1/"],
    ["a look-alike host (prefix trick)", "https://evilcarousell.com.my/p/x-1/"],
    ["the Mudah home page", "https://www.mudah.my/"],
    ["text that is not a URL", "not a url"],
    ["an empty string", ""],
  ])("rejects %s", (_label, url) => {
    expect(classifyListingUrl(url)).toBeNull();
  });

  it("returns null for undefined", () => {
    expect(classifyListingUrl(undefined)).toBeNull();
  });
});

describe("classifySellerUrl", () => {
  it("recognises a Carousell profile page", () => {
    expect(classifySellerUrl("https://www.carousell.com.my/u/some-seller/")).toEqual({
      platform: "carousell",
      host: "www.carousell.com.my",
    });
  });

  it("recognises a Mudah profile page, which is /u/<name> too (as in real captures)", () => {
    expect(classifySellerUrl("https://www.mudah.my/u/some-seller")).toEqual({
      platform: "mudah",
      host: "www.mudah.my",
    });
    expect(classifySellerUrl("https://mudah.my/u/some-seller/")?.platform).toBe("mudah");
  });

  it("recognises a generic seller or shop path", () => {
    expect(classifySellerUrl("https://www.mudah.my/shop/some-shop")?.platform).toBe("mudah");
  });

  it("does not treat a listing as a seller page", () => {
    expect(classifySellerUrl("https://www.carousell.com.my/p/phone-123/")).toBeNull();
  });

  it("does not treat other sites as seller pages", () => {
    expect(classifySellerUrl("https://example.com/u/someone/")).toBeNull();
  });
});
