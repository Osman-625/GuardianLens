// Playwright settings for the browser end-to-end tests (tests/e2e). They load the BUILT extension
// into Chromium, so run them with `npm run test:e2e`, which builds first. One worker only: each
// test launches its own Chromium with the extension, and extensions need a full profile.
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: { trace: "retain-on-failure" },
});
