// Pins what the manual form does with an error from the API: an error on a field with its own
// message shows beside that field, and an error on a seller field (rating, counts) shows beside
// the submit button, where before it showed nowhere at all.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AssessPage from "../app/assess/page";
import { GuardianLensApiError, apiFetch } from "../lib/api";

const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => router }));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/api")>()),
  apiFetch: vi.fn(),
}));

beforeEach(() => {
  window.sessionStorage.clear();
});

afterEach(() => {
  vi.resetAllMocks();
});

/** Fills the required parts of the form and presses the submit button. */
async function fillAndSubmit() {
  const user = userEvent.setup();
  render(<AssessPage />);
  await user.upload(
    screen.getByLabelText("Choose listing photos"),
    new File([new Uint8Array([1])], "photo.jpg", { type: "image/jpeg" }),
  );
  await user.type(screen.getByLabelText("Title"), "Used laptop");
  await user.type(screen.getByLabelText("Description"), "Good condition.");
  await user.type(screen.getByLabelText("Price"), "1250");
  await user.type(screen.getByLabelText("Category"), "Electronics");
  await user.click(screen.getByRole("button", { name: "Check listing" }));
  return user;
}

/** An API refusal of the given field. */
const refusal = (code: string, message: string, field: string) =>
  new GuardianLensApiError(422, { error: { code, message, field } });

describe("manual form length limits", () => {
  it("shows a title over the limit in red and keeps the button off", async () => {
    const user = userEvent.setup();
    render(<AssessPage />);
    await user.upload(
      screen.getByLabelText("Choose listing photos"),
      new File([new Uint8Array([1])], "photo.jpg", { type: "image/jpeg" }),
    );
    await user.click(screen.getByLabelText("Title"));
    await user.paste("t".repeat(501));
    await user.type(screen.getByLabelText("Description"), "Good condition.");
    await user.type(screen.getByLabelText("Price"), "1250");
    await user.type(screen.getByLabelText("Category"), "Electronics");
    expect(screen.getByText("501/500")).toHaveClass("error-text");
    expect(screen.getByText("Use 500 characters or fewer.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check listing" })).toBeDisabled();
  });
});

describe("manual form errors from the API", () => {
  it.each([
    ["rating", "Enter a rating from 0 to 5.", "Rating: Enter a rating from 0 to 5."],
    ["review_count", "Enter 10,000,000 or less.", "Review count: Enter 10,000,000 or less."],
    ["account_age_days", "Enter a whole number.", "Account age in days: Enter a whole number."],
    [
      "active_listing_count",
      "Enter zero or a positive number.",
      "Active listing count: Enter zero or a positive number.",
    ],
  ])("shows a refused %s beside the submit button", async (field, message, shown) => {
    vi.mocked(apiFetch).mockRejectedValue(refusal("x", message, field));
    await fillAndSubmit();
    expect(await screen.findByRole("alert")).toHaveTextContent(shown);
  });

  it("shows a refused price beside the price field, once", async () => {
    vi.mocked(apiFetch).mockRejectedValue(
      refusal("invalid_price", "Enter a price of 10,000,000 or less.", "price"),
    );
    await fillAndSubmit();
    expect(await screen.findByText("Enter a price of 10,000,000 or less.")).toBeInTheDocument();
    expect(screen.getAllByText("Enter a price of 10,000,000 or less.")).toHaveLength(1);
  });

  it("says the API could not be reached only when the request never arrived", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new TypeError("Failed to fetch"));
    await fillAndSubmit();
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be reached");
  });

  it("shows an answer that is not the API's own as that answer, not as 'could not be reached'", async () => {
    vi.mocked(apiFetch).mockRejectedValue(
      new GuardianLensApiError(502, {
        error: {
          code: "bad_response",
          message: "The service returned an unexpected response.",
          field: null,
        },
      }),
    );
    await fillAndSubmit();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The service returned an unexpected response.");
    expect(alert).not.toHaveTextContent("could not be reached");
  });

  it("clears the message when the buyer edits the field it names", async () => {
    vi.mocked(apiFetch).mockRejectedValue(
      refusal("invalid_rating", "Enter a rating from 0 to 5.", "rating"),
    );
    const user = await fillAndSubmit();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Rating out of 5"), "4");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
