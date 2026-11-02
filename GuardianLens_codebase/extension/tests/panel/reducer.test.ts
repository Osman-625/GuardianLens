// Pins the side panel's state machine.
// The panel moves between: idle (nothing captured), capturing, review, checking, result, and
// failure. These tests protect the behaviours a buyer relies on:
//   - a click always shows the latest capture, but an OLD capture can never overwrite newer work;
//   - the buyer's edits survive failures, cancels, and seller-page additions;
//   - a second "Check listing" press while one is running does nothing;
//   - blocked and unsupported pages produce plain explanations, never a half-read draft.
import { describe, expect, it } from "vitest";
import type { CaptureJob } from "../../lib/capture/runner";
import { draftFromListing, editField } from "../../lib/panel/draft";
import {
  initialPanelState,
  panelReducer,
  type PanelAction,
  type PanelState,
} from "../../lib/panel/reducer";
import { manyPhotos, sampleListing, sampleResult, sampleSeller } from "../helpers/samples";

/** A finished capture job of a listing page. */
const listingJob = (id: number, listing = sampleListing()): CaptureJob => ({
  id,
  tabId: 1,
  status: "done",
  result: { kind: "listing", listing },
});

/** Applies actions one after another. */
function run(state: PanelState, ...actions: PanelAction[]): PanelState {
  return actions.reduce(panelReducer, state);
}

/** A state in the Review view with a fresh draft. */
const review = () => run(initialPanelState, { type: "capture_finished", job: listingJob(10) });

describe("capture_finished", () => {
  it("starts in the idle state", () => {
    expect(initialPanelState.view).toEqual({
      name: "idle",
      reason: "no_capture",
    });
  });

  it("shows the capturing view while a capture is running", () => {
    const state = run(initialPanelState, {
      type: "capture_finished",
      job: { id: 1, tabId: 1, status: "capturing" },
    });
    expect(state.view).toEqual({ name: "capturing" });
  });

  it("opens Review with a draft for a captured listing", () => {
    const state = review();
    expect(state.view).toEqual({ name: "review" });
    expect(state.draft?.fields.title.value).toBe("Used laptop in good condition");
    expect(state.notice).toBeNull();
  });

  it("adds a notice when part of the listing could not be read", () => {
    const state = run(initialPanelState, {
      type: "capture_finished",
      job: listingJob(10, sampleListing({ pageState: "incomplete" })),
    });
    expect(state.view).toEqual({ name: "review" });
    expect(state.notice).toBe("Some details could not be read from this page. Check each field.");
  });

  it("explains a blocked page and does not create a draft", () => {
    const state = run(initialPanelState, {
      type: "capture_finished",
      job: listingJob(10, sampleListing({ pageState: "captcha" })),
    });
    expect(state.view).toEqual({
      name: "idle",
      reason: "blocked",
      pageState: "captcha",
    });
    expect(state.draft).toBeNull();
  });

  it("explains a failed capture", () => {
    const state = run(initialPanelState, {
      type: "capture_finished",
      job: { id: 1, tabId: 1, status: "error", error: "inject_failed" },
    });
    expect(state.view).toEqual({ name: "idle", reason: "capture_failed" });
  });

  it.each([
    ["not_a_listing", "not_listing"],
    ["unsupported_site", "unsupported_site"],
  ] as const)("explains an unsupported page (%s)", (reason, idleReason) => {
    const job: CaptureJob = {
      id: 1,
      tabId: 1,
      status: "done",
      result: { kind: "unsupported", reason },
    };
    expect(run(initialPanelState, { type: "capture_finished", job }).view).toEqual({
      name: "idle",
      reason: idleReason,
    });
  });

  it("keeps the buyer's draft when a later click is on an unsupported page", () => {
    const state = run(review(), {
      type: "capture_finished",
      job: {
        id: 11,
        tabId: 1,
        status: "done",
        result: { kind: "unsupported", reason: "unsupported_site" },
      },
    });
    expect(state.draft).not.toBeNull();
  });
});

describe("old captures never overwrite newer work", () => {
  it("ignores a finished job that was already applied", () => {
    const edited = run(review(), {
      type: "edit_field",
      key: "title",
      value: "My edit",
    });
    // The same job arrives again (for example when the panel is reopened).
    expect(run(edited, { type: "capture_finished", job: listingJob(10) })).toBe(edited);
  });

  it("ignores a job older than one already applied", () => {
    const state = review();
    expect(run(state, { type: "capture_finished", job: listingJob(5) })).toBe(state);
  });

  it("replaces the draft when a newer job arrives", () => {
    const state = run(review(), {
      type: "capture_finished",
      job: listingJob(
        11,
        sampleListing({
          title: { status: "captured", value: "Another listing" },
        }),
      ),
    });
    expect(state.draft?.fields.title.value).toBe("Another listing");
  });

  it("restores a stored draft, then still accepts a newer capture", () => {
    const stored = draftFromListing(sampleListing());
    const restored = run(initialPanelState, {
      type: "state_restored",
      draft: stored,
      lastDoneJobId: 10,
    });
    expect(restored.view).toEqual({ name: "review" });
    // The job that produced the stored draft is not replayed over it...
    expect(run(restored, { type: "capture_finished", job: listingJob(10) })).toBe(restored);
    // ...but a newer click is applied.
    expect(run(restored, { type: "capture_finished", job: listingJob(12) }).draft).not.toBe(stored);
  });

  it("does not let a late restore overwrite a capture that already arrived", () => {
    const live = review();
    const stale = draftFromListing(
      sampleListing({
        title: { status: "captured", value: "Old stored draft" },
      }),
    );
    expect(run(live, { type: "state_restored", draft: stale, lastDoneJobId: 3 })).toBe(live);
  });

  it("restores nothing when no draft was stored", () => {
    expect(
      run(initialPanelState, {
        type: "state_restored",
        draft: null,
        lastDoneJobId: 0,
      }).view,
    ).toEqual({ name: "idle", reason: "no_capture" });
  });
});

// The seller page used by the seller-capture tests below.
const SELLER_PAGE = "https://www.carousell.com.my/u/someone/";

describe("seller page captures", () => {
  // A finished capture job of a seller page (ready, or blocked by a captcha).
  const sellerJob = (id: number, pageState: "ready" | "captcha" = "ready"): CaptureJob => ({
    id,
    tabId: 2,
    status: "done",
    result: {
      kind: "seller",
      platform: "carousell",
      url: SELLER_PAGE,
      seller: sampleSeller(),
      pageState,
    },
  });

  it("asks for the listing first when there is no draft", () => {
    const state = run(initialPanelState, {
      type: "capture_finished",
      job: sellerJob(1),
    });
    expect(state.view).toEqual({ name: "idle", reason: "no_draft_for_seller" });
  });

  it("adds the seller details to the draft and tells the buyer", () => {
    const state = run(review(), {
      type: "capture_finished",
      job: sellerJob(11),
    });
    expect(state.view).toEqual({ name: "review" });
    expect(state.draft?.fields.rating.value).toBe("4.8");
    // The listing did not link its seller, so the notice names the page for the buyer to check.
    expect(state.notice).toBe(
      "Seller details added from www.carousell.com.my/u/someone. " +
        "Check that this is the seller of this listing, then press Check listing.",
    );
  });

  it("does not say details were added when the seller page showed none", () => {
    const empty = sampleSeller({
      accountAgeDays: { status: "not_found", value: null },
      rating: { status: "not_found", value: null },
      reviewCount: { status: "not_found", value: null },
      activeListingCount: { status: "not_found", value: null },
    });
    const state = run(review(), {
      type: "capture_finished",
      job: {
        ...sellerJob(11),
        result: {
          kind: "seller",
          platform: "carousell",
          url: SELLER_PAGE,
          seller: empty,
          pageState: "ready",
        },
      },
    });
    expect(state.view).toEqual({ name: "review" });
    expect(state.notice).toBe(
      "No seller details could be read from that page. Type what you can see below.",
    );
    expect(state.draft?.fields.rating.value).toBe("");
  });

  // The second capture opens the panel in a NEW tab, which restores the saved draft from storage.
  // A seller capture can land a moment before that finishes; it must not be thrown away.
  it("keeps a seller capture that arrives before the saved draft has been restored", () => {
    const early = run(initialPanelState, { type: "capture_finished", job: sellerJob(11) });
    const restored = run(early, {
      type: "state_restored",
      draft: draftFromListing(sampleListing()),
      lastDoneJobId: 10,
    });
    // After restoring, the controller reads the stored job again and hands it over.
    const state = run(restored, { type: "capture_finished", job: sellerJob(11) });
    expect(state.view).toEqual({ name: "review" });
    expect(state.draft?.fields.rating.value).toBe("4.8");
    expect(state.draft?.fields.activeListingCount.value).toBe("4");
  });

  it("does not overwrite what the buyer typed", () => {
    const state = run(
      review(),
      { type: "edit_field", key: "rating", value: "3" },
      { type: "capture_finished", job: sellerJob(11) },
    );
    expect(state.draft?.fields.rating.value).toBe("3");
  });

  // When the listing page linked to its seller, only that page may fill the seller details.
  describe("which seller page counts", () => {
    const withLink = () =>
      run(initialPanelState, {
        type: "capture_finished",
        job: {
          id: 10,
          tabId: 1,
          status: "done",
          result: { kind: "listing", listing: sampleListing({ sellerUrl: SELLER_PAGE }) },
        },
      });
    const otherSeller = (url: string): CaptureJob => ({
      ...sellerJob(11),
      result: {
        kind: "seller",
        platform: "carousell",
        url,
        seller: sampleSeller(),
        pageState: "ready",
      },
    });

    it("keeps the short notice when the page is the one the listing linked", () => {
      const state = run(withLink(), {
        type: "capture_finished",
        job: otherSeller(SELLER_PAGE),
      });
      expect(state.notice).toBe("Seller details added. Press Check listing to include them.");
    });

    it("accepts the linked page, whatever its capitals or trailing slash", () => {
      const state = run(withLink(), {
        type: "capture_finished",
        job: otherSeller("https://www.carousell.com.my/u/SomeOne"),
      });
      expect(state.draft?.fields.rating.value).toBe("4.8");
    });

    it("refuses another seller's page and the buyer's own profile, and says why", () => {
      for (const url of [
        "https://www.carousell.com.my/u/someone-else/",
        "https://www.carousell.com.my/u/my-own-profile/",
      ]) {
        const state = run(withLink(), { type: "capture_finished", job: otherSeller(url) });
        expect(state.draft?.fields.rating.value).toBe("");
        expect(state.view).toEqual({ name: "review" });
        expect(state.notice).toContain("not this listing's seller");
      }
    });

    it("accepts any seller page when the listing did not link to one", () => {
      const state = run(review(), {
        type: "capture_finished",
        job: otherSeller("https://www.carousell.com.my/u/anyone/"),
      });
      expect(state.draft?.fields.rating.value).toBe("4.8");
    });
  });

  it("keeps the draft and says so when the seller page could not be read", () => {
    const state = run(review(), {
      type: "capture_finished",
      job: sellerJob(11, "captcha"),
    });
    expect(state.draft?.fields.rating.value).toBe("");
    expect(state.notice).toBe(
      "The seller page could not be read, so no seller details were added.",
    );
  });
});

describe("editing", () => {
  it("marks the field edited and clears that field's error", () => {
    const failed = run(review(), {
      type: "check_failed",
      error: {
        target: "review",
        fieldErrors: { title: "Enter the listing title." },
      },
    });
    const state = run(failed, {
      type: "edit_field",
      key: "title",
      value: "New",
    });
    expect(state.draft?.fields.title).toEqual({
      value: "New",
      status: "edited",
    });
    expect(state.fieldErrors.title).toBeUndefined();
  });

  it("limits the selection to ten photos", () => {
    // A listing with 12 photos: the first ten are selected, so the eleventh cannot be added.
    const urls = manyPhotos(12);
    const twelve = run(initialPanelState, {
      type: "capture_finished",
      job: listingJob(10, sampleListing({ imageUrls: urls })),
    });
    const state = run(twelve, { type: "toggle_photo", url: urls[10] ?? "" });
    expect(state.draft?.photos[10]?.selected).toBe(false);
  });
});

describe("submitting", () => {
  it("blocks an invalid draft and shows what to fix", () => {
    const blank = run(
      review(),
      { type: "edit_field", key: "title", value: "" },
      { type: "submit_requested" },
    );
    expect(blank.submitting).toBe(false);
    expect(blank.fieldErrors.title).toBe("Enter the listing title.");
  });

  it("starts a check for a valid draft", () => {
    const state = run(review(), { type: "submit_requested" });
    expect(state.submitting).toBe(true);
  });

  it("ignores a second press while the first check is running", () => {
    const first = run(review(), { type: "submit_requested" });
    // Same object back: no state change, so nothing downstream can start a second request.
    expect(run(first, { type: "submit_requested" })).toBe(first);
  });

  it("ignores a submit outside the Review view", () => {
    const idle = initialPanelState;
    expect(run(idle, { type: "submit_requested" })).toBe(idle);
  });
});

describe("checking and results", () => {
  it("moves through accepted, stage changes, and slow wait", () => {
    let state = run(
      review(),
      { type: "submit_requested" },
      { type: "submit_accepted", assessmentId: "a1" },
    );
    expect(state.view).toEqual({
      name: "checking",
      assessmentId: "a1",
      stage: null,
      slow: false,
    });
    state = run(state, { type: "stage_changed", stage: "textual" }, { type: "slow_wait" });
    expect(state.view).toEqual({
      name: "checking",
      assessmentId: "a1",
      stage: "textual",
      slow: true,
    });
  });

  it("shows the result and stops submitting", () => {
    const state = run(
      review(),
      { type: "submit_requested" },
      { type: "submit_accepted", assessmentId: "a1" },
      { type: "check_finished", result: sampleResult(), skippedPhotos: 0 },
    );
    expect(state.view).toMatchObject({ name: "result", feedback: "idle" });
    expect(state.submitting).toBe(false);
    expect(state.notice).toBeNull();
  });

  it("mentions photos that were left out", () => {
    const one = run(review(), {
      type: "check_finished",
      result: sampleResult(),
      skippedPhotos: 1,
    });
    expect(one.notice).toBe("1 photo could not be read and was left out of this check.");
    const two = run(review(), {
      type: "check_finished",
      result: sampleResult(),
      skippedPhotos: 2,
    });
    expect(two.notice).toBe("2 photos could not be read and were left out of this check.");
  });

  it("returns to Review with field errors and the draft kept", () => {
    const state = run(
      review(),
      { type: "submit_requested" },
      {
        type: "check_failed",
        error: {
          target: "review",
          fieldErrors: { description: "Unsupported." },
        },
      },
    );
    expect(state.view).toEqual({ name: "review" });
    expect(state.fieldErrors.description).toBe("Unsupported.");
    expect(state.submitting).toBe(false);
    expect(state.draft).not.toBeNull();
  });

  it("shows a failure screen and keeps the draft for the retry", () => {
    const state = run(
      review(),
      { type: "submit_requested" },
      {
        type: "check_failed",
        error: {
          target: "failure",
          kind: "unreachable",
          message: "Can't reach it.",
        },
      },
    );
    expect(state.view).toEqual({
      name: "failure",
      kind: "unreachable",
      message: "Can't reach it.",
    });
    expect(run(state, { type: "back_to_review" }).view).toEqual({
      name: "review",
    });
    expect(run(state, { type: "back_to_review" }).draft).not.toBeNull();
  });

  it("returns to Review when the buyer cancels", () => {
    const state = run(
      review(),
      { type: "submit_requested" },
      { type: "submit_accepted", assessmentId: "a1" },
      { type: "cancelled" },
    );
    expect(state.view).toEqual({ name: "review" });
    expect(state.submitting).toBe(false);
  });

  it("tracks feedback", () => {
    const result = run(review(), {
      type: "check_finished",
      result: sampleResult(),
      skippedPhotos: 0,
    });
    expect(run(result, { type: "feedback_changed", state: "saved" }).view).toMatchObject({
      name: "result",
      feedback: "saved",
    });
  });

  it("clears the draft for the next listing", () => {
    const state = run(
      review(),
      { type: "check_finished", result: sampleResult(), skippedPhotos: 0 },
      { type: "check_another" },
    );
    expect(state.view).toEqual({ name: "idle", reason: "no_capture" });
    expect(state.draft).toBeNull();
  });
});

describe("edits survive a failed check", () => {
  it("keeps typed values through a failure and a retry", () => {
    const edited = run(review(), {
      type: "edit_field",
      key: "price",
      value: "1300",
    });
    const retried = run(
      edited,
      { type: "submit_requested" },
      {
        type: "check_failed",
        error: { target: "failure", kind: "failed", message: "x" },
      },
      { type: "back_to_review" },
    );
    expect(retried.draft?.fields.price).toEqual(
      editField(draftFromListing(sampleListing()), "price", "1300").fields.price,
    );
  });
});

// A "run" is one started check. Its id bumps when a check starts, is cancelled, or is superseded by
// a new capture, so the controller can tell a stale run (whose late answers must be ignored) from
// the current one.
describe("a check that is running", () => {
  // A panel state in the middle of a check: submitted and accepted by the API.
  const checking = () =>
    run(review(), { type: "submit_requested" }, { type: "submit_accepted", assessmentId: "a1" });

  it("gets a new run id for each submit, and cancelling retires the old one", () => {
    const first = run(review(), { type: "submit_requested" });
    expect(first.runId).toBe(review().runId + 1);
    const cancelled = run(first, { type: "cancelled" });
    expect(cancelled.runId).toBe(first.runId + 1);
    const second = run(cancelled, { type: "submit_requested" });
    expect(second.submitting).toBe(true);
    expect(second.runId).toBe(cancelled.runId + 1);
  });

  it("keeps showing the check while another page is being read", () => {
    const state = run(checking(), {
      type: "capture_finished",
      job: { id: 11, tabId: 1, status: "capturing" },
    });
    expect(state.view.name).toBe("checking");
    expect(state.submitting).toBe(true);
  });

  it("a finished capture of another listing stops the check and opens Review for it", () => {
    const before = checking();
    const other = sampleListing({
      title: { status: "captured", value: "Another listing" },
    });
    const state = run(before, {
      type: "capture_finished",
      job: listingJob(11, other),
    });
    expect(state.view).toEqual({ name: "review" });
    expect(state.draft?.fields.title.value).toBe("Another listing");
    expect(state.submitting).toBe(false);
    expect(state.runId).toBeGreaterThan(before.runId);
  });

  it("a finished seller capture stops the check too, and keeps the draft", () => {
    const before = checking();
    const state = run(before, {
      type: "capture_finished",
      job: {
        id: 11,
        tabId: 2,
        status: "done",
        result: {
          kind: "seller",
          platform: "carousell",
          url: SELLER_PAGE,
          seller: sampleSeller(),
          pageState: "ready",
        },
      },
    });
    expect(state.view).toEqual({ name: "review" });
    expect(state.submitting).toBe(false);
    expect(state.runId).toBeGreaterThan(before.runId);
    expect(state.draft?.fields.rating.value).toBe("4.8");
  });

  it("a click on an unsupported page stops the check but keeps the draft", () => {
    const before = checking();
    const state = run(before, {
      type: "capture_finished",
      job: {
        id: 11,
        tabId: 1,
        status: "done",
        result: { kind: "unsupported", reason: "unsupported_site" },
      },
    });
    expect(state.view).toEqual({ name: "idle", reason: "unsupported_site" });
    expect(state.submitting).toBe(false);
    expect(state.runId).toBeGreaterThan(before.runId);
    expect(state.draft).not.toBeNull();
  });
});
