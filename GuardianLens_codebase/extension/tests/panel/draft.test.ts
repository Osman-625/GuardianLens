// Pins the buyer's editable draft: how it is built from a capture, edited, validated, and turned
// into the form the API receives. The rules protected here:
//   - a field the page did not show is "not_found" and empty: never guessed, never zero;
//   - what the page captured is never silently shortened (a 6,000 character description stays
//     6,000 characters, and the draft is blocked with a clear message instead);
//   - at most 10 photos, and removing a photo marks the photo set as edited;
//   - the capture metadata sent to the API holds statuses and the host, never a listing URL.
import { describe, expect, it } from "vitest";
import {
  LIMITS,
  applySeller,
  buildCaptureMeta,
  buildForm,
  draftFromListing,
  editField,
  parsePriceInput,
  togglePhoto,
  validateDraft,
} from "../../lib/panel/draft";
import { PHOTOS, manyPhotos, sampleListing, sampleSeller } from "../helpers/samples";

describe("draftFromListing", () => {
  it("copies captured values and marks them captured", () => {
    const draft = draftFromListing(sampleListing());
    expect(draft.fields.title).toEqual({
      value: "Used laptop in good condition",
      status: "captured",
    });
    expect(draft.fields.price).toEqual({ value: "1250", status: "captured" });
    expect(draft.platformHost).toBe("www.carousell.com.my");
  });

  it("maps the platform category to a trained category, and keeps unknown wording as is", () => {
    expect(draftFromListing(sampleListing()).fields.category.value).toBe("Laptops");
    const odd = sampleListing({
      category: { status: "captured", value: "Aquarium supplies" },
    });
    expect(draftFromListing(odd).fields.category.value).toBe("Aquarium supplies");
  });

  it("marks values the page did not show as not found and empty, never zero", () => {
    const draft = draftFromListing(
      sampleListing({
        price: { status: "not_found", value: null },
        description: { status: "not_found", value: null },
      }),
    );
    expect(draft.fields.price).toEqual({ value: "", status: "not_found" });
    expect(draft.fields.description).toEqual({
      value: "",
      status: "not_found",
    });
  });

  it("starts every seller field as not found", () => {
    const draft = draftFromListing(sampleListing());
    for (const key of ["accountAgeDays", "rating", "reviewCount", "activeListingCount"] as const) {
      expect(draft.fields[key]).toEqual({ value: "", status: "not_found" });
    }
  });

  it("selects every photo up to the limit of ten by default", () => {
    const few = draftFromListing(sampleListing());
    expect(few.photos.every((photo) => photo.selected)).toBe(true);
    expect(few.defaultPhotoUrls).toEqual(PHOTOS);

    // A listing with 12 candidate photos: the first ten are selected, the last two are spare.
    const urls = manyPhotos(12);
    const many = draftFromListing(sampleListing({ imageUrls: urls }));
    expect(many.photos.map((photo) => photo.selected)).toEqual([
      ...Array.from({ length: 10 }, () => true),
      false,
      false,
    ]);
    expect(many.defaultPhotoUrls).toEqual(urls.slice(0, 10));
  });

  it("does not shorten a very long description", () => {
    const long = "x".repeat(6000);
    const draft = draftFromListing(
      sampleListing({ description: { status: "captured", value: long } }),
    );
    expect(draft.fields.description.value).toHaveLength(6000);
  });
});

describe("applySeller", () => {
  it("fills seller fields from the seller page", () => {
    const draft = applySeller(draftFromListing(sampleListing()), sampleSeller());
    expect(draft.fields.accountAgeDays).toEqual({
      value: "1155",
      status: "captured",
    });
    expect(draft.fields.rating).toEqual({ value: "4.8", status: "captured" });
  });

  it("never overwrites a value the buyer typed", () => {
    let draft = draftFromListing(sampleListing());
    draft = editField(draft, "rating", "3");
    draft = applySeller(draft, sampleSeller());
    expect(draft.fields.rating).toEqual({ value: "3", status: "edited" });
    expect(draft.fields.reviewCount.value).toBe("17");
  });

  it("leaves a field alone when the seller page did not show it", () => {
    const draft = applySeller(
      draftFromListing(sampleListing()),
      sampleSeller({ rating: { status: "not_found", value: null } }),
    );
    expect(draft.fields.rating).toEqual({ value: "", status: "not_found" });
  });
});

describe("editField and togglePhoto", () => {
  it("marks an edited field as edited", () => {
    const draft = editField(draftFromListing(sampleListing()), "title", "New title");
    expect(draft.fields.title).toEqual({
      value: "New title",
      status: "edited",
    });
  });

  it("allows at most ten photos", () => {
    const urls = manyPhotos(12);
    const draft = draftFromListing(sampleListing({ imageUrls: urls }));
    // The eleventh photo cannot be added while ten are selected.
    expect(togglePhoto(draft, urls[10] ?? "").photos[10]?.selected).toBe(false);
    // Removing one makes room for it.
    const swapped = togglePhoto(togglePhoto(draft, urls[0] ?? ""), urls[10] ?? "");
    expect(swapped.photos[0]?.selected).toBe(false);
    expect(swapped.photos[10]?.selected).toBe(true);
    expect(swapped.photos.filter((photo) => photo.selected)).toHaveLength(10);
  });
});

describe("parsePriceInput", () => {
  it.each([
    ["RM 1,250", 1250],
    ["1250.50", 1250.5],
    ["rm99", 99],
  ])("reads %s as %s", (text, expected) => {
    expect(parsePriceInput(text)).toBe(expected);
  });

  it.each([["Free"], ["RM 1,200 - RM 1,500"], [""], ["-5"]])("rejects %s", (text) => {
    expect(parsePriceInput(text)).toBeNull();
  });
});

describe("validateDraft", () => {
  it("accepts a complete draft", () => {
    expect(validateDraft(draftFromListing(sampleListing()))).toEqual({});
  });

  it("asks for what is missing", () => {
    const draft = draftFromListing(
      sampleListing({
        title: { status: "not_found", value: null },
        price: { status: "not_found", value: null },
        category: { status: "not_found", value: null },
        imageUrls: [],
      }),
    );
    expect(validateDraft(draft)).toMatchObject({
      title: "Enter the listing title.",
      price: "Enter a price, for example RM 1,250.",
      category: "Choose or type a category.",
      photos: "Select at least one photo.",
    });
  });

  it("blocks text over the API limits instead of cutting it", () => {
    const draft = draftFromListing(
      sampleListing({
        title: { status: "captured", value: "t".repeat(LIMITS.title + 1) },
        description: {
          status: "captured",
          value: "d".repeat(LIMITS.description + 1),
        },
      }),
    );
    const errors = validateDraft(draft);
    expect(errors.title).toBe("Use 500 characters or fewer.");
    expect(errors.description).toBe("Use 5000 characters or fewer.");
  });

  it("rejects a price that is not a single number", () => {
    const draft = editField(draftFromListing(sampleListing()), "price", "RM 1,200 - RM 1,500");
    expect(validateDraft(draft).price).toBe("Enter the price as a number, for example RM 1,250.");
  });

  it("checks optional seller fields only when they are filled in", () => {
    let draft = draftFromListing(sampleListing());
    expect(validateDraft(draft)).toEqual({});
    draft = editField(editField(draft, "rating", "7"), "reviewCount", "ten");
    expect(validateDraft(draft)).toMatchObject({
      rating: "Enter a rating from 0 to 5.",
      reviewCount: "Enter a whole number.",
    });
  });
});

describe("buildCaptureMeta", () => {
  it("reports each field's origin and the platform host", () => {
    let draft = draftFromListing(
      sampleListing({ description: { status: "not_found", value: null } }),
    );
    draft = editField(draft, "price", "1300");
    draft = applySeller(draft, sampleSeller({ rating: { status: "not_found", value: null } }));
    expect(buildCaptureMeta(draft)).toEqual({
      adapter_version: "1",
      platform_host: "www.carousell.com.my",
      fields: {
        title: "captured",
        description: "not_found",
        price: "edited",
        category: "captured",
        platform: "captured",
        images: "captured",
        account_age_days: "captured",
        rating: "not_found",
        review_count: "captured",
        active_listing_count: "captured",
      },
    });
  });

  it("marks the photos edited once the selection differs from the default", () => {
    const draft = togglePhoto(draftFromListing(sampleListing()), PHOTOS[0] ?? "");
    expect(buildCaptureMeta(draft).fields.images).toBe("edited");
  });

  it("marks the photos not found when the page had none", () => {
    const draft = draftFromListing(sampleListing({ imageUrls: [] }));
    expect(buildCaptureMeta(draft).fields.images).toBe("not_found");
  });

  it("never contains a URL", () => {
    expect(JSON.stringify(buildCaptureMeta(draftFromListing(sampleListing())))).not.toContain(
      "http",
    );
  });
});

describe("buildForm", () => {
  it("builds the multipart form the API expects", () => {
    const photo = new File([new Uint8Array([1, 2, 3])], "photo-1.jpg", {
      type: "image/jpeg",
    });
    const draft = applySeller(draftFromListing(sampleListing()), sampleSeller());
    const form = buildForm(draft, [photo]);

    expect(form.getAll("images")).toHaveLength(1);
    expect(form.get("platform")).toBe("carousell");
    expect(form.get("title")).toBe("Used laptop in good condition");
    expect(form.get("price")).toBe("1250");
    expect(form.get("category")).toBe("Laptops");
    expect(form.get("account_age_days")).toBe("1155");
    expect(form.get("rating")).toBe("4.8");
    expect(form.get("source")).toBe("extension");
    expect(JSON.parse(String(form.get("capture_meta")))).toMatchObject({
      platform_host: "www.carousell.com.my",
    });
  });

  it("sends empty strings for seller fields that were not found, so the API treats them as unknown", () => {
    const form = buildForm(draftFromListing(sampleListing()), []);
    expect(form.get("account_age_days")).toBe("");
    expect(form.get("active_listing_count")).toBe("");
  });
});
