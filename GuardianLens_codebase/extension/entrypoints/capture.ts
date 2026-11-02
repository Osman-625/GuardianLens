// The capture script. It is injected into a marketplace tab ONLY when the buyer clicks the
// toolbar icon (see lib/capture/runner.ts), and it answers one message: "capture this page".
//
// It is an "unlisted script", not a content script on purpose: a content script would add the
// marketplace sites to the extension's host permissions and run on every visit. An unlisted
// script has no standing access and runs only where the activeTab click injected it.
//
// It reads the page and returns the result; it never changes the page, never makes a network
// request, and never stores anything.
import { browser } from "wxt/browser";
import { captureCurrentPage } from "@/lib/capture/page";
import { CAPTURE_MESSAGE } from "@/lib/capture/types";

export default defineUnlistedScript(() => {
  const scope = globalThis as unknown as Record<string, unknown>;
  // The buyer can click again on the same page, which injects this script a second time.
  // Registering a second listener would answer every request twice, so install it only once.
  if (scope.__guardianlensCaptureInstalled) return;
  scope.__guardianlensCaptureInstalled = true;

  browser.runtime.onMessage.addListener((message: unknown, _sender, sendResponse) => {
    const type = (message as { type?: unknown } | null)?.type;
    if (type !== CAPTURE_MESSAGE) return false;
    sendResponse(captureCurrentPage(document, location.href, new Date()));
    // The response was sent synchronously, so the message channel does not need to stay open.
    return false;
  });
});
