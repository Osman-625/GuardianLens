// Side panel root: builds the REAL dependencies once (the API client with the header session
// transport, real photo downloads, session storage, and the tab opener) and renders the panel.
// Tests render PanelApp with fakes instead, so nothing here needs a browser to be verified.
import { createClient } from "@guardianlens/shared";
import { captureActiveTab } from "@/lib/capture/runner";
import { API_BASE_URL, SITE_BASE_URL } from "@/lib/config";
import type { ControllerDeps } from "@/lib/panel/controller";
import { browserPhotoDeps } from "@/lib/panel/photos";
import { panelStorage } from "@/lib/panel/storage";
import { tokenStore } from "@/lib/storage";
import { PanelApp } from "./PanelApp";

// Created once at module load, so the object stays the same for the life of the panel and the
// controller's effects do not restart.
const deps: ControllerDeps = {
  client: createClient({
    baseUrl: API_BASE_URL,
    transport: { kind: "header", store: tokenStore },
  }),
  photoDeps: browserPhotoDeps,
  storage: panelStorage,
  openUrl: (url) => void browser.tabs.create({ url }),
  captureActiveTab: async () => void (await captureActiveTab()),
  siteBaseUrl: SITE_BASE_URL,
};

/** The side panel's root component. */
export function App() {
  return <PanelApp deps={deps} />;
}
