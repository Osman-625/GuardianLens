// Pins what the buyer sees and can do in each side panel view. The views are pure components
// driven by props, so each test renders one view and checks its text, its controls, and the
// callbacks. The design rules protected (docs/spec/04_Design_Brief_UI_UX.md):
//   - every captured field says in WORDS whether it was captured, edited, or not found;
//   - missing seller details are "unknown, not suspicious", never a blocker;
//   - the submit button explains what is missing instead of failing silently, and over-limit text
//     is an error, not cut off;
//   - the disclaimer sits INSIDE the score region, and the development-stub warning is shown;
//   - category is free text, with a note when it is not one of the trained categories.
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { UNSEEN_CATEGORY_NOTE, type SignalCard } from "@guardianlens/shared";
import { CheckingView } from "@/entrypoints/sidepanel/views/CheckingView";
import { FailureView } from "@/entrypoints/sidepanel/views/FailureView";
import { IdleView } from "@/entrypoints/sidepanel/views/IdleView";
import { ResultView } from "@/entrypoints/sidepanel/views/ResultView";
import { ReviewView, type ReviewViewProps } from "@/entrypoints/sidepanel/views/ReviewView";
import {
  applySeller,
  draftFromListing,
  editField,
  togglePhoto,
  type Draft,
} from "@/lib/panel/draft";
import { PHOTOS, manyPhotos, sampleListing, sampleResult, sampleSeller } from "../helpers/samples";

/** Renders the Review view with working spies; `overrides` and `draft` change only what a test needs. */
function renderReview(
  overrides: Partial<ReviewViewProps> = {},
  draft: Draft = draftFromListing(sampleListing()),
) {
  const props: ReviewViewProps = {
    draft,
    fieldErrors: {},
    notice: null,
    submitting: false,
    onEdit: vi.fn(),
    onTogglePhoto: vi.fn(),
    onSubmit: vi.fn(),
    onOpenSeller: vi.fn(),
    onCapture: vi.fn(),
    onOpenSite: vi.fn(),
    ...overrides,
  };
  render(<ReviewView {...props} />);
  return props;
}

/** The `.field` container around a labelled control, so a test can look at just that field. */
function fieldOf(label: string): HTMLElement {
  return screen.getByLabelText(label).closest(".field") as HTMLElement;
}

// IdleView: what the panel says when nothing is captured, and its two ways out.
describe("IdleView", () => {
  it("has a level-one heading, like every other view (screen readers and axe expect one)", () => {
    render(<IdleView reason="no_capture" onOpenSite={vi.fn()} onCapture={vi.fn()} />);
    expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
  });

  it("tells the buyer what to do first", () => {
    render(<IdleView reason="no_capture" onOpenSite={vi.fn()} onCapture={vi.fn()} />);
    expect(
      screen.getByText("Open a Mudah.my or Carousell listing, then click the GuardianLens icon."),
    ).toBeInTheDocument();
  });

  it("explains a blocked page in plain words", () => {
    render(
      <IdleView reason="blocked" pageState="captcha" onOpenSite={vi.fn()} onCapture={vi.fn()} />,
    );
    expect(
      screen.getByText(
        "The site is asking for a security check. Complete it, then click the icon again.",
      ),
    ).toBeInTheDocument();
  });

  it("explains how to add seller details when there is no listing yet", () => {
    render(<IdleView reason="no_draft_for_seller" onOpenSite={vi.fn()} onCapture={vi.fn()} />);
    expect(screen.getByText(/Open the listing first/)).toBeInTheDocument();
  });

  it("offers the website form and the session history", async () => {
    const onOpenSite = vi.fn();
    render(<IdleView reason="no_capture" onOpenSite={onOpenSite} onCapture={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Use the website form" }));
    await userEvent.click(screen.getByRole("button", { name: "This session" }));
    expect(onOpenSite).toHaveBeenNthCalledWith(1, "/assess");
    expect(onOpenSite).toHaveBeenNthCalledWith(2, "/history");
  });
});

// ReviewView: the captured fields, how each is labelled, and what the submit button waits for.
describe("ReviewView", () => {
  it("says the data was captured when the buyer clicked, and names the marketplace", () => {
    renderReview();
    expect(screen.getByText(/Read from this page/)).toBeInTheDocument();
    expect(screen.getByText("Carousell")).toBeInTheDocument();
  });

  it("says when the category was matched to a trained one, and from what", () => {
    renderReview(
      {},
      draftFromListing(
        sampleListing({ category: { status: "captured", value: "Mobile Phones & Gadgets" } }),
      ),
    );
    expect(
      screen.getByText(
        'Matched from "Mobile Phones & Gadgets" on the page. Change it if it is wrong.',
      ),
    ).toBeInTheDocument();
  });

  it("shows no match note when the category is the page's own wording", () => {
    renderReview(
      {},
      draftFromListing(
        sampleListing({ category: { status: "captured", value: "Aquarium supplies" } }),
      ),
    );
    expect(screen.queryByText(/Matched from/)).not.toBeInTheDocument();
  });

  it("labels each field in words: captured, edited, not found", () => {
    const missingPrice = draftFromListing(
      sampleListing({ price: { status: "not_found", value: null } }),
    );
    renderReview({}, editField(missingPrice, "title", "My own title"));
    // A captured value needs no line of its own: the banner already says the page was read.
    expect(within(fieldOf("Description")).queryByText("Captured")).not.toBeInTheDocument();
    expect(within(fieldOf("Title")).getByText("Edited by you")).toBeInTheDocument();
    expect(within(fieldOf("Price")).getByText("Not found. Enter it yourself.")).toBeInTheDocument();
  });

  it("reports an edit through onEdit", async () => {
    const props = renderReview(
      {},
      draftFromListing(sampleListing({ price: { status: "not_found", value: null } })),
    );
    await userEvent.type(screen.getByLabelText("Price"), "1");
    expect(props.onEdit).toHaveBeenCalledWith("price", "1");
  });

  it("shows how many photos are included, out of the limit of ten", () => {
    renderReview();
    expect(screen.getByText("4 of 10 photos included.")).toBeInTheDocument();
  });

  it("lets the buyer swap a photo that did not fit under the limit", async () => {
    // 12 candidate photos: the first ten are included, the last two are spare.
    const urls = manyPhotos(12);
    const props = renderReview({}, draftFromListing(sampleListing({ imageUrls: urls })));
    expect(screen.getByText("10 of 10 photos included.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Photo 11: not included" }));
    expect(props.onTogglePhoto).toHaveBeenCalledWith(urls[10]);
  });

  it("accepts a category outside the trained list and notes how the price is compared", () => {
    const odd = editField(draftFromListing(sampleListing()), "category", "Aquarium supplies");
    renderReview({}, odd);
    expect(screen.getByLabelText("Category")).toHaveValue("Aquarium supplies");
    expect(screen.getByText(UNSEEN_CATEGORY_NOTE)).toBeInTheDocument();
  });

  it("treats missing seller details as unknown, not as a blocker", () => {
    renderReview();
    expect(
      screen.getByText(/Missing seller details are treated as unknown, not as suspicious/),
    ).toBeInTheDocument();
    // An empty optional field says nothing of its own; it points at the group note.
    expect(within(fieldOf("Rating out of 5")).queryByText("Not found")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Rating out of 5")).toHaveAccessibleDescription(
      /Missing seller details are treated as unknown, not as suspicious/,
    );
    expect(screen.getByRole("button", { name: "Check listing" })).toBeEnabled();
  });

  it("opens the seller group and asks for the seller details while none are captured", () => {
    renderReview();
    const group = screen
      .getByText("Seller details (recommended)")
      .closest("details") as HTMLDetailsElement;
    expect(group.open).toBe(true);
    // The prompt says why the details matter and how to get them, and it does not block the check.
    expect(screen.getByText(/No seller details yet/)).toBeInTheDocument();
    expect(screen.getByText(/treated as unknown/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check listing" })).toBeEnabled();
  });

  it("drops the seller prompt once seller details are captured", () => {
    renderReview({}, applySeller(draftFromListing(sampleListing()), sampleSeller()));
    expect(screen.queryByText(/No seller details yet/)).not.toBeInTheDocument();
    expect(within(fieldOf("Rating out of 5")).queryByText("Captured")).not.toBeInTheDocument();
  });

  it("explains what is missing instead of failing silently", () => {
    renderReview(
      {},
      draftFromListing(sampleListing({ price: { status: "not_found", value: null } })),
    );
    expect(screen.getByRole("button", { name: "Check listing" })).toBeDisabled();
    expect(screen.getByText(/To continue, add or fix a valid price/)).toBeInTheDocument();
  });

  it("blocks a description over the limit with a clear message", () => {
    const long = draftFromListing(
      sampleListing({
        description: { status: "captured", value: "d".repeat(6000) },
      }),
    );
    renderReview({}, long);
    expect(screen.getByText("Use 5000 characters or fewer.")).toBeInTheDocument();
    expect(screen.getByText("6000/5000")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check listing" })).toBeDisabled();
  });

  it("shows an error the server returned next to its field", () => {
    renderReview({
      fieldErrors: {
        description:
          "Chinese-dominant listings are outside this prototype's supported language scope.",
      },
    });
    expect(
      within(fieldOf("Description")).getByText(/outside this prototype's supported language scope/),
    ).toBeInTheDocument();
  });

  it("announces a field error to screen readers, not only through red text", () => {
    renderReview({ fieldErrors: { description: "Unsupported language." } });
    expect(within(fieldOf("Description")).getByRole("alert")).toHaveTextContent(
      "Unsupported language.",
    );
  });

  it("shows the retention notice beside the submit button, in the same group", () => {
    renderReview();
    const bar = screen
      .getByRole("button", { name: "Check listing" })
      .closest(".submit-bar") as HTMLElement;
    expect(
      within(bar).getByText(/Contact details are removed from your text before it is stored/),
    ).toBeInTheDocument();
  });

  // When the page gives the panel nothing usable (for example no photo it may download), the only
  // way forward is the website form. Review must offer it, not leave the buyer at a dead end.
  it("always offers the website form as a way out", async () => {
    const props = renderReview();
    await userEvent.click(screen.getByRole("button", { name: "Use the website form" }));
    expect(props.onOpenSite).toHaveBeenCalledWith("/assess");
  });

  it("offers the website form when no photo is selected", async () => {
    const noPhotos = PHOTOS.reduce(
      (draft, url) => togglePhoto(draft, url),
      draftFromListing(sampleListing()),
    );
    const props = renderReview({}, noPhotos);
    expect(screen.getByText("Select at least one photo.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Use the website form" }));
    expect(props.onOpenSite).toHaveBeenCalledWith("/assess");
  });

  it("submits once when the draft is valid", async () => {
    const props = renderReview();
    await userEvent.click(screen.getByRole("button", { name: "Check listing" }));
    expect(props.onSubmit).toHaveBeenCalledTimes(1);
  });

  it("disables the button while a check is running", () => {
    renderReview({ submitting: true });
    expect(screen.getByRole("button", { name: "Checking…" })).toBeDisabled();
  });

  it("shows a notice above the form", () => {
    renderReview({
      notice: "Seller details added. Press Check listing to include them.",
    });
    expect(
      screen.getByText("Seller details added. Press Check listing to include them."),
    ).toBeInTheDocument();
  });

  // The second capture: the listing page linked to the seller's profile, so the panel offers it.
  describe("the seller page step", () => {
    const SELLER_PAGE = "https://www.carousell.com.my/u/someone/";

    it("says Mudah does not show a rating or reviews, instead of 'not found'", () => {
      renderReview(
        {},
        draftFromListing(sampleListing({ platform: "mudah", platformHost: "www.mudah.my" })),
      );
      expect(screen.getAllByText(/Mudah does not show this/)).toHaveLength(2);
      expect(screen.queryAllByText(/^Not found$/)).toHaveLength(0);
    });

    it("has a 'Capture the seller's page' button", async () => {
      const props = renderReview();
      await userEvent.click(screen.getByRole("button", { name: "Capture the seller's page" }));
      expect(props.onCapture).toHaveBeenCalledTimes(1);
    });

    it("offers 'Open seller page' when the listing page linked to the seller", async () => {
      const props = renderReview({}, draftFromListing(sampleListing({ sellerUrl: SELLER_PAGE })));
      await userEvent.click(screen.getByRole("button", { name: "Open seller page" }));
      expect(props.onOpenSeller).toHaveBeenCalledTimes(1);
      expect(screen.getByText(/Click the GuardianLens icon there/)).toBeInTheDocument();
      // The instruction is given once: the button's note, not the notice above it.
      expect(screen.queryByText(/Open the seller's page and click/)).not.toBeInTheDocument();
    });

    it("offers no button when no seller link was found (the instructions still show)", () => {
      renderReview();
      expect(screen.queryByRole("button", { name: "Open seller page" })).not.toBeInTheDocument();
      expect(
        screen.getByText(/Open the seller's page and click the GuardianLens icon/),
      ).toBeInTheDocument();
    });

    it("keeps offering the button after some seller details were captured", () => {
      // Carousell's listing count only comes from the profile page, so the step is still useful.
      const draft = applySeller(
        draftFromListing(sampleListing({ sellerUrl: SELLER_PAGE })),
        sampleSeller({ activeListingCount: { status: "not_found", value: null } }),
      );
      renderReview({}, draft);
      expect(screen.getByRole("button", { name: "Open seller page" })).toBeInTheDocument();
    });
  });

  it("requires at least one photo", () => {
    // Deselect every photo of the sample listing.
    const noPhotos = PHOTOS.reduce(
      (draft, url) => togglePhoto(draft, url),
      draftFromListing(sampleListing()),
    );
    renderReview({}, noPhotos);
    expect(screen.getByText("Select at least one photo.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check listing" })).toBeDisabled();
  });
});

// CheckingView: the five stages, the slow-wait line and Cancel.
describe("CheckingView", () => {
  it("lists the five stages with no percentages", () => {
    render(<CheckingView stage="textual" slow={false} onCancel={vi.fn()} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("says so honestly when the check is slow", () => {
    render(<CheckingView stage="visual" slow={true} onCancel={vi.fn()} />);
    expect(
      screen.getByText("This is taking longer than usual. It is still working."),
    ).toBeInTheDocument();
  });

  it("can be cancelled", async () => {
    const onCancel = vi.fn();
    render(<CheckingView stage="visual" slow={false} onCancel={onCancel} />);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});

// ResultView: the score region, the three cards, notices, feedback and the exits.
describe("ResultView", () => {
  /** Renders the result view with spies. */
  function renderResult(overrides: Partial<Parameters<typeof ResultView>[0]> = {}) {
    const props = {
      result: sampleResult(),
      feedback: "idle" as const,
      notice: null,
      onSeeFull: vi.fn(),
      onFeedback: vi.fn(),
      onCheckAnother: vi.fn(),
      ...overrides,
    };
    render(<ResultView {...props} />);
    return props;
  }

  it("keeps the disclaimer inside the score region and shows the stub warning", () => {
    renderResult();
    const region = screen.getByRole("region", {
      name: "Score 58 out of 100, moderate risk",
    });
    expect(
      within(region).getByText(
        "Decision support only. Verify the seller independently before paying.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Test mode");
  });

  it("shows only the single most protective check; the rest live on the website", () => {
    renderResult();
    expect(
      screen.getByText(
        "Verify account or bank details independently using the official Semak Mule service.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Compare the price with similar listings on the same marketplace."),
    ).not.toBeInTheDocument();
  });

  it("opens the full explanation, or one signal's section", async () => {
    const props = renderResult();
    await userEvent.click(screen.getByRole("button", { name: "See full explanation" }));
    expect(props.onSeeFull).toHaveBeenLastCalledWith();
    await userEvent.click(screen.getByRole("link", { name: /Photos/ }));
    expect(props.onSeeFull).toHaveBeenLastCalledWith("visual");
  });

  it("names signals that could not be computed as unknown", () => {
    const base = sampleResult();
    // Built in full (not spread from an indexed card) so it stays a complete SignalCard.
    const unavailable: SignalCard = {
      signal: "behavioural",
      probability: null,
      available: false,
      status_word: "limited information",
      summary: "Not enough information. Treated as unknown, not as suspicious.",
      reasons: [],
      scope_note: null,
    };
    const cards = base.signal_cards.filter((card) => card.signal !== "behavioural");
    renderResult({
      result: sampleResult({
        signal_cards: [...cards, unavailable],
        missing_data_notices: [unavailable.summary],
      }),
    });
    expect(
      screen.getAllByText("Not enough information. Treated as unknown, not as suspicious.").length,
    ).toBeGreaterThan(0);
  });

  it("tells the buyer how to include seller details when the behavioural signal is unknown", () => {
    const base = sampleResult();
    const behavioural: SignalCard = {
      signal: "behavioural",
      probability: null,
      available: false,
      status_word: "limited information",
      summary: "Not enough information. Treated as unknown, not as suspicious.",
      reasons: [],
      scope_note: null,
    };
    const cards = base.signal_cards.filter((card) => card.signal !== "behavioural");
    renderResult({ result: sampleResult({ signal_cards: [...cards, behavioural] }) });
    expect(screen.getByText(/Seller details were not included/)).toBeInTheDocument();
    expect(screen.getByText(/click the GuardianLens icon there/)).toBeInTheDocument();
  });

  it("does not mention seller details when the behavioural signal was computed", () => {
    renderResult();
    expect(screen.queryByText(/Seller details were not included/)).not.toBeInTheDocument();
  });

  it("collects feedback with one tap, and then confirms", async () => {
    const props = renderResult();
    await userEvent.click(screen.getByRole("button", { name: "Helpful" }));
    expect(props.onFeedback).toHaveBeenCalledWith("helpful");
  });

  it("confirms saved feedback and removes the choices", () => {
    renderResult({ feedback: "saved" });
    expect(screen.getByText("Feedback saved.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Helpful" })).not.toBeInTheDocument();
  });

  it("lets the buyer check another listing", async () => {
    const props = renderResult();
    await userEvent.click(screen.getByRole("button", { name: "Check another listing" }));
    expect(props.onCheckAnother).toHaveBeenCalledTimes(1);
  });

  it("mentions photos that were left out", () => {
    renderResult({
      notice: "1 photo could not be read and was left out of this check.",
    });
    expect(
      screen.getByText("1 photo could not be read and was left out of this check."),
    ).toBeInTheDocument();
  });
});

// FailureView: the message, Try again, and the website form.
describe("FailureView", () => {
  it("shows the message as an alert and offers a retry", async () => {
    const onRetry = vi.fn();
    render(
      <FailureView
        kind="unreachable"
        message="Can't reach the GuardianLens service. Is the local server running?"
        onRetry={onRetry}
        onOpenSite={vi.fn()}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Can't reach the GuardianLens service");
    expect(screen.getByText(/Ask the researcher/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("offers the website form as another way in", async () => {
    const onOpenSite = vi.fn();
    render(<FailureView kind="failed" message="x" onRetry={vi.fn()} onOpenSite={onOpenSite} />);
    await userEvent.click(screen.getByRole("button", { name: "Use the website form" }));
    expect(onOpenSite).toHaveBeenCalledWith("/assess");
  });
});
