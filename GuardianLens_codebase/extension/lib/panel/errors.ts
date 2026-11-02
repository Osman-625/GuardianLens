// Turns API and network errors into something the buyer can act on.
//
// An error is one of two kinds:
//   - a problem with ONE FIELD ("target: review"): shown next to that field, with all of the
//     buyer's input kept, and a stay in the Review step;
//   - a problem with the WHOLE check ("target: failure"): a calm failure screen with a retry.
// The buyer never sees a raw error, a status code, or a stack trace.
import { GuardianLensApiError } from "@guardianlens/shared";
import type { DraftErrors } from "./draft";

/** Why the whole check failed. */
export type FailureKind = "unreachable" | "rate_limited" | "failed";

/** Where an error is shown and what it says. */
export type MappedError =
  | { target: "review"; fieldErrors: DraftErrors }
  | { target: "failure"; kind: FailureKind; message: string };

/** Shown when none of the selected photos could be prepared. */
export const NO_PHOTOS_MESSAGE =
  "None of the selected photos could be read. Use the website form to upload photos yourself.";

/** The calm generic failure message. The draft is kept, so the buyer can simply retry. */
export const FAILED_MESSAGE =
  "Something stopped the check. Your details are saved, so you can try again.";

// The API names form fields in snake_case; the draft uses camelCase.
const FIELD_KEYS: Record<string, keyof DraftErrors> = {
  title: "title",
  description: "description",
  price: "price",
  category: "category",
  rating: "rating",
  account_age_days: "accountAgeDays",
  review_count: "reviewCount",
  active_listing_count: "activeListingCount",
};

/**
 * Maps any error thrown while submitting or polling to a buyer-facing outcome.
 * @param error Whatever was thrown (usually a GuardianLensApiError).
 */
export function mapApiError(error: unknown): MappedError {
  if (error instanceof GuardianLensApiError) {
    if (error.code === "network_unreachable") {
      return {
        target: "failure",
        kind: "unreachable",
        message: "The GuardianLens service is not reachable right now.",
      };
    }
    if (error.status === 429) {
      return {
        target: "failure",
        kind: "rate_limited",
        message: "Too many checks were sent in a short time. Wait a minute and try again.",
      };
    }
    if (error.status === 422 && error.field) {
      // Every uploaded image is reported as images[<n>]; they all belong to the photo picker.
      const key = error.field.startsWith("images") ? "photos" : FIELD_KEYS[error.field];
      if (key) return { target: "review", fieldErrors: { [key]: error.message } };
    }
  }
  return { target: "failure", kind: "failed", message: FAILED_MESSAGE };
}
