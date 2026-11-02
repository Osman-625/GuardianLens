// Extension service worker (background script).
//
// The toolbar icon has no popup, so Chrome fires `action.onClicked` when the buyer clicks it.
// That single click is the explicit capture event for the whole product. It:
//   1. opens the side panel for the current tab, and
//   2. grants the extension temporary `activeTab` access to that tab, which is what lets the
//      runner inject the capture script and read the page.
// The runner writes its result to session storage; the side panel watches it and reacts.
import { runCaptureForTab } from "@/lib/capture/runner";

export default defineBackground(() => {
  browser.action.onClicked.addListener((tab) => {
    if (tab.id === undefined) return;
    // sidePanel.open() only works inside the click gesture, so it is called immediately and
    // never after an await.
    void browser.sidePanel.open({ tabId: tab.id });
    void runCaptureForTab({ id: tab.id, url: tab.url });
  });
});
