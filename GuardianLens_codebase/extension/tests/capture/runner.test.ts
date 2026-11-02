// Pins what happens when the buyer clicks the toolbar icon.
// The privacy-critical rule: the capture script is injected ONLY on the two marketplaces. The
// activeTab permission works on any site, so without this guard a click on, say, a banking tab
// would inject our script. On other sites the click must only report "unsupported".
// Dependencies are injected so the tests need no real browser tabs.
import { describe, expect, it, vi } from "vitest";
import {
  captureActiveTab,
  runCaptureForTab,
  type ActiveTabDeps,
  type CaptureJob,
  type RunnerDeps,
} from "../../lib/capture/runner";
import { PAGE_HOST_PATTERNS } from "../../lib/hosts";
import type { CaptureResult } from "../../lib/capture/types";

// The answer the fake capture script gives when asked to read the page.
const LISTING_RESULT: CaptureResult = {
  kind: "unsupported",
  reason: "not_a_listing",
};

/** Builds fake dependencies that record every state the runner writes. */
function fakeDeps(overrides: Partial<RunnerDeps> = {}) {
  const states: CaptureJob[] = [];
  const deps: RunnerDeps = {
    writeState: async (job) => void states.push(job),
    inject: vi.fn(async () => undefined),
    request: vi.fn(async () => LISTING_RESULT),
    now: () => 111,
    ...overrides,
  };
  return { deps, states };
}

describe("runCaptureForTab", () => {
  it("does not inject anything on a site that is not a supported marketplace", async () => {
    const { deps, states } = fakeDeps();
    await runCaptureForTab({ id: 7, url: "https://example.com/account" }, deps);
    expect(deps.inject).not.toHaveBeenCalled();
    expect(states).toEqual([
      {
        id: 111,
        tabId: 7,
        status: "done",
        result: { kind: "unsupported", reason: "unsupported_site" },
      },
    ]);
  });

  it("does not inject when the tab has no readable URL", async () => {
    const { deps, states } = fakeDeps();
    await runCaptureForTab({ id: 7 }, deps);
    expect(deps.inject).not.toHaveBeenCalled();
    expect(states[0]?.result).toEqual({
      kind: "unsupported",
      reason: "unsupported_site",
    });
  });

  it("writes capturing, then the result, on a marketplace page", async () => {
    const { deps, states } = fakeDeps();
    await runCaptureForTab({ id: 7, url: "https://www.carousell.com.my/p/x-123/" }, deps);
    expect(deps.inject).toHaveBeenCalledWith(7);
    expect(states.map((state) => state.status)).toEqual(["capturing", "done"]);
    expect(states[1]?.result).toEqual(LISTING_RESULT);
  });

  it("reports inject_failed when the script cannot be injected", async () => {
    const { deps, states } = fakeDeps({
      inject: vi.fn(async () => {
        throw new Error("no access");
      }),
    });
    await runCaptureForTab({ id: 7, url: "https://www.mudah.my/phone-123456.htm" }, deps);
    expect(states.at(-1)).toMatchObject({
      status: "error",
      error: "inject_failed",
    });
  });

  it("reports no_response when the script does not answer", async () => {
    const { deps, states } = fakeDeps({
      request: vi.fn(async () => undefined),
    });
    await runCaptureForTab({ id: 7, url: "https://www.mudah.my/phone-123456.htm" }, deps);
    expect(states.at(-1)).toMatchObject({
      status: "error",
      error: "no_response",
    });
  });
});

// The side panel's "Capture this page" button: it asks for access, then captures the open tab.
describe("captureActiveTab", () => {
  const CAROUSELL_TAB = { id: 9, url: "https://www.carousell.com.my/u/someone/" };
  const access = (overrides: Partial<ActiveTabDeps> = {}): ActiveTabDeps => ({
    requestAccess: vi.fn(async () => true),
    activeTab: vi.fn(async () => CAROUSELL_TAB),
    ...overrides,
  });

  it("asks only for the four marketplace hosts, then captures the open tab", async () => {
    const { deps, states } = fakeDeps();
    const tabs = access();
    expect(await captureActiveTab(tabs, deps)).toBe(true);
    expect(tabs.requestAccess).toHaveBeenCalledExactlyOnceWith(PAGE_HOST_PATTERNS);
    expect(deps.inject).toHaveBeenCalledWith(9);
    expect(states.map((state) => state.tabId)).toEqual([9, 9]);
  });

  it("reads nothing when the buyer declines access", async () => {
    const { deps, states } = fakeDeps();
    const tabs = access({ requestAccess: vi.fn(async () => false) });
    expect(await captureActiveTab(tabs, deps)).toBe(false);
    expect(tabs.activeTab).not.toHaveBeenCalled();
    expect(deps.inject).not.toHaveBeenCalled();
    expect(states).toEqual([]);
  });

  it("reads nothing when there is no tab", async () => {
    const { deps, states } = fakeDeps();
    expect(await captureActiveTab(access({ activeTab: vi.fn(async () => undefined) }), deps)).toBe(
      false,
    );
    expect(deps.inject).not.toHaveBeenCalled();
    expect(states).toEqual([]);
  });

  it("still never injects on a site that is not a marketplace", async () => {
    const { deps } = fakeDeps();
    const tabs = access({ activeTab: vi.fn(async () => ({ id: 3, url: "https://example.com/" })) });
    await captureActiveTab(tabs, deps);
    expect(deps.inject).not.toHaveBeenCalled();
  });
});
