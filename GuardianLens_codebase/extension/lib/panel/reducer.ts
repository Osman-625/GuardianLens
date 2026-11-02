// The side panel's state machine, as a pure reducer.
//
// Views: idle (nothing captured), capturing, review, checking, result, failure.
// Rules this file guarantees (each pinned by a test):
//   - a capture job is applied once: a job that was already applied, or is older than one that
//     was, is ignored, so reopening the panel can never overwrite the buyer's newer edits; and a
//     draft restored from storage never overwrites a capture that arrived while it was loading;
//   - the buyer's draft survives failures, cancels, and seller-page additions;
//   - "submit_requested" is a no-op unless the Review view is showing, nothing is running, and the
//     draft is valid, so pressing the button twice cannot start two checks.
// Side effects (storage, network, timers) live in controller.ts; this file has none.
import type { AssessmentResult, PipelineStage } from "@guardianlens/shared";
import { samePage } from "../capture/classify";
import type { CaptureJob } from "../capture/runner";
import type { PageState } from "../capture/types";
import {
  applySeller,
  draftFromListing,
  editField,
  togglePhoto,
  validateDraft,
  type Draft,
  type DraftErrors,
  type DraftFieldKey,
} from "./draft";
import type { FailureKind, MappedError } from "./errors";

/** Why the idle view is showing. */
export type IdleReason =
  | "no_capture"
  | "not_listing"
  | "unsupported_site"
  | "blocked"
  | "capture_failed"
  | "no_draft_for_seller";

/** Progress of the feedback prompt on the result view. */
export type FeedbackState = "idle" | "saving" | "saved";

/** What the panel is showing. */
export type PanelView =
  | { name: "idle"; reason: IdleReason; pageState?: PageState }
  | { name: "capturing" }
  | { name: "review" }
  | {
      name: "checking";
      assessmentId: string;
      stage: PipelineStage | null;
      slow: boolean;
    }
  | { name: "result"; result: AssessmentResult; feedback: FeedbackState }
  | { name: "failure"; kind: FailureKind; message: string };

/** Everything the panel knows. */
export interface PanelState {
  view: PanelView;
  /** The buyer's draft; kept through failures and cancels. */
  draft: Draft | null;
  /** Errors to show next to fields (server field errors and failed submit validation). */
  fieldErrors: DraftErrors;
  /** A plain one-line message shown above the form or result, or null. */
  notice: string | null;
  /** True from a valid "Check listing" press until the check ends. */
  submitting: boolean;
  /** Id of the newest finished capture job already applied. Finished jobs with an id at or below it are ignored. */
  lastDoneJobId: number;
  /**
   * Id of the current check run. It goes up when a check starts, is cancelled, or is stopped by a
   * new capture. The controller compares it to tell the current run from an older one still waiting
   * on the server, whose late answers must be ignored.
   */
  runId: number;
}

/** Everything that can happen to the panel. */
export type PanelAction =
  | { type: "capture_finished"; job: CaptureJob }
  | { type: "state_restored"; draft: Draft | null; lastDoneJobId: number }
  | { type: "edit_field"; key: DraftFieldKey; value: string }
  | { type: "toggle_photo"; url: string }
  | { type: "submit_requested" }
  | { type: "submit_accepted"; assessmentId: string }
  | { type: "stage_changed"; stage: PipelineStage | null }
  | { type: "slow_wait" }
  | { type: "check_finished"; result: AssessmentResult; skippedPhotos: number }
  | { type: "check_failed"; error: MappedError }
  | { type: "cancelled" }
  | { type: "feedback_changed"; state: FeedbackState }
  | { type: "check_another" }
  | { type: "back_to_review" };

/** The panel before anything has been captured. */
export const initialPanelState: PanelState = {
  view: { name: "idle", reason: "no_capture" },
  draft: null,
  fieldErrors: {},
  notice: null,
  submitting: false,
  lastDoneJobId: 0,
  runId: 0,
};

// The one-line notices shown above the Review form: a listing read only in part, seller details
// merged into the draft, and a seller page that could not be read.
const INCOMPLETE_NOTICE = "Some details could not be read from this page. Check each field.";
const SELLER_ADDED_NOTICE = "Seller details added. Press Check listing to include them.";
/** The notice when the listing did not link its seller, so nothing confirms this page is theirs. */
const sellerAddedFromNotice = (page: string) =>
  `Seller details added from ${page}. Check that this is the seller of this listing, then press Check listing.`;

/** "www.mudah.my/u/seller-1": the page a capture came from, without any query string. */
function pageLabel(url: string): string {
  try {
    const parsed = new URL(url);
    return `${parsed.host}${parsed.pathname}`.replace(/\/+$/, "");
  } catch {
    return url;
  }
}
const SELLER_NOTHING_NOTICE =
  "No seller details could be read from that page. Type what you can see below.";
const SELLER_OTHER_NOTICE =
  "That is not this listing's seller, so nothing was added. Use Open seller page, then click the icon there.";
const SELLER_UNREADABLE_NOTICE =
  "The seller page could not be read, so no seller details were added.";

/** True for the page states that mean the page was blocked and not read. */
function isBlocked(state: PageState): boolean {
  return state !== "ready" && state !== "incomplete";
}

/** The notice about photos that were left out of a check, or null when none were. */
function skippedNotice(count: number): string | null {
  if (count === 0) return null;
  return count === 1
    ? "1 photo could not be read and was left out of this check."
    : `${count} photos could not be read and were left out of this check.`;
}

/** Applies a capture job from the service worker. */
function applyCaptureJob(state: PanelState, job: CaptureJob): PanelState {
  if (job.status === "capturing") {
    // A "capturing" job only matters while it is newer than anything already applied.
    // While a check is running its progress stays on screen; the finished capture decides next.
    return job.id > state.lastDoneJobId && !state.submitting
      ? { ...state, view: { name: "capturing" } }
      : state;
  }
  if (job.id <= state.lastDoneJobId) return state;
  // A finished capture while a check is running means the buyer moved on to another page. It
  // stops that check (a new run id retires it), so two listings are never mixed in one panel.
  const live = state.submitting ? { ...state, submitting: false, runId: state.runId + 1 } : state;
  const base = { ...live, lastDoneJobId: job.id };

  if (job.status === "error" || !job.result) {
    return { ...base, view: { name: "idle", reason: "capture_failed" } };
  }
  const { result } = job;

  if (result.kind === "unsupported") {
    return {
      ...base,
      view: {
        name: "idle",
        reason: result.reason === "not_a_listing" ? "not_listing" : "unsupported_site",
      },
    };
  }

  if (result.kind === "listing") {
    if (isBlocked(result.listing.pageState)) {
      return {
        ...base,
        view: {
          name: "idle",
          reason: "blocked",
          pageState: result.listing.pageState,
        },
      };
    }
    return {
      ...base,
      view: { name: "review" },
      draft: draftFromListing(result.listing),
      fieldErrors: {},
      submitting: false,
      notice: result.listing.pageState === "incomplete" ? INCOMPLETE_NOTICE : null,
    };
  }

  // A seller page: its values are merged into the draft of the listing the buyer already captured.
  // With no draft yet, the job is NOT marked as applied: in a new tab the saved draft may still be
  // loading, and the controller reads the stored job again once it has, so the values are kept.
  if (state.draft === null)
    return { ...state, view: { name: "idle", reason: "no_draft_for_seller" } };
  if (isBlocked(result.pageState))
    return {
      ...base,
      view: { name: "review" },
      notice: SELLER_UNREADABLE_NOTICE,
    };
  // When the listing linked to its seller, only that page counts: another seller's details (or the
  // buyer's own profile) must not end up in this check.
  if (state.draft.sellerUrl && !samePage(state.draft.sellerUrl, result.url))
    return { ...base, view: { name: "review" }, notice: SELLER_OTHER_NOTICE };
  return {
    ...base,
    view: { name: "review" },
    draft: applySeller(state.draft, result.seller),
    fieldErrors: {},
    submitting: false,
    // A page that showed nothing must not claim that details were added.
    notice: Object.values(result.seller).some((field) => field.value !== null)
      ? state.draft.sellerUrl
        ? SELLER_ADDED_NOTICE
        : sellerAddedFromNotice(pageLabel(result.url))
      : SELLER_NOTHING_NOTICE,
  };
}

/** The reducer. Always returns the SAME object when an action changes nothing. */
export function panelReducer(state: PanelState, action: PanelAction): PanelState {
  switch (action.type) {
    // A capture job from the service worker started, finished, or failed.
    case "capture_finished":
      return applyCaptureJob(state, action.job);

    // The saved draft was read from storage when the panel opened.
    case "state_restored":
      // Restoring reads storage asynchronously, so a live capture may already have arrived. A
      // draft that is already here is newer than the stored one and must never be overwritten.
      if (state.draft !== null) return state;
      return {
        ...state,
        draft: action.draft,
        lastDoneJobId: Math.max(state.lastDoneJobId, action.lastDoneJobId),
        view: action.draft ? { name: "review" } : state.view,
      };

    // The buyer edited a field; the error shown for that field is cleared.
    case "edit_field": {
      if (!state.draft) return state;
      const { [action.key]: _cleared, ...remaining } = state.fieldErrors;
      return {
        ...state,
        draft: editField(state.draft, action.key, action.value),
        fieldErrors: remaining,
      };
    }

    // The buyer selected or deselected a photo; the photo error is cleared.
    case "toggle_photo": {
      if (!state.draft) return state;
      const { photos: _cleared, ...remaining } = state.fieldErrors;
      return {
        ...state,
        draft: togglePhoto(state.draft, action.url),
        fieldErrors: remaining,
      };
    }

    // "Check listing" was pressed: invalid drafts show their errors, a valid one starts a new run.
    case "submit_requested": {
      if (state.view.name !== "review" || state.submitting || state.draft === null) return state;
      const errors = validateDraft(state.draft);
      if (Object.keys(errors).length > 0) return { ...state, fieldErrors: errors };
      return {
        ...state,
        fieldErrors: {},
        submitting: true,
        runId: state.runId + 1,
      };
    }

    // The API accepted the submission; the progress view takes over.
    case "submit_accepted":
      return {
        ...state,
        view: {
          name: "checking",
          assessmentId: action.assessmentId,
          stage: null,
          slow: false,
        },
      };

    // The API reported a new processing stage (only meaningful while the progress view is showing).
    case "stage_changed":
      return state.view.name === "checking"
        ? { ...state, view: { ...state.view, stage: action.stage } }
        : state;

    // The check is taking longer than usual; the progress view says so.
    case "slow_wait":
      return state.view.name === "checking"
        ? { ...state, view: { ...state.view, slow: true } }
        : state;

    // The result arrived; it is shown with a notice if some photos were left out.
    case "check_finished":
      return {
        ...state,
        view: { name: "result", result: action.result, feedback: "idle" },
        submitting: false,
        notice: skippedNotice(action.skippedPhotos),
      };

    // The check failed: a problem with one field returns to Review, anything else shows a failure.
    case "check_failed":
      if (action.error.target === "review") {
        return {
          ...state,
          view: { name: "review" },
          submitting: false,
          fieldErrors: { ...state.fieldErrors, ...action.error.fieldErrors },
        };
      }
      return {
        ...state,
        view: {
          name: "failure",
          kind: action.error.kind,
          message: action.error.message,
        },
        submitting: false,
      };

    // The buyer cancelled the running check and returns to Review.
    case "cancelled":
      // The new run id retires the cancelled run, so its late answers are ignored.
      return {
        ...state,
        view: { name: "review" },
        submitting: false,
        runId: state.runId + 1,
      };

    // The feedback prompt moved between idle, saving, and saved (only on the result view).
    case "feedback_changed":
      return state.view.name === "result"
        ? { ...state, view: { ...state.view, feedback: action.state } }
        : state;

    // The buyer finished with this result; the panel resets, dropping the draft.
    case "check_another":
      return {
        ...state,
        view: { name: "idle", reason: "no_capture" },
        draft: null,
        fieldErrors: {},
        notice: null,
        submitting: false,
      };

    // The buyer left a failure screen; the draft is still there to edit and resend.
    case "back_to_review":
      return { ...state, view: { name: "review" } };
  }
}
