// Pins the listing adapter: what it reads from a listing page, and what it refuses to guess.
// Each synthetic fixture isolates one strategy (JSON-LD, DOM only, platform selectors) so a
// failure points at the strategy that broke. The rules protected here:
//   - a field no strategy can read is "not_found", never invented (the buyer fills it in Review);
//   - an ambiguous price (a range, "Free", "Negotiable") is "not_found", never 0 or one end;
//   - blocked pages (captcha, login wall, removed listing) are reported, not half-read;
//   - malformed structured data cannot crash the capture.
import { describe, expect, it } from "vitest";
import { captureListing, detectPageState } from "../../lib/capture/listing";
import { PLATFORM_SELECTORS } from "../../lib/capture/selectors";
import { loadSynthetic, parseHtml } from "../helpers/realFixtures";

// A well-formed listing URL for each platform; the adapter needs the shape, not a live page.
const CAROUSELL_URL = "https://www.carousell.com.my/p/used-laptop-1234567890/";
const MUDAH_URL = "https://www.mudah.my/samsung-galaxy-s21-123456789.htm";

/** Builds a small page from head and body markup, for tests that need one specific shape. */
function page(body: string, head = ""): Document {
  return parseHtml(
    `<!doctype html><html><head>${head}</head><body><main>${body}</main></body></html>`,
  );
}

describe("structured data page (Carousell style)", () => {
  const listing = captureListing(loadSynthetic("carousell-jsonld"), CAROUSELL_URL);

  it("reads every field", () => {
    expect(listing.title).toEqual({
      status: "captured",
      value: "Used laptop in good condition",
    });
    expect(listing.description.value).toBe(
      "Original unit, battery health 90 percent. COD available around Shah Alam.",
    );
    expect(listing.price).toEqual({ status: "captured", value: 1250 });
    expect(listing.category.value).toBe("Laptops");
  });

  it("reads the photos and identifies the page", () => {
    expect(listing.imageUrls).toEqual([
      "https://media.karousell.com/media/photos/products/1/a.jpg",
      "https://media.karousell.com/media/photos/products/1/b.jpg",
    ]);
    expect(listing.platform).toBe("carousell");
    expect(listing.platformHost).toBe("www.carousell.com.my");
    expect(listing.marketplaceListingId).toBe("1234567890");
    expect(listing.pageState).toBe("ready");
  });
});

// The seller step: a listing page that links to the seller's profile lets the panel offer
// "Open seller page" for the second capture. Real Carousell listings carry a /u/<name> link.
describe("the seller's profile link on a listing page", () => {
  const link = (href: string, platformUrl = CAROUSELL_URL) =>
    captureListing(page(`<h1>Used laptop</h1><a href="${href}">Seller</a>`), platformUrl).sellerUrl;

  it("is read from a relative Carousell profile link", () => {
    expect(link("/u/some-seller/")).toBe("https://www.carousell.com.my/u/some-seller/");
  });

  it("is read from a Mudah profile link on a Mudah listing", () => {
    expect(link("https://www.mudah.my/u/some-seller", MUDAH_URL)).toBe(
      "https://www.mudah.my/u/some-seller",
    );
  });

  it("is null when the page links to no seller", () => {
    expect(link("/p/another-listing-999/")).toBeNull();
    expect(captureListing(loadSynthetic("carousell-jsonld"), CAROUSELL_URL).sellerUrl).toBeNull();
  });

  it("ignores a profile on another marketplace and on other sites", () => {
    expect(link("https://www.mudah.my/u/someone")).toBeNull(); // a Mudah profile on a Carousell page
    expect(link("https://example.com/u/someone/")).toBeNull();
  });

  it("is not thrown by a link that is not a URL", () => {
    expect(link("http://[bad")).toBeNull();
    expect(link("javascript:void(0)")).toBeNull();
  });

  it("takes the first matching link", () => {
    const doc = page(`<a href="/u/first/">a</a><a href="/u/second/">b</a>`);
    expect(captureListing(doc, CAROUSELL_URL).sellerUrl).toBe(
      "https://www.carousell.com.my/u/first/",
    );
  });
});

describe("DOM-only page (Mudah style, no embedded ad data)", () => {
  const listing = captureListing(loadSynthetic("mudah-dom-only"), MUDAH_URL);

  it("falls back to the heading, the visible RM price, and the breadcrumb", () => {
    expect(listing.title.value).toBe("Samsung Galaxy S21 128GB");
    expect(listing.price.value).toBe(3500);
    expect(listing.category.value).toBe("Mobile Phones");
  });

  it("does not take the meta description as the seller's description on Mudah", () => {
    // Live Mudah pages put a GENERATED sentence (title, category, place) in the meta description,
    // so using it would show the buyer something that looks captured but is not the description.
    // The buyer types it instead.
    expect(listing.description).toEqual({ status: "not_found", value: null });
  });

  it("keeps the gallery photos and leaves out the icon", () => {
    expect(listing.imageUrls).toEqual([
      "https://cdn.rnudah.com/photos/1/x.jpg",
      "https://cdn.rnudah.com/photos/1/y.jpg",
    ]);
    expect(listing.pageState).toBe("ready");
  });
});

describe("Mudah page with embedded ad data (__NEXT_DATA__)", () => {
  const url = "https://www.mudah.my/used-phone-123456789.htm";
  const listing = captureListing(loadSynthetic("mudah-next-data"), url);

  it("reads the title, price, and category of THIS ad", () => {
    expect(listing.title.value).toBe("Used phone (fake)");
    // The only RM amounts in the visible page belong to related ads (599 and 650).
    expect(listing.price).toEqual({ status: "captured", value: 700 });
    // The sub-category maps straight to a trained category.
    expect(listing.category.value).toBe("Phones");
  });

  it("reads the seller's own description with its line breaks, not the generated meta description", () => {
    expect(listing.description.value).toBe("FOR SALE\nPhone model X\n64GB & box\nMeet up in KK");
  });

  it("takes the ad's own photos (full size first), not the related ads' or the og image", () => {
    expect(listing.imageUrls).toEqual([
      "https://cdn.rnudah.com/image_hd/plain/a.jpg",
      "https://cdn.rnudah.com/image_hd/plain/b.jpg",
    ]);
    expect(listing.pageState).toBe("ready");
  });

  it("ignores ad data that belongs to a different listing id", () => {
    // Same page, but the URL says it is another ad: the embedded record must not be used.
    const other = captureListing(
      loadSynthetic("mudah-next-data"),
      "https://www.mudah.my/used-phone-999999999.htm",
    );
    expect(other.price).toEqual({ status: "not_found", value: null });
    expect(other.description).toEqual({ status: "not_found", value: null });
  });

  it("never invents a price from the related ads when the ad itself shows none", () => {
    const doc = loadSynthetic("mudah-next-data");
    const script = doc.getElementById("__NEXT_DATA__");
    if (script)
      script.textContent = (script.textContent ?? "").replaceAll(
        '"price": "RM 700"',
        '"price": ""',
      );
    const noPrice = captureListing(doc, url);
    expect(noPrice.price).toEqual({ status: "not_found", value: null });
  });

  it("survives broken embedded data", () => {
    const doc = loadSynthetic("mudah-next-data");
    const script = doc.getElementById("__NEXT_DATA__");
    if (script) script.textContent = "{ not json";
    const broken = captureListing(doc, url);
    expect(broken.title.value).toBe("Used phone (fake)");
    expect(broken.description).toEqual({ status: "not_found", value: null });
  });
});

describe("platform selectors", () => {
  it("do not find a description that only a selector can reach, unless one is configured", () => {
    const without = captureListing(loadSynthetic("selectors-description"), CAROUSELL_URL);
    expect(without.description).toEqual({ status: "not_found", value: null });

    const withSelector = captureListing(loadSynthetic("selectors-description"), CAROUSELL_URL, {
      selectors: {
        ...PLATFORM_SELECTORS,
        carousell: {
          ...PLATFORM_SELECTORS.carousell,
          description: [".desc-box"],
        },
      },
    });
    expect(withSelector.description.value).toBe("Adjustable LED desk lamp, used for one year.");
  });
});

describe("price text on a page that also shows other ads", () => {
  // Marketplace pages list related ads, each with its own "RM ..." price. Taking the first amount
  // would show a different ad's price as Captured, so more than one distinct amount is ambiguous.
  it("reports not found when the page shows two different amounts", () => {
    const listing = captureListing(
      page("<h1>Used phone</h1><div>RM 700</div><div>RM 599</div>"),
      MUDAH_URL,
    );
    expect(listing.price).toEqual({ status: "not_found", value: null });
  });

  it("accepts the same amount shown more than once", () => {
    const listing = captureListing(
      page("<h1>Used phone</h1><div>RM 700</div><p><span>RM 700</span></p>"),
      MUDAH_URL,
    );
    expect(listing.price).toEqual({ status: "captured", value: 700 });
  });

  it("reports a split range as not found instead of one end", () => {
    const listing = captureListing(
      page("<h1>Used phone</h1><span>RM 1,200</span> - <span>RM 1,500</span>"),
      MUDAH_URL,
    );
    expect(listing.price).toEqual({ status: "not_found", value: null });
  });
});

describe("a price range in structured data", () => {
  it("is not captured as its low end", () => {
    const head = `<script type="application/ld+json">{"@type":"Product","name":"Used phone","offers":{"@type":"AggregateOffer","lowPrice":"1200","highPrice":"1500"}}</script>`;
    const listing = captureListing(page("<p>no visible price</p>", head), CAROUSELL_URL);
    expect(listing.price).toEqual({ status: "not_found", value: null });
  });
});

describe("blocked pages", () => {
  it.each([
    ["blocked-captcha", "captcha"],
    ["blocked-login", "login_required"],
    ["listing-unavailable", "listing_unavailable"],
  ])("reports %s as %s", (name, state) => {
    expect(captureListing(loadSynthetic(name), CAROUSELL_URL).pageState).toBe(state);
  });

  it("detects a login URL even when the text says nothing", () => {
    expect(detectPageState(page("<p>hello</p>"), "/login")).toBe("login_required");
  });

  it("returns null for an ordinary page", () => {
    expect(detectPageState(page("<h1>Phone</h1>"), "/p/phone-1/")).toBeNull();
  });
});

describe("incomplete pages", () => {
  it("marks every unreadable field as not found and the page as incomplete", () => {
    const listing = captureListing(loadSynthetic("missing-everything"), CAROUSELL_URL);
    expect(listing.title.value).toBe("Bare page");
    expect(listing.description.status).toBe("not_found");
    expect(listing.price.status).toBe("not_found");
    expect(listing.category.status).toBe("not_found");
    expect(listing.imageUrls).toEqual([]);
    expect(listing.pageState).toBe("incomplete");
  });
});

// A price written as a range, a word, or anything other than one clear "RM" amount is never guessed.
describe("ambiguous prices", () => {
  it.each([
    ["a range", "<span>RM 1,200 - RM 1,500</span>"],
    ["the word Free", "<span>Free</span>"],
    ["Negotiable", "<span>Negotiable</span>"],
  ])("are not found for %s", (_label, markup) => {
    const listing = captureListing(page(`<h1>Item</h1>${markup}`), CAROUSELL_URL);
    expect(listing.price).toEqual({ status: "not_found", value: null });
  });

  it("reads a price written without a space or with decimals", () => {
    expect(
      captureListing(page("<h1>Item</h1><span>RM1250.50</span>"), CAROUSELL_URL).price.value,
    ).toBe(1250.5);
  });
});

describe("robustness", () => {
  it("ignores malformed structured data", () => {
    const doc = page(
      "<h1>Item</h1><span>RM 10</span>",
      '<script type="application/ld+json">{bad json</script>',
    );
    const listing = captureListing(doc, CAROUSELL_URL);
    expect(listing.title.value).toBe("Item");
    expect(listing.price.value).toBe(10);
  });

  it("skips a breadcrumb entry that is just the listing title", () => {
    const doc = page(
      '<nav aria-label="Breadcrumb"><a>Home</a><a>Laptops</a><a>Used laptop</a></nav><h1>Used laptop</h1>',
    );
    expect(captureListing(doc, CAROUSELL_URL).category.value).toBe("Laptops");
  });

  it("falls back to the og:image photo when the page has no gallery images", () => {
    const doc = page(
      "<h1>Item</h1>",
      '<meta property="og:image" content="https://media.karousell.com/media/photos/products/9/cover.jpg" />',
    );
    expect(captureListing(doc, CAROUSELL_URL).imageUrls).toEqual([
      "https://media.karousell.com/media/photos/products/9/cover.jpg",
    ]);
  });

  it("refuses a URL that is not a supported listing page", () => {
    expect(() => captureListing(page("<h1>Item</h1>"), "https://example.com/p/x-1/")).toThrow();
  });
});

// A blocked-page check must never read the seller's own words. Second-hand listings say "item sold
// as is" all the time, and many sites show a reCAPTCHA notice in the footer; neither makes the page
// a removed listing or a challenge. A real listing is also long, while a challenge or error page is
// nearly empty, so only headings, banners, and very short pages are read.
describe("ordinary listings are not mistaken for blocked pages", () => {
  // Makes the page long, like a real listing page with a header, description, and footer.
  const filler = " Well kept and fully working, original box included.".repeat(20);

  it.each([
    "Item sold as is, no returns.",
    "Used item sold with box and charger.",
    "Selling because the other item has been sold.",
    "Message me to log in to continue chatting, or login on the site first.",
    "Access denied to the old account, so I am selling this one.",
  ])("a description saying '%s' is not a blocked page", (sentence) => {
    const doc = page(`<h1>Used phone</h1><p>${sentence}${filler}</p><div>RM 700</div>`);
    expect(detectPageState(doc, "/used-phone-123456789.htm")).toBeNull();
  });

  it("a title that contains blocked-page words is still a listing", () => {
    const doc = page(`<h1>Item sold as is Samsung S21</h1><p>${filler}</p>`);
    expect(detectPageState(doc, "/item-sold-as-is-123456789.htm")).toBeNull();
  });

  it("the reCAPTCHA footer notice and badge are not a challenge", () => {
    const doc = page(
      `<h1>Used phone</h1><p>${filler}</p><div class="grecaptcha-badge"></div>
       <footer>This site is protected by reCAPTCHA and the Google Privacy Policy applies.</footer>`,
    );
    expect(detectPageState(doc, "/used-phone-123456789.htm")).toBeNull();
  });

  it("still detects a removed listing from its heading", () => {
    const doc = page(`<h1>This listing is no longer available</h1><p>${filler}</p>`);
    expect(detectPageState(doc, "/used-phone-123456789.htm")).toBe("listing_unavailable");
  });
});
