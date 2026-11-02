// End-to-end tests in a real Chromium with the BUILT extension. They open the side panel page
// directly as a tab (Playwright cannot click the toolbar icon) and seed a capture, then drive the
// real UI against a mocked API. What they prove that unit tests cannot: the built manifest and
// permissions let the panel fetch photos and the API, the real storage events reach the panel, and
// the handoff tab opens with the session in the URL fragment.
import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  launchWithExtension,
  listingJob,
  mockApi,
  mockPhotos,
  mockSite,
  seedCapture,
} from "./helpers";

test("capture to result to website handoff", async () => {
  const { context, extensionId } = await launchWithExtension();
  await mockApi(context);
  await mockPhotos(context);
  await mockSite(context);
  const page = await context.newPage();
  await page.goto(`chrome-extension://${extensionId}/sidepanel.html`);

  await expect(page.getByText("Open a Mudah.my or Carousell listing")).toBeVisible();
  await seedCapture(page, listingJob());
  await expect(page.getByText("Check the captured details")).toBeVisible();
  await page.getByRole("button", { name: "Check listing" }).click();

  const region = page.getByRole("region", {
    name: "Score 58 out of 100, moderate risk",
  });
  await expect(region).toBeVisible();
  await expect(region.getByText(/Decision support only/)).toBeVisible();

  const opened = context.waitForEvent("page");
  await page.getByRole("button", { name: "See full explanation" }).click();
  // A new tab starts at about:blank, so wait for it to reach the website instead of reading the URL at once.
  await expect(await opened).toHaveURL(
    "http://localhost:3000/assess/e2e-1/explanation#st=e2e-token",
  );
  await context.close();
});

test("photos that cannot be downloaded block the check with a clear message", async () => {
  const { context, extensionId } = await launchWithExtension();
  const calls = await mockApi(context);
  await mockPhotos(context, true);
  const page = await context.newPage();
  await page.goto(`chrome-extension://${extensionId}/sidepanel.html`);

  await seedCapture(page, listingJob());
  await page.getByRole("button", { name: "Check listing" }).click();

  // Matched by its opening words so this spec does not import application code (and React) into the test runner.
  await expect(page.getByText(/None of the selected photos could be read/)).toBeVisible();
  // The title the buyer saw is still there, and nothing was sent to the API.
  await expect(page.getByLabel("Title")).toHaveValue("Used laptop in good condition");
  expect(calls.assess).toBe(0);
  await context.close();
});

// The capture boundary, checked on the BUILT manifest (not on the source): the extension has no
// standing access to the marketplace sites. It reads a page only through the buyer's click
// (activeTab), so no marketplace host may appear in host_permissions, and nothing may run
// automatically on those sites (no content scripts).
test("the built manifest gives no standing access to the marketplace sites", () => {
  const manifestPath = fileURLToPath(
    new URL("../../.output/chrome-mv3/manifest.json", import.meta.url),
  );
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as {
    permissions?: string[];
    host_permissions?: string[];
    content_scripts?: unknown[];
  };
  const marketplace = /(^|[/.*])(mudah\.my|carousell\.com\.my)\//i;
  for (const pattern of manifest.host_permissions ?? []) {
    expect(pattern, `${pattern} must not cover a marketplace site`).not.toMatch(marketplace);
  }
  expect(manifest.content_scripts ?? []).toEqual([]);
  expect([...(manifest.permissions ?? [])].sort()).toEqual([
    "activeTab",
    "scripting",
    "sidePanel",
    "storage",
  ]);
});
