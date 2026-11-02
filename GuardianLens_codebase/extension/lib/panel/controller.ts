// The side panel's controller: connects the pure state machine (reducer.ts) to the outside world.
// It owns every side effect of the panel: reading and saving the draft, listening for captures,
// running a check, cancelling, sending feedback, and opening the website.
//
// Two safety properties live here:
//   - the saved draft is never overwritten by the empty initial state: saving is switched on only
//     after the restore step has finished;
//   - a check is started exactly once per "submit": the reducer only sets `submitting` for a valid
//     draft in the Review view and gives that submit a new run id, and a run is started only for
//     a run id that has not started yet. A run is "stale" once a newer run, a cancel, or a new
//     capture has taken over (or the panel closed); a stale run stops and its late answers are
//     ignored, so a slow first check can never block or overwrite what the buyer does next.
import { useEffect, useReducer, useRef } from "react";
import {
  buildHandoffUrl,
  type FeedbackVerdict,
  type GuardianLensClient,
  type SignalName,
} from "@guardianlens/shared";
import { classifySellerUrl } from "../capture/classify";
import { runCheck } from "./check";
import type { DraftFieldKey } from "./draft";
import { mapApiError } from "./errors";
import { preparePhotos, type PhotoDeps } from "./photos";
import { initialPanelState, panelReducer, type PanelState } from "./reducer";
import type { PanelStorage } from "./storage";

/** Everything the controller needs from outside, so tests can supply fakes. */
export interface ControllerDeps {
  client: GuardianLensClient;
  photoDeps: PhotoDeps;
  storage: PanelStorage;
  /** Opens a URL in a new browser tab. */
  openUrl(url: string): void;
  /** Reads the page open in the browser now, asking for site access the first time. */
  captureActiveTab(): Promise<void>;
  /** The website's origin, for "See full explanation", "This session", and the manual form. */
  siteBaseUrl: string;
  /** Replaceable delay between status polls; defaults to a real timer. */
  wait?: (ms: number) => Promise<void>;
}

/** What the views can do. */
export interface PanelActions {
  /** Stores an edit to one field of the draft. */
  edit(key: DraftFieldKey, value: string): void;
  /** Selects or deselects one captured photo. */
  togglePhoto(url: string): void;
  /** Starts a check, if the draft is valid and nothing is already running. */
  submit(): void;
  /** Abandons the running check and returns to Review with the draft intact. */
  cancel(): void;
  /** Returns from a failure screen to Review. */
  retry(): void;
  /** Leaves a result and returns to the idle view to capture another listing. */
  checkAnother(): void;
  /** Sends the buyer's feedback choice for the result on screen. */
  sendFeedback(verdict: FeedbackVerdict): Promise<void>;
  /** Opens the website's explanation page for this result, optionally at one signal's section. */
  openFullExplanation(signal?: SignalName): Promise<void>;
  /** Opens a page of the website in a new tab (the history link carries the session handoff). */
  openSitePath(path: string): Promise<void>;
  /** Opens the seller's page found on the listing in a new tab, ready for the second capture. */
  openSellerPage(): void;
  /** Captures the page open in the browser now (the second capture, on the seller's page). */
  capture(): void;
}

// The real delay between status polls: resolves after `ms` milliseconds.
const realWait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * The panel's state and actions.
 * @param deps Stable dependencies (create them once, outside the component).
 */
export function usePanelController(deps: ControllerDeps): {
  state: PanelState;
  actions: PanelActions;
} {
  const [state, dispatch] = useReducer(panelReducer, initialPanelState);
  // The id of the newest run (mirrors state.runId), the id of the last run that was started, and
  // whether the panel has been closed. See the header comment for how they decide staleness.
  const currentRun = useRef(0);
  const startedRun = useRef(0);
  const closed = useRef(false);
  const restored = useRef(false);

  // On open: restore the saved draft, apply the newest capture if it is newer than the draft,
  // then follow new captures as the service worker writes them.
  useEffect(() => {
    let active = true;
    void (async () => {
      const saved = await deps.storage.readSaved();
      if (!active) return;
      // Switch saving on BEFORE dispatching, so the restored state is saved back unchanged.
      restored.current = true;
      if (saved)
        dispatch({
          type: "state_restored",
          draft: saved.draft,
          lastDoneJobId: saved.lastDoneJobId,
        });
      const job = await deps.storage.readCaptureState();
      if (active && job) dispatch({ type: "capture_finished", job });
    })();
    const stop = deps.storage.watchCaptureState((job) => {
      if (job) dispatch({ type: "capture_finished", job });
    });
    return () => {
      active = false;
      stop();
    };
  }, [deps]);

  // Keep the draft (and which capture it came from) so reopening the panel brings it back.
  useEffect(() => {
    if (!restored.current) return;
    void deps.storage.writeSaved({
      draft: state.draft,
      lastDoneJobId: state.lastDoneJobId,
    });
  }, [deps, state.draft, state.lastDoneJobId]);

  // Stop polling if the panel is closed mid-check. (The flag is reset when the effect runs, so a
  // development double-mount does not leave it stuck on "closed".)
  useEffect(() => {
    closed.current = false;
    return () => {
      closed.current = true;
    };
  }, []);

  // Keep the newest run id where a running check can read it. This effect is declared BEFORE the
  // one that starts runs, so it is already up to date when that one looks.
  useEffect(() => {
    currentRun.current = state.runId;
  }, [state.runId]);

  // Start a check when the reducer says one was requested for a run that has not started yet.
  useEffect(() => {
    if (!state.submitting || state.draft === null || startedRun.current === state.runId) return;
    const runId = state.runId;
    startedRun.current = runId;
    // True once the panel was closed or a newer run, a cancel, or a new capture has taken over.
    const isStale = () => closed.current || currentRun.current !== runId;
    void runCheck(state.draft, {
      client: deps.client,
      preparePhotos: (urls) => preparePhotos(urls, deps.photoDeps),
      wait: deps.wait ?? realWait,
      onAccepted: (assessmentId) => {
        if (!isStale()) dispatch({ type: "submit_accepted", assessmentId });
      },
      onStage: (stage) => {
        if (!isStale()) dispatch({ type: "stage_changed", stage });
      },
      onSlow: () => {
        if (!isStale()) dispatch({ type: "slow_wait" });
      },
      isCancelled: isStale,
    })
      .then((outcome) => {
        // A stale run says nothing: the panel already moved on (cancel, new capture, newer check).
        if (isStale()) return;
        if (outcome.status === "done") {
          dispatch({
            type: "check_finished",
            result: outcome.result,
            skippedPhotos: outcome.skippedPhotos,
          });
        } else if (outcome.status === "error") {
          dispatch({ type: "check_failed", error: outcome.error });
        }
      })
      .catch((error: unknown) => {
        // runCheck reports its own failures; this only guards against anything unexpected.
        if (!isStale()) dispatch({ type: "check_failed", error: mapApiError(error) });
      });
  }, [deps, state.submitting, state.runId, state.draft]);

  const actions: PanelActions = {
    edit: (key, value) => dispatch({ type: "edit_field", key, value }),
    togglePhoto: (url) => dispatch({ type: "toggle_photo", url }),
    submit: () => dispatch({ type: "submit_requested" }),
    // The run is retired here; runCheck notices on its next step and tells the server to stop.
    cancel: () => dispatch({ type: "cancelled" }),
    retry: () => dispatch({ type: "back_to_review" }),
    checkAnother: () => dispatch({ type: "check_another" }),
    sendFeedback: async (verdict) => {
      if (state.view.name !== "result") return;
      dispatch({ type: "feedback_changed", state: "saving" });
      try {
        await deps.client.sendFeedback(state.view.result.assessment_id, {
          verdict,
          comment: null,
        });
        dispatch({ type: "feedback_changed", state: "saved" });
      } catch {
        // Feedback is optional: on a failure the choices simply come back for another try.
        dispatch({ type: "feedback_changed", state: "idle" });
      }
    },
    openFullExplanation: async (signal) => {
      if (state.view.name !== "result") return;
      const assessmentId = state.view.result.assessment_id;
      const token = await deps.client.getToken();
      // The token travels in the URL fragment so it never reaches a server log; the website
      // removes it from the address bar and claims the session (shared/claim.ts).
      deps.openUrl(
        token
          ? buildHandoffUrl(deps.siteBaseUrl, assessmentId, token, signal)
          : `${deps.siteBaseUrl.replace(/\/+$/, "")}/assess/${assessmentId}/explanation`,
      );
    },
    openSellerPage: () => {
      const url = state.draft?.sellerUrl;
      // Only a seller page of a supported marketplace is ever opened, whatever storage holds.
      if (url && classifySellerUrl(url)) deps.openUrl(url);
    },
    // Called straight from the click: Chrome allows its permission prompt only inside a click. A
    // refusal by the buyer reads nothing and says nothing; any other failure is shown the same
    // way as a page that could not be read.
    capture: () =>
      void deps.captureActiveTab().catch(() =>
        dispatch({
          type: "capture_finished",
          job: { id: Date.now(), tabId: -1, status: "error", error: "inject_failed" },
        }),
      ),
    openSitePath: async (path) => {
      const base = deps.siteBaseUrl.replace(/\/+$/, "");
      // History lists the checks of a session, so it needs the extension's session: the link
      // carries the same fragment handoff as "See full explanation". Other pages (the manual
      // form) need no session, so their links carry no token.
      const token = path === "/history" ? await deps.client.getToken() : null;
      deps.openUrl(
        token
          ? `${base}${path}#${new URLSearchParams({ st: token }).toString()}`
          : `${base}${path}`,
      );
    },
  };

  return { state, actions };
}
