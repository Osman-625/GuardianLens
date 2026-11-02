// Pins the shared presentational components used by both the website and the side panel.
// The design rules these tests protect (docs/spec/04_Design_Brief_UI_UX.md, section 1):
//  - risk is shown as text + number + icon, never colour alone, and every band has its OWN icon
//    shape (tick circle, alert triangle, alert octagon) so colour-blind readers can tell them apart;
//  - the score is an integer, and the disclaimer lives INSIDE the score region;
//  - an unavailable signal is shown as unknown (dashed card), never as safe or suspicious;
//  - the category field accepts any text and only adds a note for untrained categories;
//  - icons are decorative SVG (hidden from screen readers), never emoji or text glyphs.
import { useState } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  BandChip,
  CategoryField,
  DevBanner,
  Icon,
  ScoreRegion,
  SignalCardView,
  StageList,
} from "../src";
import { UNSEEN_CATEGORY_NOTE } from "../src/copy";
import type { SignalCard } from "../src/types";

/** A signal card with sensible defaults; tests override only what they care about. */
function card(overrides: Partial<SignalCard> = {}): SignalCard {
  return {
    signal: "visual",
    probability: 0.4,
    available: true,
    status_word: "clear",
    summary: "No strong warning signs in the photos.",
    reasons: [],
    scope_note: null,
    ...overrides,
  };
}

describe("Icon", () => {
  it("is decorative: hidden from screen readers and not focusable", () => {
    const { container } = render(<Icon name="check" />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).toHaveAttribute("focusable", "false");
    expect(svg).toHaveAttribute("data-icon", "check");
  });
});

describe("BandChip", () => {
  it("shows the band as words, with a decorative icon and a meaning line", () => {
    const { container } = render(<BandChip band="moderate" />);
    expect(screen.getByText(/Moderate risk/)).toBeInTheDocument();
    expect(screen.getByText("Some warning signs need closer checking")).toBeInTheDocument();
    // The icon repeats the band for sighted users; screen readers get the words instead.
    expect(container.querySelector("svg[data-icon='alert-triangle']")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
  });

  it.each([
    ["low", "tick-circle"],
    ["moderate", "alert-triangle"],
    ["high", "alert-octagon"],
  ] as const)("gives the %s band its own icon shape (%s)", (band, icon) => {
    const { container } = render(<BandChip band={band} />);
    expect(container.querySelector(`svg[data-icon='${icon}']`)).not.toBeNull();
  });

  it("never describes the low band as safe", () => {
    render(<BandChip band="low" />);
    expect(screen.getByText("No strong warning signs found by this check")).toBeInTheDocument();
    expect(screen.queryByText(/safe/i)).not.toBeInTheDocument();
  });
});

describe("ScoreRegion", () => {
  it("labels the region with the score and band and contains the disclaimer", () => {
    render(<ScoreRegion score={62} band="moderate" disclaimer="Decision support only." />);
    const region = screen.getByRole("region", {
      name: "Score 62 out of 100, moderate risk",
    });
    expect(within(region).getByText("62")).toBeInTheDocument();
    // Common-region rule: the caveat is part of the verdict, not detached small print.
    expect(within(region).getByText("Decision support only.")).toBeInTheDocument();
  });

  it("never shows decimals", () => {
    render(<ScoreRegion score={61.6} band="moderate" disclaimer="x" />);
    expect(
      screen.getByRole("region", {
        name: "Score 62 out of 100, moderate risk",
      }),
    ).toBeInTheDocument();
  });
});

describe("SignalCardView", () => {
  it("renders a link when given an href", () => {
    render(<SignalCardView card={card()} href="/assess/1/explanation#visual" />);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/assess/1/explanation#visual");
    // The API's own summary names the model that ran, so a card with no reason says so plainly.
    expect(screen.getByText("No detailed reason is available.")).toBeInTheDocument();
    expect(screen.queryByText("No strong warning signs in the photos.")).not.toBeInTheDocument();
  });

  it("shows the strongest reason as the card's finding, in words", () => {
    render(
      <SignalCardView
        card={card({
          status_word: "model check",
          summary: "Analysed using a trained model.",
          reasons: [
            {
              feature_key: "w",
              direction: "raises",
              display_text: `The wording "urgent" raised this signal's risk estimate.`,
              rank: 1,
            },
          ],
        })}
        href="/x"
      />,
    );
    expect(
      screen.getByText(`The wording "urgent" raised this signal's risk estimate.`),
    ).toBeInTheDocument();
    expect(screen.getByText("Main factor: raises risk")).toBeInTheDocument();
    expect(screen.queryByText("model check")).not.toBeInTheDocument();
    expect(screen.queryByText("Analysed using a trained model.")).not.toBeInTheDocument();
  });

  it("leaves the scope note to the explanation page, so the card stays short", () => {
    render(
      <SignalCardView
        card={card({ scope_note: "A good profile is not a safe listing." })}
        href="/x"
      />,
    );
    expect(screen.queryByText("A good profile is not a safe listing.")).not.toBeInTheDocument();
  });

  it("keeps a technical scope note off a signal that could not be computed", () => {
    render(
      <SignalCardView
        card={card({ available: false, scope_note: "The fusion model receives a missing signal." })}
        href="/x"
      />,
    );
    expect(screen.queryByText(/fusion model/)).not.toBeInTheDocument();
  });

  it("shows each signal's own icon", () => {
    const { container, rerender } = render(
      <SignalCardView card={card({ signal: "visual" })} href="/x" />,
    );
    expect(container.querySelector("svg[data-icon='image']")).not.toBeNull();
    rerender(<SignalCardView card={card({ signal: "textual" })} href="/x" />);
    expect(container.querySelector("svg[data-icon='text-lines']")).not.toBeNull();
    rerender(<SignalCardView card={card({ signal: "behavioural" })} href="/x" />);
    expect(container.querySelector("svg[data-icon='person-clock']")).not.toBeNull();
  });

  it("renders a link that calls onOpen when there is no href", async () => {
    // The side panel opens the website itself, so the card is a link whose click is handled
    // in code. (A <button> cannot validly contain the card's heading.)
    const onOpen = vi.fn();
    render(<SignalCardView card={card()} onOpen={onOpen} />);
    await userEvent.click(screen.getByRole("link"));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("marks an unavailable signal with the dashed unknown style", () => {
    const { container } = render(
      <SignalCardView
        card={card({
          available: false,
          status_word: "limited information",
          summary: "Not enough information. Treated as unknown, not as suspicious.",
        })}
        href="/x"
      />,
    );
    expect(container.querySelector(".signal-unavailable")).not.toBeNull();
    // A question icon sits beside the status word, so "unknown" is not carried by the dashed border alone.
    expect(
      container.querySelector(".signal-status svg[data-icon='question-circle']"),
    ).not.toBeNull();
  });
});

describe("StageList", () => {
  it("marks earlier stages done and the current stage active", () => {
    const { container } = render(<StageList stage="textual" />);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(5);
    expect(items[0]).toHaveClass("stage-done");
    expect(items[1]).toHaveClass("stage-active");
    expect(items[1]).toHaveAttribute("aria-current", "step");
    expect(items[2]).not.toHaveClass("stage-done");
    // A finished stage shows a check icon; the others show their number.
    expect(items[0].querySelector("svg[data-icon='check']")).not.toBeNull();
    expect(container.querySelectorAll("svg[data-icon='check']")).toHaveLength(1);
  });

  it("shows every stage as pending before the first stage is reported", () => {
    render(<StageList stage={null} />);
    for (const item of screen.getAllByRole("listitem")) {
      expect(item).not.toHaveClass("stage-done");
      expect(item).not.toHaveClass("stage-active");
    }
  });
});

describe("DevBanner", () => {
  it("warns that scores are placeholder test data", () => {
    render(<DevBanner />);
    expect(screen.getByRole("status")).toHaveTextContent("Test mode");
  });
});

describe("CategoryField", () => {
  /** A controlled harness, because the field is a controlled input. */
  function Harness({ initial = "", error }: { initial?: string; error?: string }) {
    const [value, setValue] = useState(initial);
    return <CategoryField id="category" value={value} onChange={setValue} error={error} />;
  }

  it("offers the twelve trained categories as suggestions", () => {
    const { container } = render(<Harness />);
    expect(container.querySelectorAll("datalist option")).toHaveLength(12);
  });

  it("accepts any category text and notes when it is not a trained one", async () => {
    render(<Harness />);
    const input = screen.getByLabelText("Category");
    await userEvent.type(input, "Pets");
    expect(input).toHaveValue("Pets");
    expect(screen.getByText(UNSEEN_CATEGORY_NOTE)).toBeInTheDocument();
  });

  it("shows no note for a trained category", () => {
    render(<Harness initial="Phones" />);
    expect(screen.queryByText(UNSEEN_CATEGORY_NOTE)).not.toBeInTheDocument();
  });

  it("shows no note while the field is empty", () => {
    // A fresh render, because the harness keeps its own state between re-renders.
    render(<Harness initial="" />);
    expect(screen.queryByText(UNSEEN_CATEGORY_NOTE)).not.toBeInTheDocument();
  });

  it("links an error to the input and announces it", () => {
    render(<Harness initial="x" error="Choose or type a category." />);
    const input = screen.getByLabelText("Category");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription(
      expect.stringContaining("Choose or type a category."),
    );
    // Errors must be announced to screen readers, not only shown in red.
    expect(screen.getByRole("alert")).toHaveTextContent("Choose or type a category.");
  });
});
