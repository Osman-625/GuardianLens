// WXT build configuration: how the extension's manifest is generated.
//
// Permissions are deliberately minimal and match the click-only capture design:
//   activeTab  - temporary access to the current tab, granted only when the buyer clicks the icon;
//   scripting  - lets that click inject the capture script into the tab;
//   storage    - keeps the session token and the unsent draft (cleared when the browser closes);
//   sidePanel  - shows the result next to the page.
// host_permissions lists ONLY hosts the extension itself fetches from: the GuardianLens API and
// the listing-photo CDNs. The Mudah.my and Carousell sites are NOT listed, so the extension has
// no standing access to them at install; it can read a listing on the click that grants
// activeTab. They are optional_host_permissions: the panel's "Capture this page" button asks for
// them once, in Chrome's own prompt, and the buyer can remove them again.
import { defineConfig } from "wxt";
import { IMAGE_HOST_PATTERNS, PAGE_HOST_PATTERNS } from "./lib/hosts";

// The API origin is a build-time setting (WXT_API_BASE_URL), so switching to a hosted API is a
// rebuild, not a code change.
const apiOrigin = new URL(process.env.WXT_API_BASE_URL ?? "http://localhost:8000").origin;

// PNG exports of the website's navy eye tile, without the wordmark.
const icons = {
  16: "icon/16.png",
  32: "icon/32.png",
  48: "icon/48.png",
  128: "icon/128.png",
};

export default defineConfig({
  modules: ["@wxt-dev/module-react"],
  manifest: {
    name: "GuardianLens",
    icons,
    description: "Check a Mudah.my or Carousell listing for warning signs before you pay.",
    permissions: ["activeTab", "scripting", "storage", "sidePanel"],
    host_permissions: [`${apiOrigin}/*`, ...IMAGE_HOST_PATTERNS],
    optional_host_permissions: PAGE_HOST_PATTERNS,
    // An action with no popup: clicking the icon fires action.onClicked (entrypoints/background.ts).
    action: { default_title: "Check this listing with GuardianLens", default_icon: icons },
  },
});
