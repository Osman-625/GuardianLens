// The buyer's editable draft of a listing, and the pure functions that build, edit, validate, and
// submit it.
//
// A draft starts from what the capture script read and then belongs to the buyer: every field
// remembers whether it was "captured" from the page, "edited" by the buyer, or "not_found".
// That status is shown next to each field in the Review step and is reported (as statuses only,
// never as page content) in the capture metadata sent with the submission.
//
// Design rules kept here:
//   - nothing is guessed: a value the page did not show stays empty until the buyer provides it;
//   - nothing is silently shortened: text over the API limits is a validation error, not cut off;
//   - all functions are pure (they return a new draft), so they are easy to test.
import {
  LIMITS,
  resolveCategory,
  type CaptureFieldStatus,
  type CaptureMetaPayload,
  type Platform,
  type PlatformHost,
} from "@guardianlens/shared";
import type { CapturedListing, CapturedSeller } from "../capture/types";
import { parsePriceValue } from "../capture/values";

/** Where a field's value came from. */
export type FieldStatus = CaptureFieldStatus;

/** One editable field: its text and where it came from. */
export interface DraftField {
  value: string;
  status: FieldStatus;
}

/** The fields the buyer can see and edit. The last four are the optional seller details. */
export type DraftFieldKey =
  | "title"
  | "description"
  | "price"
  | "category"
  | "accountAgeDays"
  | "rating"
  | "reviewCount"
  | "activeListingCount";

/** A candidate photo and whether it is included in the check. */
export interface DraftPhoto {
  url: string;
  selected: boolean;
}

/** The whole draft. */
export interface Draft {
  platform: Platform;
  platformHost: PlatformHost;
  adapterVersion: string;
  fields: Record<DraftFieldKey, DraftField>;
  photos: DraftPhoto[];
  /** The photos selected when the page was captured; used to tell whether the buyer changed them. */
  defaultPhotoUrls: string[];
  /** The seller's profile page found on the listing page, for "Open seller page". Never submitted. */
  sellerUrl: string | null;
  /** The category exactly as the page showed it, so Review can say when it was matched to another. */
  pageCategory?: string | null;
}

/** Validation errors by field (plus "photos"). An empty object means the draft can be submitted. */
export type DraftErrors = Partial<Record<DraftFieldKey | "photos", string>>;

// The API's limits live in shared/ so the website form uses the same numbers. Text over a limit is
// reported, never cut.
export { LIMITS };

/** A fresh "not found" field (a function so no two fields share one object). */
const notFound = (): DraftField => ({ value: "", status: "not_found" });

/** A captured field, or a not-found field when the page showed nothing. */
function fromCapture(value: string | null): DraftField {
  return value === null ? notFound() : { value, status: "captured" };
}

/**
 * Starts a draft from a listing capture. The photos are selected in order up to the limit (10),
 * the platform's category text is mapped to a trained category where an obvious match exists, and
 * all seller fields start as "not found" (they come from the seller page, if the buyer adds it).
 */
export function draftFromListing(listing: CapturedListing): Draft {
  const photos = listing.imageUrls.map((url, index) => ({
    url,
    selected: index < LIMITS.photos,
  }));
  return {
    platform: listing.platform,
    platformHost: listing.platformHost,
    adapterVersion: listing.adapterVersion,
    fields: {
      title: fromCapture(listing.title.value),
      description: fromCapture(listing.description.value),
      price: fromCapture(listing.price.value === null ? null : String(listing.price.value)),
      category: fromCapture(
        listing.category.value === null ? null : resolveCategory(listing.category.value),
      ),
      accountAgeDays: notFound(),
      rating: notFound(),
      reviewCount: notFound(),
      activeListingCount: notFound(),
    },
    photos,
    defaultPhotoUrls: photos.filter((photo) => photo.selected).map((photo) => photo.url),
    sellerUrl: listing.sellerUrl,
    pageCategory: listing.category.value,
  };
}

// Which draft field each captured seller value fills.
const SELLER_FIELDS: ReadonlyArray<readonly [DraftFieldKey, keyof CapturedSeller]> = [
  ["accountAgeDays", "accountAgeDays"],
  ["rating", "rating"],
  ["reviewCount", "reviewCount"],
  ["activeListingCount", "activeListingCount"],
];

/**
 * Adds values read from the seller's page. A value the buyer already typed is never
 * overwritten, and a value the seller page did not show leaves the field unchanged.
 */
export function applySeller(draft: Draft, seller: CapturedSeller): Draft {
  const fields = { ...draft.fields };
  for (const [key, source] of SELLER_FIELDS) {
    const captured = seller[source];
    if (fields[key].status === "edited" || captured.value === null) continue;
    fields[key] = { value: String(captured.value), status: "captured" };
  }
  return { ...draft, fields };
}

/** Sets a field to what the buyer typed and marks it as edited. */
export function editField(draft: Draft, key: DraftFieldKey, value: string): Draft {
  return {
    ...draft,
    fields: { ...draft.fields, [key]: { value, status: "edited" } },
  };
}

/** Includes or excludes a photo. Adding is refused while ten photos are already selected. */
export function togglePhoto(draft: Draft, url: string): Draft {
  const selectedCount = draft.photos.filter((photo) => photo.selected).length;
  const photos = draft.photos.map((photo) => {
    if (photo.url !== url) return photo;
    if (!photo.selected && selectedCount >= LIMITS.photos) return photo;
    return { ...photo, selected: !photo.selected };
  });
  return { ...draft, photos };
}

/**
 * Reads a price the buyer typed: "RM 1,250", "1250.50", "rm99". Anything that is not exactly one
 * non-negative number (a range, a word, an empty field) returns null.
 */
export function parsePriceInput(text: string): number | null {
  return parsePriceValue(text.replace(/^\s*(?:RM|MYR)\s*/i, ""));
}

/** An error message for an optional seller field, or null when it is empty or valid. */
function sellerError(key: DraftFieldKey, value: string): string | null {
  const text = value.trim();
  if (text === "") return null;
  if (key === "rating") {
    const rating = Number(text);
    return Number.isFinite(rating) && rating >= 0 && rating <= 5
      ? null
      : "Enter a rating from 0 to 5.";
  }
  const message =
    key === "accountAgeDays" ? "Enter a whole number of days." : "Enter a whole number.";
  return /^\d+$/.test(text) ? null : message;
}

/**
 * Checks the draft against what the API will accept. Required: title, description, a single
 * price, a category, and at least one selected photo. Optional seller fields are checked only
 * when filled. Text over a limit is an error; it is never shortened to fit.
 */
export function validateDraft(draft: Draft): DraftErrors {
  const errors: DraftErrors = {};
  const { fields } = draft;

  const title = fields.title.value.trim();
  if (title === "") errors.title = "Enter the listing title.";
  else if (title.length > LIMITS.title) errors.title = `Use ${LIMITS.title} characters or fewer.`;

  const description = fields.description.value.trim();
  if (description === "") errors.description = "Enter the listing description.";
  else if (description.length > LIMITS.description) {
    errors.description = `Use ${LIMITS.description} characters or fewer.`;
  }

  const price = fields.price.value.trim();
  if (price === "") errors.price = "Enter a price, for example RM 1,250.";
  else if (parsePriceInput(price) === null)
    errors.price = "Enter the price as a number, for example RM 1,250.";

  const category = fields.category.value.trim();
  if (category === "") errors.category = "Choose or type a category.";
  else if (category.length > LIMITS.category)
    errors.category = `Use ${LIMITS.category} characters or fewer.`;

  if (!draft.photos.some((photo) => photo.selected)) errors.photos = "Select at least one photo.";

  for (const key of ["accountAgeDays", "rating", "reviewCount", "activeListingCount"] as const) {
    const message = sellerError(key, fields[key].value);
    if (message) errors[key] = message;
  }
  return errors;
}

/** Whether the selected photos are the ones captured, were changed, or the page had none. */
function imagesStatus(draft: Draft): CaptureFieldStatus {
  if (draft.photos.length === 0) return "not_found";
  const selected = draft.photos.filter((photo) => photo.selected).map((photo) => photo.url);
  const unchanged =
    selected.length === draft.defaultPhotoUrls.length &&
    selected.every((url, index) => url === draft.defaultPhotoUrls[index]);
  return unchanged ? "captured" : "edited";
}

/**
 * The capture metadata sent with the submission: the adapter version, the platform host, and
 * each field's origin. It holds statuses only. It never contains page text or a URL.
 */
export function buildCaptureMeta(draft: Draft): CaptureMetaPayload {
  const { fields } = draft;
  return {
    adapter_version: draft.adapterVersion,
    platform_host: draft.platformHost,
    fields: {
      title: fields.title.status,
      description: fields.description.status,
      price: fields.price.status,
      // shortcut: a category matched to a trained one (see resolveCategory) is still reported as
      // "captured"; the API has no "matched" status, so telling them apart needs a schema change.
      category: fields.category.status,
      platform: "captured",
      images: imagesStatus(draft),
      account_age_days: fields.accountAgeDays.status,
      rating: fields.rating.status,
      review_count: fields.reviewCount.status,
      active_listing_count: fields.activeListingCount.status,
    },
  };
}

/**
 * Builds the multipart form for POST /api/v1/assess. Seller fields that were not found are sent
 * as empty strings, which the API stores as "unknown" (never as zero or as suspicious).
 * @param draft A draft that already passed validateDraft.
 * @param photos The prepared photo files (at most ten, each within the size limit).
 */
export function buildForm(draft: Draft, photos: File[]): FormData {
  const form = new FormData();
  for (const photo of photos) form.append("images", photo);
  const { fields } = draft;
  const price = parsePriceInput(fields.price.value);
  form.append("platform", draft.platform);
  form.append("title", fields.title.value.trim());
  form.append("description", fields.description.value.trim());
  form.append("price", price === null ? fields.price.value : String(price));
  form.append("category", fields.category.value.trim());
  form.append("account_age_days", fields.accountAgeDays.value.trim());
  form.append("rating", fields.rating.value.trim());
  form.append("review_count", fields.reviewCount.value.trim());
  form.append("active_listing_count", fields.activeListingCount.value.trim());
  form.append("source", "extension");
  form.append("capture_meta", JSON.stringify(buildCaptureMeta(draft)));
  return form;
}
