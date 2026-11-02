// Pins the result page's feedback form: a saved verdict shows the thank-you, and a failed request
// puts the form back with the buyer's choice kept (it must not stay on "Saving…", disabled,
// forever).
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import ResultPage from "../app/assess/[id]/page";
import { apiFetch } from "../lib/api";

vi.mock("next/navigation", () => ({ useParams: () => ({ id: "a1" }) }));
vi.mock("@/lib/useSessionClaim", () => ({ useSessionClaim: () => true }));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/api")>()),
  apiFetch: vi.fn(),
}));

// A finished result as the API returns it, with every field the page reads.
const result = {
  assessment_id: "a1",
  title: "Used laptop",
  score: 72,
  band: "moderate",
  signal_cards: [],
  missing_data_notices: [],
  suggested_checks: ["Compare the price."],
  disclaimer: "Supports your judgement.",
  model_bundle_label: "dev-stub-unvalidated",
  created_at: "2026-10-09T08:00:00Z",
  total_latency_ms: 12,
  development_stub: false,
};

afterEach(() => {
  vi.resetAllMocks();
});

/** Opens the feedback form on a loaded result and picks the first verdict. */
async function openFeedbackAndChoose() {
  const user = userEvent.setup();
  render(<ResultPage />);
  await user.click(await screen.findByRole("button", { name: "Give feedback" }));
  const [first] = screen.getAllByRole("radio");
  await user.click(first);
  return { user, first };
}

// The feedback form on the result page: the thank-you after a save, and a retry after a failure.
describe("result page feedback", () => {
  it("shows the thank-you once the verdict is saved", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce(result).mockResolvedValueOnce(undefined);
    const { user } = await openFeedbackAndChoose();
    await user.click(screen.getByRole("button", { name: "Submit feedback" }));
    expect(await screen.findByText("Feedback saved.")).toBeInTheDocument();
  });

  it("brings the form back with the choice kept when the request fails", async () => {
    vi.mocked(apiFetch)
      .mockResolvedValueOnce(result)
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(undefined);
    const { user, first } = await openFeedbackAndChoose();
    await user.click(screen.getByRole("button", { name: "Submit feedback" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be saved");
    const submit = screen.getByRole("button", { name: "Submit feedback" });
    expect(submit).toBeEnabled();
    expect(first).toBeChecked();

    // Trying again works, and the error goes away.
    await user.click(submit);
    expect(await screen.findByText("Feedback saved.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
