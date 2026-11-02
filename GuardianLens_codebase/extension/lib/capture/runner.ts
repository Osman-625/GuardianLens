// Runs one capture when the buyer clicks the toolbar icon, and records the outcome for the side
// panel to read.
//
// Privacy rule: the capture script is injected ONLY into the two supported marketplaces. The
// activeTab permission works on every site, so without the guard below a click on any other tab
// would inject our script there. On any other site nothing is injected and the result is simply
// "unsupported".
//
// The steps are injected as `deps` so they can be tested without real browser tabs; `defaultDeps`
// are the real implementations.
import { browser } from "wxt/browser";
import { platformFromHost } from "./classify";
import { PAGE_HOST_PATTERNS } from "../hosts";
import { writeSession } from "../storage";
import { CAPTURE_MESSAGE, type CaptureResult } from "./types";

/** Where the latest capture job is stored in session storage (the side panel watches this key). */
export const CAPTURE_STATE_KEY = "captureState";

/** The state of one capture click. `id` is its start time and orders jobs (newest wins). */
export interface CaptureJob {
  id: number;
  tabId: number;
  status: "capturing" | "done" | "error";
  /** Set when status is "done". */
  result?: CaptureResult;
  /** Set when status is "error": the script could not be injected, or never answered. */
  error?: "inject_failed" | "no_response";
}

/** The side effects of a capture, injectable for tests. */
export interface RunnerDeps {
  writeState(job: CaptureJob): Promise<void>;
  inject(tabId: number): Promise<void>;
  request(tabId: number): Promise<CaptureResult | undefined>;
  now(): number;
}

/** The real implementations, using the browser's scripting, tabs, and session storage APIs. */
export const defaultDeps: RunnerDeps = {
  writeState: (job) => writeSession(CAPTURE_STATE_KEY, job),
  // /capture.js is built from entrypoints/capture.ts. activeTab, granted by the toolbar click,
  // is what permits this injection on a site the extension has no standing host permission for.
  inject: async (tabId) => {
    await browser.scripting.executeScript({
      target: { tabId },
      files: ["/capture.js"],
    });
  },
  request: async (tabId) =>
    (await browser.tabs.sendMessage(tabId, { type: CAPTURE_MESSAGE })) as CaptureResult | undefined,
  now: () => Date.now(),
};

/** The browser calls behind the side panel's "Capture this page" button, injectable for tests. */
export interface ActiveTabDeps {
  /** Asks Chrome for access to the marketplace sites; its prompt shows only the first time. */
  requestAccess(origins: string[]): Promise<boolean>;
  /** The tab that is open in the window the buyer last used. */
  activeTab(): Promise<{ id?: number; url?: string } | undefined>;
}

const defaultActiveTabDeps: ActiveTabDeps = {
  requestAccess: (origins) => browser.permissions.request({ origins }),
  activeTab: async () => (await browser.tabs.query({ active: true, lastFocusedWindow: true }))[0],
};

/**
 * The panel's "Capture this page": the same capture as the toolbar click, on the tab open now.
 * Call it straight from the click, because Chrome allows its permission prompt only inside one.
 * @returns false when nothing was read: the buyer declined access, or no tab was found.
 */
export async function captureActiveTab(
  access: ActiveTabDeps = defaultActiveTabDeps,
  deps: RunnerDeps = defaultDeps,
): Promise<boolean> {
  if (!(await access.requestAccess(PAGE_HOST_PATTERNS))) return false;
  const tab = await access.activeTab();
  if (tab?.id === undefined) return false;
  await runCaptureForTab({ id: tab.id, url: tab.url }, deps);
  return true;
}

/** True when the URL is https on one of the four supported marketplace hosts. */
function isSupportedPage(url: string | undefined): boolean {
  if (!url) return false;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" && platformFromHost(parsed.hostname) !== null;
  } catch {
    return false;
  }
}

/**
 * Handles one toolbar click: injects the capture script (supported pages only), asks it to read
 * the page, and writes the outcome through `deps.writeState`.
 * @param tab The tab the buyer clicked in; `url` is readable because the click granted activeTab.
 */
export async function runCaptureForTab(
  tab: { id: number; url?: string },
  deps: RunnerDeps = defaultDeps,
): Promise<void> {
  const id = deps.now();
  if (!isSupportedPage(tab.url)) {
    await deps.writeState({
      id,
      tabId: tab.id,
      status: "done",
      result: { kind: "unsupported", reason: "unsupported_site" },
    });
    return;
  }
  await deps.writeState({ id, tabId: tab.id, status: "capturing" });
  try {
    await deps.inject(tab.id);
    const result = await deps.request(tab.id);
    await deps.writeState(
      result
        ? { id, tabId: tab.id, status: "done", result }
        : { id, tabId: tab.id, status: "error", error: "no_response" },
    );
  } catch {
    await deps.writeState({
      id,
      tabId: tab.id,
      status: "error",
      error: "inject_failed",
    });
  }
}
