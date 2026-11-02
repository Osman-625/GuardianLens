// Pins that the website shows no invented data: the landing page has no example score (every
// number must come from a real check), and the explanation page does not print the empty "model
// check" label for a signal that was computed.
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ExplanationPage from "../app/assess/[id]/explanation/page";
import HomePage from "../app/page";
import { apiFetch } from "../lib/api";

vi.mock("next/navigation", () => ({ useParams: () => ({ id: "a1" }) }));
vi.mock("@/lib/useSessionClaim", () => ({ useSessionClaim: () => true }));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/api")>()),
  apiFetch: vi.fn(),
}));

afterEach(() => {
  vi.resetAllMocks();
});

describe("landing page", () => {
  it("shows no example score and offers the extension download once", () => {
    vi.mocked(apiFetch).mockResolvedValue({
      status: "ok",
      stub_mode: false,
      inference_mode: "trained",
    });
    const { container } = render(<HomePage />);
    expect(container.querySelector(".score-dial, .score-region")).toBeNull();
    expect(screen.queryByText(/illustrative/i)).not.toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /extension/i }).filter(isDownload)).toHaveLength(1);
  });
});

/** True for a link that downloads the extension zip. */
const isDownload = (link: HTMLElement) => link.hasAttribute("download");

describe("explanation page", () => {
  it("prints a status word only for a signal that could not be computed", async () => {
    const card = (signal: string, available: boolean, status_word: string, summary: string) => ({
      signal,
      probability: available ? 0.3 : null,
      available,
      status_word,
      summary,
      reasons: [],
      scope_note: null,
    });
    vi.mocked(apiFetch).mockResolvedValue({
      assessment_id: "a1",
      title: "Used laptop",
      score: 20,
      band: "moderate",
      signal_cards: [
        card("visual", true, "model check", "Analysed using the visual model."),
        card("textual", true, "model check", "Analysed using the text model."),
        card("behavioural", false, "limited information", "Not enough information."),
      ],
      missing_data_notices: [],
      suggested_checks: ["Compare the price."],
      disclaimer: "Supports your judgement.",
      model_bundle_label: "run",
      created_at: "2026-10-09T08:00:00Z",
      total_latency_ms: 12,
      development_stub: false,
    });
    render(<ExplanationPage />);
    expect(await screen.findByText("Analysed using the visual model.")).toBeInTheDocument();
    expect(screen.queryByText(/model check/i)).not.toBeInTheDocument();
    expect(screen.getByText(/limited information/i)).toBeInTheDocument();
  });
});
