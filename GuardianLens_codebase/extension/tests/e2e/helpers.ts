// Helpers for the browser end-to-end tests: launching Chromium with the built extension loaded,
// mocking the GuardianLens API, the website, and the photo CDN (so no server is needed), and
// seeding a capture the way the service worker would.
import { chromium, type BrowserContext, type Page, type Route } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { sampleResult } from "../helpers/samples";

/** The folder `wxt build` writes the loadable extension to. */
const EXTENSION_PATH = fileURLToPath(new URL("../../.output/chrome-mv3", import.meta.url));

// A tiny JPEG-typed payload, served for photo requests so the panel can "download" photos offline.
// The panel only checks the type and size of a photo and the API is mocked, so these bytes never
// need to decode as a real picture.
const TINY_JPEG = Buffer.from(
  "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=",
  "base64",
);

/** Launches Chromium with the extension and returns its context and the extension id. */
export async function launchWithExtension(): Promise<{
  context: BrowserContext;
  extensionId: string;
}> {
  const userDataDir = mkdtempSync(path.join(os.tmpdir(), "guardianlens-e2e-"));
  const context = await chromium.launchPersistentContext(userDataDir, {
    // Playwright's Chromium in its "new headless" mode, which is the mode that supports extensions.
    channel: "chromium",
    args: [`--disable-extensions-except=${EXTENSION_PATH}`, `--load-extension=${EXTENSION_PATH}`],
  });
  let [worker] = context.serviceWorkers();
  if (!worker) worker = await context.waitForEvent("serviceworker");
  return { context, extensionId: new URL(worker.url()).host };
}

/**
 * The CORS headers a real server would send. The panel runs on a chrome-extension:// origin. In
 * real Chrome an extension with host permissions skips CORS, but a response FULFILLED by
 * Playwright is still CORS-checked, so the mocks answer the way the real API and CDN do.
 */
function corsHeaders(route: Route): Record<string, string> {
  return {
    "access-control-allow-origin": route.request().headers()["origin"] ?? "*",
    "access-control-allow-credentials": "true",
    "access-control-allow-headers": "content-type, x-session-token",
    "access-control-allow-methods": "GET, POST, OPTIONS",
  };
}

/** Counters a test can read to check what the mocked API received. */
export interface ApiCalls {
  assess: number;
}

/** Mocks the GuardianLens API on localhost:8000: session, assess, status, result. */
export async function mockApi(context: BrowserContext): Promise<ApiCalls> {
  const calls: ApiCalls = { assess: 0 };
  await context.route("http://localhost:8000/**", async (route) => {
    // Answer the browser's CORS preflight (sent before a request with a custom header).
    if (route.request().method() === "OPTIONS")
      return route.fulfill({ status: 204, headers: corsHeaders(route) });
    const { pathname } = new URL(route.request().url());
    // Answers the request with a JSON body and the CORS headers.
    const reply = (status: number, body: unknown) =>
      route.fulfill({
        status,
        contentType: "application/json",
        headers: corsHeaders(route),
        body: JSON.stringify(body),
      });
    if (pathname === "/api/v1/session") return reply(201, { session_token: "e2e-token" });
    if (pathname === "/api/v1/assess") {
      calls.assess += 1;
      return reply(202, { assessment_id: "e2e-1" });
    }
    if (pathname.endsWith("/status"))
      return reply(200, { status: "complete", stage: null, message: null });
    if (pathname.endsWith("/result")) return reply(200, sampleResult({ assessment_id: "e2e-1" }));
    return reply(404, {
      error: { code: "not_found", message: "Not found.", field: null },
    });
  });
  return calls;
}

/** Serves a blank page for the website, so the handoff tab opens without a real server. */
export async function mockSite(context: BrowserContext): Promise<void> {
  await context.route("http://localhost:3000/**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/html",
      body: "<html><body>site</body></html>",
    }),
  );
}

/** Serves a tiny JPEG for every photo request, or fails them all when `fail` is true. */
export async function mockPhotos(context: BrowserContext, fail = false): Promise<void> {
  await context.route("https://media.karousell.com/**", (route) =>
    fail
      ? route.abort()
      : route.fulfill({
          status: 200,
          contentType: "image/jpeg",
          headers: corsHeaders(route),
          body: TINY_JPEG,
        }),
  );
}

/** A finished listing capture, as the service worker would store it. */
export function listingJob(): unknown {
  // The URL of one captured photo, on a host the manifest permits.
  const photo = (name: string) => `https://media.karousell.com/media/photos/products/1/${name}.jpg`;
  return {
    id: 100,
    tabId: 1,
    status: "done",
    result: {
      kind: "listing",
      listing: {
        adapterVersion: "1",
        platform: "carousell",
        platformHost: "www.carousell.com.my",
        marketplaceListingId: "1234567890",
        title: { status: "captured", value: "Used laptop in good condition" },
        description: {
          status: "captured",
          value: "Original unit. COD available.",
        },
        price: { status: "captured", value: 1250 },
        category: { status: "captured", value: "Laptops" },
        imageUrls: [photo("a"), photo("b")],
        pageState: "ready",
      },
    },
  };
}

/** Writes a capture into session storage from an extension page, exactly as the service worker does. */
export async function seedCapture(page: Page, job: unknown): Promise<void> {
  await page.evaluate(async (value) => {
    const chromeApi = (
      globalThis as unknown as {
        chrome: { storage: { session: { set(items: object): Promise<void> } } };
      }
    ).chrome;
    await chromeApi.storage.session.set({ captureState: value });
  }, job);
}
