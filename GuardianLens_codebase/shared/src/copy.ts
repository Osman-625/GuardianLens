// Shared wording and small lookup tables used by the website and the extension's side panel.
// Keeping them here means a sentence is changed once and both surfaces stay identical.
// Rules these strings must follow (docs/spec/04_Design_Brief_UI_UX.md): plain language, risk
// never described as "safe", missing data described as unknown (not suspicious).
import type { IconName } from "./components/Icon";
import type { FeedbackVerdict, PipelineStage, RiskBand, SignalName } from "./types";

/** The five processing stages in the order they run, with buyer-readable labels. */
export const STAGES: ReadonlyArray<{ key: PipelineStage; label: string }> = [
  { key: "visual", label: "Checking photos" },
  { key: "textual", label: "Checking wording" },
  { key: "behavioural", label: "Checking seller and price" },
  { key: "fusion", label: "Combining the results" },
  { key: "explanation", label: "Writing the explanation" },
];

/**
 * Icon and one-line meaning per band. The icon SHAPE differs for every band (tick circle, alert
 * triangle, alert octagon) so colour is never the only difference. "Low" deliberately says "no
 * strong warning signs", never "safe".
 */
export const BAND_COPY: Record<RiskBand, { icon: IconName; meaning: string }> = {
  low: {
    icon: "tick-circle",
    meaning: "No strong warning signs found by this check",
  },
  moderate: {
    icon: "alert-triangle",
    meaning: "Some warning signs need closer checking",
  },
  high: {
    icon: "alert-octagon",
    meaning: "Several warning signs need serious attention",
  },
};

/** Shown under the score so the direction is never guessed: a higher score means fewer warning signs. */
export const SCORE_HINT = "Higher is better. 100 means the fewest warning signs.";

/**
 * Display names of the three signals, in the buyer's words. The report and the code call them
 * visual, textual and behavioural; the interface says what each one looks at.
 */
export const SIGNAL_NAMES: Record<SignalName, string> = {
  visual: "Photos",
  textual: "Wording",
  behavioural: "Seller and price",
};

/** One line on what each signal looks at: the landing page and the panel's start screen. */
export const SIGNAL_LOOKS_AT: Record<SignalName, string> = {
  visual: "Photo detail, and whether the photos match known reference images.",
  textual: "Phrases that often appear in scam listings.",
  behavioural: "Account age, rating and reviews when shown, and how the price compares.",
};

/**
 * Model and method names (the model bundle, "analysed using ...") stay in the data the API sends,
 * but buyers do not see them. Set to true to show them again on the cards and the explanation.
 */
export const SHOW_MODEL_DETAILS = false;

/** Shown for a signal that ran but gave no single reason to show. */
export const NO_REASON_COPY = "No detailed reason is available.";

/** Small neutral icons for the three signals (image, text lines, person with clock). */
export const SIGNAL_ICONS: Record<SignalName, IconName> = {
  visual: "image",
  textual: "text-lines",
  behavioural: "person-clock",
};

/** Shown after the processing screen has waited a while. No percentages, no fake progress. */
export const SLOW_WAIT_COPY = "This is taking longer than usual. It is still working.";

/** Shown under the category field when the text is not one of the 12 trained categories. */
export const UNSEEN_CATEGORY_NOTE =
  "Price is compared with the overall average, not this category's average.";

/** Shown on the explanation page: why two results with the same number can have different bands. */
export const BAND_ROUNDING_NOTE =
  "Scores are rounded for display, but the band comes from the exact score. Two results with the same number can land in different bands near a boundary.";

/** Retention statement shown beside every submit control (wording pends the approved retention period). */
export const RETENTION_NOTICE =
  "Contact details are removed from your text before it is stored. How long results are kept has not been decided yet.";

/** Warning shown while scores come from development stubs rather than trained models. */
export const DEV_STUB_NOTICE = "Test mode. These scores are placeholder data, not real results.";

/** The question asked after a result, on the website and in the browser extension alike. */
export const FEEDBACK_HEADING = "Was this result helpful?";

/**
 * The three feedback choices, in the order they are shown: the value sent to the API and the label
 * on screen. Both surfaces render these, so the wording cannot drift apart.
 */
export const FEEDBACK_OPTIONS: ReadonlyArray<readonly [FeedbackVerdict, string]> = [
  ["helpful", "Helpful"],
  ["unclear", "Unclear"],
  ["potentially_incorrect", "Potentially incorrect"],
];
