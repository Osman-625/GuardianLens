// Extension-to-website session handoff.
//
// The extension and the website are different origins, so they cannot share a cookie. The
// extension therefore opens the website with the session token in the URL FRAGMENT
// ("#st=<token>"): a fragment is never sent to a server, so it stays out of server logs.
// The website reads it, removes it from the address bar, and asks the API to turn the token
// into its own httpOnly cookie. After that both clients see the same list of checks.
import type { SignalName } from "./types";

// A session token is a UUID; anything else in "st" is ignored rather than sent to the API.
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
// The only signal names a handoff link may ask the page to scroll to.
const SIGNALS: ReadonlySet<string> = new Set(["visual", "textual", "behavioural"]);

/** What a handoff fragment carries. Either value is null when absent or invalid. */
export interface HandoffParams {
  token: string | null;
  signal: SignalName | null;
}

/**
 * Reads a handoff fragment such as "#st=<uuid>&signal=visual".
 * @param hash `location.hash`, with or without the leading "#".
 * @returns The token (only if it is a valid UUID) and the signal (only if it is one of the
 *          three known signals).
 */
export function parseHandoffHash(hash: string): HandoffParams {
  const params = new URLSearchParams(hash.startsWith("#") ? hash.slice(1) : hash);
  const token = params.get("st");
  const signal = params.get("signal");
  return {
    token: token !== null && UUID.test(token) ? token : null,
    signal: signal !== null && SIGNALS.has(signal) ? (signal as SignalName) : null,
  };
}

/**
 * Builds the URL the extension opens for "See full explanation".
 * @param siteBaseUrl The website's origin, for example "http://localhost:3000".
 * @param assessmentId The assessment to show.
 * @param token The extension's session token (goes in the fragment, not the query string).
 * @param signal Optional signal card to scroll to.
 */
export function buildHandoffUrl(
  siteBaseUrl: string,
  assessmentId: string,
  token: string,
  signal?: SignalName,
): string {
  const base = siteBaseUrl.replace(/\/+$/, "");
  const fragment = new URLSearchParams({ st: token });
  if (signal) fragment.set("signal", signal);
  return `${base}/assess/${assessmentId}/explanation#${fragment.toString()}`;
}

/** The browser and network actions the claim needs, injected so the order can be tested. */
export interface ClaimDeps {
  /** The current `location.hash`. */
  hash: string;
  /**
   * Asks the visitor whether to link this browser to the extension's session; true means yes.
   * It exists because anyone can craft a handoff link containing their own token: claiming
   * silently would move the visitor into the sender's session, where the sender could later
   * read the visitor's checks (session fixation). The dialog should say that the link should
   * only be accepted when it came from the visitor's own GuardianLens extension.
   */
  confirm(): Promise<boolean>;
  /** Asks the API to attach the token's session to this browser (sets the cookie). */
  claim(token: string): Promise<void>;
  /** Rewrites the address bar's fragment without adding a history entry. */
  replaceHash(hash: string): void;
}

/**
 * "none": no token present. "claimed": session attached. "declined": the visitor said no (or the
 * question could not be shown), nothing was claimed. "failed": the claim itself failed.
 * In every case except "none" the token has already been removed from the address bar.
 */
export type ClaimOutcome = "none" | "claimed" | "declined" | "failed";

/**
 * Performs the handoff in a fixed order: scrub the token from the address bar, ask the visitor,
 * and only after a yes claim the session.
 * Scrubbing comes first so the token is gone even if the visitor declines, the claim throws, or
 * the page is closed. A signal in the fragment is kept as an ordinary anchor (for example
 * "#visual") so the page still scrolls to that card.
 */
export async function claimSessionFromHash(deps: ClaimDeps): Promise<ClaimOutcome> {
  const { token, signal } = parseHandoffHash(deps.hash);
  if (token === null) return "none";
  deps.replaceHash(signal ? `#${signal}` : "");
  try {
    // A question that cannot be shown is treated as a "no": never claim without an answer.
    if (!(await deps.confirm())) return "declined";
  } catch {
    return "declined";
  }
  try {
    await deps.claim(token);
    return "claimed";
  } catch {
    return "failed";
  }
}
