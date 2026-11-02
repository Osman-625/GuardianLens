// Pins how API and network errors become something the buyer can act on.
// Two kinds of outcome exist: a problem with ONE FIELD (shown next to that field, with the buyer's
// input kept) and a problem with the whole check (shown as a calm failure screen with a retry).
// The buyer never sees a raw error, status code, or stack trace.
import { GuardianLensApiError } from "@guardianlens/shared";
import { describe, expect, it } from "vitest";
import { FAILED_MESSAGE, mapApiError } from "../../lib/panel/errors";

/** Builds the error the API client throws. */
function apiError(status: number, code: string, message: string, field: string | null = null) {
  return new GuardianLensApiError(status, { error: { code, message, field } });
}

describe("mapApiError", () => {
  it("puts a field error next to its field", () => {
    const error = apiError(
      422,
      "unsupported_language",
      "Chinese-dominant listings are outside this prototype's supported language scope.",
      "description",
    );
    expect(mapApiError(error)).toEqual({
      target: "review",
      fieldErrors: {
        description:
          "Chinese-dominant listings are outside this prototype's supported language scope.",
      },
    });
  });

  it("maps server field names to draft field names", () => {
    expect(
      mapApiError(apiError(422, "invalid_integer", "Enter a whole number.", "account_age_days")),
    ).toEqual({
      target: "review",
      fieldErrors: { accountAgeDays: "Enter a whole number." },
    });
  });

  it("maps any image field to the photos", () => {
    expect(
      mapApiError(apiError(422, "unsupported_image_type", "Use a JPEG.", "images[0]")),
    ).toEqual({
      target: "review",
      fieldErrors: { photos: "Use a JPEG." },
    });
  });

  it("says the service is not reachable", () => {
    const result = mapApiError(apiError(0, "network_unreachable", "x"));
    expect(result).toMatchObject({ target: "failure", kind: "unreachable" });
    expect(result.target === "failure" && result.message).toContain("not reachable");
  });

  it("explains rate limiting", () => {
    expect(mapApiError(apiError(429, "rate_limit_exceeded", "x"))).toMatchObject({
      target: "failure",
      kind: "rate_limited",
    });
  });

  it("falls back to a calm generic failure for anything else", () => {
    expect(mapApiError(apiError(500, "internal_error", "boom"))).toEqual({
      target: "failure",
      kind: "failed",
      message: FAILED_MESSAGE,
    });
    expect(mapApiError(new Error("random"))).toEqual({
      target: "failure",
      kind: "failed",
      message: FAILED_MESSAGE,
    });
    // A 422 without a field cannot be placed next to anything, so it is a whole-check failure.
    expect(mapApiError(apiError(422, "validation_error", "x"))).toMatchObject({
      target: "failure",
      kind: "failed",
    });
  });
});
