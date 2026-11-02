// Completes the extension-to-website session handoff once per page load, and tells the page when it
// is safe to load data.
//
// When the buyer clicks "See full explanation" in the extension, the website opens at
// ".../explanation#st=<token>". This hook (1) removes the token from the address bar, (2) asks the
// visitor to confirm, and (3) only after a yes asks the API to turn the token into this browser's
// session cookie, using the shared claimSessionFromHash (shared/src/claim.ts, which also pins that
// order). The confirmation matters: anyone can craft a link with their own token, and claiming it
// silently would move the visitor into someone else's session.
// A page must wait for `true` before fetching the result, or the first request would arrive
// without the cookie and be refused.
import { useEffect, useState } from "react";
import { claimSessionFromHash } from "@guardianlens/shared";
import { apiFetch } from "@/lib/api";

// What the visitor is asked before the session is claimed. A browser dialog is used on purpose: it
// cannot be styled or hidden by the page, it blocks until answered, and it is keyboard accessible.
const CONFIRM_MESSAGE = [
  "Open this result from your GuardianLens extension?",
  "",
  "This link opens a session from your browser extension. Continue only if you opened it from your own GuardianLens extension.",
  "Continuing replaces this browser's session, so checks made here earlier will no longer be listed. If you did not expect this link, choose Cancel.",
].join("\n");

// Module-level on purpose. React StrictMode (development only) runs every effect twice; sharing one
// in-flight claim lets the second run wait for the same request, instead of reading an address bar
// that was already cleaned, asking the visitor twice, or loading data before the cookie exists.
let pendingClaim: Promise<unknown> | null = null;

/**
 * @returns false while a handoff in the URL is still being completed, then true. It is true almost
 *          immediately when the URL carries no handoff, and also after the visitor declines (the
 *          page then shows its normal "could not be loaded for this browser session" message).
 */
export function useSessionClaim(): boolean {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let active = true;
    pendingClaim ??= claimSessionFromHash({
      hash: window.location.hash,
      confirm: async () => window.confirm(CONFIRM_MESSAGE),
      claim: (token) =>
        apiFetch<void>("/api/v1/session/claim", {
          method: "POST",
          body: JSON.stringify({ token }),
        }),
      // Keeps the current path and query; only the fragment changes, and no history entry is added.
      replaceHash: (hash) =>
        window.history.replaceState(
          null,
          "",
          `${window.location.pathname}${window.location.search}${hash}`,
        ),
    });
    void pendingClaim.finally(() => {
      if (active) setReady(true);
    });
    return () => {
      active = false;
    };
  }, []);

  return ready;
}
