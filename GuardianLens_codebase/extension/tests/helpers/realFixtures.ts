// Helpers for tests that read page fixtures.
//
// Two kinds of fixture exist:
//  - synthetic: small hand-written pages in tests/fixtures/synthetic/. Committed; always run.
//  - real: pages recorded from live Mudah.my / Carousell with fixtures/record-fixture.js. They
//    hold third-party listing text, so they are git-ignored and live only on the developer's
//    machine. Tests built on them skip themselves when none are present.
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import type { Platform } from "@guardianlens/shared";

// Paths are resolved from the working directory, which is the extension package whenever the tests
// run (`npm run test -w extension`). import.meta.url is not a file: URL under the jsdom test
// environment, so it cannot be used to locate these folders.
const REAL_ROOT = resolve(process.cwd(), "fixtures/real");
const SYNTHETIC_ROOT = resolve(process.cwd(), "tests/fixtures/synthetic");

/** What a human read off the live page when recording it (see fixtures/README.md). Null = not shown. */
export interface ExpectedFixture {
  /** Date the page was recorded (YYYY-MM-DD); account-age tests use it as "today". */
  recordedOn: string;
  platform: Platform;
  title: string | null;
  priceRm: number | null;
  category: string | null;
  descriptionStartsWith: string | null;
  imageCountAtLeast: number | null;
  seller: {
    accountAgeDays: number | null;
    rating: number | null;
    reviewCount: number | null;
    activeListingCount: number | null;
  };
}

/** One recorded page set: fixtures/real/<platform>/<slug>/. */
export interface RealFixture {
  platform: Platform;
  slug: string;
  dir: string;
  expected: ExpectedFixture;
}

/** Lists every real fixture folder that has an expected.json; empty when none are recorded. */
export function listRealFixtures(): RealFixture[] {
  if (!existsSync(REAL_ROOT)) return [];
  const fixtures: RealFixture[] = [];
  for (const platform of ["mudah", "carousell"] as const) {
    const platformDir = join(REAL_ROOT, platform);
    if (!existsSync(platformDir)) continue;
    for (const slug of readdirSync(platformDir)) {
      const dir = join(platformDir, slug);
      const expectedPath = join(dir, "expected.json");
      if (!existsSync(expectedPath)) continue;
      const expected = JSON.parse(readFileSync(expectedPath, "utf8")) as ExpectedFixture;
      fixtures.push({ platform, slug, dir, expected });
    }
  }
  return fixtures;
}

/** Reads a recorded page's HTML, or null when that file was not recorded. */
export function readFixtureHtml(fixture: RealFixture, name: "listing" | "seller"): string | null {
  const path = join(fixture.dir, `${name}.html`);
  return existsSync(path) ? readFileSync(path, "utf8") : null;
}

/** Parses an HTML string into a document, the way the capture script sees a live page. */
export function parseHtml(html: string): Document {
  return new DOMParser().parseFromString(html, "text/html");
}

/** Loads one committed synthetic fixture page by file name (without ".html"). */
export function loadSynthetic(name: string): Document {
  return parseHtml(readFileSync(join(SYNTHETIC_ROOT, `${name}.html`), "utf8"));
}
