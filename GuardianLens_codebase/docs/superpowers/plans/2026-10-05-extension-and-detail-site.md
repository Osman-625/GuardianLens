# GuardianLens Extension and Detail Site Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A buyer clicks the GuardianLens extension icon on a Mudah.my or Carousell listing, reviews the captured fields in a side panel, runs the existing assessment pipeline, and opens the full explanation on the website without a login.

**Architecture:** One npm-workspaces repo with three clients over the existing FastAPI service: `extension/` (WXT, React, Manifest V3, side panel, click-only capture through `activeTab`), `frontend/` (existing Next.js site, repurposed as the detail and fallback surface), and `shared/` (types, API client, handoff logic, design tokens, and presentational components used by both). The backend gains a header-based session token, a session claim endpoint for the website handoff, and `source` and `capture_meta` fields on `POST /assess`. Everything runs on the stub pipeline and the in-memory repository; real inference and Supabase are separate plans.

**Tech Stack:** Python 3.13 (FastAPI 0.128.2, pytest), Node 24, TypeScript 5.9.3, React 19.2.0, Next 16.2.10, WXT 0.21.4, Vite 7.3.6, Vitest 5.0.3 with jsdom 30.1.2, Testing Library, Playwright 1.63.0.

**Spec:** `docs/superpowers/specs/2026-10-05-extension-and-detail-site-design.md` (read it first; this plan implements sections 1 to 7 and 9 to 12 of it, slices 0 to 4 of its build order). Section 8 of the spec (model serving) is a separate plan.

## Global Constraints

Every task's requirements implicitly include this section. Values are copied from the spec unless marked as a developer instruction.

- **Comments (developer instruction, 2026-10-05).** Every code file starts with a header comment saying what the file is for and what uses it. Every exported function, class, type, and component has a doc comment saying what it does, what it takes, and what it returns. Non-obvious blocks carry a short comment explaining why, not what. Test files start with a comment saying which behaviour they pin, and each `describe` group says which rule it covers. When a later task or a fix changes code, rewrite the affected comment in place so it describes the current behaviour. Never stack "updated" notes beside an old comment, never leave a stale comment behind, and never make a comment-only commit: a comment change goes in the same commit as the code change that caused it. JSON files cannot hold comments, so the task text beside them explains their fields. The code blocks in this plan already carry their comments; keep them when you type or edit the code.
- Capture happens on the buyer's click only, for one listing, with no crawling, no background scraping, and no automatic navigation.
- Extension permissions are `activeTab`, `scripting`, `storage`, and `sidePanel`. `host_permissions` hold only the API origin and the listing-photo CDN hosts. The Mudah.my and Carousell hosts are never in `host_permissions`; the capture script is injected through `activeTab`. The capture script is an unlisted script injected with `scripting.executeScript`, never a `defineContentScript` (a content script with `registration: 'runtime'` would add the platform hosts to `host_permissions`).
- The score is an integer from 0 to 100, never a decimal. Risk is communicated by text, number, and icon; colour is never the only carrier. The disclaimer is content inside the result region, not a banner. Unavailable signals read exactly: "Not enough information. Treated as unknown, not as suspicious." Missing data is unknown, never suspicious and never safe. Errors never discard entered input.
- The development-stub warning stays visible until a real model bundle is served.
- Category is free text. The 12 trained categories (Phones, Gaming, Home Appliances, Laptops, Fashion, Audio, Cameras, Sports, Wearables, Tablets, Collectibles, Other) are suggestions only; any other category is accepted. A category outside the trained 12 shows the note "Price is compared with the overall average, not this category's average."
- Photos: at most 3, at most 5 MB each; the extension re-encodes to JPEG when needed.
- Title at most 180 characters, description at most 5000, category at most 80.
- `capture_meta` stores the platform host only, never the listing URL. Allowed hosts: `mudah.my`, `www.mudah.my`, `carousell.com.my`, `www.carousell.com.my`.
- Session: an opaque UUID. Header `X-Session-Token` or the httpOnly cookie. `POST /api/v1/session` returns `{ session_token }`. `POST /api/v1/session/claim` takes `{ token }` and sets the cookie. The website handoff URL is `/assess/{id}/explanation#st=<token>` (optionally `&signal=visual|textual|behavioural`); the fragment is removed with `history.replaceState` before anything else happens.
- The side panel is a single column about 360 to 420 px wide; the website is verified at 375, 768, and 1440 px. English UI only. WCAG 2.1 AA, visible focus, touch targets at least 44 px, and `prefers-reduced-motion` respected.
- Every markdown file under `docs/` and `README.md` must contain no em dash and no en dash (`python scripts/check_prose.py` enforces it).
- Python is `>=3.12,<3.14` (use 3.13). ruff line length 100, mypy strict.
- Pinned versions: TypeScript 5.9.3, React and React DOM 19.2.0, `@types/react` and `@types/react-dom` 19.2.2, `@types/node` 24.10.0, Next 16.2.10, WXT 0.21.4, `@wxt-dev/module-react` 1.2.2, Vite 7.3.6, Vitest 5.0.3, jsdom 30.1.2, `@testing-library/react` 16.3.3, `@testing-library/jest-dom` 7.0.1, `@testing-library/user-event` 14.6.7, `@playwright/test` 1.63.0.
- Git: the repository root is `04_System_Workspaces/`; all paths in this plan are relative to `GuardianLens_codebase/`, the directory every command assumes you are in. Work on the branch `feat/extension-and-detail-site`. Commit messages follow the Co-Authored-By trailer rule of the executing session; the examples below omit the trailer for brevity.
- Commands are written for Git Bash (forward slashes). They also work in PowerShell unless noted.

## Review Focus

Failure modes the spec implies but a happy-path build would not exercise, most likely first. Each one has a pinning test in the task named in brackets.

1. **Prices that are not `RM 1,250`:** "RM1250.50", "MYR 99", a range "RM 1,200 - RM 1,500", "Free", "Negotiable", or no price at all. The panel must never invent `0`; an unparseable or ambiguous price is "Not found" and the buyer types it. [Task 8, Task 12]
2. **Photos that cannot be read:** CDN host not permitted, hotlink blocked, `data:` or SVG sources, a 12 MB original, an AVIF the API rejects, or every photo failing. The check proceeds with the photos that worked, tells the buyer how many were skipped, and blocks with a clear message only when none work. [Task 8, Task 13, Task 15]
3. **Text over the API limits:** a captured description of 6,000 characters. It must not be silently truncated; the Review state shows the counter and a field error and blocks submission. [Task 12]
4. **Stale session after a backend restart:** the stored token is unknown to the new process. The client mints a new session and retries the submission once; the buyer sees no error. [Task 3, Task 4]
5. **Double submission:** a second click or Enter press while the first request is in flight must not create a second assessment. [Task 14]

---

## File Structure

```text
GuardianLens_codebase/
  package.json                       npm workspaces root (new)
  package-lock.json                  generated; replaces frontend/package-lock.json
  shared/                            new workspace package @guardianlens/shared
    package.json  tsconfig.json  vitest.config.ts
    src/index.ts                     public exports
    src/types.ts                     API and capture-meta types
    src/categories.ts                12 trained categories, matcher, resolver
    src/api.ts                       createClient, GuardianLensApiError, TokenStore
    src/claim.ts                     handoff URL build, parse, claim
    src/copy.ts                      stage labels, band copy, shared sentences
    src/styles.css                   tokens + shared component styles
    src/components/                  BandChip, ScoreRegion, SignalCardView, StageList,
                                     DevBanner, CategoryField
    tests/                           vitest + Testing Library
  extension/                         new workspace package @guardianlens/extension
    package.json  wxt.config.ts  tsconfig.json  vitest.config.ts  playwright.config.ts
    entrypoints/background.ts        opens the panel, starts capture on click
    entrypoints/capture.ts           unlisted script injected on click
    entrypoints/sidepanel/           index.html, main.tsx, App.tsx, PanelApp.tsx, panel.css, views/
    lib/config.ts  lib/hosts.ts  lib/storage.ts
    lib/capture/                     classify, values, images, seller, listing, selectors, page,
                                     runner, types
    lib/panel/                       draft, photos, errors, reducer, check, storage, controller
    tests/                           unit, component, helpers/, synthetic fixtures, e2e
    fixtures/                        record-fixture.js, README; real/ is git-ignored
    docs/SPIKE_NOTES.md              findings from Task 1
    scripts/package-for-site.mjs
  frontend/                          existing Next.js site (modified)
  api/                               existing FastAPI service (modified)
```

Responsibilities worth fixing now, because later tasks depend on these exact names:

- `extension/lib/capture/classify.ts` exports `platformFromHost`, `classifyListingUrl`, `classifySellerUrl`.
- `extension/lib/capture/values.ts` exports `normalizeText`, `textOf`, `parsePriceRm`, `parsePriceValue`.
- `extension/lib/capture/images.ts` exports `selectGalleryImages`.
- `extension/lib/capture/seller.ts` exports `parseAccountAgeDays`, `parseReviewStats`, `countActiveListings`, `parseSellerPage`.
- `extension/lib/capture/listing.ts` exports `captureListing`, `detectPageState`.
- `extension/lib/capture/page.ts` exports `captureCurrentPage`.
- `extension/lib/capture/runner.ts` exports `runCaptureForTab`.
- `extension/lib/capture/selectors.ts` exports `PLATFORM_SELECTORS`; `extension/lib/capture/types.ts` exports the capture types, `ADAPTER_VERSION`, and `CAPTURE_MESSAGE`.
- `extension/lib/panel/draft.ts` exports `draftFromListing`, `applySeller`, `editField`, `togglePhoto`, `validateDraft`, `buildCaptureMeta`, `buildForm`, `parsePriceInput`, `LIMITS`.
- `extension/lib/panel/photos.ts` exports `preparePhotos`, `browserPhotoDeps`, `MAX_PHOTO_BYTES`.
- `extension/lib/panel/errors.ts` exports `mapApiError`, `NO_PHOTOS_MESSAGE`, `FAILED_MESSAGE`.
- `extension/lib/panel/reducer.ts` exports `panelReducer`, `initialPanelState`.
- `extension/lib/panel/check.ts` exports `runCheck`, `POLL_INTERVAL_MS`, `SLOW_AFTER_MS`, `GIVE_UP_AFTER_MS`.
- `extension/lib/panel/storage.ts` exports `panelStorage` and the `PanelStorage` and `SavedPanel` types.
- `extension/lib/panel/controller.ts` exports `usePanelController` and the `ControllerDeps` and `PanelActions` types.

---

### Task 0: Branch and baseline

**Files:** none created or modified except the commit of the spec and this plan.

**Interfaces:**
- Consumes: nothing.
- Produces: branch `feat/extension-and-detail-site`, a working Python 3.13 virtual environment at `.venv`, and a recorded baseline of what passes before any change.

- [ ] **Step 1: Create the branch**

```bash
cd "C:/Users/cusma/OneDrive/Desktop/FYP Project/04_System_Workspaces/GuardianLens_codebase"
git switch -c feat/extension-and-detail-site
```

Expected: `Switched to a new branch 'feat/extension-and-detail-site'`.

- [ ] **Step 2: Commit the spec and this plan**

```bash
git add docs/superpowers
git commit -m "docs: add extension and detail site spec and plan"
```

- [ ] **Step 3: Create the Python environment**

The machine default is Python 3.14, which `pyproject.toml` excludes. `uv` downloads 3.13.

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements-dev.txt
.venv/Scripts/python --version
```

Expected: `Python 3.13.x`.

- [ ] **Step 4: Record the backend baseline**

```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check api ml scripts
.venv/Scripts/python -m mypy api ml/src/guardianlens_ml
.venv/Scripts/python scripts/check_prose.py
.venv/Scripts/python scripts/secret_scan.py
```

Expected: pytest reports all passed with no failures, ruff and mypy report no errors, both scripts print their passed message. If any command already fails before you touch anything, write the exact failure into your notes, do not fix it, and mention it in the Task 4 commit message.

- [ ] **Step 5: Record the frontend baseline**

```bash
cd frontend
npm ci
npm run lint
npm run typecheck
npm run build
cd ..
```

Expected: all four succeed. `npm run build` creates `frontend/.next`, which is git-ignored.

---

### Task 1: Real-page spike and local fixtures

This task answers the questions the spec lists in section 3.4, using real pages, before any adapter code is trusted. Its deliverables are a fixture recorder, a findings document, and local-only fixtures. It writes no production code.

**Files:**
- Create: `extension/fixtures/record-fixture.js`
- Create: `extension/fixtures/README.md`
- Create: `extension/docs/SPIKE_NOTES.md`
- Create (local only, git-ignored): `extension/fixtures/real/<platform>/<slug>/{listing.html,seller.html,expected.json}`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces: `extension/docs/SPIKE_NOTES.md` sections that later tasks read: `Image hosts` (Task 7), `Description and category selectors` (Task 10), `Seller page phrases` (Task 9), `Seller page URL shapes` (Task 8). The `expected.json` schema in Step 6 is what Task 10 and Task 9 real-fixture tests read.

**Rules for this task.** Browse as a normal buyer. Do not log in as a private profile you do not want recorded, do not solve or bypass a CAPTCHA, and stop and report if a platform blocks you. Do not run the recorder while viewing your own account pages. Fixtures contain third-party listing text, so they never go into git.

- [ ] **Step 1: Ignore local fixtures and build output**

Append to `.gitignore`:

```gitignore

# Browser extension, shared package, workspaces
# node_modules and build output are generated; real fixtures hold third-party
# listing text and must never be committed.
node_modules/
extension/.output/
extension/.wxt/
extension/fixtures/real/
extension/playwright-report/
extension/test-results/
frontend/public/downloads/
```

- [ ] **Step 2: Create the fixture recorder**

`extension/fixtures/record-fixture.js`:

```js
// Fixture recorder (developer tool, not part of the shipped extension).
//
// What it does: copies the page you are looking at into a sanitised, self-contained HTML
// file so the adapter tests can run against a real Mudah.my or Carousell page without
// needing a network or a login.
//
// How to use: paste this whole file into the DevTools console on a live page, then run
//   recordFixture("listing")   on a listing page, or
//   recordFixture("seller")    on a seller / profile page.
// The browser downloads "<host>-<kind>.html". Open it and check it for personal data before
// using it. Recorded files stay local and are never committed.
(() => {
  // Elements that must never be dropped for being "hidden" (they are not rendered anyway).
  const SKIP_HIDING = new Set(["HTML", "HEAD", "BODY", "SCRIPT", "STYLE", "META", "LINK", "TITLE", "NOSCRIPT"]);
  // Contact details are redacted in every text node, in case the page shows them.
  const EMAIL = /[\w.+-]+@[\w-]+\.[\w.-]+/g;
  const PHONE = /(?<!\d)(?:\+?6?0?1\d[\s.-]?)\d{7,8}(?!\d)/g;

  window.recordFixture = function recordFixture(kind) {
    // Clone the live document, then walk both trees in parallel (same order, same length)
    // so we can read computed layout from the live element and write it onto the copy.
    const liveAll = Array.from(document.documentElement.querySelectorAll("*"));
    const clone = document.documentElement.cloneNode(true);
    const cloneAll = Array.from(clone.querySelectorAll("*"));
    if (liveAll.length !== cloneAll.length) throw new Error("The page changed while cloning. Try again.");

    const hidden = [];
    liveAll.forEach((live, index) => {
      const copy = cloneAll[index];
      if (live.tagName === "IMG") {
        // Stamp the rendered size onto the copy. jsdom has no layout engine, so the tests
        // use these width/height attributes to tell gallery photos from small icons.
        const rect = live.getBoundingClientRect();
        copy.setAttribute("width", String(Math.round(rect.width)));
        copy.setAttribute("height", String(Math.round(rect.height)));
        // Pin the URL the browser actually chose (srcset picks one at runtime).
        const source = live.currentSrc || live.src;
        if (source) copy.setAttribute("src", source);
        copy.removeAttribute("srcset");
        copy.removeAttribute("sizes");
      }
      // Elements hidden by CSS are not part of what a buyer sees, so they are dropped.
      if (!SKIP_HIDING.has(live.tagName) && getComputedStyle(live).display === "none") hidden.push(copy);
    });
    hidden.forEach((node) => node.remove());

    // Strip everything the adapters never read. JSON-LD scripts are kept on purpose:
    // they are one of the main data sources for title, price, and photos.
    clone
      .querySelectorAll("script:not([type='application/ld+json']), style, noscript, iframe, svg, link[rel='stylesheet']")
      .forEach((node) => node.remove());
    clone.querySelectorAll("[style]").forEach((node) => node.removeAttribute("style"));

    // Redact contact details in text and drop HTML comments.
    const walker = document.createTreeWalker(clone, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_COMMENT);
    const comments = [];
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (node.nodeType === Node.COMMENT_NODE) comments.push(node);
      else node.nodeValue = node.nodeValue.replace(EMAIL, "[email]").replace(PHONE, "[phone]");
    }
    comments.forEach((node) => node.remove());

    // Download the result as a file.
    const html = "<!doctype html>\n" + clone.outerHTML;
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([html], { type: "text/html" }));
    link.download = `${location.hostname}-${kind}.html`;
    link.click();
    URL.revokeObjectURL(link.href);
    return { kind, characters: html.length, host: location.hostname };
  };
})();
```

- [ ] **Step 3: Create the fixtures README**

`extension/fixtures/README.md`:

```markdown
# Local page fixtures

`record-fixture.js` records a sanitised copy of a live page for adapter tests.

- Recorded pages live in `fixtures/real/<platform>/<slug>/` and are git-ignored because they
  contain third-party listing content. Do not commit them.
- Each slug folder holds `listing.html`, `seller.html`, and `expected.json`.
- Tests that read these folders skip themselves when the folder is missing. The committed
  synthetic fixtures in `tests/fixtures/synthetic/` always run.
- Before using a recorded file, open it and check for names, phone numbers, emails, and
  profile links you do not want on disk. Redact by hand if needed.

`expected.json` schema (null where the page does not show the value):

    {
      "recordedOn": "2026-10-05",
      "platform": "carousell",
      "title": "exact visible title",
      "priceRm": 1250,
      "category": "category text as the platform shows it",
      "descriptionStartsWith": "first 40 characters of the description",
      "imageCountAtLeast": 3,
      "seller": { "accountAgeDays": 1155, "rating": 4.8, "reviewCount": 17, "activeListingCount": 4 }
    }
```

- [ ] **Step 4: Choose the listings**

In your own Chrome, pick three current listings per platform (six total):

1. a complete listing with at least three photos and a visible seller card;
2. a listing with exactly one photo;
3. a listing whose category is outside the 12 trained categories (for example pets, property, or services).

If a sold, removed, or login-gated listing is easy to find, record one extra per platform as `unavailable`.

- [ ] **Step 5: Record the pages**

For each listing: open it, scroll through the whole photo gallery so lazy images load, open DevTools (F12), paste `record-fixture.js` into the console, and run `recordFixture("listing")`. Then open that listing's seller or profile page from its own seller link, scroll until the listings section has loaded, and run `recordFixture("seller")`. Move the two downloaded files into `extension/fixtures/real/<platform>/<slug>/` as `listing.html` and `seller.html`. Use short slugs such as `phone-complete`, `one-photo`, `other-category`.

Confirm git ignores them:

```bash
git status --short extension/fixtures
```

Expected: no `fixtures/real` paths listed.

- [ ] **Step 6: Write expected.json for each slug**

Read the values from the live page by eye and write `expected.json` in each slug folder using the schema in `extension/fixtures/README.md`. Use `null` for anything the page does not show. `priceRm` is a number, `accountAgeDays` is days using 1 year = 365 and 1 month = 30 (a stated duration), or days from a stated join date to today.

- [ ] **Step 7: Answer the spec questions in SPIKE_NOTES.md**

On each live listing page run these in the console and copy the results:

```js
// image hosts used by the photos on the page
[...new Set([...document.images].map((i) => new URL(i.currentSrc || i.src, location.href).host))]
// structured data types present
[...document.querySelectorAll('script[type="application/ld+json"]')].map((s) => s.textContent.slice(0, 120))
```

Then create `extension/docs/SPIKE_NOTES.md` with exactly these sections, filled from what you observed (no personal data):

```markdown
# Real-page spike notes (2026-10)

## Listing fields
For Mudah.my and Carousell: for each of title, price, description, category, and photos, state
whether it comes from JSON-LD, a meta tag, or the visible DOM, and give the selector or JSON path.

## Description and category selectors
The CSS selectors to add to `PLATFORM_SELECTORS` (Task 10) when JSON-LD does not carry them.

## Image hosts
Every host that served a listing photo, one per line, as seen in the console output.

## Seller page URL shapes
The path pattern of the seller or profile page on each platform, and whether the listing page
links to it.

## Seller page phrases
The exact wording the seller page uses for account age, rating, review count, and the listings
section, including the "no reviews yet" and "sold" wordings. These drive Task 9.

## Seller data on the listing page
Whether any of account age, rating, review count, or listing count appears on the listing page itself.

## Blocking and login behaviour
Anything that looked like a CAPTCHA, access-denied, or login wall, and on which pages.
```

- [ ] **Step 8: Commit**

```bash
git add .gitignore extension/fixtures/README.md extension/fixtures/record-fixture.js extension/docs/SPIKE_NOTES.md
git commit -m "docs: record real-page spike notes and fixture recorder"
```

Platform behaviour of the toolbar icon, side panel, and `activeTab` is verified later in Task 7, once there is an extension to load.

---

### Task 2: Workspaces and the shared types and categories

**Files:**
- Create: `package.json`, `shared/package.json`, `shared/tsconfig.json`, `shared/vitest.config.ts`
- Create: `shared/src/index.ts`, `shared/src/types.ts`, `shared/src/categories.ts`
- Create: `shared/tests/setup.ts`, `shared/tests/categories.test.ts`
- Modify: `frontend/package.json`, `frontend/lib/types.ts`, `frontend/next.config.ts`, `Makefile`
- Delete: `frontend/package-lock.json`

**Interfaces:**
- Consumes: nothing.
- Produces (from `@guardianlens/shared`): types `RiskBand`, `PipelineStage`, `SignalName`, `AssessmentStatus`, `FeedbackVerdict`, `Platform`, `PlatformHost`, `ApiError`, `SignalReason`, `SignalCard`, `AssessmentResult`, `HistoryItem`, `AssessmentStatusResponse`, `SessionCreated`, `FeedbackRequest`, `CaptureFieldName`, `CaptureFieldStatus`, `CaptureMetaPayload`; values `TRAINED_CATEGORIES`, `isTrainedCategory(value: string): boolean`, `matchTrainedCategory(text: string | null | undefined): TrainedCategory | null`, `resolveCategory(text: string | null | undefined): string`.

- [ ] **Step 1: Write the failing categories test**

`shared/tests/categories.test.ts`:

```ts
// Pins the category rules shared by the website form and the extension:
//  - the models were trained on 12 categories, but the product accepts ANY category text;
//  - a platform's own category wording is mapped to a trained category when an obvious
//    keyword matches (so the price comparison can use the right category average);
//  - when nothing matches, the platform's own text is kept as typed, never replaced or dropped.
import { describe, expect, it } from "vitest";
import {
  TRAINED_CATEGORIES,
  isTrainedCategory,
  matchTrainedCategory,
  resolveCategory,
} from "../src/categories";

// The list itself: it must stay in sync with the categories in the training data.
describe("TRAINED_CATEGORIES", () => {
  it("lists the twelve categories the models were trained on", () => {
    expect(TRAINED_CATEGORIES).toHaveLength(12);
    expect(TRAINED_CATEGORIES).toContain("Home Appliances");
    expect(TRAINED_CATEGORIES).toContain("Other");
  });
});

// Keyword matching: real platform category wording on the left, trained category on the right.
describe("matchTrainedCategory", () => {
  it.each([
    ["Mobile Phones & Gadgets", "Phones"],
    ["iPad Air tablet", "Tablets"],
    ["Home Appliances & Kitchen", "Home Appliances"],
    ["Hobby & Collectibles", "Collectibles"],
    ["Computers > Laptops", "Laptops"],
    ["Smart Watches", "Wearables"],
    ["Cameras & Photography", "Cameras"],
    ["Headphones", "Audio"],
  ])("maps %s to %s", (text, expected) => {
    expect(matchTrainedCategory(text)).toBe(expected);
  });

  it("returns null when nothing matches", () => {
    expect(matchTrainedCategory("Gardening supplies")).toBeNull();
  });

  it("returns null for empty and missing input", () => {
    expect(matchTrainedCategory("")).toBeNull();
    expect(matchTrainedCategory(null)).toBeNull();
    expect(matchTrainedCategory(undefined)).toBeNull();
  });
});

// resolveCategory is what the extension prefills into the Category field.
describe("resolveCategory", () => {
  it("prefers a trained category", () => {
    expect(resolveCategory("Mobile Phones & Gadgets")).toBe("Phones");
  });

  it("keeps the platform's own text, trimmed, when nothing matches", () => {
    expect(resolveCategory("  Gardening supplies ")).toBe("Gardening supplies");
  });

  it("returns an empty string when there is no text", () => {
    expect(resolveCategory(null)).toBe("");
  });
});

// isTrainedCategory drives the "price is compared with the overall average" note.
describe("isTrainedCategory", () => {
  it("ignores case and surrounding spaces", () => {
    expect(isTrainedCategory(" phones ")).toBe(true);
  });

  it("is false for any other category", () => {
    expect(isTrainedCategory("Pets")).toBe(false);
  });
});
```

- [ ] **Step 2: Create the workspace files**

`package.json` (codebase root). JSON cannot hold comments, so the fields are explained here: `private` stops the workspace root from being published; `workspaces` lists the packages npm links together (`shared` is imported by `frontend`, and later by `extension`, as `@guardianlens/shared`; `extension` joins this list in Task 7, when its folder gets a `package.json`, because npm cannot link a folder that has none); each script runs the same-named script in every workspace that defines one, so `npm test` at the root runs all test suites.

```json
{
  "name": "guardianlens-workspace",
  "private": true,
  "workspaces": ["shared", "frontend"],
  "scripts": {
    "test": "npm run test --workspaces --if-present",
    "lint": "npm run lint --workspaces --if-present",
    "typecheck": "npm run typecheck --workspaces --if-present",
    "build": "npm run build --workspaces --if-present"
  }
}
```

`shared/package.json`. Fields explained: `exports` points straight at TypeScript source, so Next.js (through `transpilePackages`) and Vite (WXT) compile the package with the app that imports it and there is no separate build step; `./styles.css` is the shared design tokens and component styles; `react` and `react-dom` are peer dependencies because the consuming app owns the React copy; the dev dependencies are only for the package's own tests.

```json
{
  "name": "@guardianlens/shared",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "exports": {
    ".": "./src/index.ts",
    "./styles.css": "./src/styles.css"
  },
  "scripts": {
    "test": "vitest run",
    "typecheck": "tsc --noEmit"
  },
  "peerDependencies": {
    "react": "19.2.0",
    "react-dom": "19.2.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "7.0.1",
    "@testing-library/react": "16.3.3",
    "@testing-library/user-event": "14.6.7",
    "@types/node": "24.10.0",
    "@types/react": "19.2.2",
    "@types/react-dom": "19.2.2",
    "jsdom": "30.1.2",
    "react": "19.2.0",
    "react-dom": "19.2.0",
    "typescript": "5.9.3",
    "vite": "7.3.6",
    "vitest": "5.0.3"
  }
}
```

`shared/tsconfig.json` (comments are allowed in tsconfig files):

```jsonc
{
  // Type-check only: the apps that import this package compile it, so nothing is emitted here.
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "esnext"],
    "module": "esnext",
    // "bundler" resolution understands package "exports" that point at .ts source.
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noEmit": true,
    "skipLibCheck": true,
    "isolatedModules": true,
    "esModuleInterop": true
  },
  "include": ["src", "tests"]
}
```

`shared/vitest.config.ts`:

```ts
// Test runner settings for the shared package.
// jsdom gives component tests a browser-like document. Tests that need Node's own
// fetch/Response/FormData (the API client tests) opt out with a
// `// @vitest-environment node` comment on their first line.
import { defineConfig } from "vitest/config";

export default defineConfig({
  // Compile JSX with the automatic runtime so test files do not import React.
  esbuild: { jsx: "automatic" },
  test: {
    environment: "jsdom",
    // Registers the jest-dom matchers and unmounts rendered components after each test.
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
  },
});
```

`shared/tests/setup.ts`:

```ts
// Runs before every test file in this package.
// 1. Adds the jest-dom matchers (toBeInTheDocument, toHaveAccessibleName, ...) to expect().
// 2. Unmounts anything a test rendered so tests cannot affect each other. Testing Library
//    only does this on its own when test globals are enabled, and we keep them off.
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => cleanup());
```

- [ ] **Step 3: Install and confirm the test fails**

```bash
git rm frontend/package-lock.json
npm install
npm run test -w shared
```

Expected: the run fails with a message that `../src/categories` cannot be resolved.

- [ ] **Step 4: Write the shared types**

`shared/src/types.ts`:

```ts
// Shared type definitions: the shapes the FastAPI service sends and receives, plus the
// small "capture metadata" record the extension attaches to a submission.
// Used by the website, the extension, and the API client. Keep these in step with
// api/schemas.py: when a field changes there, change it here in the same commit.

/** The three risk bands the fused score maps to. */
export type RiskBand = "low" | "moderate" | "high";

/** The five processing stages, in the order the API reports them. */
export type PipelineStage = "visual" | "textual" | "behavioural" | "fusion" | "explanation";

/** The three independent signals shown as cards. */
export type SignalName = "visual" | "textual" | "behavioural";

/** Lifecycle of one assessment on the server. */
export type AssessmentStatus = "processing" | "complete" | "failed" | "abandoned";

/** What a buyer can say about a result. */
export type FeedbackVerdict = "helpful" | "unclear" | "potentially_incorrect";

/** The two marketplaces GuardianLens supports. */
export type Platform = "mudah" | "carousell";

/**
 * The exact hosts a listing page can be served from. The API accepts only these values in
 * capture metadata, so a listing URL can never be smuggled in through that field.
 */
export type PlatformHost = "mudah.my" | "www.mudah.my" | "carousell.com.my" | "www.carousell.com.my";

/** The JSON body of every error response: `{ "error": { code, message, field } }`. */
export interface ApiError {
  error: {
    /** Stable machine-readable code, for example "invalid_price". */
    code: string;
    /** Plain-language message that is safe to show to a buyer. */
    message: string;
    /** The form field the error belongs to, or null when it is not about one field. */
    field: string | null;
  };
}

/** One plain-language reason behind a signal's status (top reasons only). */
export interface SignalReason {
  feature_key: string;
  /** Whether this reason pushed the risk up or down. */
  direction: "raises" | "lowers";
  display_text: string;
  rank: number;
}

/** One of the three signal cards on a result. */
export interface SignalCard {
  signal: SignalName;
  /** Null when the signal could not be computed (unavailable). */
  probability: number | null;
  /** False means the signal is "unknown", never "safe" and never "suspicious". */
  available: boolean;
  status_word: string;
  summary: string;
  reasons: SignalReason[];
  /** Extra wording that limits what the signal proves (for example corpus scope). */
  scope_note: string | null;
}

/** A finished assessment, as returned by GET /api/v1/assess/{id}/result. */
export interface AssessmentResult {
  assessment_id: string;
  title: string;
  /** Integer from 0 to 100. Never shown with decimals. */
  score: number;
  band: RiskBand;
  signal_cards: SignalCard[];
  missing_data_notices: string[];
  suggested_checks: string[];
  /** Must be shown wherever the score is shown. */
  disclaimer: string;
  model_bundle_label: string;
  created_at: string;
  total_latency_ms: number;
  /** True while the scores come from development stubs, not trained models. */
  development_stub: boolean;
}

/** One row of the session history list. */
export interface HistoryItem {
  assessment_id: string;
  title: string;
  score: number;
  band: RiskBand;
  created_at: string;
}

/** Progress of a running assessment, polled while the buyer waits. */
export interface AssessmentStatusResponse {
  status: AssessmentStatus;
  /** The stage currently running, or null when none is. */
  stage: PipelineStage | null;
  message: string | null;
}

/** Response of POST /api/v1/session: the opaque token a header-transport client stores. */
export interface SessionCreated {
  session_token: string;
}

/** Body of POST /api/v1/assess/{id}/feedback. */
export interface FeedbackRequest {
  verdict: FeedbackVerdict;
  comment: string | null;
}

/** The fields whose origin the extension reports in capture metadata. */
export type CaptureFieldName =
  | "title"
  | "description"
  | "price"
  | "category"
  | "platform"
  | "images"
  | "account_age_days"
  | "rating"
  | "review_count"
  | "active_listing_count";

/**
 * Where a submitted value came from: read from the page, changed by the buyer after
 * capture, or not found on the page (so the buyer typed it or left it blank).
 */
export type CaptureFieldStatus = "captured" | "edited" | "not_found";

/**
 * Metadata sent with an extension submission (form field `capture_meta`, JSON string).
 * It is stored for evaluation only and never feeds the score. It deliberately holds the
 * platform host and per-field status, and never the listing URL.
 */
export interface CaptureMetaPayload {
  /** Version of the extraction code that produced the capture. */
  adapter_version: string;
  platform_host: PlatformHost;
  fields: Record<CaptureFieldName, CaptureFieldStatus>;
}
```

- [ ] **Step 5: Write the categories module**

`shared/src/categories.ts`:

```ts
// Category helpers shared by the website's manual form and the extension's Review state.
//
// Background: the behavioural model compares a listing's price with the average price of its
// category, and it was trained on 12 categories. The product does NOT restrict buyers to
// those 12: any category text is accepted, and the model falls back to the overall average
// price for a category it has not seen. These helpers only (a) list the 12 as suggestions
// and (b) map a platform's own category wording onto one of them when the match is obvious.

/** The categories present in the training data, offered as suggestions in the UI. */
export const TRAINED_CATEGORIES = [
  "Phones",
  "Gaming",
  "Home Appliances",
  "Laptops",
  "Fashion",
  "Audio",
  "Cameras",
  "Sports",
  "Wearables",
  "Tablets",
  "Collectibles",
  "Other",
] as const;

/** One of the 12 trained category names. */
export type TrainedCategory = (typeof TRAINED_CATEGORIES)[number];

// Keyword rules, checked in this order; the first match wins. The narrower categories come
// first on purpose: "Mobile Phones & Tablets" should resolve to Tablets only because
// Tablets is tested before Phones, and "Smart Watches" must not fall into Phones.
// "Other" has no keywords: it is only ever chosen by the buyer.
const KEYWORDS: ReadonlyArray<readonly [Exclude<TrainedCategory, "Other">, RegExp]> = [
  ["Tablets", /\b(tablet|tablets|ipad)\b/i],
  ["Phones", /\b(phone|phones|mobile|smartphone|iphone|android)\b/i],
  ["Wearables", /\b(wearable|wearables|smart ?watch(?:es)?|watch|watches|fitbit)\b/i],
  ["Laptops", /\b(laptop|laptops|notebook|macbook|computer|computers)\b/i],
  ["Cameras", /\b(camera|cameras|lens|lenses|dslr|mirrorless|photography)\b/i],
  ["Audio", /\b(audio|headphones?|earphones?|earbuds|speakers?|hi-?fi)\b/i],
  ["Gaming", /\b(gaming|game|games|console|consoles|playstation|xbox|nintendo)\b/i],
  ["Home Appliances", /\b(appliance|appliances|kitchen|washing|refrigerator|fridge|air ?con|vacuum)\b/i],
  ["Fashion", /\b(fashion|clothing|clothes|shoes|bags?|apparel|dress|jewell?ery)\b/i],
  ["Sports", /\b(sport|sports|bicycle|bike|fitness|golf|badminton|outdoor)\b/i],
  ["Collectibles", /\b(collectible|collectibles|hobby|hobbies|toys?|figures?|trading cards?)\b/i],
];

/**
 * Finds the trained category that an arbitrary category text obviously refers to.
 * @param text A platform category such as "Mobile Phones & Gadgets", or nothing.
 * @returns The trained category name, or null when no keyword matches.
 */
export function matchTrainedCategory(text: string | null | undefined): TrainedCategory | null {
  if (!text) return null;
  for (const [category, pattern] of KEYWORDS) {
    if (pattern.test(text)) return category;
  }
  return null;
}

/**
 * Chooses the category text to prefill: a trained category when one matches, otherwise the
 * platform's own wording unchanged (trimmed). Never discards what the page said.
 * @param text The category text read from the page, or nothing.
 * @returns The text to put in the Category field; "" when there is no text.
 */
export function resolveCategory(text: string | null | undefined): string {
  if (!text) return "";
  return matchTrainedCategory(text) ?? text.trim();
}

/**
 * Tells whether a typed category is one of the 12 trained names (ignoring case and spaces).
 * The UI uses this to decide whether to show the "overall average" price note.
 */
export function isTrainedCategory(value: string): boolean {
  const normalised = value.trim().toLowerCase();
  return TRAINED_CATEGORIES.some((category) => category.toLowerCase() === normalised);
}
```

`shared/src/index.ts`:

```ts
// Public entry point of @guardianlens/shared. Everything the website and the extension may
// import is re-exported here; import from "@guardianlens/shared", never from deep paths.
// Add one export line here when a task adds a new public module.
export * from "./types";
export * from "./categories";
```

- [ ] **Step 6: Run the shared tests and typecheck**

```bash
npm run test -w shared
npm run typecheck -w shared
```

Expected: all categories tests pass and the typecheck reports no errors.

- [ ] **Step 7: Point the frontend at the shared package**

`frontend/package.json`: add to `"dependencies"` (keep the existing entries). This makes npm link the local `shared/` folder as `@guardianlens/shared`:

```json
    "@guardianlens/shared": "*",
```

`frontend/lib/types.ts`: replace the whole file with:

```ts
// Frontend type entry point. The definitions now live in @guardianlens/shared so the website
// and the extension cannot drift apart; this file only re-exports the ones the pages use,
// which keeps the existing `@/lib/types` imports working.
export type {
  ApiError,
  AssessmentResult,
  HistoryItem,
  PipelineStage,
  RiskBand,
  SignalCard,
  SignalReason,
} from "@guardianlens/shared";
```

`frontend/next.config.ts`: replace the whole file with:

```ts
import type { NextConfig } from "next";

// Next.js settings for the GuardianLens website.
const nextConfig: NextConfig = {
  reactStrictMode: true,
  // @guardianlens/shared ships TypeScript source (no build step), so Next must compile it
  // together with the website's own code.
  transpilePackages: ["@guardianlens/shared"],
};

export default nextConfig;
```

`Makefile`: in the `install` and `install-dev` targets replace the line `cd frontend && npm ci` with `npm ci`, and replace the `web:` target body with `npm run dev -w frontend`.

- [ ] **Step 8: Verify the frontend still builds against the workspace**

```bash
npm install
npm run typecheck -w frontend
npm run lint -w frontend
npm run build -w frontend
```

Expected: all succeed. If `build` reports `Can't resolve '@guardianlens/shared'`, confirm `transpilePackages` is in `next.config.ts` and that exactly one lockfile (`package-lock.json` at the codebase root) exists; if Next warns about an inferred workspace root, add `turbopack: { root: path.resolve(__dirname, "..") }` to the config with `import path from "node:path"`, and update the comment above `transpilePackages` to mention the root setting in the same edit.

- [ ] **Step 9: Commit**

```bash
git add package.json package-lock.json shared frontend/package.json frontend/lib/types.ts frontend/next.config.ts Makefile
git commit -m "feat: add npm workspaces and shared types and categories"
```

---

### Task 3: Shared API client and website handoff logic

**Files:**
- Create: `shared/src/api.ts`, `shared/src/claim.ts`
- Create: `shared/tests/api.test.ts`, `shared/tests/claim.test.ts`
- Modify: `shared/src/index.ts`

**Interfaces:**
- Consumes: `ApiError`, `AssessmentResult`, `AssessmentStatusResponse`, `FeedbackRequest`, `HistoryItem`, `SessionCreated`, `SignalName` from `./types`.
- Produces:
  - `class GuardianLensApiError extends Error { status: number; code: string; field: string | null }`
  - `interface TokenStore { get(): Promise<string | null>; set(token: string | null): Promise<void> }`
  - `type SessionTransport = { kind: "cookie" } | { kind: "header"; store: TokenStore }`
  - `createClient(options: { baseUrl: string; transport: SessionTransport; fetchImpl?: typeof fetch })` returning `{ ensureSession(): Promise<void>; submit(form: FormData): Promise<{ assessment_id: string }>; getStatus(id: string): Promise<AssessmentStatusResponse>; getResult(id: string): Promise<AssessmentResult>; cancel(id: string): Promise<void>; sendFeedback(id: string, body: FeedbackRequest): Promise<void>; getHistory(): Promise<HistoryItem[]>; claimSession(token: string): Promise<void>; getToken(): Promise<string | null> }`
  - `parseHandoffHash(hash: string): { token: string | null; signal: SignalName | null }`
  - `buildHandoffUrl(siteBaseUrl: string, assessmentId: string, token: string, signal?: SignalName): string`
  - `claimSessionFromHash(deps: { hash: string; claim(token: string): Promise<void>; replaceHash(hash: string): void }): Promise<"none" | "claimed" | "failed">`

- [ ] **Step 1: Write the failing claim tests**

`shared/tests/claim.test.ts`:

```ts
// Pins the extension-to-website session handoff.
// The extension opens the website at ".../explanation#st=<token>". The website must (1) accept
// only a well-formed token, (2) remove the token from the address bar BEFORE doing anything
// else, so it never lingers in history or a screenshot, and (3) claim the session so the
// website sees the same checks as the extension.
import { describe, expect, it } from "vitest";
import { buildHandoffUrl, claimSessionFromHash, parseHandoffHash } from "../src/claim";

// A syntactically valid session token (UUID).
const TOKEN = "3f0c2a52-8b7e-4c55-9d0e-1a2b3c4d5e6f";

// Reading the fragment: only a valid token and a known signal name are accepted.
describe("parseHandoffHash", () => {
  it("reads a token with or without the leading hash", () => {
    expect(parseHandoffHash(`#st=${TOKEN}`).token).toBe(TOKEN);
    expect(parseHandoffHash(`st=${TOKEN}`).token).toBe(TOKEN);
  });

  it("reads a known signal", () => {
    expect(parseHandoffHash(`#st=${TOKEN}&signal=visual`)).toEqual({ token: TOKEN, signal: "visual" });
  });

  it("rejects a token that is not a UUID", () => {
    expect(parseHandoffHash("#st=not-a-token").token).toBeNull();
  });

  it("ignores an unknown signal", () => {
    expect(parseHandoffHash(`#st=${TOKEN}&signal=other`).signal).toBeNull();
  });

  it("returns nothing for an ordinary anchor", () => {
    // "#visual" is the normal in-page anchor on the explanation page, not a handoff.
    expect(parseHandoffHash("#visual")).toEqual({ token: null, signal: null });
  });
});

// Building the URL the extension opens.
describe("buildHandoffUrl", () => {
  it("builds the explanation URL with the token in the fragment", () => {
    expect(buildHandoffUrl("http://localhost:3000/", "abc", TOKEN)).toBe(
      `http://localhost:3000/assess/abc/explanation#st=${TOKEN}`,
    );
  });

  it("adds the signal when given", () => {
    expect(buildHandoffUrl("http://localhost:3000", "abc", TOKEN, "textual")).toBe(
      `http://localhost:3000/assess/abc/explanation#st=${TOKEN}&signal=textual`,
    );
  });
});

// The order of operations is the security property: scrub the address first, then claim.
describe("claimSessionFromHash", () => {
  it("does nothing when there is no token", async () => {
    const calls: string[] = [];
    const outcome = await claimSessionFromHash({
      hash: "#visual",
      claim: async () => void calls.push("claim"),
      replaceHash: () => void calls.push("replace"),
    });
    expect(outcome).toBe("none");
    expect(calls).toEqual([]);
  });

  it("removes the token from the address before claiming", async () => {
    const calls: string[] = [];
    const outcome = await claimSessionFromHash({
      hash: `#st=${TOKEN}&signal=visual`,
      claim: async (token) => void calls.push(`claim:${token}`),
      replaceHash: (hash) => void calls.push(`replace:${hash}`),
    });
    expect(outcome).toBe("claimed");
    // The signal survives as an ordinary anchor so the page still scrolls to that section.
    expect(calls).toEqual(["replace:#visual", `claim:${TOKEN}`]);
  });

  it("still removes the token when the claim fails", async () => {
    const calls: string[] = [];
    const outcome = await claimSessionFromHash({
      hash: `#st=${TOKEN}`,
      claim: async () => {
        throw new Error("nope");
      },
      replaceHash: (hash) => void calls.push(`replace:${hash}`),
    });
    expect(outcome).toBe("failed");
    expect(calls).toEqual(["replace:"]);
  });
});
```

- [ ] **Step 2: Write the failing API client tests**

`shared/tests/api.test.ts`:

```ts
// @vitest-environment node
// Pins the behaviour of the GuardianLens API client (shared by the extension and, later, the
// website) using a fake `fetch`, so no server is needed. The "node" environment above gives
// real Response, Headers and FormData objects.
//
// What matters here:
//  - the cookie transport sends credentials; the header transport sends X-Session-Token;
//  - a header client mints its own session once, and recovers from a stale token by minting
//    a new one and retrying the submission exactly once (backend restarts drop sessions);
//  - every failure is turned into a GuardianLensApiError the UI can show.
import { describe, expect, it } from "vitest";
import { GuardianLensApiError, createClient, type TokenStore } from "../src/api";

/** One recorded request: the URL fetched and the options it was fetched with. */
interface Call {
  url: string;
  init: RequestInit;
}

/** Builds a JSON Response with the given status. */
function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/**
 * A scripted fetch: the Nth request is answered by the Nth handler, and every request is
 * recorded in `calls`. A request with no handler left fails the test loudly.
 */
function fakeFetch(handlers: Array<(call: Call) => Response | Promise<Response>>) {
  const calls: Call[] = [];
  const impl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const call = { url: String(input), init: init ?? {} };
    calls.push(call);
    const handler = handlers[calls.length - 1];
    if (!handler) throw new Error(`Unexpected request ${calls.length}: ${call.url}`);
    return handler(call);
  }) as typeof fetch;
  return { impl, calls };
}

/** An in-memory TokenStore; `value` lets a test read what was stored. */
function memoryStore(initial: string | null = null): TokenStore & { value: string | null } {
  const store = {
    value: initial,
    async get() {
      return store.value;
    },
    async set(token: string | null) {
      store.value = token;
    },
  };
  return store;
}

/** Reads one header off a recorded request. */
function headerOf(call: Call, name: string): string | null {
  return new Headers(call.init.headers).get(name);
}

// Website transport: the browser holds an httpOnly cookie, so the client only asks for it to be sent.
describe("cookie transport", () => {
  it("sends credentials and no session header", async () => {
    const { impl, calls } = fakeFetch([() => json([])]);
    const client = createClient({ baseUrl: "http://api.test", transport: { kind: "cookie" }, fetchImpl: impl });
    await client.getHistory();
    expect(calls[0].url).toBe("http://api.test/api/v1/session/history");
    expect(calls[0].init.credentials).toBe("include");
    expect(headerOf(calls[0], "X-Session-Token")).toBeNull();
  });
});

// Extension transport: no cookie, so the client owns an opaque token and sends it as a header.
describe("header transport", () => {
  it("mints a session once and attaches the token", async () => {
    const store = memoryStore();
    const { impl, calls } = fakeFetch([
      () => json({ session_token: "token-1" }, 201),
      () => json({ assessment_id: "a1" }, 202),
      () => json({ status: "complete", stage: null, message: null }),
    ]);
    const client = createClient({ baseUrl: "http://api.test", transport: { kind: "header", store }, fetchImpl: impl });

    await client.submit(new FormData());
    await client.getStatus("a1");

    expect(calls.map((call) => call.url)).toEqual([
      "http://api.test/api/v1/session",
      "http://api.test/api/v1/assess",
      "http://api.test/api/v1/assess/a1/status",
    ]);
    expect(store.value).toBe("token-1");
    expect(headerOf(calls[1], "X-Session-Token")).toBe("token-1");
    expect(headerOf(calls[2], "X-Session-Token")).toBe("token-1");
    // Header clients must not send cookies.
    expect(calls[1].init.credentials).toBeUndefined();
  });

  // Review Focus 4: the backend restarted and no longer knows the stored token.
  it("mints a new session and retries once when the stored token is rejected", async () => {
    const store = memoryStore("stale");
    const { impl, calls } = fakeFetch([
      () => json({ error: { code: "session_invalid", message: "expired", field: null } }, 401),
      () => json({ session_token: "fresh" }, 201),
      () => json({ assessment_id: "a2" }, 202),
    ]);
    const client = createClient({ baseUrl: "http://api.test", transport: { kind: "header", store }, fetchImpl: impl });

    const accepted = await client.submit(new FormData());

    expect(accepted.assessment_id).toBe("a2");
    expect(store.value).toBe("fresh");
    expect(headerOf(calls[0], "X-Session-Token")).toBe("stale");
    expect(headerOf(calls[2], "X-Session-Token")).toBe("fresh");
  });

  it("does not retry a second time", async () => {
    const store = memoryStore("stale");
    const invalid = () => json({ error: { code: "session_invalid", message: "expired", field: null } }, 401);
    const { impl, calls } = fakeFetch([invalid, () => json({ session_token: "fresh" }, 201), invalid]);
    const client = createClient({ baseUrl: "http://api.test", transport: { kind: "header", store }, fetchImpl: impl });

    await expect(client.submit(new FormData())).rejects.toMatchObject({ code: "session_invalid" });
    // stale attempt, mint, one retry: three requests and then it gives up.
    expect(calls).toHaveLength(3);
  });
});

// Every failure becomes a GuardianLensApiError so the panel and site can show a plain message.
describe("errors", () => {
  it("maps the error envelope", async () => {
    const { impl } = fakeFetch([
      () => json({ error: { code: "invalid_price", message: "Enter a valid non-negative price.", field: "price" } }, 422),
    ]);
    const client = createClient({ baseUrl: "http://api.test", transport: { kind: "cookie" }, fetchImpl: impl });

    const error = await client.submit(new FormData()).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(GuardianLensApiError);
    expect(error).toMatchObject({ status: 422, code: "invalid_price", field: "price" });
  });

  it("reports an unreachable service", async () => {
    const impl = (async () => {
      throw new TypeError("fetch failed");
    }) as typeof fetch;
    const client = createClient({ baseUrl: "http://api.test", transport: { kind: "cookie" }, fetchImpl: impl });

    await expect(client.getHistory()).rejects.toMatchObject({ status: 0, code: "network_unreachable" });
  });

  it("reports a body that is not the error envelope", async () => {
    // For example an HTML error page from a proxy in front of the API.
    const { impl } = fakeFetch([() => new Response("<html>oops</html>", { status: 502 })]);
    const client = createClient({ baseUrl: "http://api.test", transport: { kind: "cookie" }, fetchImpl: impl });

    await expect(client.getHistory()).rejects.toMatchObject({ status: 502, code: "bad_response" });
  });

  it("returns undefined for 204 responses", async () => {
    const { impl } = fakeFetch([() => new Response(null, { status: 204 })]);
    const client = createClient({ baseUrl: "http://api.test", transport: { kind: "cookie" }, fetchImpl: impl });

    await expect(client.cancel("a1")).resolves.toBeUndefined();
  });
});

// The website calls this once, right after reading the token from the handoff URL.
describe("claimSession", () => {
  it("posts the token as JSON with credentials", async () => {
    const { impl, calls } = fakeFetch([() => new Response(null, { status: 204 })]);
    const client = createClient({ baseUrl: "http://api.test", transport: { kind: "cookie" }, fetchImpl: impl });

    await client.claimSession("token-9");

    expect(calls[0].url).toBe("http://api.test/api/v1/session/claim");
    expect(calls[0].init.method).toBe("POST");
    expect(calls[0].init.body).toBe(JSON.stringify({ token: "token-9" }));
    expect(headerOf(calls[0], "Content-Type")).toBe("application/json");
    expect(calls[0].init.credentials).toBe("include");
  });
});
```

- [ ] **Step 3: Run the tests to confirm they fail**

```bash
npm run test -w shared
```

Expected: `claim.test.ts` and `api.test.ts` fail because `../src/claim` and `../src/api` do not exist.

- [ ] **Step 4: Implement the handoff logic**

`shared/src/claim.ts`:

```ts
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
  /** Asks the API to attach the token's session to this browser (sets the cookie). */
  claim(token: string): Promise<void>;
  /** Rewrites the address bar's fragment without adding a history entry. */
  replaceHash(hash: string): void;
}

/** "none": no token present. "claimed": session attached. "failed": token removed, claim failed. */
export type ClaimOutcome = "none" | "claimed" | "failed";

/**
 * Performs the handoff: scrub the token from the address bar first, then claim the session.
 * Scrubbing comes first so the token is gone even if the claim throws or the page is closed.
 * A signal in the fragment is kept as an ordinary anchor (for example "#visual") so the page
 * still scrolls to that card.
 */
export async function claimSessionFromHash(deps: ClaimDeps): Promise<ClaimOutcome> {
  const { token, signal } = parseHandoffHash(deps.hash);
  if (token === null) return "none";
  deps.replaceHash(signal ? `#${signal}` : "");
  try {
    await deps.claim(token);
    return "claimed";
  } catch {
    return "failed";
  }
}
```

- [ ] **Step 5: Implement the API client**

`shared/src/api.ts`:

```ts
// GuardianLens API client, shared by the extension and the website.
//
// It wraps `fetch` for the /api/v1 endpoints and hides the one real difference between the
// two clients: how the buyer's anonymous session travels.
//   - "cookie"  (website): the browser keeps an httpOnly cookie; we only ask for it to be sent.
//   - "header"  (extension): there is no cookie, so the client mints a session token, stores it
//                            through a TokenStore, and sends it as the X-Session-Token header.
// Every failure is surfaced as a GuardianLensApiError so the UI can show a plain message.
import type {
  ApiError,
  AssessmentResult,
  AssessmentStatusResponse,
  FeedbackRequest,
  HistoryItem,
  SessionCreated,
} from "./types";

/**
 * An error from the API or the network. `status` is the HTTP status, or 0 when the service
 * could not be reached. `code` is a stable machine-readable string; `field` names the form
 * field the error belongs to, when there is one.
 */
export class GuardianLensApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly field: string | null;

  constructor(status: number, payload: ApiError) {
    super(payload.error.message);
    this.name = "GuardianLensApiError";
    this.status = status;
    this.code = payload.error.code;
    this.field = payload.error.field;
  }
}

/** Where a header-transport client keeps its token (chrome.storage in the extension). */
export interface TokenStore {
  get(): Promise<string | null>;
  /** Pass null to forget the token. */
  set(token: string | null): Promise<void>;
}

/** How the anonymous session travels with each request. */
export type SessionTransport = { kind: "cookie" } | { kind: "header"; store: TokenStore };

/** Settings for createClient. `fetchImpl` exists so tests can script responses. */
export interface ClientOptions {
  baseUrl: string;
  transport: SessionTransport;
  fetchImpl?: typeof fetch;
}

// Header the API reads for the extension's session token.
const SESSION_HEADER = "X-Session-Token";

// Synthetic errors for failures that never produced a proper API error body.
const NETWORK_ERROR: ApiError = {
  error: { code: "network_unreachable", message: "Can't reach the GuardianLens service.", field: null },
};
const BAD_RESPONSE: ApiError = {
  error: { code: "bad_response", message: "The service returned an unexpected response.", field: null },
};

/**
 * Creates an API client.
 * @param options Base URL (no trailing slash needed), the session transport, and an optional
 *                fetch override for tests.
 * @returns An object with one method per endpoint the clients use.
 */
export function createClient(options: ClientOptions) {
  const baseUrl = options.baseUrl.replace(/\/+$/, "");
  // Wrapped so `fetch` is always called with the right `this`, whatever the environment.
  const doFetch: typeof fetch = options.fetchImpl ?? ((input, init) => fetch(input, init));
  const { transport } = options;

  /** Sends one request with the session attached; turns a network failure into an API error. */
  async function send(path: string, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers);
    // JSON bodies are strings; FormData sets its own multipart header, so it is left alone.
    if (typeof init.body === "string" && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const request: RequestInit = { ...init, headers };
    if (transport.kind === "cookie") {
      request.credentials = "include";
    } else {
      const token = await transport.store.get();
      if (token) headers.set(SESSION_HEADER, token);
    }
    try {
      return await doFetch(`${baseUrl}${path}`, request);
    } catch {
      throw new GuardianLensApiError(0, NETWORK_ERROR);
    }
  }

  /** Parses a response: throws on error statuses, returns undefined for 204, JSON otherwise. */
  async function read<T>(response: Response): Promise<T> {
    if (!response.ok) {
      let payload: ApiError = BAD_RESPONSE;
      try {
        const body = (await response.json()) as Partial<ApiError> | null;
        // Only trust a body that really is the documented error envelope.
        if (body?.error?.code && body.error.message) payload = body as ApiError;
      } catch {
        payload = BAD_RESPONSE;
      }
      throw new GuardianLensApiError(response.status, payload);
    }
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  /** Header transport only: makes sure a session token is stored, minting one if needed. */
  async function ensureSession(): Promise<void> {
    if (transport.kind !== "header") return;
    if (await transport.store.get()) return;
    const created = await read<SessionCreated>(await send("/api/v1/session", { method: "POST" }));
    await transport.store.set(created.session_token);
  }

  /**
   * Submits a listing. For header clients, a "session_invalid" answer means the server no
   * longer knows the stored token (for example it restarted), so the client forgets the
   * token, mints a fresh session, and retries exactly once. The same FormData is reused.
   */
  async function submit(form: FormData): Promise<{ assessment_id: string }> {
    await ensureSession();
    const attempt = async () =>
      read<{ assessment_id: string }>(await send("/api/v1/assess", { method: "POST", body: form }));
    try {
      return await attempt();
    } catch (error) {
      if (
        transport.kind === "header" &&
        error instanceof GuardianLensApiError &&
        error.code === "session_invalid"
      ) {
        await transport.store.set(null);
        await ensureSession();
        return attempt();
      }
      throw error;
    }
  }

  return {
    ensureSession,
    submit,
    /** Polls the processing stage of an assessment. */
    async getStatus(id: string): Promise<AssessmentStatusResponse> {
      return read(await send(`/api/v1/assess/${id}/status`));
    },
    /** Fetches the finished result (409 while it is not ready, 404 for a foreign session). */
    async getResult(id: string): Promise<AssessmentResult> {
      return read(await send(`/api/v1/assess/${id}/result`));
    },
    /** Abandons a running assessment. */
    async cancel(id: string): Promise<void> {
      return read(await send(`/api/v1/assess/${id}/cancel`, { method: "POST" }));
    },
    /** Saves the buyer's helpful / unclear / potentially incorrect choice. */
    async sendFeedback(id: string, body: FeedbackRequest): Promise<void> {
      return read(await send(`/api/v1/assess/${id}/feedback`, { method: "POST", body: JSON.stringify(body) }));
    },
    /** Lists this session's checks, newest first. */
    async getHistory(): Promise<HistoryItem[]> {
      return read(await send("/api/v1/session/history"));
    },
    /** Website only: attaches an extension session to this browser by setting the cookie. */
    async claimSession(token: string): Promise<void> {
      return read(await send("/api/v1/session/claim", { method: "POST", body: JSON.stringify({ token }) }));
    },
    /** The stored session token (header transport), or null. Used to build the handoff URL. */
    async getToken(): Promise<string | null> {
      return transport.kind === "header" ? transport.store.get() : null;
    },
  };
}

/** The type of the object createClient returns, for code that receives a client. */
export type GuardianLensClient = ReturnType<typeof createClient>;
```

Append to `shared/src/index.ts` (the header comment already says to add one line per new public module):

```ts
export * from "./api";
export * from "./claim";
```

- [ ] **Step 6: Run the tests and typecheck**

```bash
npm run test -w shared
npm run typecheck -w shared
```

Expected: all tests pass (categories, claim, api) and the typecheck is clean.

- [ ] **Step 7: Commit**

```bash
git add shared
git commit -m "feat: add shared API client and website handoff helpers"
```

---

### Task 4: Backend session transport and endpoints

**Files:**
- Create: `api/routers/session.py`, `api/tests/test_sessions.py`
- Modify: `api/schemas.py`, `api/dependencies.py`, `api/routers/assess.py`, `api/main.py`

**Interfaces:**
- Consumes: `AssessmentRepository.create_session()` and `.session_exists()` (existing), `AppError` (existing).
- Produces: `POST /api/v1/session` returning `201 {"session_token": "<uuid>"}`; `POST /api/v1/session/claim` taking `{"token": "<uuid>"}`, returning `204` and setting the httpOnly cookie, or `404 not_found`; `parse_session` accepting the `X-Session-Token` header (header wins over cookie); `POST /api/v1/assess` returning `401 session_invalid` when a header token is present but unknown; CORS allowing the `X-Session-Token` header; helper `session_header_value(request) -> str | None` in `api/dependencies.py`.

- [ ] **Step 1: Write the failing tests**

`api/tests/test_sessions.py`:

```python
"""Tests for the header-based session transport and the session claim endpoint.

The browser extension cannot share the website's cookie, so it identifies its buyer with an
opaque token sent in the X-Session-Token header. These tests pin:
  - minting a session, and using the token to own and read assessments;
  - an unknown token on submit is rejected with `session_invalid` (so the client can mint a
    new session and retry), while reading someone else's data stays a generic "not found";
  - the claim endpoint turns a token into the website's httpOnly cookie;
  - CORS allows the new header for the website.

One TestClient is used per test on purpose: the app creates its in-memory repository when it
starts up, so two clients would not share sessions. Which "browser" is calling is simulated by
sending the header, or not.
"""

from __future__ import annotations

import io
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from httpx import Response
from PIL import Image

from api.main import create_app

COOKIE_NAME = "guardianlens_session"


def make_image() -> bytes:
    """A small valid JPEG, so the upload passes the API's image validation."""
    buffer = io.BytesIO()
    Image.new("RGB", (640, 480), (230, 230, 230)).save(buffer, format="JPEG")
    return buffer.getvalue()


def submit_with_token(client: TestClient, token: str | None) -> Response:
    """Submits a minimal valid listing, identifying the buyer by header when a token is given."""
    headers = {"X-Session-Token": token} if token is not None else {}
    return client.post(
        "/api/v1/assess",
        data={
            "platform": "carousell",
            "title": "Used laptop",
            "description": "Original unit in good condition. COD available.",
            "price": "RM 1,250",
            "category": "Laptops",
        },
        files=[("images", ("listing.jpg", make_image(), "image/jpeg"))],
        headers=headers,
    )


def test_create_session_returns_a_token() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/session")
        assert response.status_code == 201
        # The token must be a UUID, and header clients must not be handed a cookie.
        UUID(response.json()["session_token"])
        assert COOKIE_NAME not in client.cookies


def test_header_token_owns_the_assessment() -> None:
    with TestClient(create_app()) as client:
        token = client.post("/api/v1/session").json()["session_token"]
        accepted = submit_with_token(client, token)
        assert accepted.status_code == 202, accepted.text
        assessment_id = accepted.json()["assessment_id"]
        # A valid header token means no lazy cookie session is created.
        assert COOKIE_NAME not in client.cookies

        headers = {"X-Session-Token": token}
        result = client.get(f"/api/v1/assess/{assessment_id}/result", headers=headers)
        assert result.status_code == 200
        history = client.get("/api/v1/session/history", headers=headers).json()
        assert [item["assessment_id"] for item in history] == [assessment_id]


def test_unknown_header_token_on_submit_is_session_invalid() -> None:
    # Happens after a backend restart: the extension still holds a token the new process
    # does not know. The 401 tells the client to mint a new session and retry.
    with TestClient(create_app()) as client:
        response = submit_with_token(client, str(uuid4()))
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "session_invalid"


def test_malformed_header_token_on_submit_is_session_invalid() -> None:
    with TestClient(create_app()) as client:
        response = submit_with_token(client, "not-a-uuid")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "session_invalid"


def test_header_token_cannot_read_another_session() -> None:
    with TestClient(create_app()) as client:
        first = client.post("/api/v1/session").json()["session_token"]
        second = client.post("/api/v1/session").json()["session_token"]
        assessment_id = submit_with_token(client, first).json()["assessment_id"]

        hidden = client.get(
            f"/api/v1/assess/{assessment_id}/result", headers={"X-Session-Token": second}
        )
        # Reads never reveal that an assessment exists for someone else.
        assert hidden.status_code == 404
        assert hidden.json()["error"]["code"] == "not_found"


def test_claim_turns_a_token_into_the_cookie() -> None:
    with TestClient(create_app()) as client:
        token = client.post("/api/v1/session").json()["session_token"]
        assessment_id = submit_with_token(client, token).json()["assessment_id"]
        # The "website" has no cookie yet, so it cannot see the extension's checks.
        assert COOKIE_NAME not in client.cookies
        assert client.get("/api/v1/session/history").json() == []

        claimed = client.post("/api/v1/session/claim", json={"token": token})

        assert claimed.status_code == 204
        assert client.cookies.get(COOKIE_NAME) == token
        history = client.get("/api/v1/session/history").json()
        assert [item["assessment_id"] for item in history] == [assessment_id]


def test_claim_unknown_token_is_not_found() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/session/claim", json={"token": str(uuid4())})
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
        assert COOKIE_NAME not in client.cookies


def test_claim_rejects_a_malformed_token() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/session/claim", json={"token": "nope"})
        assert response.status_code == 422


def test_cors_allows_the_session_header() -> None:
    with TestClient(create_app()) as client:
        response = client.options(
            "/api/v1/assess",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-session-token",
            },
        )
        assert response.status_code == 200
        allowed = response.headers["access-control-allow-headers"].lower()
        assert "x-session-token" in allowed
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
.venv/Scripts/python -m pytest api/tests/test_sessions.py -q
```

Expected: failures, mostly `404 != 201` for `POST /api/v1/session` because the route does not exist yet.

- [ ] **Step 3: Add the new request and response models**

In `api/schemas.py`, directly after the `AssessAccepted` class, add:

```python
class SessionCreated(BaseModel):
    """Response of POST /api/v1/session: the opaque token a header-transport client stores."""

    session_token: UUID


class SessionClaimRequest(BaseModel):
    """Body of POST /api/v1/session/claim.

    `token` is typed as a UUID, so a malformed value is rejected with a 422 before any lookup.
    """

    token: UUID
```

- [ ] **Step 4: Teach the session dependency about the header**

In `api/dependencies.py`, replace the existing `parse_session` function with the following (the rest of the file is unchanged):

```python
# Header the browser extension uses to send its session token. Starlette lower-cases header
# names when reading them, so the constant is lower case.
SESSION_HEADER = "x-session-token"


def session_header_value(request: Request) -> str | None:
    """Returns the X-Session-Token header value, or None when the client did not send one."""
    return request.headers.get(SESSION_HEADER) or None


def parse_session(request: Request, *, required: bool = True) -> UUID | None:
    """Identifies the buyer's session from the request.

    The extension sends its token in the X-Session-Token header; the website sends the httpOnly
    cookie. The header wins when both are present. A missing, malformed, or unknown value is
    handled the same way: with `required=True` it raises the generic "not found" error, so the
    existence of an assessment is never revealed to the wrong caller; otherwise it returns None.
    """
    settings = get_app_settings(request)
    raw = session_header_value(request) or request.cookies.get(settings.guardianlens_session_cookie)
    if not raw:
        if required:
            raise AppError(404, "not_found", "The requested assessment was not found.")
        return None
    try:
        session_id = UUID(raw)
    except ValueError as exc:
        if required:
            raise AppError(404, "not_found", "The requested assessment was not found.") from exc
        return None
    repository = get_repository(request)
    if not repository.session_exists(session_id):
        if required:
            raise AppError(404, "not_found", "The requested assessment was not found.")
        return None
    return session_id
```

- [ ] **Step 5: Reject unknown header tokens on submit**

In `api/routers/assess.py`, change the dependencies import to include the new helper (keep the list sorted):

```python
from api.dependencies import (
    get_app_settings,
    get_rate_limiter,
    get_repository,
    parse_session,
    require_owned_assessment,
    session_header_value,
)
```

Then, in `create_assessment`, replace the block that starts with `session_id = parse_session(request, required=False)` and ends with the `response.set_cookie(...)` call by:

```python
    session_id = parse_session(request, required=False)
    if session_id is None:
        # A client that sent the header but whose token is unknown (for example the server
        # restarted) must be told, so it can mint a new session and retry. Silently creating
        # a cookie session would leave it holding a token that no longer matches anything.
        if session_header_value(request) is not None:
            raise AppError(
                401, "session_invalid", "Your session expired. Reconnect and try again."
            )
        session_id = repository.create_session()
        response.set_cookie(
            key=settings.guardianlens_session_cookie,
            value=str(session_id),
            httponly=True,
            samesite="lax",
            secure=settings.guardianlens_env == "production",
        )
```

- [ ] **Step 6: Add the session router**

`api/routers/session.py`:

```python
"""Session endpoints for clients that cannot rely on the website's cookie.

The browser extension has its own origin, so it keeps an opaque session token and sends it in
the X-Session-Token header. These endpoints mint that token and let the website adopt it:

  POST /api/v1/session        mint a new anonymous session and return its token
  POST /api/v1/session/claim  turn a token into this browser's httpOnly cookie, so the website
                              shows the same checks as the extension

A session is anonymous: it holds no account, name, or contact detail. The token is a random
UUID, and holding it is what proves ownership of the session's assessments.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from api.dependencies import get_app_settings, get_repository
from api.errors import AppError
from api.schemas import SessionClaimRequest, SessionCreated

router = APIRouter(prefix="/api/v1", tags=["session"])


@router.post("/session", response_model=SessionCreated, status_code=status.HTTP_201_CREATED)
def create_session(request: Request) -> SessionCreated:
    """Mints a new anonymous session and returns its token. No cookie is set."""
    session_id = get_repository(request).create_session()
    return SessionCreated(session_token=session_id)


@router.post("/session/claim", status_code=status.HTTP_204_NO_CONTENT)
def claim_session(request: Request, payload: SessionClaimRequest) -> Response:
    """Attaches an existing session to the caller's browser by setting the session cookie.

    An unknown token gets the same generic "not found" error as any other unknown session, so
    this endpoint cannot be used to test which tokens exist.
    """
    settings = get_app_settings(request)
    if not get_repository(request).session_exists(payload.token):
        raise AppError(404, "not_found", "The requested session was not found.")
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.set_cookie(
        key=settings.guardianlens_session_cookie,
        value=str(payload.token),
        httponly=True,
        samesite="lax",
        secure=settings.guardianlens_env == "production",
    )
    return response
```

- [ ] **Step 7: Register the router and allow the header in CORS**

In `api/main.py`: change the routers import to `from api.routers import admin, assess, feedback, health, session`; change the CORS `allow_headers` argument to `allow_headers=["Content-Type", "X-Admin-Token", "X-Session-Token"],`; and add `application.include_router(session.router)` after `application.include_router(feedback.router)`.

- [ ] **Step 8: Run the tests, linters, and type checker**

```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check api
.venv/Scripts/python -m mypy api ml/src/guardianlens_ml
```

Expected: every test passes (the existing suite plus the nine new ones), ruff and mypy report no errors.

- [ ] **Step 9: Commit**

```bash
git add api
git commit -m "feat(api): add header session tokens and the session claim endpoint"
```

---

### Task 5: Backend source, capture metadata, category length, and admin source column

**Files:**
- Create: `api/services/capture_meta.py`, `api/tests/test_capture_meta.py`
- Modify: `api/schemas.py`, `api/models/domain.py`, `api/settings.py`, `api/routers/assess.py`, `api/routers/admin.py`, `.env.example`

**Interfaces:**
- Consumes: `AppError` (existing), the session behaviour from Task 4.
- Produces: `POST /api/v1/assess` accepting optional form fields `source` (`extension` or `manual`, default `manual`) and `capture_meta` (JSON string, extension only); a `category` length limit (`GUARDIANLENS_CATEGORY_MAX_LENGTH`, default 80, error code `category_too_long`); `AssessmentRecord.source` and `AssessmentRecord.capture_meta`; `AdminRecordSummary.source`; a `source` column in the admin export; `parse_source(value: str) -> str` and `parse_capture_meta(raw: str | None, source: str) -> dict[str, object] | None` in `api/services/capture_meta.py`; the `CaptureMeta` model in `api/schemas.py`.

- [ ] **Step 1: Write the failing tests**

`api/tests/test_capture_meta.py`:

```python
"""Tests for the `source` and `capture_meta` fields of POST /api/v1/assess, and the category limit.

The extension tells the API where each submitted value came from (read from the page, edited by
the buyer, or not found) so the research export can describe how data was captured. That record
must stay safe to store, so these tests pin that:
  - `source` is one of two fixed values and defaults to "manual";
  - `capture_meta` accepts only a fixed set of keys and a fixed set of platform hosts, so a
    listing URL (or any other free text) can never be stored through it;
  - capture details are accepted only from the extension, and are size limited;
  - the admin records and CSV export show the source;
  - category is free text but length limited.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from PIL import Image

from api.main import create_app
from api.settings import get_settings

ADMIN = {"X-Admin-Token": "test-admin-token"}

# A complete, valid capture_meta payload that individual tests then break on purpose.
VALID_META = {
    "adapter_version": "1",
    "platform_host": "www.carousell.com.my",
    "fields": {
        "title": "captured",
        "description": "captured",
        "price": "edited",
        "category": "captured",
        "platform": "captured",
        "images": "captured",
        "account_age_days": "not_found",
        "rating": "not_found",
        "review_count": "not_found",
        "active_listing_count": "not_found",
    },
}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A client whose app knows the development admin token, so admin routes are reachable."""
    monkeypatch.setenv("GUARDIANLENS_DEV_ADMIN_TOKEN", "test-admin-token")
    # Settings are cached after the first read; clear so this test's environment is used,
    # and clear again afterwards so it does not leak into other tests.
    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    get_settings.cache_clear()


def post_listing(client: TestClient, **extra: str) -> Response:
    """Submits a minimal valid listing; `extra` fields override or add form fields."""
    buffer = io.BytesIO()
    Image.new("RGB", (640, 480), (230, 230, 230)).save(buffer, format="JPEG")
    data = {
        "platform": "carousell",
        "title": "Used laptop",
        "description": "Original unit in good condition.",
        "price": "RM 1,250",
        "category": "Laptops",
    }
    data.update(extra)
    return client.post(
        "/api/v1/assess",
        data=data,
        files=[("images", ("listing.jpg", buffer.getvalue(), "image/jpeg"))],
    )


def admin_records(client: TestClient) -> list[dict[str, object]]:
    return client.get("/api/v1/admin/records", headers=ADMIN).json()  # type: ignore[no-any-return]


def test_source_defaults_to_manual(client: TestClient) -> None:
    assert post_listing(client).status_code == 202
    assert admin_records(client)[0]["source"] == "manual"


def test_extension_source_with_capture_meta_is_accepted(client: TestClient) -> None:
    response = post_listing(client, source="extension", capture_meta=json.dumps(VALID_META))
    assert response.status_code == 202, response.text
    assert admin_records(client)[0]["source"] == "extension"


def test_extension_source_without_capture_meta_is_accepted(client: TestClient) -> None:
    assert post_listing(client, source="extension").status_code == 202


def test_unknown_source_is_rejected(client: TestClient) -> None:
    response = post_listing(client, source="bot")
    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "invalid_source",
        "message": "Source must be extension or manual.",
        "field": "source",
    }


def test_capture_meta_rejects_an_unknown_key(client: TestClient) -> None:
    # The model forbids extra keys, so a listing URL cannot ride along in a made-up field.
    bad = {**VALID_META, "listing_url": "https://www.carousell.com.my/p/x-1/"}
    response = post_listing(client, source="extension", capture_meta=json.dumps(bad))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_capture_meta"


def test_capture_meta_rejects_a_url_as_the_host(client: TestClient) -> None:
    bad = {**VALID_META, "platform_host": "https://www.carousell.com.my/p/x-1/"}
    response = post_listing(client, source="extension", capture_meta=json.dumps(bad))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_capture_meta"


def test_capture_meta_rejects_text_that_is_not_json(client: TestClient) -> None:
    response = post_listing(client, source="extension", capture_meta="{not json")
    assert response.status_code == 422
    assert response.json()["error"]["field"] == "capture_meta"


def test_capture_meta_rejects_an_oversized_payload(client: TestClient) -> None:
    response = post_listing(client, source="extension", capture_meta="x" * 2001)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_capture_meta"


def test_manual_source_cannot_carry_capture_meta(client: TestClient) -> None:
    response = post_listing(client, source="manual", capture_meta=json.dumps(VALID_META))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_capture_meta"


def test_category_is_free_text_but_length_limited(client: TestClient) -> None:
    # Any category text is fine, including ones the models were not trained on.
    assert post_listing(client, category="Pets and aquarium supplies").status_code == 202
    too_long = post_listing(client, category="x" * 81)
    assert too_long.status_code == 422
    assert too_long.json()["error"]["code"] == "category_too_long"
    assert too_long.json()["error"]["field"] == "category"


def test_export_has_a_source_column(client: TestClient) -> None:
    post_listing(client, source="extension", capture_meta=json.dumps(VALID_META))
    export = client.get("/api/v1/admin/export?dataset=outputs", headers=ADMIN)
    lines = export.text.strip().splitlines()
    assert "source" in lines[0].split(",")
    assert lines[1].split(",")[lines[0].split(",").index("source")] == "extension"
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
.venv/Scripts/python -m pytest api/tests/test_capture_meta.py -q
```

Expected: failures (the `source` key is missing from admin records, unknown sources are accepted, and so on).

- [ ] **Step 3: Add the capture metadata model and the admin source field**

In `api/schemas.py`, change the pydantic import to `from pydantic import BaseModel, ConfigDict, Field`, and add this block before the `AdminBundleSummary` class:

```python
# --- Capture metadata (extension submissions) --------------------------------------------
# The extension reports where each submitted value came from. The allowed hosts and field
# names are fixed lists so that a listing URL, a seller name, or any other free text can
# never be stored through this field.
PlatformHost = Literal["mudah.my", "www.mudah.my", "carousell.com.my", "www.carousell.com.my"]
CaptureField = Literal[
    "title",
    "description",
    "price",
    "category",
    "platform",
    "images",
    "account_age_days",
    "rating",
    "review_count",
    "active_listing_count",
]
CaptureStatus = Literal["captured", "edited", "not_found"]


class CaptureMeta(BaseModel):
    """What the extension reports about how a submission was captured.

    Stored for research evaluation only; it never feeds the score. `extra="forbid"` rejects
    any key not listed here.
    """

    model_config = ConfigDict(extra="forbid")

    # Version of the extraction code that produced the capture.
    adapter_version: str = Field(min_length=1, max_length=40)
    # Host only. The listing URL is deliberately not accepted anywhere.
    platform_host: PlatformHost
    # Per-field origin: read from the page, edited by the buyer, or not found.
    fields: dict[CaptureField, CaptureStatus]
```

In the same file, add one field to `AdminRecordSummary`, after `status`:

```python
    # Where the submission came from: "extension" or "manual".
    source: str
```

- [ ] **Step 4: Add the validation helpers**

`api/services/capture_meta.py`:

```python
"""Validation of the `source` and `capture_meta` form fields of POST /api/v1/assess.

Kept separate from the router so the rules are in one place and easy to test. Both functions
raise AppError (a 422 with a field name) so the buyer-facing error envelope stays consistent.
"""

from __future__ import annotations

from api.errors import AppError
from api.schemas import CaptureMeta

# Where a submission can come from: the browser extension, or the website's manual form.
VALID_SOURCES = frozenset({"extension", "manual"})

# Upper bound on the raw JSON string, checked before parsing so a huge body is never parsed.
MAX_CAPTURE_META_CHARS = 2000


def parse_source(value: str) -> str:
    """Returns the normalised source, or raises a 422 on the `source` field."""
    cleaned = value.strip().lower()
    if cleaned not in VALID_SOURCES:
        raise AppError(422, "invalid_source", "Source must be extension or manual.", "source")
    return cleaned


def parse_capture_meta(raw: str | None, source: str) -> dict[str, object] | None:
    """Validates the `capture_meta` JSON string and returns it as a plain dict.

    Returns None when no metadata was sent. Raises a 422 on the `capture_meta` field when the
    metadata comes from a non-extension source, is too large, is not JSON, or does not match
    the CaptureMeta model (unknown keys, a host that is not one of the four platform hosts,
    or a field status outside captured / edited / not_found).
    """
    if raw is None or raw == "":
        return None
    if source != "extension":
        raise AppError(
            422,
            "invalid_capture_meta",
            "Capture details are only accepted from the extension.",
            "capture_meta",
        )
    if len(raw) > MAX_CAPTURE_META_CHARS:
        raise AppError(
            422, "invalid_capture_meta", "Capture details are too large.", "capture_meta"
        )
    try:
        meta = CaptureMeta.model_validate_json(raw)
    except ValueError as exc:  # pydantic's ValidationError is a ValueError
        raise AppError(
            422,
            "invalid_capture_meta",
            "Capture details were not in the expected format.",
            "capture_meta",
        ) from exc
    return meta.model_dump(mode="json")
```

- [ ] **Step 5: Store the new fields on the assessment record**

In `api/models/domain.py`, add two fields at the end of `AssessmentRecord` (after `error_message`):

```python
    # Where the submission came from ("extension" or "manual") and how its values were
    # captured. Research metadata only: it is never read by the scoring pipeline.
    source: str = "manual"
    capture_meta: dict[str, object] | None = None
```

- [ ] **Step 6: Add the category length setting**

In `api/settings.py`, add after `guardianlens_description_max_length`:

```python
    # Category is free text (any category is accepted), but bounded so it cannot be abused.
    guardianlens_category_max_length: int = 80
```

In `.env.example`, add after the `GUARDIANLENS_DESCRIPTION_MAX_LENGTH=5000` line: `GUARDIANLENS_CATEGORY_MAX_LENGTH=80`.

- [ ] **Step 7: Use the new fields in the assess route**

In `api/routers/assess.py`: add the import `from api.services.capture_meta import parse_capture_meta, parse_source` (keep imports sorted). Add two form parameters to `create_assessment`, after `active_listing_count`:

```python
    source: Annotated[str, Form()] = "manual",
    capture_meta: Annotated[str | None, Form()] = None,
```

Directly after the `if not category:` check, add:

```python
    # Category is free text; only its length is limited.
    if len(category) > settings.guardianlens_category_max_length:
        raise AppError(
            422,
            "category_too_long",
            f"Use {settings.guardianlens_category_max_length} characters or fewer.",
            "category",
        )
    clean_source = parse_source(source)
    parsed_meta = parse_capture_meta(capture_meta, clean_source)
```

In the `AssessmentRecord(...)` call, add `source=clean_source,` and `capture_meta=parsed_meta,` after `images=clean_images,`.

- [ ] **Step 8: Show the source in the admin records and export**

In `api/routers/admin.py`, in `list_records` add `source=record.source,` after `status=record.status,`. In `export_records`, add `"source",` after `"band",` in the header row, and add `record.source,` after the band value in each data row (the one that writes `record.result.band.value if record.result else ""`).

- [ ] **Step 9: Run the tests, linters, and type checker**

```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check api
.venv/Scripts/python -m mypy api ml/src/guardianlens_ml
```

Expected: all tests pass, ruff and mypy report no errors. If mypy flags the `# type: ignore[no-any-return]` in the test as unused, delete that comment in the same edit and keep the helper's docstring or nearby comment accurate.

- [ ] **Step 10: Commit**

```bash
git add api .env.example
git commit -m "feat(api): record submission source and capture metadata, limit category length"
```

---

### Task 6: Shared copy, styles, and components

**Files:**
- Create: `shared/src/copy.ts`, `shared/src/styles.css`
- Create: `shared/src/components/BandChip.tsx`, `ScoreRegion.tsx`, `SignalCardView.tsx`, `StageList.tsx`, `DevBanner.tsx`, `CategoryField.tsx`, `index.ts`
- Create: `shared/tests/components.test.tsx`
- Modify: `shared/src/index.ts`

**Interfaces:**
- Consumes: `RiskBand`, `PipelineStage`, `SignalCard`, `SignalName` from `./types`; `TRAINED_CATEGORIES`, `isTrainedCategory` from `./categories`.
- Produces: from `@guardianlens/shared`: constants `STAGES`, `BAND_COPY`, `SIGNAL_NAMES`, `SIGNAL_ICONS`, `SLOW_WAIT_COPY`, `UNSEEN_CATEGORY_NOTE`, `UNAVAILABLE_SIGNAL_SENTENCE`, `RETENTION_NOTICE`, `DEV_STUB_NOTICE`; components `BandChip({ band })`, `ScoreRegion({ score, band, disclaimer })`, `SignalCardView({ card, href?, LinkComponent?, onOpen? })`, `StageList({ stage })`, `DevBanner()`, `CategoryField({ id, value, onChange, error? })`; and the stylesheet `@guardianlens/shared/styles.css` (tokens plus the styles of these components and of the form, button, and notice classes the website and the panel share).

- [ ] **Step 1: Write the failing component tests**

`shared/tests/components.test.tsx`:

```tsx
// Pins the shared presentational components used by both the website and the side panel.
// The design rules these tests protect (docs/spec/04_Design_Brief_UI_UX.md, section 1):
//  - risk is shown as text + number + icon, never colour alone;
//  - the score is an integer, and the disclaimer lives INSIDE the score region;
//  - an unavailable signal is shown as unknown (dashed card), never as safe or suspicious;
//  - the category field accepts any text and only adds a note for untrained categories.
import { useState } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  BandChip,
  CategoryField,
  DevBanner,
  ScoreRegion,
  SignalCardView,
  StageList,
} from "../src";
import { UNSEEN_CATEGORY_NOTE } from "../src/copy";
import type { SignalCard } from "../src/types";

/** A signal card with sensible defaults; tests override only what they care about. */
function card(overrides: Partial<SignalCard> = {}): SignalCard {
  return {
    signal: "visual",
    probability: 0.4,
    available: true,
    status_word: "clear",
    summary: "No strong warning signs in the photos.",
    reasons: [],
    scope_note: null,
    ...overrides,
  };
}

describe("BandChip", () => {
  it("shows the band as words, with a decorative icon and a meaning line", () => {
    const { container } = render(<BandChip band="moderate" />);
    expect(screen.getByText(/Moderate risk/)).toBeInTheDocument();
    expect(screen.getByText("Some warning signs need closer checking")).toBeInTheDocument();
    // The icon repeats the band for sighted users; screen readers get the words instead.
    expect(container.querySelector("[aria-hidden='true']")).toHaveTextContent("!");
  });

  it("never describes the low band as safe", () => {
    render(<BandChip band="low" />);
    expect(screen.getByText("No strong warning signs found by this check")).toBeInTheDocument();
    expect(screen.queryByText(/safe/i)).not.toBeInTheDocument();
  });
});

describe("ScoreRegion", () => {
  it("labels the region with the score and band and contains the disclaimer", () => {
    render(<ScoreRegion score={62} band="moderate" disclaimer="Decision support only." />);
    const region = screen.getByRole("region", { name: "Risk score 62 out of 100, moderate" });
    expect(within(region).getByText("62")).toBeInTheDocument();
    // Common-region rule: the caveat is part of the verdict, not detached small print.
    expect(within(region).getByText("Decision support only.")).toBeInTheDocument();
  });

  it("never shows decimals", () => {
    render(<ScoreRegion score={61.6} band="moderate" disclaimer="x" />);
    expect(screen.getByRole("region", { name: "Risk score 62 out of 100, moderate" })).toBeInTheDocument();
  });
});

describe("SignalCardView", () => {
  it("renders a link when given an href", () => {
    render(<SignalCardView card={card()} href="/assess/1/explanation#visual" />);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/assess/1/explanation#visual");
    expect(screen.getByText("No strong warning signs in the photos.")).toBeInTheDocument();
  });

  it("renders a link that calls onOpen when there is no href", async () => {
    // The side panel opens the website itself, so the card is a link whose click is handled
    // in code. (A <button> cannot validly contain the card's heading.)
    const onOpen = vi.fn();
    render(<SignalCardView card={card()} onOpen={onOpen} />);
    await userEvent.click(screen.getByRole("link"));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("marks an unavailable signal with the dashed unknown style", () => {
    const { container } = render(
      <SignalCardView
        card={card({ available: false, status_word: "limited information", summary: "Not enough information. Treated as unknown, not as suspicious." })}
        href="/x"
      />,
    );
    expect(container.querySelector(".signal-unavailable")).not.toBeNull();
  });
});

describe("StageList", () => {
  it("marks earlier stages done and the current stage active", () => {
    render(<StageList stage="textual" />);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(5);
    expect(items[0]).toHaveClass("stage-done");
    expect(items[1]).toHaveClass("stage-active");
    expect(items[1]).toHaveAttribute("aria-current", "step");
    expect(items[2]).not.toHaveClass("stage-done");
  });

  it("shows every stage as pending before the first stage is reported", () => {
    render(<StageList stage={null} />);
    for (const item of screen.getAllByRole("listitem")) {
      expect(item).not.toHaveClass("stage-done");
      expect(item).not.toHaveClass("stage-active");
    }
  });
});

describe("DevBanner", () => {
  it("warns that scores are interface test data", () => {
    render(<DevBanner />);
    expect(screen.getByRole("status")).toHaveTextContent("Development stub");
  });
});

describe("CategoryField", () => {
  /** A controlled harness, because the field is a controlled input. */
  function Harness({ initial = "", error }: { initial?: string; error?: string }) {
    const [value, setValue] = useState(initial);
    return <CategoryField id="category" value={value} onChange={setValue} error={error} />;
  }

  it("offers the twelve trained categories as suggestions", () => {
    const { container } = render(<Harness />);
    expect(container.querySelectorAll("datalist option")).toHaveLength(12);
  });

  it("accepts any category text and notes when it is not a trained one", async () => {
    render(<Harness />);
    const input = screen.getByLabelText("Category");
    await userEvent.type(input, "Pets");
    expect(input).toHaveValue("Pets");
    expect(screen.getByText(UNSEEN_CATEGORY_NOTE)).toBeInTheDocument();
  });

  it("shows no note for a trained category", () => {
    render(<Harness initial="Phones" />);
    expect(screen.queryByText(UNSEEN_CATEGORY_NOTE)).not.toBeInTheDocument();
  });

  it("shows no note while the field is empty", () => {
    // A fresh render, because the harness keeps its own state between re-renders.
    render(<Harness initial="" />);
    expect(screen.queryByText(UNSEEN_CATEGORY_NOTE)).not.toBeInTheDocument();
  });

  it("links an error to the input", () => {
    render(<Harness initial="x" error="Choose or type a category." />);
    const input = screen.getByLabelText("Category");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription(expect.stringContaining("Choose or type a category."));
  });
});
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
npm run test -w shared
```

Expected: `components.test.tsx` fails because `../src/copy` and the components do not exist.

- [ ] **Step 3: Write the shared copy**

`shared/src/copy.ts`:

```ts
// Shared wording and small lookup tables used by the website and the extension's side panel.
// Keeping them here means a sentence is changed once and both surfaces stay identical.
// Rules these strings must follow (docs/spec/04_Design_Brief_UI_UX.md): plain language, risk
// never described as "safe", missing data described as unknown (not suspicious).
import type { PipelineStage, RiskBand, SignalName } from "./types";

/** The five processing stages in the order they run, with buyer-readable labels. */
export const STAGES: ReadonlyArray<{ key: PipelineStage; label: string }> = [
  { key: "visual", label: "Checking photos" },
  { key: "textual", label: "Checking listing wording" },
  { key: "behavioural", label: "Checking visible seller details" },
  { key: "fusion", label: "Combining available signals" },
  { key: "explanation", label: "Preparing plain-language reasons" },
];

/**
 * Icon glyph and one-line meaning per band. The glyph differs for every band so colour is
 * never the only difference. "Low" deliberately says "no strong warning signs", never "safe".
 */
export const BAND_COPY: Record<RiskBand, { icon: string; meaning: string }> = {
  low: { icon: "✓", meaning: "No strong warning signs found by this check" },
  moderate: { icon: "!", meaning: "Some warning signs need closer checking" },
  high: { icon: "×", meaning: "Several warning signs need serious attention" },
};

/** Display names of the three signals. */
export const SIGNAL_NAMES: Record<SignalName, string> = {
  visual: "Visual",
  textual: "Textual",
  behavioural: "Behavioural",
};

/** Small neutral glyphs for the three signals (image, text lines, person with clock). */
export const SIGNAL_ICONS: Record<SignalName, string> = {
  visual: "▧",
  textual: "≡",
  behavioural: "◷",
};

/** Shown after the processing screen has waited a while. No percentages, no fake progress. */
export const SLOW_WAIT_COPY = "This is taking longer than usual. The current stage is still running.";

/** Shown under the category field when the text is not one of the 12 trained categories. */
export const UNSEEN_CATEGORY_NOTE = "Price is compared with the overall average, not this category's average.";

/** The fixed sentence for any signal that could not be computed. */
export const UNAVAILABLE_SIGNAL_SENTENCE = "Not enough information. Treated as unknown, not as suspicious.";

/** Retention statement shown beside every submit control (wording pends the approved retention period). */
export const RETENTION_NOTICE =
  "Raw uploaded text is scrubbed before storage. The exact retention period remains an open supervisor item and must be filled before the user study.";

/** Warning shown while scores come from development stubs rather than trained models. */
export const DEV_STUB_NOTICE = "Development stub. These scores are interface test data, not trained model results.";
```

- [ ] **Step 4: Write the shared stylesheet**

`shared/src/styles.css`:

```css
/* GuardianLens shared styles.

   Imported by the website (frontend/app/layout.tsx) and by the extension side panel
   (extension/entrypoints/sidepanel/main.tsx), so both surfaces look identical. It holds:
     1. the design tokens (docs/spec/04_Design_Brief_UI_UX.md, section 3),
     2. base element styles, form controls, buttons, and notices,
     3. the styles of the components in src/components.
   Page-specific layout stays in each app's own stylesheet. Colours that carry risk are always
   paired with text and an icon in the components, never used alone. */

/* ---- 1. Design tokens ---------------------------------------------------------------- */
:root {
  --color-ink: #1a2332;            /* primary text */
  --color-ink-muted: #4a5568;      /* secondary text, captions */
  --color-surface: #ffffff;        /* cards and sheets */
  --color-surface-alt: #f4f6f8;    /* page background */
  --color-border: #d7dee6;
  --color-primary: #1d4ed8;        /* primary actions, links, focus ring */
  --color-primary-dark: #173da8;
  --color-primary-ink: #ffffff;    /* text on primary */
  --color-risk-low: #1e7a46;
  --color-risk-moderate: #9a5b00;
  --color-risk-high: #b42318;
  --color-risk-unknown: #4a5568;
  --radius-card: 12px;
  --radius-input: 8px;
  --shadow-sheet: 0 12px 32px rgb(26 35 50 / 0.14);
}

/* ---- 2. Base, forms, buttons, notices ------------------------------------------------ */
* { box-sizing: border-box; }
html { background: var(--color-surface-alt); }
body {
  margin: 0;
  color: var(--color-ink);
  background: var(--color-surface-alt);
  font-family: Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  font-size: 16px;
  line-height: 1.5;
}
a { color: var(--color-primary); text-decoration: none; }
a:hover { text-decoration: underline; }
button, input, textarea, select { font: inherit; }
button, a, input, textarea, select { -webkit-tap-highlight-color: transparent; }
/* Visible focus on every interactive element (WCAG 2.1 AA). */
:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }

/* Wordmark: ring mark plus the product name, used in both headers. */
.wordmark { display: inline-flex; align-items: center; gap: 10px; color: var(--color-ink); font-weight: 700; }
.wordmark:hover { text-decoration: none; }
.lens-mark { width: 24px; height: 24px; border: 3px solid var(--color-primary); border-radius: 50%; position: relative; }
.lens-mark::after { content: ""; position: absolute; width: 8px; height: 3px; background: var(--color-primary); right: -7px; bottom: -3px; transform: rotate(45deg); border-radius: 4px; }

.eyebrow { margin: 0 0 8px; color: var(--color-primary); font-size: 13px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; }

/* Cards. `.explainer-card` is the website landing page's card and shares the same look. */
.explainer-card, .card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-card);
  background: var(--color-surface);
  padding: 20px;
}
.explainer-card h2, .card h2 { margin: 0 0 8px; font-size: 20px; }
.explainer-card p, .card p { margin: 0; color: var(--color-ink-muted); }

/* Buttons: at least 48px tall so they are easy to hit on touch screens. */
.button {
  min-height: 48px;
  border: 1px solid transparent;
  border-radius: 10px;
  padding: 11px 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  cursor: pointer;
  font-weight: 650;
  transition: background 160ms ease-out, border-color 160ms ease-out, opacity 160ms ease-out;
}
.button:hover { text-decoration: none; }
.button-primary { color: var(--color-primary-ink); background: var(--color-primary); }
.button-primary:hover { background: var(--color-primary-dark); }
.button-secondary { color: var(--color-ink); background: var(--color-surface); border-color: var(--color-border); }
.button-text { color: var(--color-primary); background: transparent; padding-inline: 8px; }
.button:disabled { cursor: not-allowed; opacity: .55; }
.button-full { width: 100%; }

/* Form fields: a label above the control, helper and error text below it. */
.field { display: grid; gap: 7px; margin-bottom: 16px; }
.field:last-child { margin-bottom: 0; }
label, .field-label { font-size: 14px; font-weight: 650; }
input, textarea, select {
  width: 100%;
  min-height: 46px;
  border: 1px solid #aeb8c5;
  border-radius: var(--radius-input);
  background: var(--color-surface);
  color: var(--color-ink);
  padding: 10px 12px;
}
textarea { min-height: 132px; resize: vertical; }
.helper { color: var(--color-ink-muted); font-size: 14px; }
.error-text { color: var(--color-risk-high); font-size: 14px; font-weight: 600; }
.char-count { text-align: right; color: var(--color-ink-muted); font-size: 13px; }

/* Collapsible optional group (seller information). */
details.optional { border-top: 1px solid var(--color-border); padding-top: 16px; }
details.optional summary { cursor: pointer; font-weight: 650; }

/* Retention notice and the sticky submit bar it sits in (kept in one visual group). */
.retention { border-left: 3px solid var(--color-primary); padding: 10px 12px; background: #eef4ff; color: var(--color-ink-muted); font-size: 14px; }
.submit-bar { position: sticky; bottom: 0; z-index: 10; margin-top: 20px; padding: 14px; border: 1px solid var(--color-border); border-radius: 12px; background: rgb(255 255 255 / .97); box-shadow: var(--shadow-sheet); }

/* Notices and manual-check lists. */
.notice { border: 1px solid var(--color-border); border-radius: 10px; background: #f8fafc; padding: 14px; color: var(--color-ink-muted); }
.check-list { margin: 0; padding-left: 22px; }
.check-list li { margin: 10px 0; }

/* Feedback choices (helpful / unclear / potentially incorrect). */
.feedback-options { display: grid; gap: 8px; }
.option-row { display: flex; gap: 10px; align-items: center; min-height: 48px; border: 1px solid var(--color-border); border-radius: 9px; padding: 10px 12px; cursor: pointer; }
.option-row input { width: 18px; min-height: 18px; }
.success-text { color: var(--color-risk-low); font-weight: 650; }

.loading { min-height: 180px; display: grid; place-items: center; color: var(--color-ink-muted); }

/* ---- 3. Component styles ------------------------------------------------------------- */

/* DevBanner: shown while scores come from development stubs. */
.dev-banner { border: 1px solid #f0c36a; background: #fff8e8; color: #6d4600; border-radius: 10px; padding: 12px 14px; margin-bottom: 20px; font-weight: 600; }

/* StageList: the five processing stages (done / active / pending). */
.stage-list { margin: 24px 0; padding: 0; list-style: none; text-align: left; }
.stage-item { display: flex; align-items: center; gap: 12px; min-height: 48px; color: var(--color-ink-muted); }
.stage-dot { width: 24px; height: 24px; border: 2px solid var(--color-border); border-radius: 50%; display: grid; place-items: center; font-size: 12px; }
.stage-active { color: var(--color-ink); font-weight: 650; }
.stage-active .stage-dot { border-color: var(--color-primary); box-shadow: 0 0 0 5px rgb(29 78 216 / .12); }
.stage-done .stage-dot { border-color: var(--color-risk-low); color: var(--color-risk-low); }

/* ScoreRegion + BandChip: the score, band, and disclaimer as one bounded region. */
.score-region { border: 1px solid var(--color-border); border-radius: 16px; background: var(--color-surface); padding: 28px 20px; text-align: center; }
.score-number { font-size: 52px; line-height: 1; font-weight: 750; font-variant-numeric: tabular-nums; letter-spacing: -.03em; }
.score-total { color: var(--color-ink-muted); font-size: 15px; }
.band-unit { margin-top: 14px; display: grid; justify-items: center; gap: 7px; }
.band-chip { display: inline-flex; align-items: center; gap: 8px; border-radius: 999px; padding: 7px 12px; font-size: 13px; font-weight: 750; text-transform: uppercase; letter-spacing: .03em; }
.band-meaning { color: var(--color-ink-muted); font-size: 14px; }
.band-low .band-chip { color: var(--color-risk-low); background: #e8f5ed; }
.band-moderate .band-chip { color: var(--color-risk-moderate); background: #fff3dd; }
.band-high .band-chip { color: var(--color-risk-high); background: #fdeceb; }
.disclaimer { border-top: 1px solid var(--color-border); margin-top: 20px; padding-top: 16px; color: var(--color-ink-muted); font-size: 14px; text-align: left; }

/* SignalCardView: one card per signal. All three share one template. */
.signal-grid { display: grid; gap: 12px; margin: 20px 0; }
.signal-card { display: block; border: 1px solid var(--color-border); border-radius: var(--radius-card); background: var(--color-surface); color: var(--color-ink); padding: 18px; }
.signal-card:hover { border-color: #9eb5df; text-decoration: none; }
.signal-heading { display: grid; grid-template-columns: 36px 1fr auto; align-items: center; gap: 10px; }
.signal-heading h2 { margin: 0; font-size: 18px; }
.signal-icon { width: 34px; height: 34px; border-radius: 8px; display: grid; place-items: center; background: #eef4ff; color: var(--color-primary); font-size: 20px; }
.signal-status { color: var(--color-ink-muted); font-size: 13px; text-transform: capitalize; }
.signal-card p { margin: 12px 0 0; color: var(--color-ink-muted); }
/* A dashed border marks an unavailable ("unknown") signal. */
.signal-unavailable { border-style: dashed; }
.chevron { font-size: 28px; color: var(--color-ink-muted); }

/* Respect the reader's motion preference: no transitions or animations at all. */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; transition: none !important; animation: none !important; }
}
```

- [ ] **Step 5: Write the components**

`shared/src/components/BandChip.tsx`:

```tsx
// Risk band chip: icon + band word + one-line meaning, so colour is never the only signal.
import { BAND_COPY } from "../copy";
import type { RiskBand } from "../types";

/**
 * Shows a risk band. The icon is decorative (aria-hidden) because the band is also written
 * as words; the colour comes from the `band-<name>` class and only reinforces the text.
 */
export function BandChip({ band }: { band: RiskBand }) {
  const item = BAND_COPY[band];
  return (
    <div className={`band-unit band-${band}`}>
      <span className="band-chip">
        <span aria-hidden="true">{item.icon}</span>
        {band[0].toUpperCase() + band.slice(1)} risk
      </span>
      <span className="band-meaning">{item.meaning}</span>
    </div>
  );
}
```

`shared/src/components/ScoreRegion.tsx`:

```tsx
// The score region: score, band chip, and disclaimer as ONE bounded region, so the caveat is
// read as part of the verdict (Design Brief: Common Region and Selective Attention rules).
import { BandChip } from "./BandChip";
import type { RiskBand } from "../types";

export interface ScoreRegionProps {
  /** The risk score. Rounded to an integer for display; decimals are never shown. */
  score: number;
  band: RiskBand;
  /** Must be shown wherever a score is shown, so it is a required part of this component. */
  disclaimer: string;
}

/** Renders the score, its band, and the disclaimer inside one labelled region. */
export function ScoreRegion({ score, band, disclaimer }: ScoreRegionProps) {
  const shown = Math.round(score);
  return (
    <section className="score-region" aria-label={`Risk score ${shown} out of 100, ${band}`}>
      <div className="score-number">{shown}</div>
      <div className="score-total">out of 100</div>
      <BandChip band={band} />
      <p className="disclaimer">{disclaimer}</p>
    </section>
  );
}
```

`shared/src/components/SignalCardView.tsx`:

```tsx
// One signal card (visual, textual, or behavioural). All three use this single template so
// they read as a set (Design Brief: Similarity rule).
import type { ElementType, ReactNode } from "react";
import { SIGNAL_ICONS, SIGNAL_NAMES } from "../copy";
import type { SignalCard } from "../types";

/** The props a link component must accept. A plain <a> and Next.js's Link both do. */
interface LinkProps {
  href: string;
  className?: string;
  children: ReactNode;
}

export interface SignalCardViewProps {
  card: SignalCard;
  /** Where the card links to (its section on the explanation page). Omit for a button/plain card. */
  href?: string;
  /** Link component used when `href` is set. Defaults to a plain anchor; the website passes next/link. */
  LinkComponent?: ElementType<LinkProps>;
  /**
   * When there is no `href`, the card is a link whose click calls this instead of navigating
   * (the side panel opens the website itself, with a session handoff it must build first).
   */
  onOpen?: () => void;
}

/**
 * Renders a signal card. An unavailable signal gets the dashed `signal-unavailable` style and
 * keeps the API's summary text, which says the signal is unknown rather than safe or suspicious.
 * With neither `href` nor `onOpen` it is a plain, non-interactive card.
 */
export function SignalCardView({ card, href, LinkComponent, onOpen }: SignalCardViewProps) {
  const className = `signal-card ${card.available ? "" : "signal-unavailable"}`.trim();
  const body = (
    <>
      <div className="signal-heading">
        <span className="signal-icon" aria-hidden="true">{SIGNAL_ICONS[card.signal]}</span>
        <div>
          <h2>{SIGNAL_NAMES[card.signal]}</h2>
          <span className="signal-status">{card.status_word}</span>
        </div>
        <span className="chevron" aria-hidden="true">{"›"}</span>
      </div>
      <p>{card.summary}</p>
    </>
  );

  if (href !== undefined) {
    const Link: ElementType<LinkProps> = LinkComponent ?? "a";
    return <Link className={className} href={href}>{body}</Link>;
  }
  if (onOpen) {
    // href="#" keeps it a real, keyboard-focusable link; preventDefault stops the jump to "#".
    return (
      <a
        className={className}
        href="#"
        onClick={(event) => {
          event.preventDefault();
          onOpen();
        }}
      >
        {body}
      </a>
    );
  }
  return <div className={className}>{body}</div>;
}
```

`shared/src/components/StageList.tsx`:

```tsx
// The five labelled processing stages with three states: done, active, pending.
// There are deliberately no percentages: progress reflects the real pipeline stage only.
import { STAGES } from "../copy";
import type { PipelineStage } from "../types";

/**
 * Renders the stage list.
 * @param stage The stage currently running, or null before the first stage is reported
 *              (every stage then shows as pending).
 */
export function StageList({ stage }: { stage: PipelineStage | null }) {
  const activeIndex = STAGES.findIndex((item) => item.key === stage);
  return (
    <ol className="stage-list">
      {STAGES.map((item, index) => {
        const state = index < activeIndex ? "stage-done" : index === activeIndex ? "stage-active" : "";
        return (
          <li
            className={`stage-item ${state}`.trim()}
            key={item.key}
            aria-current={index === activeIndex ? "step" : undefined}
          >
            <span className="stage-dot" aria-hidden="true">{index < activeIndex ? "✓" : index + 1}</span>
            {item.label}
          </li>
        );
      })}
    </ol>
  );
}
```

`shared/src/components/DevBanner.tsx`:

```tsx
// Warning banner shown while scores come from development stubs, not trained models.
// It must stay visible until a real model bundle is served (project integrity rule).
import { DEV_STUB_NOTICE } from "../copy";

/** Renders the development-stub warning as a status message. */
export function DevBanner() {
  return (
    <div className="dev-banner" role="status">
      {DEV_STUB_NOTICE}
    </div>
  );
}
```

`shared/src/components/CategoryField.tsx`:

```tsx
// Category input shared by the website's manual form and the extension's Review state.
// It is FREE TEXT: the 12 categories the models were trained on are only offered as
// suggestions (a datalist), and any other category is accepted. When the text is not a
// trained category, a plain note explains that the price comparison uses the overall average.
import { isTrainedCategory, TRAINED_CATEGORIES } from "../categories";
import { UNSEEN_CATEGORY_NOTE } from "../copy";

export interface CategoryFieldProps {
  /** Unique id; the label, the suggestion list, and the note are all derived from it. */
  id: string;
  value: string;
  onChange(value: string): void;
  /** A validation or server error to show under the field. */
  error?: string | null;
}

/** A labelled, free-text category input with the trained categories as suggestions. */
export function CategoryField({ id, value, onChange, error }: CategoryFieldProps) {
  const listId = `${id}-suggestions`;
  const noteId = `${id}-note`;
  const errorId = `${id}-error`;
  const showNote = value.trim() !== "" && !isTrainedCategory(value);
  // The input is described by whichever of the note and the error are on screen.
  const describedBy = [showNote ? noteId : null, error ? errorId : null].filter(Boolean).join(" ");

  return (
    <div className="field">
      <label htmlFor={id}>Category</label>
      <input
        id={id}
        list={listId}
        value={value}
        maxLength={80}
        autoComplete="off"
        placeholder="Choose or type a category"
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
      />
      <datalist id={listId}>
        {TRAINED_CATEGORIES.map((category) => (
          <option key={category} value={category} />
        ))}
      </datalist>
      {showNote && <span className="helper" id={noteId}>{UNSEEN_CATEGORY_NOTE}</span>}
      {error && <span className="error-text" id={errorId}>{error}</span>}
    </div>
  );
}
```

`shared/src/components/index.ts`:

```ts
// Barrel file for the shared components; re-exported from the package entry point.
export { BandChip } from "./BandChip";
export { CategoryField } from "./CategoryField";
export type { CategoryFieldProps } from "./CategoryField";
export { DevBanner } from "./DevBanner";
export { ScoreRegion } from "./ScoreRegion";
export type { ScoreRegionProps } from "./ScoreRegion";
export { SignalCardView } from "./SignalCardView";
export type { SignalCardViewProps } from "./SignalCardView";
export { StageList } from "./StageList";
```

Append to `shared/src/index.ts`:

```ts
export * from "./copy";
export * from "./components";
```

- [ ] **Step 6: Run the tests and typecheck**

```bash
npm run test -w shared
npm run typecheck -w shared
```

Expected: all shared tests pass and the typecheck is clean. If the `toHaveAccessibleDescription` assertion is unsupported by the installed jest-dom, replace it with `expect(input).toHaveAttribute("aria-describedby", "category-error")` in the same edit and keep the test's comment accurate.

- [ ] **Step 7: Commit**

```bash
git add shared
git commit -m "feat(shared): add shared copy, styles, and presentational components"
```

---

### Task 7: Extension skeleton and platform verification

**Files:**
- Create: `extension/package.json`, `extension/wxt.config.ts`, `extension/tsconfig.json`, `extension/vitest.config.ts`
- Create: `extension/lib/config.ts`, `extension/lib/hosts.ts`, `extension/lib/storage.ts`
- Create: `extension/entrypoints/background.ts`
- Create: `extension/entrypoints/sidepanel/index.html`, `extension/entrypoints/sidepanel/main.tsx`, `extension/entrypoints/sidepanel/App.tsx`
- Create: `extension/tests/setup.ts`, `extension/tests/hosts.test.ts`, `extension/tests/storage.test.ts`
- Modify: `extension/docs/SPIKE_NOTES.md`

**Interfaces:**
- Consumes: `TokenStore` from `@guardianlens/shared` (Task 3); `@guardianlens/shared/styles.css` (Task 6); the `Image hosts` section of `extension/docs/SPIKE_NOTES.md` (Task 1).
- Produces:
  - `API_BASE_URL: string`, `SITE_BASE_URL: string` from `extension/lib/config.ts`
  - `IMAGE_HOST_PATTERNS: string[]`, `isFetchableImageUrl(url: string): boolean` from `extension/lib/hosts.ts`
  - `readSession<T>(key: string): Promise<T | null>`, `writeSession(key: string, value: unknown): Promise<void>`, `removeSession(key: string): Promise<void>`, `watchSession<T>(key: string, listener: (value: T | null) => void): () => void`, `tokenStore: TokenStore` from `extension/lib/storage.ts`
  - A buildable extension at `extension/.output/chrome-mv3/` whose toolbar click opens the side panel.
  - Verified facts about the toolbar click, `sidePanel.open`, and `activeTab` in Chrome and Edge, recorded in `SPIKE_NOTES.md`.

- [ ] **Step 1: Write the failing tests**

`extension/tests/hosts.test.ts`:

```ts
// Pins which photo URLs the extension will try to fetch.
// The extension downloads listing photos itself so it can upload them to the API, and a
// browser extension may only read another site's files for hosts named in the manifest's
// host_permissions. isFetchableImageUrl mirrors that list at run time, so a photo from an
// unlisted host is skipped cleanly instead of failing with a confusing network error.
// Matching must be EXACT on the host: a look-alike such as "mudah.my.evil.com" is never allowed.
import { describe, expect, it } from "vitest";
import { IMAGE_HOST_PATTERNS, isFetchableImageUrl } from "../lib/hosts";

describe("IMAGE_HOST_PATTERNS", () => {
  it("uses the manifest match-pattern shape https://<host>/*", () => {
    for (const pattern of IMAGE_HOST_PATTERNS) {
      expect(pattern).toMatch(/^https:\/\/(\*\.)?[a-z0-9.-]+\/\*$/);
    }
  });
});

describe("isFetchableImageUrl", () => {
  it("accepts an https photo on a listed host", () => {
    expect(isFetchableImageUrl("https://media.karousell.com/media/photos/products/1/a.jpg")).toBe(true);
  });

  it("accepts a subdomain and the bare domain of a wildcard pattern", () => {
    expect(isFetchableImageUrl("https://cdn.mudah.my/photos/a.jpg")).toBe(true);
    expect(isFetchableImageUrl("https://mudah.my/photos/a.jpg")).toBe(true);
  });

  it.each([
    ["a look-alike host", "https://mudah.my.evil.com/a.jpg"],
    ["an unlisted host", "https://example.com/a.jpg"],
    ["plain http", "http://media.karousell.com/a.jpg"],
    ["a data URL", "data:image/png;base64,AAAA"],
    ["something that is not a URL", "not a url"],
    ["an empty string", ""],
  ])("rejects %s", (_label, url) => {
    expect(isFetchableImageUrl(url)).toBe(false);
  });
});
```

`extension/tests/storage.test.ts`:

```ts
// Pins the thin wrapper around chrome.storage.session that the extension uses for its session
// token, its latest capture, and the buyer's unsent draft. Session storage is cleared when the
// browser closes, which is exactly the "history lives only in this browser session" promise.
// The tests run against WXT's in-memory fake of the browser API (reset before each test).
import { describe, expect, it } from "vitest";
import { readSession, removeSession, tokenStore, watchSession, writeSession } from "../lib/storage";

describe("session storage helpers", () => {
  it("round-trips a value", async () => {
    await writeSession("k", { a: 1 });
    expect(await readSession("k")).toEqual({ a: 1 });
  });

  it("returns null for a missing key", async () => {
    expect(await readSession("missing")).toBeNull();
  });

  it("removes a value", async () => {
    await writeSession("k", 1);
    await removeSession("k");
    expect(await readSession("k")).toBeNull();
  });

  it("tells a watcher about changes and removals, and stops after unsubscribe", async () => {
    const seen: unknown[] = [];
    const stop = watchSession("k", (value) => seen.push(value));
    await writeSession("k", 1);
    await removeSession("k");
    stop();
    await writeSession("k", 2);
    expect(seen).toEqual([1, null]);
  });
});

describe("tokenStore", () => {
  it("stores, reads, and clears the session token", async () => {
    expect(await tokenStore.get()).toBeNull();
    await tokenStore.set("token-1");
    expect(await tokenStore.get()).toBe("token-1");
    await tokenStore.set(null);
    expect(await tokenStore.get()).toBeNull();
  });
});
```

- [ ] **Step 2: Create the package and tool configuration**

First add the extension to the workspace list: in the root `package.json` change the `workspaces` line to `"workspaces": ["shared", "extension", "frontend"],`.

`extension/package.json`. JSON cannot hold comments, so the fields are explained here: `dev` runs WXT's development server with hot reload; `build` writes the loadable extension to `.output/chrome-mv3`; `zip` packs it for sharing; `postinstall` runs `wxt prepare`, which generates the `.wxt/` types and path aliases the editor and compiler need; `typecheck` regenerates those and runs the compiler; `test` runs unit and component tests; `test:e2e` builds first because the browser tests load the built extension; `package:site` zips the extension and copies it into the website's downloads folder (Task 20). `@guardianlens/shared` is the local workspace package.

```json
{
  "name": "@guardianlens/extension",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "wxt",
    "build": "wxt build",
    "zip": "wxt zip",
    "postinstall": "wxt prepare",
    "typecheck": "wxt prepare && tsc --noEmit",
    "test": "vitest run",
    "test:e2e": "wxt build && playwright test",
    "package:site": "wxt zip && node scripts/package-for-site.mjs"
  },
  "dependencies": {
    "@guardianlens/shared": "*",
    "react": "19.2.0",
    "react-dom": "19.2.0"
  },
  "devDependencies": {
    "@playwright/test": "1.63.0",
    "@testing-library/jest-dom": "7.0.1",
    "@testing-library/react": "16.3.3",
    "@testing-library/user-event": "14.6.7",
    "@types/node": "24.10.0",
    "@types/react": "19.2.2",
    "@types/react-dom": "19.2.2",
    "@wxt-dev/module-react": "1.2.2",
    "jsdom": "30.1.2",
    "typescript": "5.9.3",
    "vite": "7.3.6",
    "vitest": "5.0.3",
    "wxt": "0.21.4"
  }
}
```

`extension/wxt.config.ts`:

```ts
// WXT build configuration: how the extension's manifest is generated.
//
// Permissions are deliberately minimal and match the click-only capture design:
//   activeTab  - temporary access to the current tab, granted only when the buyer clicks the icon;
//   scripting  - lets that click inject the capture script into the tab;
//   storage    - keeps the session token and the unsent draft (cleared when the browser closes);
//   sidePanel  - shows the result next to the page.
// host_permissions lists ONLY hosts the extension itself fetches from: the GuardianLens API and
// the listing-photo CDNs. The Mudah.my and Carousell sites are NOT listed, so the extension has
// no standing access to them; it can read a listing only on the click that grants activeTab.
import { defineConfig } from "wxt";
import { IMAGE_HOST_PATTERNS } from "./lib/hosts";

// The API origin is a build-time setting (WXT_API_BASE_URL), so switching to a hosted API is a
// rebuild, not a code change.
const apiOrigin = new URL(process.env.WXT_API_BASE_URL ?? "http://localhost:8000").origin;

export default defineConfig({
  modules: ["@wxt-dev/module-react"],
  manifest: {
    name: "GuardianLens",
    description: "Check a Mudah.my or Carousell listing for warning signs before you pay.",
    permissions: ["activeTab", "scripting", "storage", "sidePanel"],
    host_permissions: [`${apiOrigin}/*`, ...IMAGE_HOST_PATTERNS],
    // An action with no popup: clicking the icon fires action.onClicked (entrypoints/background.ts).
    action: { default_title: "Check this listing with GuardianLens" },
  },
});
```

`extension/tsconfig.json`:

```jsonc
{
  // WXT generates .wxt/tsconfig.json (path aliases such as "@/", auto-imported globals like
  // defineBackground, and the browser API types). `npm install` and `npm run typecheck` refresh it.
  "extends": "./.wxt/tsconfig.json",
  "compilerOptions": {
    "jsx": "react-jsx",
    "strict": true,
    "skipLibCheck": true
  },
  // fixtures/ holds recorded HTML and a console script, not TypeScript.
  "exclude": ["node_modules", ".output", "fixtures"]
}
```

`extension/vitest.config.ts`:

```ts
// Unit and component test settings for the extension.
// WxtVitest wires in what extension code expects at run time: an in-memory fake of the
// `browser` API (storage, tabs, ...), the "@/..." path aliases, and WXT's build-time globals.
import { defineConfig } from "vitest/config";
import { WxtVitest } from "wxt/testing/vitest-plugin";

export default defineConfig({
  plugins: [WxtVitest()],
  // Compile JSX with the automatic runtime so test and component files do not import React.
  esbuild: { jsx: "automatic" },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
    // The Playwright browser specs live in tests/e2e and run with `npm run test:e2e`.
    exclude: ["tests/e2e/**", "node_modules/**"],
  },
});
```

`extension/tests/setup.ts`:

```ts
// Runs before every test file in the extension package.
// 1. Adds the jest-dom matchers to expect().
// 2. Resets the in-memory fake browser before each test so storage never leaks between tests.
// 3. Unmounts anything a test rendered (Testing Library only does this by itself when test
//    globals are on, and we keep them off).
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";
import { fakeBrowser } from "wxt/testing/fake-browser";

beforeEach(() => fakeBrowser.reset());
afterEach(() => cleanup());
```

- [ ] **Step 3: Install and confirm the tests fail**

```bash
npm install
npm run test -w extension
```

Expected: both test files fail because `../lib/hosts` and `../lib/storage` do not exist. If `npm install` fails on `wxt prepare`, run `npm run postinstall -w extension` once more after the files in Step 4 exist.

- [ ] **Step 4: Write the library files**

`extension/lib/config.ts`:

```ts
// Build-time settings for the extension.
// WXT exposes variables whose names start with WXT_ through import.meta.env. They are set when
// building, for example `WXT_API_BASE_URL=https://api.example npm run build`, which is how a
// later hosted deployment moves the extension off localhost without a code change.

/** Base URL of the GuardianLens API. It must also be in host_permissions (wxt.config.ts). */
export const API_BASE_URL: string = import.meta.env.WXT_API_BASE_URL ?? "http://localhost:8000";

/** Base URL of the GuardianLens website, opened by "See full explanation" and "This session". */
export const SITE_BASE_URL: string = import.meta.env.WXT_SITE_BASE_URL ?? "http://localhost:3000";
```

`extension/lib/hosts.ts`:

```ts
// Hosts that serve listing photos.
//
// The extension downloads photos itself (to upload them to the API), and a browser extension may
// only read another site's files for hosts listed in the manifest's host_permissions. This list
// feeds wxt.config.ts, and the same list decides at run time which photo URLs the extension will
// even try to fetch, so an unlisted host is skipped cleanly instead of failing noisily.
//
// Source of truth: the "Image hosts" section of docs/SPIKE_NOTES.md. When the spike (or a later
// page change) shows a new photo host, add it here and nowhere else.

/** Match patterns for the photo CDNs, in manifest host_permissions format. */
export const IMAGE_HOST_PATTERNS: string[] = [
  "https://media.karousell.com/*",
  "https://*.mudah.my/*",
];

/**
 * Tells whether the extension may fetch a photo from this URL.
 * Requires https and an exact host match against IMAGE_HOST_PATTERNS. A wildcard pattern such
 * as "*.mudah.my" matches the bare domain and its subdomains, never a look-alike host.
 */
export function isFetchableImageUrl(url: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (parsed.protocol !== "https:") return false;
  const host = parsed.hostname.toLowerCase();
  return IMAGE_HOST_PATTERNS.some((pattern) => {
    const match = /^https:\/\/([^/]+)\/\*$/.exec(pattern);
    if (!match) return false;
    const allowed = match[1].toLowerCase();
    if (allowed.startsWith("*.")) {
      const base = allowed.slice(2);
      return host === base || host.endsWith(`.${base}`);
    }
    return host === allowed;
  });
}
```

`extension/lib/storage.ts`:

```ts
// Thin helpers over chrome.storage.session, plus the token store the API client uses.
//
// Session storage lives only until the browser closes and is never synced, which matches the
// product promise that the history lives only in this browser session. It holds three things:
// the anonymous session token, the latest capture job, and the buyer's unsent draft.
import { browser } from "wxt/browser";
import type { TokenStore } from "@guardianlens/shared";

/** Reads one value from session storage, or null when the key is absent. */
export async function readSession<T>(key: string): Promise<T | null> {
  const stored = await browser.storage.session.get(key);
  return (stored[key] as T | undefined) ?? null;
}

/** Writes one value to session storage (replacing any previous value). */
export async function writeSession(key: string, value: unknown): Promise<void> {
  await browser.storage.session.set({ [key]: value });
}

/** Deletes one value from session storage. */
export async function removeSession(key: string): Promise<void> {
  await browser.storage.session.remove(key);
}

/**
 * Calls `listener` with the new value each time `key` changes in session storage (null when it
 * is removed). Used by the side panel to react to a capture the service worker just wrote.
 * @returns A function that stops listening.
 */
export function watchSession<T>(key: string, listener: (value: T | null) => void): () => void {
  const handler = (changes: Record<string, { newValue?: unknown }>, area: string) => {
    // onChanged fires for every storage area; only the session area and this key matter here.
    if (area !== "session" || !(key in changes)) return;
    listener((changes[key].newValue as T | undefined) ?? null);
  };
  browser.storage.onChanged.addListener(handler);
  return () => browser.storage.onChanged.removeListener(handler);
}

/** The session token store for the API client's "header" transport. */
export const tokenStore: TokenStore = {
  async get() {
    const token = await readSession<string>("sessionToken");
    return typeof token === "string" ? token : null;
  },
  async set(token) {
    if (token) await writeSession("sessionToken", token);
    else await removeSession("sessionToken");
  },
};
```

If the `watchSession` test sees no events, WXT's fake browser may not implement `storage.session.onChanged`; in that case replace that one test with a stub of `browser.storage.onChanged` (call the registered listener by hand), rewrite the test's comment to say what is faked, and leave the real behaviour to the Task 16 end-to-end test.

- [ ] **Step 5: Write the entrypoints**

`extension/entrypoints/background.ts` (this version contains a temporary verification block; Step 9 removes it together with its comment):

```ts
// Extension service worker (background script).
//
// The toolbar icon has no popup, so Chrome fires `action.onClicked` when the buyer clicks it.
// That single click is the explicit capture event for the whole product. It (1) opens the side
// panel for the current tab and (2) is what grants the extension temporary `activeTab` access
// to that tab. Task 11 adds the capture step to this handler.
export default defineBackground(() => {
  browser.action.onClicked.addListener((tab) => {
    if (tab.id === undefined) return;
    // sidePanel.open() only works inside the click gesture, so it is called immediately and
    // never after an await.
    void browser.sidePanel.open({ tabId: tab.id });

    // TEMPORARY (Task 7, platform check): proves the click granted activeTab. Removed in Step 9.
    void browser.scripting
      .executeScript({ target: { tabId: tab.id }, func: () => document.title })
      .then(
        (results) => console.log("activeTab ok:", results[0]?.result),
        (error: unknown) => console.warn("activeTab FAILED:", error),
      );
  });
});
```

`extension/entrypoints/sidepanel/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <!-- WXT builds this page as the extension's side panel (entrypoints/sidepanel). -->
    <title>GuardianLens</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="./main.tsx"></script>
  </body>
</html>
```

`extension/entrypoints/sidepanel/main.tsx`:

```tsx
// Side panel entry point: loads the shared design styles and mounts the React app into #root.
import "@guardianlens/shared/styles.css";
import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

`extension/entrypoints/sidepanel/App.tsx`:

```tsx
// Side panel root component.
// Skeleton for Task 7: it only shows the idle message so the build and the toolbar click can be
// verified. Task 16 replaces this body with the real panel (idle, review, checking, result).
export function App() {
  return (
    <main style={{ padding: 16 }}>
      <span className="wordmark">
        <span className="lens-mark" aria-hidden="true" />
        GuardianLens
      </span>
      <p className="helper">Open a Mudah.my or Carousell listing, then click the GuardianLens icon.</p>
    </main>
  );
}
```

- [ ] **Step 6: Run the tests and the typecheck**

```bash
npm run test -w extension
npm run typecheck -w extension
```

Expected: the hosts and storage tests pass and the typecheck is clean. If TypeScript cannot find `defineBackground` or `browser`, run `npm run postinstall -w extension` to regenerate `.wxt/` types, then retry.

- [ ] **Step 7: Build and check the manifest**

Before building, open `extension/docs/SPIKE_NOTES.md`, read the `Image hosts` section, and make `IMAGE_HOST_PATTERNS` in `extension/lib/hosts.ts` match it exactly (add a pattern for every host the spike found; remove a guess the spike disproved), keeping the file's header comment accurate in the same edit. Then:

```bash
npm run build -w extension
node -e "const m=require('./extension/.output/chrome-mv3/manifest.json'); console.log(JSON.stringify({permissions:m.permissions,host_permissions:m.host_permissions,side_panel:m.side_panel,action:m.action,content_scripts:m.content_scripts}, null, 2))"
```

Expected: `permissions` contains `activeTab`, `scripting`, `storage`, `sidePanel`; `host_permissions` holds the API origin and the photo hosts and nothing for mudah.my or carousell.com.my pages; `side_panel.default_path` is set; `action` has a `default_title` and no `default_popup`; `content_scripts` is `undefined`.

- [ ] **Step 8: Verify the platform behaviour in real browsers (manual)**

1. Open `chrome://extensions`, turn on Developer mode, choose Load unpacked, and select `extension/.output/chrome-mv3`.
2. Open a real Carousell listing and click the GuardianLens toolbar icon. The side panel must open showing the idle message.
3. On the extension card click the `service worker` link to open its console. Expected line: `activeTab ok: <the listing page title>`.
4. In the same tab, open a different listing by clicking inside the site (same-origin navigation) and click the icon again. Expected: `activeTab ok:` again.
5. Open `https://example.com` and click the icon. Expected: `activeTab ok: Example Domain` (activeTab works on any site, which is why Task 11 refuses to inject anywhere except the two marketplaces).
6. Repeat steps 1 to 4 in Microsoft Edge using `edge://extensions`.

If the panel does not open, `browser.sidePanel` is undefined, or `activeTab FAILED` appears on a listing page, stop. Record exactly what happened and ask the developer how to proceed (for example opening the panel UI in a small popup window instead). Do not choose a fallback silently.

Add a section to `extension/docs/SPIKE_NOTES.md`:

```markdown
## Platform behaviour (Task 7)
| Check | Chrome | Edge |
| --- | --- | --- |
| Browser version | fill in | fill in |
| Toolbar click opens the side panel | yes or no | yes or no |
| Toolbar click grants activeTab (executeScript works) | yes or no | yes or no |
| activeTab survives same-site navigation | yes or no | yes or no |
| Notes | anything surprising | anything surprising |
```

- [ ] **Step 9: Remove the temporary verification code**

Delete the whole `// TEMPORARY (Task 7, platform check)` block (the comment and the `void browser.scripting ... );` statement) from `extension/entrypoints/background.ts`, and rewrite nothing else: the header comment already describes the final behaviour. Rebuild to confirm:

```bash
npm run build -w extension
```

- [ ] **Step 10: Commit**

```bash
git add package-lock.json extension
git commit -m "feat(extension): add WXT skeleton, storage helpers, and platform verification notes"
```

---

### Task 8: URL classifier, price parser, and photo selection

**Files:**
- Create: `extension/lib/capture/classify.ts`, `extension/lib/capture/values.ts`, `extension/lib/capture/images.ts`
- Create: `extension/tests/capture/classify.test.ts`, `extension/tests/capture/values.test.ts`, `extension/tests/capture/images.test.ts`

**Interfaces:**
- Consumes: `Platform`, `PlatformHost` from `@guardianlens/shared`; the `Seller page URL shapes` section of `SPIKE_NOTES.md`.
- Produces:
  - `interface PlatformInfo { platform: Platform; host: PlatformHost }`, `interface ListingRef extends PlatformInfo { listingId: string }`
  - `platformFromHost(hostname: string): PlatformInfo | null`
  - `classifyListingUrl(url: string | undefined): ListingRef | null`
  - `classifySellerUrl(url: string | undefined): PlatformInfo | null`
  - `normalizeText(value: string | null | undefined): string`
  - `textOf(node: Element | null | undefined): string`
  - `parsePriceRm(text: string | null | undefined): number | null`
  - `parsePriceValue(value: string | number | null | undefined): number | null`
  - `interface ImageCandidate { url: string; width: number; height: number }`
  - `directoryKey(url: string): string | null`
  - `selectGalleryImages(candidates: ImageCandidate[], structuredUrls: string[], limit?: number): string[]`

- [ ] **Step 1: Write the failing classifier tests**

`extension/tests/capture/classify.test.ts`:

```ts
// Pins how the extension decides what the current tab is.
// Getting this wrong has two costs: a real listing treated as "not a listing" blocks the buyer,
// and a look-alike site treated as a marketplace would get the capture script injected. So host
// matching is EXACT (no suffix tricks), only https counts, and the listing URL shapes are the
// ones the URL crawler and the Data Collector already use.
import { describe, expect, it } from "vitest";
import { classifyListingUrl, classifySellerUrl, platformFromHost } from "../../lib/capture/classify";

describe("platformFromHost", () => {
  it("knows the four marketplace hosts", () => {
    expect(platformFromHost("www.carousell.com.my")).toEqual({ platform: "carousell", host: "www.carousell.com.my" });
    expect(platformFromHost("mudah.my")).toEqual({ platform: "mudah", host: "mudah.my" });
  });

  it("is case-insensitive and rejects anything else", () => {
    expect(platformFromHost("WWW.MUDAH.MY")?.platform).toBe("mudah");
    expect(platformFromHost("example.com")).toBeNull();
  });
});

describe("classifyListingUrl", () => {
  it("recognises a Carousell listing", () => {
    expect(classifyListingUrl("https://www.carousell.com.my/p/iphone-13-1234567890/")).toEqual({
      platform: "carousell",
      host: "www.carousell.com.my",
      listingId: "1234567890",
    });
  });

  it("recognises a Mudah listing", () => {
    expect(classifyListingUrl("https://www.mudah.my/samsung-galaxy-s21-123456789.htm")).toEqual({
      platform: "mudah",
      host: "www.mudah.my",
      listingId: "123456789",
    });
  });

  it("ignores query strings and a missing trailing slash", () => {
    expect(classifyListingUrl("https://www.carousell.com.my/p/phone-99?ref=search")?.listingId).toBe("99");
  });

  it.each([
    ["plain http", "http://www.carousell.com.my/p/x-1/"],
    ["a category page", "https://www.carousell.com.my/categories/phones/"],
    ["an id that starts with zero", "https://www.carousell.com.my/p/x-0/"],
    ["another site", "https://example.com/p/x-1/"],
    ["a look-alike host (suffix trick)", "https://www.carousell.com.my.evil.com/p/x-1/"],
    ["a look-alike host (prefix trick)", "https://evilcarousell.com.my/p/x-1/"],
    ["the Mudah home page", "https://www.mudah.my/"],
    ["text that is not a URL", "not a url"],
    ["an empty string", ""],
  ])("rejects %s", (_label, url) => {
    expect(classifyListingUrl(url)).toBeNull();
  });

  it("returns null for undefined", () => {
    expect(classifyListingUrl(undefined)).toBeNull();
  });
});

describe("classifySellerUrl", () => {
  it("recognises a Carousell profile page", () => {
    expect(classifySellerUrl("https://www.carousell.com.my/u/some-seller/")).toEqual({
      platform: "carousell",
      host: "www.carousell.com.my",
    });
  });

  it("recognises a generic seller or shop path", () => {
    expect(classifySellerUrl("https://www.mudah.my/shop/some-shop")?.platform).toBe("mudah");
  });

  it("does not treat a listing as a seller page", () => {
    expect(classifySellerUrl("https://www.carousell.com.my/p/phone-123/")).toBeNull();
  });

  it("does not treat other sites as seller pages", () => {
    expect(classifySellerUrl("https://example.com/u/someone/")).toBeNull();
  });
});
```

- [ ] **Step 2: Write the failing price and text tests**

`extension/tests/capture/values.test.ts`:

```ts
// Pins the text helpers and, above all, the price rules.
// A fraud-risk model compares the price with the category average, so a WRONG price is worse
// than a missing one. The rules are therefore conservative (Review Focus 1):
//   - "RM 1,250", "RM1250.50" and "MYR 99" parse;
//   - a range ("RM 1,200 - RM 1,500"), "Free", "Negotiable", or no price give null, so the buyer
//     types the price; the code never invents 0 and never picks one end of a range.
import { describe, expect, it } from "vitest";
import { normalizeText, parsePriceRm, parsePriceValue, textOf } from "../../lib/capture/values";

describe("normalizeText", () => {
  it("collapses whitespace and trims", () => {
    expect(normalizeText("  a \n\t b  ")).toBe("a b");
  });

  it("returns an empty string for missing input", () => {
    expect(normalizeText(null)).toBe("");
    expect(normalizeText(undefined)).toBe("");
  });
});

describe("textOf", () => {
  it("reads the visible text of an element, normalised", () => {
    const div = document.createElement("div");
    div.innerHTML = "<p>Hello   <b>world</b></p>";
    expect(textOf(div)).toBe("Hello world");
  });

  it("returns an empty string for a missing element", () => {
    expect(textOf(null)).toBe("");
  });
});

describe("parsePriceRm", () => {
  it.each([
    ["RM 1,250", 1250],
    ["RM1250.50", 1250.5],
    ["MYR 99", 99],
    ["rm 3,500 nego", 3500],
    ["Price: RM 80 each, RM 80 per piece", 80],
    ["RM 0", 0],
  ])("reads %s as %s", (text, expected) => {
    expect(parsePriceRm(text)).toBe(expected);
  });

  it.each([
    ["a range", "RM 1,200 - RM 1,500"],
    ["Free", "Free"],
    ["Negotiable", "Negotiable"],
    ["a number with no currency", "1250"],
    ["an empty string", ""],
  ])("returns null for %s", (_label, text) => {
    expect(parsePriceRm(text)).toBeNull();
  });

  it("returns null for null and undefined", () => {
    expect(parsePriceRm(null)).toBeNull();
    expect(parsePriceRm(undefined)).toBeNull();
  });
});

describe("parsePriceValue", () => {
  it.each([
    ["1250.00", 1250],
    ["1,250", 1250],
    [99, 99],
  ])("reads %s as %s", (value, expected) => {
    expect(parsePriceValue(value)).toBe(expected);
  });

  it.each([["abc"], [""], [-5], [Number.NaN], [null], [undefined]])("returns null for %s", (value) => {
    expect(parsePriceValue(value)).toBeNull();
  });
});
```

- [ ] **Step 3: Write the failing photo selection tests**

`extension/tests/capture/images.test.ts`:

```ts
// Pins how the listing's own photos are told apart from icons and unrelated thumbnails.
// The rules are ported from the Data Collector's extension (collectPageData), which was tested on
// real Mudah.my and Carousell pages:
//   - photos named in the page's structured data come first;
//   - large rendered images (at least 160 x 160) are gallery photos;
//   - small images (at least 48 x 48) count only when they sit in the same CDN folder as a large
//     gallery photo (galleries often render the non-selected photos as thumbnails);
//   - only https URLs count; SVGs and data: URLs are dropped; duplicates are removed; the result
//     is capped (default 12).
import { describe, expect, it } from "vitest";
import { directoryKey, selectGalleryImages, type ImageCandidate } from "../../lib/capture/images";

const CDN = "https://media.karousell.com/photos/1";

/** Builds an image candidate; the size is what the page rendered. */
function img(url: string, width: number, height: number): ImageCandidate {
  return { url, width, height };
}

describe("directoryKey", () => {
  it("is the host plus the folder, so thumbnails can be matched to their full-size photo", () => {
    expect(directoryKey(`${CDN}/a.jpg`)).toBe("media.karousell.com/photos/1/");
  });

  it("returns null for something that is not a URL", () => {
    expect(directoryKey("nope")).toBeNull();
  });
});

describe("selectGalleryImages", () => {
  it("puts structured-data photos first and removes duplicates", () => {
    const result = selectGalleryImages([img(`${CDN}/b.jpg`, 600, 400), img(`${CDN}/a.jpg`, 600, 400)], [`${CDN}/a.jpg`]);
    expect(result).toEqual([`${CDN}/a.jpg`, `${CDN}/b.jpg`]);
  });

  it("keeps small thumbnails only when they share a folder with a large photo", () => {
    const result = selectGalleryImages(
      [
        img(`${CDN}/big.jpg`, 640, 480),
        img(`${CDN}/thumb.jpg`, 80, 80),
        img("https://media.karousell.com/related/9/thumb.jpg", 80, 80),
      ],
      [],
    );
    expect(result).toEqual([`${CDN}/big.jpg`, `${CDN}/thumb.jpg`]);
  });

  it("drops icons that are too small", () => {
    expect(selectGalleryImages([img(`${CDN}/big.jpg`, 640, 480), img(`${CDN}/icon.png`, 24, 24)], [])).toEqual([`${CDN}/big.jpg`]);
  });

  it("drops svg, http, and data: sources (Review Focus 2)", () => {
    const result = selectGalleryImages(
      [
        img(`${CDN}/logo.svg`, 640, 480),
        img("http://media.karousell.com/photos/1/plain.jpg", 640, 480),
        img("data:image/png;base64,AAAA", 640, 480),
        img(`${CDN}/ok.jpg`, 640, 480),
      ],
      [],
    );
    expect(result).toEqual([`${CDN}/ok.jpg`]);
  });

  it("caps the number of photos", () => {
    const many = Array.from({ length: 20 }, (_, index) => img(`${CDN}/p${index}.jpg`, 640, 480));
    expect(selectGalleryImages(many, [])).toHaveLength(12);
    expect(selectGalleryImages(many, [], 3)).toHaveLength(3);
  });

  it("returns an empty list when there is nothing usable", () => {
    expect(selectGalleryImages([], [])).toEqual([]);
  });
});
```

- [ ] **Step 4: Run the tests to confirm they fail**

```bash
npm run test -w extension
```

Expected: the three new test files fail because their modules do not exist.

- [ ] **Step 5: Implement the classifier**

`extension/lib/capture/classify.ts`:

```ts
// Decides what kind of page a URL is: a supported marketplace's LISTING page, its SELLER page,
// or neither. Pure string logic with no browser calls, so it is fast to test.
//
// Listing URL shapes are ported from URL_Crawler/url_utils.py and the Data Collector's
// extension. Seller URL shapes come from docs/SPIKE_NOTES.md ("Seller page URL shapes"); if a
// real seller page is not recognised, add its pattern here and a test with a fake slug for it.
import type { Platform, PlatformHost } from "@guardianlens/shared";

/** A recognised marketplace and the exact host the page was served from. */
export interface PlatformInfo {
  platform: Platform;
  host: PlatformHost;
}

/** A recognised listing page: the marketplace plus the listing's numeric id. */
export interface ListingRef extends PlatformInfo {
  listingId: string;
}

// The only four hosts the extension will ever act on. Matching is exact on purpose: a
// look-alike such as "www.carousell.com.my.evil.com" must never be treated as a marketplace.
const HOSTS: Record<string, PlatformInfo> = {
  "mudah.my": { platform: "mudah", host: "mudah.my" },
  "www.mudah.my": { platform: "mudah", host: "www.mudah.my" },
  "carousell.com.my": { platform: "carousell", host: "carousell.com.my" },
  "www.carousell.com.my": { platform: "carousell", host: "www.carousell.com.my" },
};

// Carousell listing: /p/<slug>-<numeric id>/        Mudah listing: /<slug>-<numeric id>.htm
// The id must start with 1-9 (no leading zero), matching the crawler's rule.
const CAROUSELL_LISTING = /^\/p\/[^/]+-([1-9]\d*)\/?$/i;
const MUDAH_LISTING = /^\/[^/]+-([1-9]\d*)\.htm$/i;

// Seller pages. Carousell profiles are /u/<username>/. Elsewhere a path segment named seller,
// profile, user, shop, or dealer marks one (the same words the Collector scores seller links by).
const CAROUSELL_SELLER = /^\/u\/[^/]+\/?$/i;
const GENERIC_SELLER = /\/(?:seller|profile|user|shop|dealer)(?:\/|$)/i;

/** Looks up a hostname in the four known marketplace hosts (case-insensitive, exact match). */
export function platformFromHost(hostname: string): PlatformInfo | null {
  return HOSTS[hostname.toLowerCase()] ?? null;
}

/** Parses a URL, accepting only https; returns null for anything else or for invalid text. */
function parseHttps(url: string | undefined): URL | null {
  try {
    const parsed = new URL(url ?? "");
    return parsed.protocol === "https:" ? parsed : null;
  } catch {
    return null;
  }
}

/**
 * Recognises a marketplace listing page.
 * @returns The platform, host, and listing id, or null when the URL is not a listing page.
 */
export function classifyListingUrl(url: string | undefined): ListingRef | null {
  const parsed = parseHttps(url);
  if (!parsed) return null;
  const info = platformFromHost(parsed.hostname);
  if (!info) return null;
  const pattern = info.platform === "carousell" ? CAROUSELL_LISTING : MUDAH_LISTING;
  const match = pattern.exec(parsed.pathname);
  return match ? { ...info, listingId: match[1] } : null;
}

/**
 * Recognises a marketplace seller / profile page.
 * @returns The platform and host, or null when the URL is not a seller page. A listing page is
 *          never a seller page, even if its path contains one of the seller words.
 */
export function classifySellerUrl(url: string | undefined): PlatformInfo | null {
  const parsed = parseHttps(url);
  if (!parsed) return null;
  const info = platformFromHost(parsed.hostname);
  if (!info || classifyListingUrl(url)) return null;
  const isSeller = CAROUSELL_SELLER.test(parsed.pathname) || GENERIC_SELLER.test(parsed.pathname);
  return isSeller ? info : null;
}
```

- [ ] **Step 6: Implement the text and price helpers**

`extension/lib/capture/values.ts`:

```ts
// Small helpers for reading values off a page: whitespace cleanup, the visible text of an
// element, and parsing a Malaysian-ringgit price. No browser APIs beyond the DOM node type.

/** Collapses runs of whitespace to single spaces and trims. Missing input gives "". */
export function normalizeText(value: string | null | undefined): string {
  return (value ?? "").replace(/\s+/g, " ").trim();
}

/**
 * The visible text of an element, normalised.
 * Real browsers provide `innerText`, which respects what is actually visible. jsdom (used by the
 * tests) does not implement it, so `textContent` is the fallback.
 */
export function textOf(node: Element | null | undefined): string {
  if (!node) return "";
  const visible = (node as HTMLElement).innerText;
  return normalizeText(typeof visible === "string" ? visible : node.textContent);
}

// An amount written with a currency prefix: "RM 1,250.50", "RM1250", "MYR 99".
const RM_AMOUNT = /(?:RM|MYR)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)/gi;

/**
 * Reads a price written with an RM or MYR prefix.
 * Conservative on purpose (a wrong price misleads the model more than a missing one):
 *  - exactly one distinct amount is required, so a range ("RM 1,200 - RM 1,500") is ambiguous
 *    and returns null rather than guessing an end;
 *  - words such as "Free" or "Negotiable", and bare numbers without a currency, return null.
 * @returns The amount in ringgit, or null when no single clear price is stated.
 */
export function parsePriceRm(text: string | null | undefined): number | null {
  const amounts = new Set<number>();
  for (const match of (text ?? "").matchAll(RM_AMOUNT)) {
    const value = Number(match[1].replace(/,/g, ""));
    if (Number.isFinite(value)) amounts.add(value);
  }
  return amounts.size === 1 ? [...amounts][0] : null;
}

/**
 * Reads a price from a structured value that carries no currency symbol, such as JSON-LD
 * `offers.price` ("1250.00") or a meta tag's content.
 * @returns A finite, non-negative number, or null.
 */
export function parsePriceValue(value: string | number | null | undefined): number | null {
  if (typeof value === "number") return Number.isFinite(value) && value >= 0 ? value : null;
  const cleaned = (value ?? "").replace(/[,\s]/g, "");
  if (!/^[0-9]+(?:\.[0-9]+)?$/.test(cleaned)) return null;
  const parsed = Number(cleaned);
  return Number.isFinite(parsed) ? parsed : null;
}
```

- [ ] **Step 7: Implement the photo selection**

`extension/lib/capture/images.ts`:

```ts
// Chooses which images on a listing page are the listing's own photos.
//
// Ported from the Data Collector's extension (extension/background.js, collectPageData), which
// was tested on real marketplace pages:
//   1. photos named in the page's structured data (JSON-LD) come first;
//   2. large rendered images (at least 160 x 160) are gallery photos;
//   3. small images (at least 48 x 48) count ONLY if they sit in the same CDN folder as a large
//      gallery photo: galleries often render the non-selected photos as thumbnails, while icons
//      and "related listings" thumbnails live in other folders;
//   4. only https URLs are kept; SVGs and data: URLs are dropped; duplicates are removed; at most
//      `limit` URLs are returned.

/** An image found on the page and the size it was rendered at. */
export interface ImageCandidate {
  url: string;
  width: number;
  height: number;
}

const LARGE_EDGE = 160;
const THUMBNAIL_EDGE = 48;

/** True for an https URL that is not an SVG (logos and icons are often SVG). */
function isUsable(url: string): boolean {
  if (/\.svg(?:[?#]|$)/i.test(url)) return false;
  try {
    return new URL(url).protocol === "https:";
  } catch {
    return false;
  }
}

/**
 * Groups an image URL by host and folder, so a thumbnail can be matched back to a full-size
 * photo served from the same CDN folder without depending on any site's CSS classes.
 * @returns "host/dir/" in lower case, or null when the URL cannot be parsed.
 */
export function directoryKey(url: string): string | null {
  try {
    const parsed = new URL(url);
    const lastSlash = parsed.pathname.lastIndexOf("/");
    const directory = lastSlash >= 0 ? parsed.pathname.slice(0, lastSlash + 1) : parsed.pathname;
    return `${parsed.hostname.toLowerCase()}${directory}`;
  } catch {
    return null;
  }
}

/**
 * Picks the listing's photos.
 * @param candidates Images found in the page's gallery area, with their rendered sizes.
 * @param structuredUrls Photo URLs named in the page's structured data (JSON-LD), if any.
 * @param limit Maximum number of URLs to return (default 12).
 * @returns Photo URLs, structured ones first, without duplicates.
 */
export function selectGalleryImages(
  candidates: ImageCandidate[],
  structuredUrls: string[],
  limit = 12,
): string[] {
  const usable = candidates.filter((candidate) => isUsable(candidate.url));
  const large = usable.filter((c) => c.width >= LARGE_EDGE && c.height >= LARGE_EDGE);
  const galleryDirectories = new Set(
    large.map((c) => directoryKey(c.url)).filter((key): key is string => key !== null),
  );
  const thumbnails =
    galleryDirectories.size === 0
      ? []
      : usable.filter(
          (c) =>
            c.width >= THUMBNAIL_EDGE &&
            c.height >= THUMBNAIL_EDGE &&
            !(c.width >= LARGE_EDGE && c.height >= LARGE_EDGE) &&
            galleryDirectories.has(directoryKey(c.url) ?? ""),
        );
  const ordered = [
    ...structuredUrls.filter(isUsable),
    ...large.map((c) => c.url),
    ...thumbnails.map((c) => c.url),
  ];
  return [...new Set(ordered)].slice(0, limit);
}
```

- [ ] **Step 8: Run the tests and the typecheck**

```bash
npm run test -w extension
npm run typecheck -w extension
```

Expected: all extension tests pass and the typecheck is clean.

- [ ] **Step 9: Compare with the spike notes**

Open `extension/docs/SPIKE_NOTES.md`, section `Seller page URL shapes`. For each real seller or profile URL shape it lists, confirm `classifySellerUrl` accepts a URL of that shape. If one is rejected, add its pattern next to `CAROUSELL_SELLER` / `GENERIC_SELLER` in `classify.ts`, add one test with a made-up slug in `classify.test.ts`, and update the comment above the patterns in the same edit so it names the new shape.

- [ ] **Step 10: Commit**

```bash
git add extension
git commit -m "feat(extension): add URL classifier, price parser, and photo selection"
```

---

### Task 9: Seller page parsers

**Files:**
- Create: `extension/lib/capture/seller.ts`
- Create: `extension/tests/capture/seller.test.ts`, `extension/tests/capture/seller.real.test.ts`, `extension/tests/helpers/realFixtures.ts`
- Modify: `extension/fixtures/README.md` (add `recordedOn` to the schema)

**Interfaces:**
- Consumes: `Platform` from `@guardianlens/shared`; `classifyListingUrl` from `./classify`; `normalizeText`, `textOf` from `./values`; the `Seller page phrases` section of `SPIKE_NOTES.md`.
- Produces:
  - `interface SellerValues { accountAgeDays: number | null; rating: number | null; reviewCount: number | null; activeListingCount: number | null }`
  - `parseAccountAgeDays(text: string, now: Date): number | null`
  - `parseReviewStats(text: string): { rating: number | null; reviewCount: number | null }`
  - `countActiveListings(doc: Document, platform: Platform, baseUrl: string): number | null`
  - `parseSellerPage(doc: Document, platform: Platform, baseUrl: string, now: Date): SellerValues`
  - Test helpers `listRealFixtures()`, `readFixtureHtml(fixture, name)`, `parseHtml(html)`, `loadSynthetic(name)`, and the `ExpectedFixture` / `RealFixture` types in `extension/tests/helpers/realFixtures.ts`.

- [ ] **Step 1: Add `recordedOn` to the fixture schema**

In `extension/fixtures/README.md`, in the `expected.json` schema block, add as the first key `"recordedOn": "2026-10-05",` and add under the schema one sentence: "`recordedOn` is the date you recorded the page; account-age tests use it as 'today' so a stated join date still gives the same number of days later." Add the same key to each `expected.json` you wrote in Task 1.

- [ ] **Step 2: Write the test helpers**

`extension/tests/helpers/realFixtures.ts`:

```ts
// Helpers for tests that read page fixtures.
//
// Two kinds of fixture exist:
//  - synthetic: small hand-written pages in tests/fixtures/synthetic/. Committed; always run.
//  - real: pages recorded from live Mudah.my / Carousell with fixtures/record-fixture.js. They
//    hold third-party listing text, so they are git-ignored and live only on the developer's
//    machine. Tests built on them skip themselves when none are present.
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import type { Platform } from "@guardianlens/shared";

const REAL_ROOT = fileURLToPath(new URL("../../fixtures/real", import.meta.url));
const SYNTHETIC_ROOT = fileURLToPath(new URL("../fixtures/synthetic", import.meta.url));

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
```

- [ ] **Step 3: Write the failing seller tests**

`extension/tests/capture/seller.test.ts`:

```ts
// Pins the seller-page parsers.
// The behavioural model was trained on seller fields that the Data Collector extracted with an
// LLM under fixed rules (Collector: extraction_contract.py). The extension has no LLM, so these
// parsers must reproduce the SAME conventions or the model would see inputs unlike its training
// data. The conventions pinned here:
//   - account age in days: a stated duration is 1 year = 365 days and 1 month = 30 days; a stated
//     join date counts the days from that date to today;
//   - "No reviews yet" means review count 0 (and rating 0.0 when no rating is shown);
//   - active listings are the listing cards NOT marked SOLD; a "Listings" heading with no cards
//     is 0; no heading and no cards is "not found" (null).
import { describe, expect, it } from "vitest";
import {
  countActiveListings,
  parseAccountAgeDays,
  parseReviewStats,
  parseSellerPage,
} from "../../lib/capture/seller";
import { parseHtml } from "../helpers/realFixtures";

// "Today" for every date calculation, so the tests do not depend on the real clock.
const NOW = new Date(Date.UTC(2026, 9, 5));
const BASE = "https://www.carousell.com.my/u/someone/";

describe("parseAccountAgeDays", () => {
  it.each([
    ["Joined 3 years 2 months ago", 1155],
    ["Joined 11 years ago", 4015],
    ["Joined 8 months ago", 240],
    ["Been on Carousell for 2 years", 730],
  ])("converts the stated duration in %s", (text, days) => {
    expect(parseAccountAgeDays(text, NOW)).toBe(days);
  });

  it.each([
    ["Joined Since 21 May 2020"],
    ["Member since May 21, 2020"],
  ])("counts the days from a stated join date in %s", (text) => {
    // 21 May 2020 to 5 Oct 2026 is 2328 days.
    expect(parseAccountAgeDays(text, NOW)).toBe(2328);
  });

  it("does not guess from a year alone", () => {
    expect(parseAccountAgeDays("Member since 2019", NOW)).toBeNull();
  });

  it("ignores a duration that is not about the account", () => {
    expect(parseAccountAgeDays("Usually replies within 3 months", NOW)).toBeNull();
  });

  it("rejects a join date in the future and an impossible date", () => {
    expect(parseAccountAgeDays("Joined 1 Jan 2030", NOW)).toBeNull();
    expect(parseAccountAgeDays("Joined 31 Feb 2020", NOW)).toBeNull();
  });
});

describe("parseReviewStats", () => {
  it("reads a combined rating and count", () => {
    expect(parseReviewStats("4.8 (17 reviews)")).toEqual({ rating: 4.8, reviewCount: 17 });
  });

  it("reads separate rating and count", () => {
    expect(parseReviewStats("Rating 4.5 out of 5 · 1,120 reviews")).toEqual({ rating: 4.5, reviewCount: 1120 });
  });

  it("treats 'No reviews yet' as zero reviews and a 0.0 rating", () => {
    expect(parseReviewStats("No reviews yet N/A")).toEqual({ rating: 0, reviewCount: 0 });
  });

  it("reports a count with no rating as a missing rating", () => {
    expect(parseReviewStats("12 reviews")).toEqual({ rating: null, reviewCount: 12 });
  });

  it("rejects a rating outside 0 to 5", () => {
    expect(parseReviewStats("7.5 stars, 3 reviews").rating).toBeNull();
  });

  it("returns nothing when the text says nothing about reviews", () => {
    expect(parseReviewStats("Joined 3 years ago")).toEqual({ rating: null, reviewCount: null });
  });
});

describe("countActiveListings", () => {
  const card = (id: string, sold = false) =>
    `<article><a href="/p/item-${id}/">Item</a>${sold ? "<span>SOLD</span>" : ""}</article>`;

  it("counts listing cards that are not marked SOLD", () => {
    const doc = parseHtml(`<body><h2>Listings</h2>${card("111")}${card("222", true)}${card("333")}</body>`);
    expect(countActiveListings(doc, "carousell", BASE)).toBe(2);
  });

  it("counts a listing once even when it is linked twice", () => {
    const doc = parseHtml(
      '<body><article><a href="/p/item-111/"><img alt="" /></a><a href="/p/item-111/">Title</a></article></body>',
    );
    expect(countActiveListings(doc, "carousell", BASE)).toBe(1);
  });

  it("is zero when the Listings heading has no cards", () => {
    expect(countActiveListings(parseHtml("<body><h2>Listings</h2></body>"), "carousell", BASE)).toBe(0);
  });

  it("is zero when every card is sold", () => {
    const doc = parseHtml(`<body><h2>Listings</h2>${card("111", true)}</body>`);
    expect(countActiveListings(doc, "carousell", BASE)).toBe(0);
  });

  it("is not found when there is no Listings heading and no cards", () => {
    expect(countActiveListings(parseHtml("<body><p>Hello</p></body>"), "carousell", BASE)).toBeNull();
  });

  it("ignores links to listings on the other marketplace", () => {
    const doc = parseHtml('<body><a href="https://www.mudah.my/phone-123456.htm">x</a></body>');
    expect(countActiveListings(doc, "carousell", BASE)).toBeNull();
  });
});

describe("parseSellerPage", () => {
  it("combines all four values from one page", () => {
    const doc = parseHtml(`<body>
      <h1>Seller</h1>
      <p>Joined 3 years 2 months ago</p>
      <p>4.8 (17 reviews)</p>
      <h2>Listings</h2>
      <article><a href="/p/phone-111/">Phone</a></article>
      <article><a href="/p/laptop-222/">Laptop</a><span>SOLD</span></article>
    </body>`);
    expect(parseSellerPage(doc, "carousell", BASE, NOW)).toEqual({
      accountAgeDays: 1155,
      rating: 4.8,
      reviewCount: 17,
      activeListingCount: 1,
    });
  });
});
```

`extension/tests/capture/seller.real.test.ts`:

```ts
// Checks the seller parsers against seller pages recorded from the live sites (Task 1).
// These pages are git-ignored, so on a machine without them the whole file skips itself.
// A value of null in expected.json means "the page does not show it"; only shown values are compared.
import { describe, expect, it } from "vitest";
import { parseSellerPage } from "../../lib/capture/seller";
import { listRealFixtures, parseHtml, readFixtureHtml } from "../helpers/realFixtures";

const fixtures = listRealFixtures();
const BASE = {
  carousell: "https://www.carousell.com.my/u/seller/",
  mudah: "https://www.mudah.my/seller/shop",
} as const;

describe.skipIf(fixtures.length === 0)("seller parsing on locally recorded real pages", () => {
  for (const fixture of fixtures) {
    const html = readFixtureHtml(fixture, "seller");
    it.skipIf(html === null)(`${fixture.platform}/${fixture.slug}`, () => {
      const today = new Date(`${fixture.expected.recordedOn}T00:00:00Z`);
      const parsed = parseSellerPage(parseHtml(html as string), fixture.platform, BASE[fixture.platform], today);
      const shown = fixture.expected.seller;
      if (shown.accountAgeDays !== null) expect(parsed.accountAgeDays).toBe(shown.accountAgeDays);
      if (shown.rating !== null) expect(parsed.rating).toBe(shown.rating);
      if (shown.reviewCount !== null) expect(parsed.reviewCount).toBe(shown.reviewCount);
      if (shown.activeListingCount !== null) expect(parsed.activeListingCount).toBe(shown.activeListingCount);
    });
  }
});
```

- [ ] **Step 4: Run the tests to confirm they fail**

```bash
npm run test -w extension
```

Expected: `seller.test.ts` fails because `../../lib/capture/seller` does not exist (`seller.real.test.ts` also fails to import until then, or skips when no real fixtures exist).

- [ ] **Step 5: Implement the seller parsers**

`extension/lib/capture/seller.ts`:

```ts
// Reads seller details from a seller / profile page, using the SAME conventions the models were
// trained on.
//
// Why conventions matter: the behavioural model was trained on seller fields that the Data
// Collector extracted with an LLM under fixed rules (Collector: extraction_contract.py). The
// extension has no LLM, so these deterministic parsers must reproduce those rules or the model
// would see inputs unlike its training data:
//   - account age (days): a stated duration is 1 year = 365 days and 1 month = 30 days; a stated
//     join date is the number of days from that date to today;
//   - "No reviews yet": review count 0, and rating 0.0 when no rating is shown;
//   - active listings: the listing cards NOT marked SOLD. A "Listings" heading with no cards is 0;
//     no heading and no cards is "not found" (null), never 0.
//
// The exact wording on the real pages comes from docs/SPIKE_NOTES.md ("Seller page phrases").
// When a real page uses wording these patterns miss, add the pattern here AND a test for that
// wording in seller.test.ts, and keep the comments above accurate.
import type { Platform } from "@guardianlens/shared";
import { classifyListingUrl } from "./classify";
import { normalizeText, textOf } from "./values";

/** The four seller values; each is null when the page does not show it. */
export interface SellerValues {
  accountAgeDays: number | null;
  rating: number | null;
  reviewCount: number | null;
  activeListingCount: number | null;
}

const MONTHS: Record<string, number> = {
  jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5, jul: 6, aug: 7, sep: 8, oct: 9, nov: 10, dec: 11,
};

// Words that introduce the account-age statement. A duration or date is read only when it
// follows one of these, so an unrelated "3 months" elsewhere on the page is ignored.
const AGE_ANCHOR =
  /(joined(?:\s+since)?|member\s+since|been\s+on\s+(?:carousell|mudah)(?:\s+for)?|account\s+(?:age|created))/i;

/** Builds a UTC date, or null when the month name is unknown or the day does not exist (31 Feb). */
function utcDate(year: string, monthName: string, day: string): Date | null {
  const month = MONTHS[monthName.slice(0, 3).toLowerCase()];
  if (month === undefined) return null;
  const date = new Date(Date.UTC(Number(year), month, Number(day)));
  // Date.UTC rolls 31 Feb over into March, so check the date came back unchanged.
  return date.getUTCMonth() === month && date.getUTCDate() === Number(day) ? date : null;
}

/** Whole days between two dates, ignoring the time of day. */
function daysBetween(from: Date, to: Date): number {
  const start = Date.UTC(from.getUTCFullYear(), from.getUTCMonth(), from.getUTCDate());
  const end = Date.UTC(to.getUTCFullYear(), to.getUTCMonth(), to.getUTCDate());
  return Math.round((end - start) / 86_400_000);
}

/**
 * Reads the account age in days from seller-page text.
 * @param text Visible text of the page.
 * @param now "Today", used when the page states a join date instead of a duration.
 * @returns Days, or null when the page states neither a duration nor a full join date after an
 *          account-age phrase (a bare year such as "Member since 2019" is not enough).
 */
export function parseAccountAgeDays(text: string, now: Date): number | null {
  const anchor = AGE_ANCHOR.exec(text);
  if (!anchor) return null;
  const start = anchor.index + anchor[0].length;
  // Only the 80 characters after the anchor are read, so later text on the page cannot leak in.
  const nearby = text.slice(start, start + 80);

  // A stated join date: "21 May 2020" or "May 21, 2020".
  const dayFirst = /(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})/.exec(nearby);
  const monthFirst = /([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})/.exec(nearby);
  const joined = dayFirst
    ? utcDate(dayFirst[3], dayFirst[2], dayFirst[1])
    : monthFirst
      ? utcDate(monthFirst[3], monthFirst[1], monthFirst[2])
      : null;
  if (joined) {
    const days = daysBetween(joined, now);
    return days >= 0 ? days : null;
  }

  // A stated duration: "3 years 2 months", "11 years", "8 months".
  const years = /(\d+)\s*(?:years?|yrs?)\b/i.exec(nearby);
  const months = /(\d+)\s*(?:months?|mths?)\b/i.exec(nearby);
  if (!years && !months) return null;
  return (years ? Number(years[1]) * 365 : 0) + (months ? Number(months[1]) * 30 : 0);
}

/** A rating from 0 to 5, or null when the number is outside that range. */
function boundedRating(value: string): number | null {
  const rating = Number(value);
  return Number.isFinite(rating) && rating >= 0 && rating <= 5 ? rating : null;
}

/** An integer written possibly with thousands separators ("1,120"). */
function toInt(value: string): number {
  return Number(value.replace(/,/g, ""));
}

/**
 * Reads the rating and the number of reviews from seller-page text.
 * Follows the training convention: "No reviews yet" is 0 reviews, and a 0.0 rating when no
 * rating is otherwise shown (an "N/A" rating beside it means there is nothing to average).
 */
export function parseReviewStats(text: string): { rating: number | null; reviewCount: number | null } {
  // "4.8 (17 reviews)"
  const combined = /(\d(?:\.\d{1,2})?)\s*\(\s*(\d[\d,]*)\s*reviews?\s*\)/i.exec(text);
  if (combined) return { rating: boundedRating(combined[1]), reviewCount: toInt(combined[2]) };

  const noReviews = /\bno\s+reviews?(?:\s+yet)?\b/i.test(text);
  const counted = /(\d[\d,]*)\s+reviews?\b/i.exec(text);
  const reviewCount = counted ? toInt(counted[1]) : noReviews ? 0 : null;

  const labelled = /rating[:\s]+(\d(?:\.\d{1,2})?)/i.exec(text);
  const suffixed = /(\d(?:\.\d{1,2})?)\s*(?:\/\s*5|out of 5|stars?|★)/i.exec(text);
  const found = labelled ?? suffixed;
  const rating = found ? boundedRating(found[1]) : noReviews ? 0 : null;

  return { rating, reviewCount };
}

/** True when the page has a heading that reads "Listings" (optionally with a count). */
function hasListingsHeading(doc: Document): boolean {
  return Array.from(doc.querySelectorAll("h1, h2, h3, h4, [role='heading']")).some((element) =>
    /^listings?(?:\s*\(\d+\))?$/i.test(textOf(element)),
  );
}

/**
 * Counts the seller's listing cards that are not marked SOLD.
 * @param baseUrl The page's URL, used to resolve relative links.
 * @returns The count; 0 when a Listings heading exists with no cards; null when the page shows
 *          no listings section at all.
 */
export function countActiveListings(doc: Document, platform: Platform, baseUrl: string): number | null {
  // listing id -> whether any card for it says SOLD
  const seen = new Map<string, boolean>();
  for (const anchor of Array.from(doc.querySelectorAll<HTMLAnchorElement>("a[href]"))) {
    let absolute: string;
    try {
      absolute = new URL(anchor.getAttribute("href") ?? "", baseUrl).href;
    } catch {
      continue;
    }
    const ref = classifyListingUrl(absolute);
    if (!ref || ref.platform !== platform) continue;
    // The card is the nearest article or list item around the link, else the link itself.
    const card = anchor.closest("article, li, [data-testid*='listing' i]") ?? anchor;
    const sold = /\bsold\b/i.test(textOf(card));
    // A listing is often linked twice (photo and title); it is sold if any of its cards says so.
    seen.set(ref.listingId, (seen.get(ref.listingId) ?? false) || sold);
  }
  if (seen.size > 0) return [...seen.values()].filter((sold) => !sold).length;
  return hasListingsHeading(doc) ? 0 : null;
}

/**
 * Reads all four seller values from a seller / profile page.
 * @param doc The seller page document.
 * @param platform Which marketplace the page belongs to.
 * @param baseUrl The page's URL, used to resolve listing links.
 * @param now "Today", for join-date calculations.
 */
export function parseSellerPage(doc: Document, platform: Platform, baseUrl: string, now: Date): SellerValues {
  const text = normalizeText(textOf(doc.body));
  const { rating, reviewCount } = parseReviewStats(text);
  return {
    accountAgeDays: parseAccountAgeDays(text, now),
    rating,
    reviewCount,
    activeListingCount: countActiveListings(doc, platform, baseUrl),
  };
}
```

- [ ] **Step 6: Run the tests and the typecheck**

```bash
npm run test -w extension
npm run typecheck -w extension
```

Expected: all pass. If jsdom rejects a selector that uses the case-insensitive `i` flag (for example `[data-testid*='listing' i]`), replace it with two selectors, `[data-testid*='listing'], [data-testid*='Listing']`, and update the nearby comment in the same edit.

- [ ] **Step 7: Run the parsers against the real pages**

Open `extension/docs/SPIKE_NOTES.md`, section `Seller page phrases`, then run:

```bash
npm run test -w extension -- seller.real
```

Expected: every real fixture passes. For each failure: find the real phrase on that page (it is in `seller.html`), adjust the matching pattern in `seller.ts` (for example add a new anchor word to `AGE_ANCHOR` or a new rating phrasing), add a unit test with that phrase in `seller.test.ts`, and update the comments above the changed pattern. Rerun until all pass or until a value genuinely is not shown (then set it to `null` in that `expected.json`).

- [ ] **Step 8: Commit**

```bash
git add extension
git commit -m "feat(extension): add seller page parsers that follow the training conventions"
```

---

### Task 10: Listing adapter

**Files:**
- Create: `extension/lib/capture/types.ts`, `extension/lib/capture/selectors.ts`, `extension/lib/capture/listing.ts`
- Create: `extension/tests/fixtures/synthetic/carousell-jsonld.html`, `mudah-dom-only.html`, `selectors-description.html`, `blocked-captcha.html`, `blocked-login.html`, `listing-unavailable.html`, `missing-everything.html`
- Create: `extension/tests/capture/listing.test.ts`, `extension/tests/capture/listing.real.test.ts`

**Interfaces:**
- Consumes: `classifyListingUrl` (Task 8), `selectGalleryImages` and `ImageCandidate` (Task 8), `normalizeText`, `textOf`, `parsePriceRm`, `parsePriceValue` (Task 8), `loadSynthetic`, `parseHtml`, `listRealFixtures`, `readFixtureHtml` (Task 9), `isFetchableImageUrl` (Task 7), the `Description and category selectors` section of `SPIKE_NOTES.md`.
- Produces:
  - from `types.ts`: `ADAPTER_VERSION: string`, `CAPTURE_MESSAGE: string`, types `BlockedState`, `PageState`, `CapturedField<T>`, `CapturedListing`, `CapturedSeller`, `CaptureResult`
  - from `selectors.ts`: `interface PlatformSelectors { title: string[]; description: string[]; price: string[]; category: string[] }`, `PLATFORM_SELECTORS: Record<Platform, PlatformSelectors>`
  - from `listing.ts`: `detectPageState(doc: Document, pathname: string): BlockedState | null`, `interface CaptureOptions { selectors?: Record<Platform, PlatformSelectors> }`, `captureListing(doc: Document, url: string, options?: CaptureOptions): CapturedListing` (throws for a URL that is not a supported listing page)

- [ ] **Step 1: Create the synthetic fixtures**

These are small hand-written pages that always run in CI. Each isolates one extraction strategy.

`extension/tests/fixtures/synthetic/carousell-jsonld.html` (everything is in JSON-LD; the breadcrumb ends with the category):

```html
<!doctype html>
<!-- Synthetic Carousell-style listing: all fields are in JSON-LD structured data. -->
<html lang="en">
<head>
  <title>Used laptop in good condition | Carousell Malaysia</title>
  <meta property="og:title" content="Used laptop in good condition - Carousell Malaysia" />
  <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@graph": [
        {
          "@type": "Product",
          "name": "Used laptop in good condition",
          "description": "Original unit, battery health 90 percent. COD available around Shah Alam.",
          "image": [
            "https://media.karousell.com/media/photos/products/1/a.jpg",
            "https://media.karousell.com/media/photos/products/1/b.jpg"
          ],
          "offers": { "@type": "Offer", "price": "1250.00", "priceCurrency": "MYR" }
        },
        {
          "@type": "BreadcrumbList",
          "itemListElement": [
            { "@type": "ListItem", "position": 1, "name": "Home" },
            { "@type": "ListItem", "position": 2, "name": "Computers and Tech" },
            { "@type": "ListItem", "position": 3, "name": "Laptops" }
          ]
        }
      ]
    }
  </script>
</head>
<body>
  <main>
    <h1>Used laptop in good condition</h1>
    <div class="gallery">
      <img src="https://media.karousell.com/media/photos/products/1/a.jpg" width="640" height="480" alt="" />
      <img src="https://media.karousell.com/media/photos/products/1/b.jpg" width="640" height="480" alt="" />
    </div>
    <p class="price">RM 1,250</p>
  </main>
</body>
</html>
```

`extension/tests/fixtures/synthetic/mudah-dom-only.html` (no structured data: title from the heading, price from a visible RM leaf, description from the og meta tag, category from the breadcrumb links, one icon that must not count as a photo):

```html
<!doctype html>
<!-- Synthetic Mudah-style listing with NO structured data: every field comes from the DOM or meta tags. -->
<html lang="en">
<head>
  <title>Samsung Galaxy S21 128GB - Mudah.my</title>
  <meta property="og:description" content="Samsung phone, screen cracked, price negotiable. Meet up around KL." />
</head>
<body>
  <nav aria-label="Breadcrumb">
    <a href="/">Home</a>
    <a href="/malaysia/mobile-phones">Mobile Phones</a>
  </nav>
  <main>
    <h1>Samsung Galaxy S21 128GB</h1>
    <div class="gallery">
      <img src="https://img.mudah.my/photos/1/x.jpg" width="600" height="450" alt="" />
      <img src="https://img.mudah.my/photos/1/y.jpg" width="600" height="450" alt="" />
      <img src="https://img.mudah.my/static/icon.png" width="24" height="24" alt="" />
    </div>
    <div><span>RM 3,500</span></div>
  </main>
</body>
</html>
```

`extension/tests/fixtures/synthetic/selectors-description.html` (the description lives in a plain box that only a platform selector can find):

```html
<!doctype html>
<!-- Synthetic page where the description is only reachable through a platform-specific selector. -->
<html lang="en">
<head><title>Desk lamp</title></head>
<body>
  <main>
    <h1>Desk lamp</h1>
    <div class="desc-box">Adjustable LED desk lamp, used for one year.</div>
    <span>RM 45</span>
  </main>
</body>
</html>
```

`extension/tests/fixtures/synthetic/blocked-captcha.html`:

```html
<!doctype html>
<!-- Synthetic page the marketplace shows when it suspects a bot. -->
<html lang="en">
<head><title>Security check</title></head>
<body><main><h1>One more step</h1><p>Please verify that you are human to continue.</p></main></body>
</html>
```

`extension/tests/fixtures/synthetic/blocked-login.html`:

```html
<!doctype html>
<!-- Synthetic page that asks the visitor to log in before showing the listing. -->
<html lang="en">
<head><title>Log in</title></head>
<body><main><h1>Welcome back</h1><p>Please log in to continue.</p></main></body>
</html>
```

`extension/tests/fixtures/synthetic/listing-unavailable.html`:

```html
<!doctype html>
<!-- Synthetic page for a listing that was removed. -->
<html lang="en">
<head><title>Not available</title></head>
<body><main><h1>Oops</h1><p>This listing has been removed by the seller.</p></main></body>
</html>
```

`extension/tests/fixtures/synthetic/missing-everything.html`:

```html
<!doctype html>
<!-- Synthetic page with only a heading: nothing else can be read, so every other field is "not found". -->
<html lang="en">
<head><title>Page</title></head>
<body><main><h1>Bare page</h1></main></body>
</html>
```

- [ ] **Step 2: Write the failing adapter tests**

`extension/tests/capture/listing.test.ts`:

```ts
// Pins the listing adapter: what it reads from a listing page, and what it refuses to guess.
// Each synthetic fixture isolates one strategy (JSON-LD, DOM only, platform selectors) so a
// failure points at the strategy that broke. The rules protected here:
//   - a field no strategy can read is "not_found", never invented (the buyer fills it in Review);
//   - an ambiguous price (a range, "Free", "Negotiable") is "not_found", never 0 or one end;
//   - blocked pages (captcha, login wall, removed listing) are reported, not half-read;
//   - malformed structured data cannot crash the capture.
import { describe, expect, it } from "vitest";
import { captureListing, detectPageState } from "../../lib/capture/listing";
import { PLATFORM_SELECTORS } from "../../lib/capture/selectors";
import { loadSynthetic, parseHtml } from "../helpers/realFixtures";

const CAROUSELL_URL = "https://www.carousell.com.my/p/used-laptop-1234567890/";
const MUDAH_URL = "https://www.mudah.my/samsung-galaxy-s21-123456789.htm";

/** Builds a small page from head and body markup, for tests that need one specific shape. */
function page(body: string, head = ""): Document {
  return parseHtml(`<!doctype html><html><head>${head}</head><body><main>${body}</main></body></html>`);
}

describe("structured data page (Carousell style)", () => {
  const listing = captureListing(loadSynthetic("carousell-jsonld"), CAROUSELL_URL);

  it("reads every field", () => {
    expect(listing.title).toEqual({ status: "captured", value: "Used laptop in good condition" });
    expect(listing.description.value).toBe("Original unit, battery health 90 percent. COD available around Shah Alam.");
    expect(listing.price).toEqual({ status: "captured", value: 1250 });
    expect(listing.category.value).toBe("Laptops");
  });

  it("reads the photos and identifies the page", () => {
    expect(listing.imageUrls).toEqual([
      "https://media.karousell.com/media/photos/products/1/a.jpg",
      "https://media.karousell.com/media/photos/products/1/b.jpg",
    ]);
    expect(listing.platform).toBe("carousell");
    expect(listing.platformHost).toBe("www.carousell.com.my");
    expect(listing.marketplaceListingId).toBe("1234567890");
    expect(listing.pageState).toBe("ready");
  });
});

describe("DOM-only page (Mudah style)", () => {
  const listing = captureListing(loadSynthetic("mudah-dom-only"), MUDAH_URL);

  it("falls back to the heading, the visible RM price, the og description, and the breadcrumb", () => {
    expect(listing.title.value).toBe("Samsung Galaxy S21 128GB");
    expect(listing.price.value).toBe(3500);
    expect(listing.description.value).toBe("Samsung phone, screen cracked, price negotiable. Meet up around KL.");
    expect(listing.category.value).toBe("Mobile Phones");
  });

  it("keeps the gallery photos and leaves out the icon", () => {
    expect(listing.imageUrls).toEqual([
      "https://img.mudah.my/photos/1/x.jpg",
      "https://img.mudah.my/photos/1/y.jpg",
    ]);
    expect(listing.pageState).toBe("ready");
  });
});

describe("platform selectors", () => {
  it("do not find a description that only a selector can reach, unless one is configured", () => {
    const without = captureListing(loadSynthetic("selectors-description"), CAROUSELL_URL);
    expect(without.description).toEqual({ status: "not_found", value: null });

    const withSelector = captureListing(loadSynthetic("selectors-description"), CAROUSELL_URL, {
      selectors: { ...PLATFORM_SELECTORS, carousell: { ...PLATFORM_SELECTORS.carousell, description: [".desc-box"] } },
    });
    expect(withSelector.description.value).toBe("Adjustable LED desk lamp, used for one year.");
  });
});

describe("blocked pages", () => {
  it.each([
    ["blocked-captcha", "captcha"],
    ["blocked-login", "login_required"],
    ["listing-unavailable", "listing_unavailable"],
  ])("reports %s as %s", (name, state) => {
    expect(captureListing(loadSynthetic(name), CAROUSELL_URL).pageState).toBe(state);
  });

  it("detects a login URL even when the text says nothing", () => {
    expect(detectPageState(page("<p>hello</p>"), "/login")).toBe("login_required");
  });

  it("returns null for an ordinary page", () => {
    expect(detectPageState(page("<h1>Phone</h1>"), "/p/phone-1/")).toBeNull();
  });
});

describe("incomplete pages", () => {
  it("marks every unreadable field as not found and the page as incomplete", () => {
    const listing = captureListing(loadSynthetic("missing-everything"), CAROUSELL_URL);
    expect(listing.title.value).toBe("Bare page");
    expect(listing.description.status).toBe("not_found");
    expect(listing.price.status).toBe("not_found");
    expect(listing.category.status).toBe("not_found");
    expect(listing.imageUrls).toEqual([]);
    expect(listing.pageState).toBe("incomplete");
  });
});

// Review Focus 1: prices that are not "RM 1,250".
describe("ambiguous prices", () => {
  it.each([
    ["a range", "<span>RM 1,200 - RM 1,500</span>"],
    ["the word Free", "<span>Free</span>"],
    ["Negotiable", "<span>Negotiable</span>"],
  ])("are not found for %s", (_label, markup) => {
    const listing = captureListing(page(`<h1>Item</h1>${markup}`), CAROUSELL_URL);
    expect(listing.price).toEqual({ status: "not_found", value: null });
  });

  it("reads a price written without a space or with decimals", () => {
    expect(captureListing(page("<h1>Item</h1><span>RM1250.50</span>"), CAROUSELL_URL).price.value).toBe(1250.5);
  });
});

describe("robustness", () => {
  it("ignores malformed structured data", () => {
    const doc = page("<h1>Item</h1><span>RM 10</span>", '<script type="application/ld+json">{bad json</script>');
    const listing = captureListing(doc, CAROUSELL_URL);
    expect(listing.title.value).toBe("Item");
    expect(listing.price.value).toBe(10);
  });

  it("skips a breadcrumb entry that is just the listing title", () => {
    const doc = page(
      '<nav aria-label="Breadcrumb"><a>Home</a><a>Laptops</a><a>Used laptop</a></nav><h1>Used laptop</h1>',
    );
    expect(captureListing(doc, CAROUSELL_URL).category.value).toBe("Laptops");
  });

  it("falls back to the og:image photo when the page has no gallery images", () => {
    const doc = page("<h1>Item</h1>", '<meta property="og:image" content="https://media.karousell.com/media/photos/products/9/cover.jpg" />');
    expect(captureListing(doc, CAROUSELL_URL).imageUrls).toEqual([
      "https://media.karousell.com/media/photos/products/9/cover.jpg",
    ]);
  });

  it("refuses a URL that is not a supported listing page", () => {
    expect(() => captureListing(page("<h1>Item</h1>"), "https://example.com/p/x-1/")).toThrow();
  });
});
```

`extension/tests/capture/listing.real.test.ts`:

```ts
// Checks the listing adapter against listing pages recorded from the live sites (Task 1).
// These pages are git-ignored, so on a machine without them the whole file skips itself.
// A null in expected.json means "the page does not show it", and only shown values are compared.
// The photo check also protects host_permissions: the first photos the adapter picks must be
// fetchable, otherwise a photo host is missing from lib/hosts.ts.
import { describe, expect, it } from "vitest";
import { captureListing } from "../../lib/capture/listing";
import { isFetchableImageUrl } from "../../lib/hosts";
import { listRealFixtures, parseHtml, readFixtureHtml } from "../helpers/realFixtures";

const fixtures = listRealFixtures();
// Any well-formed listing URL for the platform: the adapter only needs the shape, not a real id.
const LISTING_URL = {
  carousell: "https://www.carousell.com.my/p/fixture-1000000001/",
  mudah: "https://www.mudah.my/fixture-1000000001.htm",
} as const;

describe.skipIf(fixtures.length === 0)("listing capture on locally recorded real pages", () => {
  for (const fixture of fixtures) {
    const html = readFixtureHtml(fixture, "listing");
    it.skipIf(html === null)(`${fixture.platform}/${fixture.slug}`, () => {
      const listing = captureListing(parseHtml(html as string), LISTING_URL[fixture.platform]);
      const shown = fixture.expected;
      if (shown.title !== null) expect(listing.title.value).toBe(shown.title);
      if (shown.priceRm !== null) expect(listing.price.value).toBe(shown.priceRm);
      if (shown.category !== null) {
        expect(listing.category.value?.toLowerCase()).toContain(shown.category.toLowerCase());
      }
      if (shown.descriptionStartsWith !== null) {
        expect(listing.description.value?.startsWith(shown.descriptionStartsWith)).toBe(true);
      }
      if (shown.imageCountAtLeast !== null) {
        expect(listing.imageUrls.length).toBeGreaterThanOrEqual(shown.imageCountAtLeast);
      }
      for (const url of listing.imageUrls.slice(0, 3)) expect(isFetchableImageUrl(url)).toBe(true);
    });
  }
});
```

- [ ] **Step 3: Run the tests to confirm they fail**

```bash
npm run test -w extension
```

Expected: `listing.test.ts` fails because `../../lib/capture/listing` and `selectors` do not exist.

- [ ] **Step 4: Write the types**

`extension/lib/capture/types.ts`:

```ts
// Types for what the capture script reads from a page, and the one message that triggers it.
// Mostly type definitions plus two constants, so every part of the extension (the injected
// script, the service worker, and the side panel) agrees on the same shapes.
import type { Platform, PlatformHost } from "@guardianlens/shared";

/**
 * Version of the extraction logic. Bump it whenever the adapters change in a way that could
 * change what is captured, so research records can tell which logic produced a capture.
 */
export const ADAPTER_VERSION = "1";

/** Message type the service worker sends to the injected capture script to request a capture. */
export const CAPTURE_MESSAGE = "guardianlens:capture";

/** Pages the extension refuses to read, with the reason. */
export type BlockedState = "captcha" | "access_denied" | "login_required" | "listing_unavailable";

/**
 * "ready": title, price, and at least one photo were found.
 * "incomplete": the page was read but one of those is missing (the buyer fills it in).
 * The remaining values mean the page was blocked and was not read.
 */
export type PageState = "ready" | "incomplete" | BlockedState;

/** One value read from a page: "captured" with a value, or "not_found" (value is null). */
export interface CapturedField<T> {
  status: "captured" | "not_found";
  value: T | null;
}

/** What the capture script read from a listing page. */
export interface CapturedListing {
  adapterVersion: string;
  platform: Platform;
  platformHost: PlatformHost;
  /** The marketplace's numeric listing id. Kept for debugging; never sent to the API. */
  marketplaceListingId: string;
  title: CapturedField<string>;
  description: CapturedField<string>;
  /** Price in ringgit. */
  price: CapturedField<number>;
  /** The platform's own category text, before any mapping to a trained category. */
  category: CapturedField<string>;
  /** Candidate photo URLs (up to 12), best first. */
  imageUrls: string[];
  pageState: PageState;
}

/** What the capture script read from a seller / profile page. */
export interface CapturedSeller {
  accountAgeDays: CapturedField<number>;
  rating: CapturedField<number>;
  reviewCount: CapturedField<number>;
  activeListingCount: CapturedField<number>;
}

/** The result of one capture click. */
export type CaptureResult =
  | { kind: "listing"; listing: CapturedListing }
  | { kind: "seller"; platform: Platform; seller: CapturedSeller; pageState: PageState }
  | { kind: "unsupported"; reason: "not_a_listing" | "unsupported_site" };
```

- [ ] **Step 5: Write the platform selectors file**

`extension/lib/capture/selectors.ts`:

```ts
// Per-platform CSS selectors that refine the generic extraction in listing.ts.
//
// The generic strategies (structured data, meta tags, headings, "RM" prices, breadcrumb links)
// are tried first for every field; the selectors here are tried NEXT, in order, for the pages
// that need them. Each list starts empty and is filled only where a real page proved a
// selector necessary, using docs/SPIKE_NOTES.md ("Description and category selectors") and the
// real-fixture tests. Keep each selector short and prefer stable attributes (data-testid, ARIA
// labels, itemprop) over generated class names, which change with every site release.
//
// Example (illustrative): description: ["[data-testid='listing-description']"].
import type { Platform } from "@guardianlens/shared";

/** The selectors tried, in order, for each field. An empty list means "generic strategies only". */
export interface PlatformSelectors {
  title: string[];
  description: string[];
  price: string[];
  category: string[];
}

/** Selectors per marketplace. */
export const PLATFORM_SELECTORS: Record<Platform, PlatformSelectors> = {
  mudah: { title: [], description: [], price: [], category: [] },
  carousell: { title: [], description: [], price: [], category: [] },
};
```

- [ ] **Step 6: Write the listing adapter**

`extension/lib/capture/listing.ts`:

```ts
// The listing adapter: reads ONE marketplace listing from the page's DOM.
//
// Every field is read by trying several strategies in order and taking the first that yields a
// value:
//   title        heading (h1) > platform selectors > structured data name > og:title
//   description  structured data > platform selectors > og:description > meta description
//   price        structured data > price meta tags > platform selectors > price elements > any
//                visible "RM ..." text
//   category     structured data > breadcrumb data > breadcrumb links > platform selectors
//   photos       structured data photos, then large gallery images (images.ts), then og:image
// Nothing here guesses. A field no strategy can read is reported as "not_found", and the buyer
// fills it in during the Review step. Pages that are blocked (captcha, login wall, removed
// listing) are reported through `pageState` and not read further.
//
// Code here runs inside the injected capture script on the buyer's click. It must stay free of
// network calls and of anything that changes the page.
import type { Platform } from "@guardianlens/shared";
import { classifyListingUrl } from "./classify";
import { selectGalleryImages, type ImageCandidate } from "./images";
import { PLATFORM_SELECTORS, type PlatformSelectors } from "./selectors";
import {
  ADAPTER_VERSION,
  type BlockedState,
  type CapturedField,
  type CapturedListing,
  type PageState,
} from "./types";
import { normalizeText, parsePriceRm, parsePriceValue, textOf } from "./values";

type JsonObject = Record<string, unknown>;

// Headings that are page chrome rather than a listing title.
const GENERIC_HEADINGS = new Set([
  "browse", "carousell", "categories", "category", "home", "login", "mudah",
  "profile", "search", "search results", "sign in", "sign up",
]);

/** Wraps a value as a captured field, or as a not-found field when it is null. */
function field<T>(value: T | null): CapturedField<T> {
  return value === null ? { status: "not_found", value: null } : { status: "captured", value };
}

/** Returns the first non-null result of the strategies, trying them in order. */
function firstOf<T>(...strategies: Array<() => T | null>): T | null {
  for (const strategy of strategies) {
    const value = strategy();
    if (value !== null) return value;
  }
  return null;
}

/** A non-empty, whitespace-normalised string, or null for anything else. */
function clean(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const text = normalizeText(value);
  return text === "" ? null : text;
}

// ---- Structured data (JSON-LD) -------------------------------------------------------------

/** The `@type` values of a JSON-LD node, lower-cased and stripped of any namespace prefix. */
function typesOf(node: JsonObject): string[] {
  const raw = node["@type"];
  const list = Array.isArray(raw) ? raw : [raw];
  return list
    .filter((type): type is string => typeof type === "string")
    .map((type) => type.toLowerCase().split(/[/#]/).pop() ?? "");
}

/**
 * Visits every object in a parsed JSON-LD value. `budget` caps how many nodes are visited and
 * `depth` how deep, so a huge or hostile page cannot stall the capture.
 */
function walk(value: unknown, visit: (node: JsonObject) => void, budget: { left: number }, depth: number): void {
  if (budget.left <= 0 || depth > 8 || value === null || typeof value !== "object") return;
  budget.left -= 1;
  if (Array.isArray(value)) {
    for (const item of value) walk(item, visit, budget, depth + 1);
    return;
  }
  const node = value as JsonObject;
  visit(node);
  for (const child of Object.values(node)) walk(child, visit, budget, depth + 1);
}

/** The Product and BreadcrumbList nodes found in the page's JSON-LD scripts. */
function readStructuredData(doc: Document): { products: JsonObject[]; breadcrumbs: JsonObject[] } {
  const products: JsonObject[] = [];
  const breadcrumbs: JsonObject[] = [];
  const budget = { left: 2000 };
  const visit = (node: JsonObject): void => {
    const types = typesOf(node);
    if (types.includes("product")) products.push(node);
    if (types.includes("breadcrumblist")) breadcrumbs.push(node);
  };
  for (const script of Array.from(doc.querySelectorAll('script[type="application/ld+json"]'))) {
    try {
      walk(JSON.parse(script.textContent ?? ""), visit, budget, 0);
    } catch {
      // Malformed JSON-LD is ignored: the other strategies still run.
    }
  }
  return { products, breadcrumbs };
}

/** The photo URLs a Product node names (absolute, resolved against the page URL). */
function productPhotos(product: JsonObject | undefined, baseUrl: string): string[] {
  const urls: string[] = [];
  const add = (value: unknown, depth: number): void => {
    if (depth > 4) return;
    if (Array.isArray(value)) {
      value.slice(0, 20).forEach((item) => add(item, depth + 1));
    } else if (value && typeof value === "object") {
      const node = value as JsonObject;
      add(node.url ?? node.contentUrl, depth + 1);
    } else if (typeof value === "string") {
      try {
        urls.push(new URL(value, baseUrl).href);
      } catch {
        // A value that is not a URL is skipped.
      }
    }
  };
  add(product?.image, 0);
  return urls;
}

/** The price in a Product's offers (price, else lowPrice), or null. */
function productPrice(product: JsonObject | undefined): number | null {
  const offers = product?.offers;
  const list = Array.isArray(offers) ? offers : offers ? [offers] : [];
  for (const offer of list) {
    if (!offer || typeof offer !== "object") continue;
    const node = offer as JsonObject;
    const value =
      parsePriceValue(node.price as string | number | undefined) ??
      parsePriceValue(node.lowPrice as string | number | undefined);
    if (value !== null) return value;
  }
  return null;
}

/**
 * The category from a breadcrumb trail in structured data: the last entry whose name is not the
 * listing title (some sites end the trail with the listing itself).
 */
function breadcrumbCategory(breadcrumbs: JsonObject[], title: string | null): string | null {
  for (const crumb of breadcrumbs) {
    const items = Array.isArray(crumb.itemListElement) ? (crumb.itemListElement as JsonObject[]) : [];
    const names = [...items]
      .sort((a, b) => Number(a.position ?? 0) - Number(b.position ?? 0))
      .map((item) => {
        const nested = item.item && typeof item.item === "object" ? (item.item as JsonObject).name : null;
        return clean(item.name) ?? clean(nested);
      })
      .filter((name): name is string => name !== null && name.toLowerCase() !== title?.toLowerCase());
    const last = names.pop();
    if (last) return last;
  }
  return null;
}

// ---- DOM and meta strategies ----------------------------------------------------------------

/** The content of the first meta tag matching `selector`, or null. */
function metaContent(doc: Document, selector: string): string | null {
  return clean(doc.querySelector<HTMLMetaElement>(selector)?.content);
}

/** The text of the first element matched by any of `selectors`, tried in order. */
function firstText(doc: Document, selectors: string[]): string | null {
  for (const selector of selectors) {
    const text = clean(textOf(doc.querySelector(selector)));
    if (text) return text;
  }
  return null;
}

/** The first h1 that reads like a listing title rather than page chrome. */
function headingTitle(doc: Document): string | null {
  for (const heading of Array.from(doc.querySelectorAll("h1"))) {
    const text = textOf(heading);
    if (text.length >= 3 && text.length <= 500 && !GENERIC_HEADINGS.has(text.toLowerCase())) return text;
  }
  return null;
}

// A site name is separated from the title by "|", a hyphen, an en dash (character code 0x2013), or an
// em dash (0x2014). The dashes are built from their character codes so this source stays plain ASCII.
// The hyphen goes last inside the character class so it is read as a literal hyphen, not a range.
const SITE_NAME_SEPARATORS = `|${String.fromCharCode(0x2013, 0x2014)}-`;
const SITE_NAME_SUFFIX = new RegExp(`\\s*[${SITE_NAME_SEPARATORS}]\\s*(?:Carousell|Mudah)[^|]*$`, "i");

/** Removes a trailing " - Carousell Malaysia" / " | Mudah.my" style site name from a title. */
function withoutSiteName(text: string | null): string | null {
  if (text === null) return null;
  return clean(text.replace(SITE_NAME_SUFFIX, ""));
}

/** The last breadcrumb link that is not the listing title. */
function domBreadcrumbCategory(doc: Document, title: string | null): string | null {
  const links = Array.from(doc.querySelectorAll('nav[aria-label*="readcrumb" i] a, [class*="readcrumb" i] a'))
    .map((link) => clean(textOf(link)))
    .filter((name): name is string => name !== null && name.toLowerCase() !== title?.toLowerCase());
  return links.pop() ?? null;
}

/** A price from elements matched by the platform's own price selectors. */
function priceFromSelectors(doc: Document, selectors: string[]): number | null {
  for (const selector of selectors) {
    const value = parsePriceRm(textOf(doc.querySelector(selector)));
    if (value !== null) return value;
  }
  return null;
}

/**
 * A price from elements that look like prices: meta/itemprop tags first (their `content` is a
 * bare number), then any element whose own text is just "RM ...", looking only inside the main
 * content so a "related listings" price lower on the page is not picked up.
 */
function priceFromDom(doc: Document): number | null {
  const semantic = doc.querySelectorAll(
    'meta[itemprop="price"][content], meta[property="product:price:amount"][content], [itemprop="price"], [data-testid*="price" i], [class*="price" i]',
  );
  for (const node of Array.from(semantic)) {
    const content = node.getAttribute("content");
    const value = content !== null ? parsePriceValue(content) : parsePriceRm(textOf(node));
    if (value !== null) return value;
  }
  const scope = doc.querySelector("main, [role='main']") ?? doc.body;
  const leaves = Array.from(scope?.querySelectorAll("span, strong, p, div") ?? []).slice(0, 2000);
  for (const node of leaves) {
    if (node.childElementCount !== 0) continue;
    const text = textOf(node);
    if (/^(?:RM|MYR)\s*\d[\d,.]*$/i.test(text)) {
      const value = parsePriceRm(text);
      if (value !== null) return value;
    }
  }
  return null;
}

// ---- Photos ---------------------------------------------------------------------------------

/** True when the browser reports the element as not displayed. Tolerates documents with no window. */
function isHidden(element: Element): boolean {
  try {
    const style = globalThis.getComputedStyle(element);
    return style.display === "none" || style.visibility === "hidden";
  } catch {
    // A document without a browsing context (as in tests) has no computed style: treat as visible.
    return false;
  }
}

/**
 * The images in the page's gallery area with the size they were rendered at.
 * In a real page the layout rectangle is the size. Fixtures recorded for tests carry the size as
 * width/height attributes instead (jsdom has no layout engine), so the attribute is the fallback.
 */
function collectImageCandidates(doc: Document, baseUrl: string): ImageCandidate[] {
  const scoped = Array.from(
    doc.querySelectorAll<HTMLImageElement>(
      'main img, [role="main"] img, [data-testid*="gallery" i] img, [class*="gallery" i] img',
    ),
  );
  const pool = scoped.length > 0 ? scoped : Array.from(doc.images);
  const viewportHeight = globalThis.innerHeight || 768;
  const candidates: ImageCandidate[] = [];
  for (const img of pool) {
    if (isHidden(img)) continue;
    const raw = img.currentSrc || img.getAttribute("src") || "";
    if (!raw || raw.startsWith("data:")) continue;
    let url: string;
    try {
      url = new URL(raw, baseUrl).href;
    } catch {
      continue;
    }
    const rect = img.getBoundingClientRect();
    // Images far below the fold (related listings) are not the listing's photos.
    if (rect.top > viewportHeight * 3) continue;
    candidates.push({ url, width: rect.width || img.width, height: rect.height || img.height });
  }
  return candidates;
}

/** The og:image URL as a one-item list, or an empty list. */
function ogImage(doc: Document, baseUrl: string): string[] {
  const content = metaContent(doc, 'meta[property="og:image"]');
  if (!content) return [];
  try {
    return [new URL(content, baseUrl).href];
  } catch {
    return [];
  }
}

// ---- Page state -----------------------------------------------------------------------------

/**
 * Detects pages the extension must not read: a CAPTCHA, an access-denied block, a login wall, or
 * a removed listing. The checks are ported from the Data Collector, which detects (and never
 * bypasses) the same pages.
 * @returns The blocked state, or null for an ordinary page.
 */
export function detectPageState(doc: Document, pathname: string): BlockedState | null {
  const sample = `${doc.title}\n${normalizeText(textOf(doc.body)).slice(0, 120000)}`.toLowerCase();
  const path = pathname.toLowerCase();
  if (
    doc.querySelector('iframe[src*="recaptcha" i], [class*="captcha" i], [id*="captcha" i]') ||
    /captcha|verify (?:that )?you are human|complete the security check/.test(sample)
  ) {
    return "captcha";
  }
  if (
    /access denied|request blocked|checking your browser|just a moment/.test(sample) ||
    doc.querySelector("[data-ray], #cf-challenge-running, .cf-browser-verification")
  ) {
    return "access_denied";
  }
  if (
    /\/(?:login|signin|sign-in)(?:\/|$)/.test(path) ||
    /(?:log|sign) in (?:is )?required|(?:log|sign) in to (?:continue|view)/.test(sample)
  ) {
    return "login_required";
  }
  if (
    /listing (?:is |has been )?(?:unavailable|deleted|removed|expired)|item (?:is |has been )?(?:unavailable|deleted|removed|sold)|page (?:does not exist|not found)/.test(
      sample,
    )
  ) {
    return "listing_unavailable";
  }
  return null;
}

// ---- Public entry point ---------------------------------------------------------------------

/** Options for captureListing. `selectors` lets tests supply their own platform selectors. */
export interface CaptureOptions {
  selectors?: Record<Platform, PlatformSelectors>;
}

/**
 * Reads a listing page.
 * @param doc The listing page's document.
 * @param url The page's URL (it must be a supported listing URL).
 * @param options Optional overrides, used by tests.
 * @returns The captured fields, the photo candidates, and the page state.
 * @throws Error when `url` is not a supported marketplace listing page.
 */
export function captureListing(doc: Document, url: string, options: CaptureOptions = {}): CapturedListing {
  const ref = classifyListingUrl(url);
  if (!ref) throw new Error("captureListing needs a supported marketplace listing URL");
  const selectors = (options.selectors ?? PLATFORM_SELECTORS)[ref.platform];
  const { products, breadcrumbs } = readStructuredData(doc);
  const product = products[0];

  const title = firstOf(
    () => headingTitle(doc),
    () => firstText(doc, selectors.title),
    () => clean(product?.name),
    () => withoutSiteName(metaContent(doc, 'meta[property="og:title"]')),
  );
  const description = firstOf(
    () => clean(product?.description),
    () => firstText(doc, selectors.description),
    () => metaContent(doc, 'meta[property="og:description"]'),
    () => metaContent(doc, 'meta[name="description"]'),
  );
  const price = firstOf(
    () => productPrice(product),
    () => parsePriceValue(metaContent(doc, 'meta[property="product:price:amount"], meta[itemprop="price"]')),
    () => priceFromSelectors(doc, selectors.price),
    () => priceFromDom(doc),
  );
  const category = firstOf(
    () => clean(product?.category),
    () => breadcrumbCategory(breadcrumbs, title),
    () => domBreadcrumbCategory(doc, title),
    () => firstText(doc, selectors.category),
  );

  const gallery = selectGalleryImages(collectImageCandidates(doc, url), productPhotos(product, url));
  const imageUrls = gallery.length > 0 ? gallery : ogImage(doc, url);

  const blocked = detectPageState(doc, new URL(url).pathname);
  const pageState: PageState =
    blocked ?? (title !== null && price !== null && imageUrls.length > 0 ? "ready" : "incomplete");

  return {
    adapterVersion: ADAPTER_VERSION,
    platform: ref.platform,
    platformHost: ref.host,
    marketplaceListingId: ref.listingId,
    title: field(title),
    description: field(description),
    price: field(price),
    category: field(category),
    imageUrls,
    pageState,
  };
}
```

- [ ] **Step 7: Run the tests and the typecheck**

```bash
npm run test -w extension
npm run typecheck -w extension
```

Expected: all synthetic adapter tests pass; the real-fixture file passes or skips; the typecheck is clean. If jsdom rejects a selector containing the case-insensitive `i` flag, split it into two selectors (lower case and capitalised) in the same edit and update the nearby comment.

- [ ] **Step 8: Make the real pages pass**

If you recorded real fixtures in Task 1, run:

```bash
npm run test -w extension -- listing.real
```

For each failing field of each fixture: open the fixture's `listing.html`, find where that value lives, and follow the order of preference: (1) fix a generic strategy if the problem is general (add a test to `listing.test.ts` with a minimal synthetic page for it); (2) otherwise add a selector to the matching list in `extension/lib/capture/selectors.ts` and update that file's example comment if it is no longer illustrative. A photo failure of the form `isFetchableImageUrl(...) = false` means a CDN host is missing from `extension/lib/hosts.ts`: add it, rebuild, and keep the `Image hosts` section of `SPIKE_NOTES.md` in step. Rerun until every real fixture passes.

- [ ] **Step 9: Commit**

```bash
git add extension
git commit -m "feat(extension): add the listing adapter with synthetic and real-page tests"
```

---

### Task 11: Page capture, the click-time runner, and the injected script

**Files:**
- Create: `extension/lib/capture/page.ts`, `extension/lib/capture/runner.ts`, `extension/entrypoints/capture.ts`
- Create: `extension/tests/capture/page.test.ts`, `extension/tests/capture/runner.test.ts`
- Modify: `extension/entrypoints/background.ts`

**Interfaces:**
- Consumes: `classifyListingUrl`, `classifySellerUrl`, `platformFromHost` (Task 8); `parseSellerPage`, `SellerValues` (Task 9); `captureListing`, `detectPageState` and the capture types (Task 10); `writeSession` (Task 7).
- Produces:
  - `captureCurrentPage(doc: Document, url: string, now: Date): CaptureResult` from `page.ts`
  - `interface CaptureJob { id: number; tabId: number; status: "capturing" | "done" | "error"; result?: CaptureResult; error?: "inject_failed" | "no_response" }`
  - `const CAPTURE_STATE_KEY = "captureState"`
  - `interface RunnerDeps { writeState(job: CaptureJob): Promise<void>; inject(tabId: number): Promise<void>; request(tabId: number): Promise<CaptureResult | undefined>; now(): number }`
  - `defaultDeps: RunnerDeps`, `runCaptureForTab(tab: { id: number; url?: string }, deps?: RunnerDeps): Promise<void>` from `runner.ts`
  - A toolbar click that opens the panel AND writes the latest `CaptureJob` to session storage under `captureState`.

- [ ] **Step 1: Write the failing page-capture tests**

`extension/tests/capture/page.test.ts`:

```ts
// Pins the entry point of the injected capture script: given the page it was injected into, decide
// whether it is a listing, a seller page, or something else, and return the right capture result.
import { describe, expect, it } from "vitest";
import { captureCurrentPage } from "../../lib/capture/page";
import { loadSynthetic, parseHtml } from "../helpers/realFixtures";

const NOW = new Date(Date.UTC(2026, 9, 5));

describe("captureCurrentPage", () => {
  it("captures a listing page", () => {
    const result = captureCurrentPage(
      loadSynthetic("carousell-jsonld"),
      "https://www.carousell.com.my/p/used-laptop-1234567890/",
      NOW,
    );
    expect(result.kind).toBe("listing");
    if (result.kind === "listing") expect(result.listing.title.value).toBe("Used laptop in good condition");
  });

  it("captures a seller page into captured and not-found fields", () => {
    const doc = parseHtml(`<body>
      <p>Joined 8 months ago</p>
      <h2>Listings</h2>
      <article><a href="/p/phone-111/">Phone</a></article>
    </body>`);
    const result = captureCurrentPage(doc, "https://www.carousell.com.my/u/someone/", NOW);
    expect(result.kind).toBe("seller");
    if (result.kind === "seller") {
      expect(result.seller.accountAgeDays).toEqual({ status: "captured", value: 240 });
      expect(result.seller.activeListingCount).toEqual({ status: "captured", value: 1 });
      // The page says nothing about reviews, so they are "not found", never 0 or suspicious.
      expect(result.seller.reviewCount).toEqual({ status: "not_found", value: null });
      expect(result.seller.rating).toEqual({ status: "not_found", value: null });
      expect(result.pageState).toBe("ready");
    }
  });

  it("reports a blocked seller page", () => {
    const doc = parseHtml("<body><p>Please verify that you are human.</p></body>");
    const result = captureCurrentPage(doc, "https://www.carousell.com.my/u/someone/", NOW);
    expect(result.kind === "seller" && result.pageState).toBe("captcha");
  });

  it("says a marketplace page that is neither listing nor seller is not a listing", () => {
    const result = captureCurrentPage(parseHtml("<body></body>"), "https://www.carousell.com.my/categories/phones/", NOW);
    expect(result).toEqual({ kind: "unsupported", reason: "not_a_listing" });
  });

  it("says another site is unsupported", () => {
    const result = captureCurrentPage(parseHtml("<body></body>"), "https://example.com/", NOW);
    expect(result).toEqual({ kind: "unsupported", reason: "unsupported_site" });
  });
});
```

- [ ] **Step 2: Write the failing runner tests**

`extension/tests/capture/runner.test.ts`:

```ts
// Pins what happens when the buyer clicks the toolbar icon.
// The privacy-critical rule: the capture script is injected ONLY on the two marketplaces. The
// activeTab permission works on any site, so without this guard a click on, say, a banking tab
// would inject our script. On other sites the click must only report "unsupported".
// Dependencies are injected so the tests need no real browser tabs.
import { describe, expect, it, vi } from "vitest";
import { runCaptureForTab, type CaptureJob, type RunnerDeps } from "../../lib/capture/runner";
import type { CaptureResult } from "../../lib/capture/types";

const LISTING_RESULT: CaptureResult = { kind: "unsupported", reason: "not_a_listing" };

/** Builds fake dependencies that record every state the runner writes. */
function fakeDeps(overrides: Partial<RunnerDeps> = {}) {
  const states: CaptureJob[] = [];
  const deps: RunnerDeps = {
    writeState: async (job) => void states.push(job),
    inject: vi.fn(async () => undefined),
    request: vi.fn(async () => LISTING_RESULT),
    now: () => 111,
    ...overrides,
  };
  return { deps, states };
}

describe("runCaptureForTab", () => {
  it("does not inject anything on a site that is not a supported marketplace", async () => {
    const { deps, states } = fakeDeps();
    await runCaptureForTab({ id: 7, url: "https://example.com/account" }, deps);
    expect(deps.inject).not.toHaveBeenCalled();
    expect(states).toEqual([
      { id: 111, tabId: 7, status: "done", result: { kind: "unsupported", reason: "unsupported_site" } },
    ]);
  });

  it("does not inject when the tab has no readable URL", async () => {
    const { deps, states } = fakeDeps();
    await runCaptureForTab({ id: 7 }, deps);
    expect(deps.inject).not.toHaveBeenCalled();
    expect(states[0].result).toEqual({ kind: "unsupported", reason: "unsupported_site" });
  });

  it("writes capturing, then the result, on a marketplace page", async () => {
    const { deps, states } = fakeDeps();
    await runCaptureForTab({ id: 7, url: "https://www.carousell.com.my/p/x-123/" }, deps);
    expect(deps.inject).toHaveBeenCalledWith(7);
    expect(states.map((state) => state.status)).toEqual(["capturing", "done"]);
    expect(states[1].result).toEqual(LISTING_RESULT);
  });

  it("reports inject_failed when the script cannot be injected", async () => {
    const { deps, states } = fakeDeps({
      inject: vi.fn(async () => {
        throw new Error("no access");
      }),
    });
    await runCaptureForTab({ id: 7, url: "https://www.mudah.my/phone-123456.htm" }, deps);
    expect(states.at(-1)).toMatchObject({ status: "error", error: "inject_failed" });
  });

  it("reports no_response when the script does not answer", async () => {
    const { deps, states } = fakeDeps({ request: vi.fn(async () => undefined) });
    await runCaptureForTab({ id: 7, url: "https://www.mudah.my/phone-123456.htm" }, deps);
    expect(states.at(-1)).toMatchObject({ status: "error", error: "no_response" });
  });
});
```

- [ ] **Step 3: Run the tests to confirm they fail**

```bash
npm run test -w extension
```

Expected: `page.test.ts` and `runner.test.ts` fail because their modules do not exist.

- [ ] **Step 4: Write the page capture**

`extension/lib/capture/page.ts`:

```ts
// Entry point of the injected capture script's logic: given the page it runs in, decide whether it
// is a listing, a seller page, or something else, and return the matching capture result.
// Kept free of any browser-extension API so it can be tested in jsdom like any other function.
import { classifyListingUrl, classifySellerUrl, platformFromHost } from "./classify";
import { captureListing, detectPageState } from "./listing";
import { parseSellerPage, type SellerValues } from "./seller";
import type { CapturedField, CapturedSeller, CaptureResult } from "./types";

/** Wraps a nullable number as a captured / not-found field. */
function numberField(value: number | null): CapturedField<number> {
  return value === null ? { status: "not_found", value: null } : { status: "captured", value };
}

/** Converts parsed seller values to captured fields (null becomes "not found"). */
function toCapturedSeller(values: SellerValues): CapturedSeller {
  return {
    accountAgeDays: numberField(values.accountAgeDays),
    rating: numberField(values.rating),
    reviewCount: numberField(values.reviewCount),
    activeListingCount: numberField(values.activeListingCount),
  };
}

/** The hostname of a URL, or "" when it cannot be parsed. */
function hostnameOf(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return "";
  }
}

/**
 * Captures the current page.
 * @param doc The page's document.
 * @param url The page's URL.
 * @param now "Today", for seller join-date calculations.
 * @returns A listing capture, a seller capture, or an "unsupported" result with the reason.
 */
export function captureCurrentPage(doc: Document, url: string, now: Date): CaptureResult {
  if (classifyListingUrl(url)) {
    return { kind: "listing", listing: captureListing(doc, url) };
  }
  const seller = classifySellerUrl(url);
  if (seller) {
    const blocked = detectPageState(doc, new URL(url).pathname);
    return {
      kind: "seller",
      platform: seller.platform,
      seller: toCapturedSeller(parseSellerPage(doc, seller.platform, url, now)),
      pageState: blocked ?? "ready",
    };
  }
  return {
    kind: "unsupported",
    reason: platformFromHost(hostnameOf(url)) ? "not_a_listing" : "unsupported_site",
  };
}
```

- [ ] **Step 5: Write the runner**

`extension/lib/capture/runner.ts`:

```ts
// Runs one capture when the buyer clicks the toolbar icon, and records the outcome for the side
// panel to read.
//
// Privacy rule: the capture script is injected ONLY into the two supported marketplaces. The
// activeTab permission works on every site, so without the guard below a click on any other tab
// would inject our script there. On any other site nothing is injected and the result is simply
// "unsupported".
//
// The steps are injected as `deps` so they can be tested without real browser tabs; `defaultDeps`
// are the real implementations.
import { browser } from "wxt/browser";
import { platformFromHost } from "./classify";
import { writeSession } from "../storage";
import { CAPTURE_MESSAGE, type CaptureResult } from "./types";

/** Where the latest capture job is stored in session storage (the side panel watches this key). */
export const CAPTURE_STATE_KEY = "captureState";

/** The state of one capture click. `id` is its start time and orders jobs (newest wins). */
export interface CaptureJob {
  id: number;
  tabId: number;
  status: "capturing" | "done" | "error";
  /** Set when status is "done". */
  result?: CaptureResult;
  /** Set when status is "error": the script could not be injected, or never answered. */
  error?: "inject_failed" | "no_response";
}

/** The side effects of a capture, injectable for tests. */
export interface RunnerDeps {
  writeState(job: CaptureJob): Promise<void>;
  inject(tabId: number): Promise<void>;
  request(tabId: number): Promise<CaptureResult | undefined>;
  now(): number;
}

/** The real implementations, using the browser's scripting, tabs, and session storage APIs. */
export const defaultDeps: RunnerDeps = {
  writeState: (job) => writeSession(CAPTURE_STATE_KEY, job),
  // /capture.js is built from entrypoints/capture.ts. activeTab, granted by the toolbar click,
  // is what permits this injection on a site the extension has no standing host permission for.
  inject: async (tabId) => {
    await browser.scripting.executeScript({ target: { tabId }, files: ["/capture.js"] });
  },
  request: async (tabId) =>
    (await browser.tabs.sendMessage(tabId, { type: CAPTURE_MESSAGE })) as CaptureResult | undefined,
  now: () => Date.now(),
};

/** True when the URL is https on one of the four supported marketplace hosts. */
function isSupportedPage(url: string | undefined): boolean {
  if (!url) return false;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" && platformFromHost(parsed.hostname) !== null;
  } catch {
    return false;
  }
}

/**
 * Handles one toolbar click: injects the capture script (supported pages only), asks it to read
 * the page, and writes the outcome through `deps.writeState`.
 * @param tab The tab the buyer clicked in; `url` is readable because the click granted activeTab.
 */
export async function runCaptureForTab(
  tab: { id: number; url?: string },
  deps: RunnerDeps = defaultDeps,
): Promise<void> {
  const id = deps.now();
  if (!isSupportedPage(tab.url)) {
    await deps.writeState({
      id,
      tabId: tab.id,
      status: "done",
      result: { kind: "unsupported", reason: "unsupported_site" },
    });
    return;
  }
  await deps.writeState({ id, tabId: tab.id, status: "capturing" });
  try {
    await deps.inject(tab.id);
    const result = await deps.request(tab.id);
    await deps.writeState(
      result
        ? { id, tabId: tab.id, status: "done", result }
        : { id, tabId: tab.id, status: "error", error: "no_response" },
    );
  } catch {
    await deps.writeState({ id, tabId: tab.id, status: "error", error: "inject_failed" });
  }
}
```

- [ ] **Step 6: Write the injected capture script**

`extension/entrypoints/capture.ts`:

```ts
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
```

- [ ] **Step 7: Start the capture from the toolbar click**

Replace the whole of `extension/entrypoints/background.ts` with:

```ts
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
```

- [ ] **Step 8: Run the tests and the typecheck**

```bash
npm run test -w extension
npm run typecheck -w extension
```

Expected: all tests pass and the typecheck is clean. If TypeScript rejects `files: ["/capture.js"]`, use the exact path string its error message lists (for example `capture.js`), and update the comment above `inject` in the same edit if it names the path.

- [ ] **Step 9: Build and verify in a real browser (manual)**

```bash
npm run build -w extension
ls extension/.output/chrome-mv3
```

Expected: the listing contains `capture.js` next to `manifest.json`. Then reload the unpacked extension in Chrome, open a real Carousell listing, click the icon, open the extension's `service worker` console, and run:

```js
await chrome.storage.session.get("captureState")
```

Expected: `status: "done"` and `result.kind: "listing"` with the real title, price, and photo URLs; `pageState` is `ready` or `incomplete` as appropriate. Repeat on a seller page (`result.kind: "seller"`), on a marketplace page that is neither (`kind: "unsupported"`, reason `not_a_listing`), and on `https://example.com` (`reason: "unsupported_site"`, and no injected script: confirm in DevTools > Sources of that tab that `capture.js` is absent). If a result looks wrong, add a case to the matching unit or real-fixture test first, then fix the code.

- [ ] **Step 10: Commit**

```bash
git add extension
git commit -m "feat(extension): capture on click through an injected script, marketplaces only"
```

---

### Task 12: Draft, validation, and submission form

**Files:**
- Create: `extension/lib/panel/draft.ts`
- Create: `extension/tests/helpers/samples.ts`, `extension/tests/panel/draft.test.ts`

**Interfaces:**
- Consumes: `resolveCategory`, `CaptureFieldStatus`, `CaptureMetaPayload`, `Platform`, `PlatformHost`, `AssessmentResult` from `@guardianlens/shared`; `CapturedListing`, `CapturedSeller` (Task 10); `parsePriceValue` (Task 8).
- Produces from `draft.ts`:
  - types `FieldStatus`, `DraftField { value: string; status: FieldStatus }`, `DraftFieldKey` (`"title" | "description" | "price" | "category" | "accountAgeDays" | "rating" | "reviewCount" | "activeListingCount"`), `DraftPhoto { url: string; selected: boolean }`, `Draft`, `DraftErrors`
  - `LIMITS` (`{ title: 180, description: 5000, category: 80, photos: 3 }`)
  - `draftFromListing(listing: CapturedListing): Draft`
  - `applySeller(draft: Draft, seller: CapturedSeller): Draft`
  - `editField(draft: Draft, key: DraftFieldKey, value: string): Draft`
  - `togglePhoto(draft: Draft, url: string): Draft`
  - `parsePriceInput(text: string): number | null`
  - `validateDraft(draft: Draft): DraftErrors`
  - `buildCaptureMeta(draft: Draft): CaptureMetaPayload`
  - `buildForm(draft: Draft, photos: File[]): FormData`
- Produces test builders `sampleListing(overrides?)`, `sampleSeller(overrides?)`, `sampleResult(overrides?)` in `extension/tests/helpers/samples.ts`.

- [ ] **Step 1: Write the shared test builders**

`extension/tests/helpers/samples.ts`:

```ts
// Builders for the test data used across the panel tests: a captured listing, a captured seller,
// and a finished API result. Each takes overrides so a test can change only what it cares about.
import type { AssessmentResult } from "@guardianlens/shared";
import type { CapturedListing, CapturedSeller } from "../../lib/capture/types";

/** Four photo URLs on an allowed host: the first three are selected by default, the fourth is spare. */
export const PHOTOS = [
  "https://media.karousell.com/media/photos/products/1/a.jpg",
  "https://media.karousell.com/media/photos/products/1/b.jpg",
  "https://media.karousell.com/media/photos/products/1/c.jpg",
  "https://media.karousell.com/media/photos/products/1/d.jpg",
];

/** A fully captured Carousell listing. */
export function sampleListing(overrides: Partial<CapturedListing> = {}): CapturedListing {
  return {
    adapterVersion: "1",
    platform: "carousell",
    platformHost: "www.carousell.com.my",
    marketplaceListingId: "1234567890",
    title: { status: "captured", value: "Used laptop in good condition" },
    description: { status: "captured", value: "Original unit. COD available." },
    price: { status: "captured", value: 1250 },
    category: { status: "captured", value: "Computers and Tech > Laptops" },
    imageUrls: PHOTOS,
    pageState: "ready",
    ...overrides,
  };
}

/** A fully captured seller page. */
export function sampleSeller(overrides: Partial<CapturedSeller> = {}): CapturedSeller {
  return {
    accountAgeDays: { status: "captured", value: 1155 },
    rating: { status: "captured", value: 4.8 },
    reviewCount: { status: "captured", value: 17 },
    activeListingCount: { status: "captured", value: 4 },
    ...overrides,
  };
}

/** A finished assessment result (development stub, moderate band, three available signals). */
export function sampleResult(overrides: Partial<AssessmentResult> = {}): AssessmentResult {
  const card = (signal: "visual" | "textual" | "behavioural", summary: string) => ({
    signal,
    probability: 0.4,
    available: true,
    status_word: "clear",
    summary,
    reasons: [],
    scope_note: null,
  });
  return {
    assessment_id: "a1",
    title: "Used laptop in good condition",
    score: 42,
    band: "moderate",
    signal_cards: [
      card("visual", "No strong warning signs in the photos."),
      card("textual", "The wording looks ordinary."),
      card("behavioural", "The seller details look ordinary."),
    ],
    missing_data_notices: [],
    suggested_checks: [
      "Compare the price with similar listings on the same marketplace.",
      "Verify account or bank details independently using the official Semak Mule service.",
    ],
    disclaimer: "Decision support only. Verify the seller independently before paying.",
    model_bundle_label: "dev-stub-unvalidated",
    created_at: "2026-10-05T10:00:00Z",
    total_latency_ms: 120,
    development_stub: true,
    ...overrides,
  };
}
```

- [ ] **Step 2: Write the failing draft tests**

`extension/tests/panel/draft.test.ts`:

```ts
// Pins the buyer's editable draft: how it is built from a capture, edited, validated, and turned
// into the form the API receives. The rules protected here:
//   - a field the page did not show is "not_found" and empty: never guessed, never zero;
//   - what the page captured is never silently shortened (Review Focus 3: a 6,000 character
//     description stays 6,000 characters, and the draft is blocked with a clear message instead);
//   - at most 3 photos, and removing a photo marks the photo set as edited;
//   - the capture metadata sent to the API holds statuses and the host, never a listing URL.
import { describe, expect, it } from "vitest";
import {
  LIMITS,
  applySeller,
  buildCaptureMeta,
  buildForm,
  draftFromListing,
  editField,
  parsePriceInput,
  togglePhoto,
  validateDraft,
} from "../../lib/panel/draft";
import { PHOTOS, sampleListing, sampleSeller } from "../helpers/samples";

describe("draftFromListing", () => {
  it("copies captured values and marks them captured", () => {
    const draft = draftFromListing(sampleListing());
    expect(draft.fields.title).toEqual({ value: "Used laptop in good condition", status: "captured" });
    expect(draft.fields.price).toEqual({ value: "1250", status: "captured" });
    expect(draft.platformHost).toBe("www.carousell.com.my");
  });

  it("maps the platform category to a trained category, and keeps unknown wording as is", () => {
    expect(draftFromListing(sampleListing()).fields.category.value).toBe("Laptops");
    const odd = sampleListing({ category: { status: "captured", value: "Aquarium supplies" } });
    expect(draftFromListing(odd).fields.category.value).toBe("Aquarium supplies");
  });

  it("marks values the page did not show as not found and empty, never zero", () => {
    const draft = draftFromListing(
      sampleListing({ price: { status: "not_found", value: null }, description: { status: "not_found", value: null } }),
    );
    expect(draft.fields.price).toEqual({ value: "", status: "not_found" });
    expect(draft.fields.description).toEqual({ value: "", status: "not_found" });
  });

  it("starts every seller field as not found", () => {
    const draft = draftFromListing(sampleListing());
    for (const key of ["accountAgeDays", "rating", "reviewCount", "activeListingCount"] as const) {
      expect(draft.fields[key]).toEqual({ value: "", status: "not_found" });
    }
  });

  it("selects the first three photos by default", () => {
    const draft = draftFromListing(sampleListing());
    expect(draft.photos.map((photo) => photo.selected)).toEqual([true, true, true, false]);
    expect(draft.defaultPhotoUrls).toEqual(PHOTOS.slice(0, 3));
  });

  it("does not shorten a very long description (Review Focus 3)", () => {
    const long = "x".repeat(6000);
    const draft = draftFromListing(sampleListing({ description: { status: "captured", value: long } }));
    expect(draft.fields.description.value).toHaveLength(6000);
  });
});

describe("applySeller", () => {
  it("fills seller fields from the seller page", () => {
    const draft = applySeller(draftFromListing(sampleListing()), sampleSeller());
    expect(draft.fields.accountAgeDays).toEqual({ value: "1155", status: "captured" });
    expect(draft.fields.rating).toEqual({ value: "4.8", status: "captured" });
  });

  it("never overwrites a value the buyer typed", () => {
    let draft = draftFromListing(sampleListing());
    draft = editField(draft, "rating", "3");
    draft = applySeller(draft, sampleSeller());
    expect(draft.fields.rating).toEqual({ value: "3", status: "edited" });
    expect(draft.fields.reviewCount.value).toBe("17");
  });

  it("leaves a field alone when the seller page did not show it", () => {
    const draft = applySeller(
      draftFromListing(sampleListing()),
      sampleSeller({ rating: { status: "not_found", value: null } }),
    );
    expect(draft.fields.rating).toEqual({ value: "", status: "not_found" });
  });
});

describe("editField and togglePhoto", () => {
  it("marks an edited field as edited", () => {
    const draft = editField(draftFromListing(sampleListing()), "title", "New title");
    expect(draft.fields.title).toEqual({ value: "New title", status: "edited" });
  });

  it("allows at most three photos", () => {
    const draft = draftFromListing(sampleListing());
    // The fourth photo cannot be added while three are selected.
    expect(togglePhoto(draft, PHOTOS[3]).photos[3].selected).toBe(false);
    // Removing one makes room for it.
    const swapped = togglePhoto(togglePhoto(draft, PHOTOS[0]), PHOTOS[3]);
    expect(swapped.photos.map((photo) => photo.selected)).toEqual([false, true, true, true]);
  });
});

describe("parsePriceInput", () => {
  it.each([
    ["RM 1,250", 1250],
    ["1250.50", 1250.5],
    ["rm99", 99],
  ])("reads %s as %s", (text, expected) => {
    expect(parsePriceInput(text)).toBe(expected);
  });

  it.each([["Free"], ["RM 1,200 - RM 1,500"], [""], ["-5"]])("rejects %s", (text) => {
    expect(parsePriceInput(text)).toBeNull();
  });
});

describe("validateDraft", () => {
  it("accepts a complete draft", () => {
    expect(validateDraft(draftFromListing(sampleListing()))).toEqual({});
  });

  it("asks for what is missing", () => {
    const draft = draftFromListing(
      sampleListing({
        title: { status: "not_found", value: null },
        price: { status: "not_found", value: null },
        category: { status: "not_found", value: null },
        imageUrls: [],
      }),
    );
    expect(validateDraft(draft)).toMatchObject({
      title: "Enter the listing title.",
      price: "Enter a price, for example RM 1,250.",
      category: "Choose or type a category.",
      photos: "Select at least one photo.",
    });
  });

  it("blocks text over the API limits instead of cutting it (Review Focus 3)", () => {
    const draft = draftFromListing(
      sampleListing({
        title: { status: "captured", value: "t".repeat(LIMITS.title + 1) },
        description: { status: "captured", value: "d".repeat(LIMITS.description + 1) },
      }),
    );
    const errors = validateDraft(draft);
    expect(errors.title).toBe("Use 180 characters or fewer.");
    expect(errors.description).toBe("Use 5000 characters or fewer.");
  });

  it("rejects a price that is not a single number", () => {
    const draft = editField(draftFromListing(sampleListing()), "price", "RM 1,200 - RM 1,500");
    expect(validateDraft(draft).price).toBe("Enter the price as a number, for example RM 1,250.");
  });

  it("checks optional seller fields only when they are filled in", () => {
    let draft = draftFromListing(sampleListing());
    expect(validateDraft(draft)).toEqual({});
    draft = editField(editField(draft, "rating", "7"), "reviewCount", "ten");
    expect(validateDraft(draft)).toMatchObject({
      rating: "Enter a rating from 0 to 5.",
      reviewCount: "Enter a whole number.",
    });
  });
});

describe("buildCaptureMeta", () => {
  it("reports each field's origin and the platform host", () => {
    let draft = draftFromListing(
      sampleListing({ description: { status: "not_found", value: null } }),
    );
    draft = editField(draft, "price", "1300");
    draft = applySeller(draft, sampleSeller({ rating: { status: "not_found", value: null } }));
    expect(buildCaptureMeta(draft)).toEqual({
      adapter_version: "1",
      platform_host: "www.carousell.com.my",
      fields: {
        title: "captured",
        description: "not_found",
        price: "edited",
        category: "captured",
        platform: "captured",
        images: "captured",
        account_age_days: "captured",
        rating: "not_found",
        review_count: "captured",
        active_listing_count: "captured",
      },
    });
  });

  it("marks the photos edited once the selection differs from the default", () => {
    const draft = togglePhoto(draftFromListing(sampleListing()), PHOTOS[0]);
    expect(buildCaptureMeta(draft).fields.images).toBe("edited");
  });

  it("marks the photos not found when the page had none", () => {
    const draft = draftFromListing(sampleListing({ imageUrls: [] }));
    expect(buildCaptureMeta(draft).fields.images).toBe("not_found");
  });

  it("never contains a URL", () => {
    expect(JSON.stringify(buildCaptureMeta(draftFromListing(sampleListing())))).not.toContain("http");
  });
});

describe("buildForm", () => {
  it("builds the multipart form the API expects", () => {
    const photo = new File([new Uint8Array([1, 2, 3])], "photo-1.jpg", { type: "image/jpeg" });
    const draft = applySeller(draftFromListing(sampleListing()), sampleSeller());
    const form = buildForm(draft, [photo]);

    expect(form.getAll("images")).toHaveLength(1);
    expect(form.get("platform")).toBe("carousell");
    expect(form.get("title")).toBe("Used laptop in good condition");
    expect(form.get("price")).toBe("1250");
    expect(form.get("category")).toBe("Laptops");
    expect(form.get("account_age_days")).toBe("1155");
    expect(form.get("rating")).toBe("4.8");
    expect(form.get("source")).toBe("extension");
    expect(JSON.parse(String(form.get("capture_meta")))).toMatchObject({ platform_host: "www.carousell.com.my" });
  });

  it("sends empty strings for seller fields that were not found, so the API treats them as unknown", () => {
    const form = buildForm(draftFromListing(sampleListing()), []);
    expect(form.get("account_age_days")).toBe("");
    expect(form.get("active_listing_count")).toBe("");
  });
});
```

- [ ] **Step 3: Run the tests to confirm they fail**

```bash
npm run test -w extension
```

Expected: `draft.test.ts` fails because `../../lib/panel/draft` does not exist.

- [ ] **Step 4: Implement the draft module**

`extension/lib/panel/draft.ts`:

```ts
// The buyer's editable draft of a listing, and the pure functions that build, edit, validate, and
// submit it.
//
// A draft starts from what the capture script read and then belongs to the buyer: every field
// remembers whether it was "captured" from the page, "edited" by the buyer, or "not_found".
// That status is shown next to each field in the Review step and is reported (as statuses only,
// never as page content) in the capture metadata sent with the submission.
//
// Design rules kept here:
//   - nothing is guessed: a value the page did not show stays empty until the buyer provides it;
//   - nothing is silently shortened: text over the API limits is a validation error, not cut off;
//   - all functions are pure (they return a new draft), so they are easy to test.
import {
  resolveCategory,
  type CaptureFieldStatus,
  type CaptureMetaPayload,
  type Platform,
  type PlatformHost,
} from "@guardianlens/shared";
import type { CapturedListing, CapturedSeller } from "../capture/types";
import { parsePriceValue } from "../capture/values";

/** Where a field's value came from. */
export type FieldStatus = CaptureFieldStatus;

/** One editable field: its text and where it came from. */
export interface DraftField {
  value: string;
  status: FieldStatus;
}

/** The fields the buyer can see and edit. The last four are the optional seller details. */
export type DraftFieldKey =
  | "title"
  | "description"
  | "price"
  | "category"
  | "accountAgeDays"
  | "rating"
  | "reviewCount"
  | "activeListingCount";

/** A candidate photo and whether it is included in the check. */
export interface DraftPhoto {
  url: string;
  selected: boolean;
}

/** The whole draft. */
export interface Draft {
  platform: Platform;
  platformHost: PlatformHost;
  adapterVersion: string;
  fields: Record<DraftFieldKey, DraftField>;
  photos: DraftPhoto[];
  /** The photos selected when the page was captured; used to tell whether the buyer changed them. */
  defaultPhotoUrls: string[];
}

/** Validation errors by field (plus "photos"). An empty object means the draft can be submitted. */
export type DraftErrors = Partial<Record<DraftFieldKey | "photos", string>>;

/** The API's limits. Text over a limit is reported, never cut. */
export const LIMITS = { title: 180, description: 5000, category: 80, photos: 3 } as const;

/** A fresh "not found" field (a function so no two fields share one object). */
const notFound = (): DraftField => ({ value: "", status: "not_found" });

/** A captured field, or a not-found field when the page showed nothing. */
function fromCapture(value: string | null): DraftField {
  return value === null ? notFound() : { value, status: "captured" };
}

/**
 * Starts a draft from a listing capture. The first three photos are selected, the platform's
 * category text is mapped to a trained category where an obvious match exists, and all seller
 * fields start as "not found" (they come from the seller page, if the buyer adds it).
 */
export function draftFromListing(listing: CapturedListing): Draft {
  const photos = listing.imageUrls.map((url, index) => ({ url, selected: index < LIMITS.photos }));
  return {
    platform: listing.platform,
    platformHost: listing.platformHost,
    adapterVersion: listing.adapterVersion,
    fields: {
      title: fromCapture(listing.title.value),
      description: fromCapture(listing.description.value),
      price: fromCapture(listing.price.value === null ? null : String(listing.price.value)),
      category: fromCapture(listing.category.value === null ? null : resolveCategory(listing.category.value)),
      accountAgeDays: notFound(),
      rating: notFound(),
      reviewCount: notFound(),
      activeListingCount: notFound(),
    },
    photos,
    defaultPhotoUrls: photos.filter((photo) => photo.selected).map((photo) => photo.url),
  };
}

// Which draft field each captured seller value fills.
const SELLER_FIELDS: ReadonlyArray<readonly [DraftFieldKey, keyof CapturedSeller]> = [
  ["accountAgeDays", "accountAgeDays"],
  ["rating", "rating"],
  ["reviewCount", "reviewCount"],
  ["activeListingCount", "activeListingCount"],
];

/**
 * Adds values read from the seller's page. A value the buyer already typed is never
 * overwritten, and a value the seller page did not show leaves the field unchanged.
 */
export function applySeller(draft: Draft, seller: CapturedSeller): Draft {
  const fields = { ...draft.fields };
  for (const [key, source] of SELLER_FIELDS) {
    const captured = seller[source];
    if (fields[key].status === "edited" || captured.value === null) continue;
    fields[key] = { value: String(captured.value), status: "captured" };
  }
  return { ...draft, fields };
}

/** Sets a field to what the buyer typed and marks it as edited. */
export function editField(draft: Draft, key: DraftFieldKey, value: string): Draft {
  return { ...draft, fields: { ...draft.fields, [key]: { value, status: "edited" } } };
}

/** Includes or excludes a photo. Adding is refused while three photos are already selected. */
export function togglePhoto(draft: Draft, url: string): Draft {
  const selectedCount = draft.photos.filter((photo) => photo.selected).length;
  const photos = draft.photos.map((photo) => {
    if (photo.url !== url) return photo;
    if (!photo.selected && selectedCount >= LIMITS.photos) return photo;
    return { ...photo, selected: !photo.selected };
  });
  return { ...draft, photos };
}

/**
 * Reads a price the buyer typed: "RM 1,250", "1250.50", "rm99". Anything that is not exactly one
 * non-negative number (a range, a word, an empty field) returns null.
 */
export function parsePriceInput(text: string): number | null {
  return parsePriceValue(text.replace(/^\s*(?:RM|MYR)\s*/i, ""));
}

/** An error message for an optional seller field, or null when it is empty or valid. */
function sellerError(key: DraftFieldKey, value: string): string | null {
  const text = value.trim();
  if (text === "") return null;
  if (key === "rating") {
    const rating = Number(text);
    return Number.isFinite(rating) && rating >= 0 && rating <= 5 ? null : "Enter a rating from 0 to 5.";
  }
  const message = key === "accountAgeDays" ? "Enter a whole number of days." : "Enter a whole number.";
  return /^\d+$/.test(text) ? null : message;
}

/**
 * Checks the draft against what the API will accept. Required: title, description, a single
 * price, a category, and at least one selected photo. Optional seller fields are checked only
 * when filled. Text over a limit is an error; it is never shortened to fit.
 */
export function validateDraft(draft: Draft): DraftErrors {
  const errors: DraftErrors = {};
  const { fields } = draft;

  const title = fields.title.value.trim();
  if (title === "") errors.title = "Enter the listing title.";
  else if (title.length > LIMITS.title) errors.title = `Use ${LIMITS.title} characters or fewer.`;

  const description = fields.description.value.trim();
  if (description === "") errors.description = "Enter the listing description.";
  else if (description.length > LIMITS.description) {
    errors.description = `Use ${LIMITS.description} characters or fewer.`;
  }

  const price = fields.price.value.trim();
  if (price === "") errors.price = "Enter a price, for example RM 1,250.";
  else if (parsePriceInput(price) === null) errors.price = "Enter the price as a number, for example RM 1,250.";

  const category = fields.category.value.trim();
  if (category === "") errors.category = "Choose or type a category.";
  else if (category.length > LIMITS.category) errors.category = `Use ${LIMITS.category} characters or fewer.`;

  if (!draft.photos.some((photo) => photo.selected)) errors.photos = "Select at least one photo.";

  for (const key of ["accountAgeDays", "rating", "reviewCount", "activeListingCount"] as const) {
    const message = sellerError(key, fields[key].value);
    if (message) errors[key] = message;
  }
  return errors;
}

/** Whether the selected photos are the ones captured, were changed, or the page had none. */
function imagesStatus(draft: Draft): CaptureFieldStatus {
  if (draft.photos.length === 0) return "not_found";
  const selected = draft.photos.filter((photo) => photo.selected).map((photo) => photo.url);
  const unchanged =
    selected.length === draft.defaultPhotoUrls.length &&
    selected.every((url, index) => url === draft.defaultPhotoUrls[index]);
  return unchanged ? "captured" : "edited";
}

/**
 * The capture metadata sent with the submission: the adapter version, the platform host, and
 * each field's origin. It holds statuses only. It never contains page text or a URL.
 */
export function buildCaptureMeta(draft: Draft): CaptureMetaPayload {
  const { fields } = draft;
  return {
    adapter_version: draft.adapterVersion,
    platform_host: draft.platformHost,
    fields: {
      title: fields.title.status,
      description: fields.description.status,
      price: fields.price.status,
      category: fields.category.status,
      platform: "captured",
      images: imagesStatus(draft),
      account_age_days: fields.accountAgeDays.status,
      rating: fields.rating.status,
      review_count: fields.reviewCount.status,
      active_listing_count: fields.activeListingCount.status,
    },
  };
}

/**
 * Builds the multipart form for POST /api/v1/assess. Seller fields that were not found are sent
 * as empty strings, which the API stores as "unknown" (never as zero or as suspicious).
 * @param draft A draft that already passed validateDraft.
 * @param photos The prepared photo files (at most three, each within the size limit).
 */
export function buildForm(draft: Draft, photos: File[]): FormData {
  const form = new FormData();
  for (const photo of photos) form.append("images", photo);
  const { fields } = draft;
  const price = parsePriceInput(fields.price.value);
  form.append("platform", draft.platform);
  form.append("title", fields.title.value.trim());
  form.append("description", fields.description.value.trim());
  form.append("price", price === null ? fields.price.value : String(price));
  form.append("category", fields.category.value.trim());
  form.append("account_age_days", fields.accountAgeDays.value.trim());
  form.append("rating", fields.rating.value.trim());
  form.append("review_count", fields.reviewCount.value.trim());
  form.append("active_listing_count", fields.activeListingCount.value.trim());
  form.append("source", "extension");
  form.append("capture_meta", JSON.stringify(buildCaptureMeta(draft)));
  return form;
}
```

- [ ] **Step 5: Run the tests and the typecheck**

```bash
npm run test -w extension
npm run typecheck -w extension
```

Expected: all tests pass and the typecheck is clean.

- [ ] **Step 6: Commit**

```bash
git add extension
git commit -m "feat(extension): add the editable draft, validation, and submission form"
```

---

### Task 13: Photo preparation

**Files:**
- Create: `extension/lib/panel/photos.ts`
- Create: `extension/tests/panel/photos.test.ts`

**Interfaces:**
- Consumes: `isFetchableImageUrl` (Task 7).
- Produces from `photos.ts`: `MAX_PHOTO_BYTES: number`, `interface PhotoDeps { fetchBlob(url: string): Promise<Blob>; encodeJpeg(blob: Blob, maxEdge: number, quality: number): Promise<Blob> }`, `interface PreparedPhotos { files: File[]; skipped: number }`, `preparePhotos(urls: string[], deps: PhotoDeps): Promise<PreparedPhotos>`, `browserPhotoDeps: PhotoDeps`.

- [ ] **Step 1: Write the failing tests**

`extension/tests/panel/photos.test.ts`:

```ts
// Pins how the buyer's selected photos are downloaded and made upload-ready (Review Focus 2).
// The API accepts JPEG, PNG, or WebP up to 5 MB each, and photos come from third-party CDNs, so
// things go wrong in ordinary ways: a host is not permitted, the CDN refuses the request, a
// photo is too large, or it is an AVIF the API rejects. The rules:
//   - a photo that works is passed through unchanged when it already fits;
//   - an oversize or unsupported photo is re-encoded as JPEG, smaller until it fits;
//   - a photo that cannot be prepared is SKIPPED (counted), it never fails the whole check;
//   - the caller learns how many were skipped, and decides what to tell the buyer.
import { describe, expect, it, vi } from "vitest";
import { MAX_PHOTO_BYTES, preparePhotos, type PhotoDeps } from "../../lib/panel/photos";

const GOOD = "https://media.karousell.com/media/photos/products/1/a.jpg";
const OTHER = "https://media.karousell.com/media/photos/products/1/b.jpg";
const BAD_HOST = "https://example.com/a.jpg";

/** A blob of the given size and type (its bytes are zeros; only size and type matter). */
function blobOf(size: number, type: string): Blob {
  return new Blob([new Uint8Array(size)], { type });
}

/** Fake dependencies; `overrides` replace the defaults, which fetch a 1 KB JPEG. */
function deps(overrides: Partial<PhotoDeps> = {}): PhotoDeps & { fetchBlob: ReturnType<typeof vi.fn>; encodeJpeg: ReturnType<typeof vi.fn> } {
  return {
    fetchBlob: vi.fn(async () => blobOf(1000, "image/jpeg")),
    encodeJpeg: vi.fn(async () => blobOf(1000, "image/jpeg")),
    ...overrides,
  } as never;
}

describe("preparePhotos", () => {
  it("passes a photo through unchanged when it already fits", async () => {
    const fake = deps();
    const { files, skipped } = await preparePhotos([GOOD], fake);
    expect(skipped).toBe(0);
    expect(files).toHaveLength(1);
    expect(files[0].name).toBe("photo-1.jpg");
    expect(files[0].type).toBe("image/jpeg");
    expect(files[0].size).toBe(1000);
    expect(fake.encodeJpeg).not.toHaveBeenCalled();
  });

  it("names the file after the real type", async () => {
    const png = deps({ fetchBlob: vi.fn(async () => blobOf(10, "image/png")) });
    expect((await preparePhotos([GOOD], png)).files[0].name).toBe("photo-1.png");
  });

  it("re-encodes an oversize photo, trying a lower quality until it fits", async () => {
    const fake = deps({
      fetchBlob: vi.fn(async () => blobOf(MAX_PHOTO_BYTES + 1, "image/jpeg")),
      // Too big at the first quality, small enough at the second.
      encodeJpeg: vi.fn(async (_blob: Blob, _edge: number, quality: number) =>
        blobOf(quality > 0.8 ? MAX_PHOTO_BYTES + 1 : 1000, "image/jpeg"),
      ),
    });
    const { files, skipped } = await preparePhotos([GOOD], fake);
    expect(skipped).toBe(0);
    expect(files[0].size).toBe(1000);
    expect(fake.encodeJpeg).toHaveBeenNthCalledWith(1, expect.anything(), 1600, 0.85);
    expect(fake.encodeJpeg).toHaveBeenNthCalledWith(2, expect.anything(), 1600, 0.7);
  });

  it("re-encodes a type the API rejects, such as AVIF", async () => {
    const fake = deps({ fetchBlob: vi.fn(async () => blobOf(5000, "image/avif")) });
    const { files } = await preparePhotos([GOOD], fake);
    expect(files[0].type).toBe("image/jpeg");
    expect(fake.encodeJpeg).toHaveBeenCalledTimes(1);
  });

  it("skips a photo that never gets small enough", async () => {
    const fake = deps({
      fetchBlob: vi.fn(async () => blobOf(MAX_PHOTO_BYTES + 1, "image/jpeg")),
      encodeJpeg: vi.fn(async () => blobOf(MAX_PHOTO_BYTES + 1, "image/jpeg")),
    });
    const { files, skipped } = await preparePhotos([GOOD], fake);
    expect(files).toEqual([]);
    expect(skipped).toBe(1);
    // 3 sizes x 4 qualities, then it gives up.
    expect(fake.encodeJpeg).toHaveBeenCalledTimes(12);
  });

  it("skips a photo the browser cannot decode", async () => {
    const fake = deps({
      fetchBlob: vi.fn(async () => blobOf(5000, "image/avif")),
      encodeJpeg: vi.fn(async () => {
        throw new Error("decode failed");
      }),
    });
    expect((await preparePhotos([GOOD], fake)).skipped).toBe(1);
    expect(fake.encodeJpeg).toHaveBeenCalledTimes(1);
  });

  it("skips a photo the CDN refuses to serve", async () => {
    const fake = deps({
      fetchBlob: vi.fn(async () => {
        throw new Error("403");
      }),
    });
    expect(await preparePhotos([GOOD], fake)).toEqual({ files: [], skipped: 1 });
  });

  it("does not even try a host the extension has no permission for", async () => {
    const fake = deps();
    expect(await preparePhotos([BAD_HOST], fake)).toEqual({ files: [], skipped: 1 });
    expect(fake.fetchBlob).not.toHaveBeenCalled();
  });

  it("keeps the photos that worked, in order, and counts the rest", async () => {
    const { files, skipped } = await preparePhotos([GOOD, BAD_HOST, OTHER], deps());
    expect(files.map((file) => file.name)).toEqual(["photo-1.jpg", "photo-3.jpg"]);
    expect(skipped).toBe(1);
  });

  it("reports every photo skipped when none can be prepared", async () => {
    const result = await preparePhotos([BAD_HOST, BAD_HOST], deps());
    expect(result).toEqual({ files: [], skipped: 2 });
  });
});
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
npm run test -w extension
```

Expected: `photos.test.ts` fails because `../../lib/panel/photos` does not exist.

- [ ] **Step 3: Implement photo preparation**

`extension/lib/panel/photos.ts`:

```ts
// Downloads the buyer's selected photos and makes them upload-ready.
//
// The API accepts JPEG, PNG, or WebP up to 5 MB each. Photos come from third-party CDNs, so this
// module is built to fail softly: a photo that cannot be fetched or shrunk is SKIPPED and
// counted, it never fails the whole check. The caller tells the buyer how many were skipped,
// and blocks only when none could be prepared.
//
// `deps` hold the two operations that need a real browser (fetching and re-encoding), so the
// decision logic can be tested with fakes. `browserPhotoDeps` are the real implementations; they
// are covered by the end-to-end test and the manual smoke test rather than by unit tests.
import { isFetchableImageUrl } from "../hosts";

/** The API's limit for one photo. */
export const MAX_PHOTO_BYTES = 5 * 1024 * 1024;

// Types the API accepts as they are, and the file extension used for each.
const ACCEPTED: Record<string, string> = { "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp" };

// Re-encoding tries these sizes (longest edge, in pixels) and JPEG qualities, largest and best
// first, and stops at the first result that fits.
const EDGES = [1600, 1200, 800];
const QUALITIES = [0.85, 0.7, 0.55, 0.4];

/** The two browser-dependent operations. */
export interface PhotoDeps {
  /** Downloads a photo. Rejects when the request fails or the CDN refuses. */
  fetchBlob(url: string): Promise<Blob>;
  /** Re-encodes an image as JPEG with its longest edge at most `maxEdge`. Rejects when it cannot be decoded. */
  encodeJpeg(blob: Blob, maxEdge: number, quality: number): Promise<Blob>;
}

/** The photos that could be prepared and how many selected photos had to be left out. */
export interface PreparedPhotos {
  files: File[];
  skipped: number;
}

/** Prepares one photo, or returns null when it must be skipped. `index` is its place in the selection. */
async function prepareOne(url: string, index: number, deps: PhotoDeps): Promise<File | null> {
  // Never try a host the manifest does not permit: the request would fail noisily anyway.
  if (!isFetchableImageUrl(url)) return null;

  let blob: Blob;
  try {
    blob = await deps.fetchBlob(url);
  } catch {
    return null;
  }

  const extension = ACCEPTED[blob.type];
  if (extension && blob.size <= MAX_PHOTO_BYTES) {
    return new File([blob], `photo-${index + 1}.${extension}`, { type: blob.type });
  }

  // Too big, or a type the API rejects (AVIF, HEIC, unknown): re-encode as JPEG and shrink until it fits.
  for (const edge of EDGES) {
    for (const quality of QUALITIES) {
      try {
        const encoded = await deps.encodeJpeg(blob, edge, quality);
        if (encoded.size <= MAX_PHOTO_BYTES) {
          return new File([encoded], `photo-${index + 1}.jpg`, { type: "image/jpeg" });
        }
      } catch {
        // The browser cannot decode this image at all; trying other sizes will not help.
        return null;
      }
    }
  }
  return null;
}

/**
 * Prepares the selected photos for upload.
 * @param urls The selected photo URLs, in the order the buyer sees them.
 * @param deps The fetch and re-encode operations.
 * @returns The files that could be prepared (original order, named photo-<n>.<ext>) and the
 *          number of photos skipped.
 */
export async function preparePhotos(urls: string[], deps: PhotoDeps): Promise<PreparedPhotos> {
  const prepared = await Promise.all(urls.map((url, index) => prepareOne(url, index, deps)));
  const files = prepared.filter((file): file is File => file !== null);
  return { files, skipped: urls.length - files.length };
}

/** The real implementations, used in the side panel. */
export const browserPhotoDeps: PhotoDeps = {
  async fetchBlob(url) {
    // Credentials are omitted: photo CDNs are public, and sending the buyer's cookies would only
    // share them needlessly.
    const response = await fetch(url, { credentials: "omit" });
    if (!response.ok) throw new Error(`Photo request failed with status ${response.status}`);
    return response.blob();
  },
  async encodeJpeg(blob, maxEdge, quality) {
    const bitmap = await createImageBitmap(blob);
    // Only ever shrink: an image already smaller than maxEdge keeps its size.
    const scale = Math.min(1, maxEdge / Math.max(bitmap.width, bitmap.height));
    const canvas = new OffscreenCanvas(
      Math.max(1, Math.round(bitmap.width * scale)),
      Math.max(1, Math.round(bitmap.height * scale)),
    );
    const context = canvas.getContext("2d");
    if (!context) throw new Error("A 2D canvas is not available");
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    return canvas.convertToBlob({ type: "image/jpeg", quality });
  },
};
```

- [ ] **Step 4: Run the tests and the typecheck**

```bash
npm run test -w extension
npm run typecheck -w extension
```

Expected: all pass. If TypeScript objects to the `as never` cast in the test helper `deps()`, replace it with an explicit return type that matches the two `vi.fn` members, and keep the helper's doc comment accurate in the same edit.

- [ ] **Step 5: Commit**

```bash
git add extension
git commit -m "feat(extension): add photo preparation that skips what cannot be read"
```

---

### Task 14: Error mapping, the check runner, and the panel state machine

**Files:**
- Create: `extension/lib/panel/errors.ts`, `extension/lib/panel/check.ts`, `extension/lib/panel/reducer.ts`
- Create: `extension/tests/panel/errors.test.ts`, `extension/tests/panel/check.test.ts`, `extension/tests/panel/reducer.test.ts`

**Interfaces:**
- Consumes: `GuardianLensApiError`, `GuardianLensClient`, `AssessmentResult`, `PipelineStage`, `FeedbackVerdict` from `@guardianlens/shared`; `Draft`, `DraftErrors`, `DraftFieldKey`, `buildForm`, `draftFromListing`, `applySeller`, `editField`, `togglePhoto`, `validateDraft` (Task 12); `PreparedPhotos` (Task 13); `CaptureJob` (Task 11); `PageState`, `BlockedState` (Task 10).
- Produces:
  - from `errors.ts`: `type FailureKind = "unreachable" | "rate_limited" | "failed"`, `type MappedError = { target: "review"; fieldErrors: DraftErrors } | { target: "failure"; kind: FailureKind; message: string }`, `NO_PHOTOS_MESSAGE`, `FAILED_MESSAGE`, `mapApiError(error: unknown): MappedError`
  - from `check.ts`: `POLL_INTERVAL_MS`, `SLOW_AFTER_MS`, `GIVE_UP_AFTER_MS`, `interface CheckDeps { client: Pick<GuardianLensClient, "submit" | "getStatus" | "getResult">; preparePhotos(urls: string[]): Promise<PreparedPhotos>; wait(ms: number): Promise<void>; onAccepted(assessmentId: string): void; onStage(stage: PipelineStage | null): void; onSlow(): void; isCancelled(): boolean }`, `type CheckOutcome = { status: "done"; result: AssessmentResult; skippedPhotos: number } | { status: "error"; error: MappedError } | { status: "cancelled" }`, `runCheck(draft: Draft, deps: CheckDeps): Promise<CheckOutcome>`
  - from `reducer.ts`: types `IdleReason`, `FeedbackState`, `PanelView`, `PanelState`, `PanelAction`; `initialPanelState: PanelState`; `panelReducer(state: PanelState, action: PanelAction): PanelState`

- [ ] **Step 1: Write the failing error-mapping tests**

`extension/tests/panel/errors.test.ts`:

```ts
// Pins how API and network errors become something the buyer can act on.
// Two kinds of outcome exist: a problem with ONE FIELD (shown next to that field, with the buyer's
// input kept) and a problem with the whole check (shown as a calm failure screen with a retry).
// The buyer never sees a raw error, status code, or stack trace.
import { GuardianLensApiError } from "@guardianlens/shared";
import { describe, expect, it } from "vitest";
import { FAILED_MESSAGE, mapApiError } from "../../lib/panel/errors";

/** Builds the error the API client throws. */
function apiError(status: number, code: string, message: string, field: string | null = null) {
  return new GuardianLensApiError(status, { error: { code, message, field } });
}

describe("mapApiError", () => {
  it("puts a field error next to its field", () => {
    const error = apiError(422, "unsupported_language", "Chinese-dominant listings are outside this prototype's supported language scope.", "description");
    expect(mapApiError(error)).toEqual({
      target: "review",
      fieldErrors: { description: "Chinese-dominant listings are outside this prototype's supported language scope." },
    });
  });

  it("maps server field names to draft field names", () => {
    expect(mapApiError(apiError(422, "invalid_integer", "Enter a whole number.", "account_age_days"))).toEqual({
      target: "review",
      fieldErrors: { accountAgeDays: "Enter a whole number." },
    });
  });

  it("maps any image field to the photos", () => {
    expect(mapApiError(apiError(422, "unsupported_image_type", "Use a JPEG.", "images[0]"))).toEqual({
      target: "review",
      fieldErrors: { photos: "Use a JPEG." },
    });
  });

  it("says the service is unreachable, mentioning the local server", () => {
    const result = mapApiError(apiError(0, "network_unreachable", "x"));
    expect(result).toMatchObject({ target: "failure", kind: "unreachable" });
    expect(result.target === "failure" && result.message).toContain("local server");
  });

  it("explains rate limiting", () => {
    expect(mapApiError(apiError(429, "rate_limit_exceeded", "x"))).toMatchObject({ target: "failure", kind: "rate_limited" });
  });

  it("falls back to a calm generic failure for anything else", () => {
    expect(mapApiError(apiError(500, "internal_error", "boom"))).toEqual({ target: "failure", kind: "failed", message: FAILED_MESSAGE });
    expect(mapApiError(new Error("random"))).toEqual({ target: "failure", kind: "failed", message: FAILED_MESSAGE });
    // A 422 without a field cannot be placed next to anything, so it is a whole-check failure.
    expect(mapApiError(apiError(422, "validation_error", "x"))).toMatchObject({ target: "failure", kind: "failed" });
  });
});
```

- [ ] **Step 2: Write the failing check-runner tests**

`extension/tests/panel/check.test.ts`:

```ts
// Pins the check runner: prepare photos, submit once, follow the five stages until a result.
// Rules protected here:
//   - if no photo can be prepared, nothing is submitted and the buyer is told (Review Focus 2);
//   - a field error on submit returns to Review with input kept; other errors are a calm failure;
//   - the "taking longer than usual" notice appears once, after the threshold, with no percentages;
//   - the runner stops when the buyer cancels, and gives up after two minutes rather than polling forever.
// Time is faked: `wait` returns immediately, so these tests run instantly.
import { GuardianLensApiError, type AssessmentStatusResponse } from "@guardianlens/shared";
import { describe, expect, it, vi } from "vitest";
import { buildForm, draftFromListing } from "../../lib/panel/draft";
import { GIVE_UP_AFTER_MS, POLL_INTERVAL_MS, SLOW_AFTER_MS, runCheck, type CheckDeps } from "../../lib/panel/check";
import { NO_PHOTOS_MESSAGE } from "../../lib/panel/errors";
import { sampleListing, sampleResult } from "../helpers/samples";

const draft = draftFromListing(sampleListing());
const processing = (stage: AssessmentStatusResponse["stage"]): AssessmentStatusResponse => ({ status: "processing", stage, message: null });
const complete: AssessmentStatusResponse = { status: "complete", stage: null, message: null };

/** Fake dependencies; `statuses` is the sequence the status endpoint returns (the last one repeats). */
function fakeDeps(statuses: AssessmentStatusResponse[], overrides: Partial<CheckDeps> = {}) {
  let call = 0;
  const events: string[] = [];
  const client = {
    submit: vi.fn(async (_form: FormData) => ({ assessment_id: "a1" })),
    getStatus: vi.fn(async () => statuses[Math.min(call++, statuses.length - 1)]),
    getResult: vi.fn(async () => sampleResult()),
  };
  const deps: CheckDeps = {
    client,
    preparePhotos: async () => ({ files: [new File([new Uint8Array([1])], "photo-1.jpg", { type: "image/jpeg" })], skipped: 0 }),
    wait: async () => undefined,
    onAccepted: (id) => events.push(`accepted:${id}`),
    onStage: (stage) => events.push(`stage:${stage}`),
    onSlow: () => events.push("slow"),
    isCancelled: () => false,
    ...overrides,
  };
  return { deps, client, events };
}

describe("runCheck", () => {
  it("submits once, follows the stages, and returns the result", async () => {
    const { deps, client, events } = fakeDeps([processing("visual"), processing("textual"), complete]);
    const outcome = await runCheck(draft, deps);

    expect(outcome).toMatchObject({ status: "done", skippedPhotos: 0 });
    expect(client.submit).toHaveBeenCalledTimes(1);
    expect(events).toEqual(["accepted:a1", "stage:visual", "stage:textual", "stage:null"]);
    const form = client.submit.mock.calls[0][0] as FormData;
    expect(form.get("source")).toBe("extension");
  });

  it("passes on how many photos were skipped", async () => {
    const { deps } = fakeDeps([complete], { preparePhotos: async () => ({ files: [new File([new Uint8Array([1])], "p.jpg", { type: "image/jpeg" })], skipped: 2 }) });
    expect(await runCheck(draft, deps)).toMatchObject({ status: "done", skippedPhotos: 2 });
  });

  it("does not submit when no photo can be prepared", async () => {
    const { deps, client } = fakeDeps([complete], { preparePhotos: async () => ({ files: [], skipped: 3 }) });
    expect(await runCheck(draft, deps)).toEqual({
      status: "error",
      error: { target: "review", fieldErrors: { photos: NO_PHOTOS_MESSAGE } },
    });
    expect(client.submit).not.toHaveBeenCalled();
  });

  it("returns to Review with the field error when the API rejects a field", async () => {
    const { deps, client } = fakeDeps([complete]);
    client.submit.mockRejectedValueOnce(
      new GuardianLensApiError(422, { error: { code: "unsupported_language", message: "Unsupported language.", field: "description" } }),
    );
    expect(await runCheck(draft, deps)).toEqual({
      status: "error",
      error: { target: "review", fieldErrors: { description: "Unsupported language." } },
    });
    expect(client.getStatus).not.toHaveBeenCalled();
  });

  it("reports an unreachable service as a failure", async () => {
    const { deps, client } = fakeDeps([complete]);
    client.submit.mockRejectedValueOnce(new GuardianLensApiError(0, { error: { code: "network_unreachable", message: "x", field: null } }));
    const outcome = await runCheck(draft, deps);
    expect(outcome).toMatchObject({ status: "error", error: { target: "failure", kind: "unreachable" } });
  });

  it("reports a failed assessment with the server's message", async () => {
    const { deps } = fakeDeps([{ status: "failed", stage: null, message: "The check could not be completed." }]);
    expect(await runCheck(draft, deps)).toEqual({
      status: "error",
      error: { target: "failure", kind: "failed", message: "The check could not be completed." },
    });
  });

  it("stops when the buyer cancels", async () => {
    let cancelled = false;
    const { deps } = fakeDeps([processing("visual"), processing("textual"), complete], {
      onStage: () => {
        cancelled = true;
      },
      isCancelled: () => cancelled,
    });
    expect(await runCheck(draft, deps)).toEqual({ status: "cancelled" });
  });

  it("says it is taking longer than usual exactly once", async () => {
    const polls = Math.ceil(SLOW_AFTER_MS / POLL_INTERVAL_MS) + 5;
    const statuses = [...Array.from({ length: polls }, () => processing("visual")), complete];
    const { deps, events } = fakeDeps(statuses);
    await runCheck(draft, deps);
    expect(events.filter((event) => event === "slow")).toHaveLength(1);
  });

  it("gives up after two minutes instead of polling forever", async () => {
    const { deps, client } = fakeDeps([processing("visual")]);
    const outcome = await runCheck(draft, deps);
    expect(outcome).toMatchObject({ status: "error", error: { target: "failure", kind: "failed" } });
    expect(client.getStatus.mock.calls.length).toBe(Math.ceil(GIVE_UP_AFTER_MS / POLL_INTERVAL_MS));
  });

  it("builds the same form the draft module builds", () => {
    // Guards against the runner and the draft drifting apart: the runner uses buildForm directly.
    expect(buildForm(draft, []).get("source")).toBe("extension");
  });
});
```

- [ ] **Step 3: Write the failing reducer tests**

`extension/tests/panel/reducer.test.ts`:

```ts
// Pins the side panel's state machine.
// The panel moves between: idle (nothing captured), capturing, review, checking, result, and
// failure. These tests protect the behaviours a buyer relies on:
//   - a click always shows the latest capture, but an OLD capture can never overwrite newer work;
//   - the buyer's edits survive failures, cancels, and seller-page additions;
//   - a second "Check listing" press while one is running does nothing (Review Focus 5);
//   - blocked and unsupported pages produce plain explanations, never a half-read draft.
import { describe, expect, it } from "vitest";
import type { CaptureJob } from "../../lib/capture/runner";
import { draftFromListing, editField } from "../../lib/panel/draft";
import { initialPanelState, panelReducer, type PanelAction, type PanelState } from "../../lib/panel/reducer";
import { sampleListing, sampleResult, sampleSeller } from "../helpers/samples";

/** A finished capture job of a listing page. */
const listingJob = (id: number, listing = sampleListing()): CaptureJob => ({
  id,
  tabId: 1,
  status: "done",
  result: { kind: "listing", listing },
});

/** Applies actions one after another. */
function run(state: PanelState, ...actions: PanelAction[]): PanelState {
  return actions.reduce(panelReducer, state);
}

/** A state in the Review view with a fresh draft. */
const review = () => run(initialPanelState, { type: "capture_finished", job: listingJob(10) });

describe("capture_finished", () => {
  it("starts in the idle state", () => {
    expect(initialPanelState.view).toEqual({ name: "idle", reason: "no_capture" });
  });

  it("shows the capturing view while a capture is running", () => {
    const state = run(initialPanelState, { type: "capture_finished", job: { id: 1, tabId: 1, status: "capturing" } });
    expect(state.view).toEqual({ name: "capturing" });
  });

  it("opens Review with a draft for a captured listing", () => {
    const state = review();
    expect(state.view).toEqual({ name: "review" });
    expect(state.draft?.fields.title.value).toBe("Used laptop in good condition");
    expect(state.notice).toBeNull();
  });

  it("adds a notice when part of the listing could not be read", () => {
    const state = run(initialPanelState, { type: "capture_finished", job: listingJob(10, sampleListing({ pageState: "incomplete" })) });
    expect(state.view).toEqual({ name: "review" });
    expect(state.notice).toBe("Some details could not be read from this page. Check each field.");
  });

  it("explains a blocked page and does not create a draft", () => {
    const state = run(initialPanelState, { type: "capture_finished", job: listingJob(10, sampleListing({ pageState: "captcha" })) });
    expect(state.view).toEqual({ name: "idle", reason: "blocked", pageState: "captcha" });
    expect(state.draft).toBeNull();
  });

  it("explains a failed capture", () => {
    const state = run(initialPanelState, { type: "capture_finished", job: { id: 1, tabId: 1, status: "error", error: "inject_failed" } });
    expect(state.view).toEqual({ name: "idle", reason: "capture_failed" });
  });

  it.each([
    ["not_a_listing", "not_listing"],
    ["unsupported_site", "unsupported_site"],
  ] as const)("explains an unsupported page (%s)", (reason, idleReason) => {
    const job: CaptureJob = { id: 1, tabId: 1, status: "done", result: { kind: "unsupported", reason } };
    expect(run(initialPanelState, { type: "capture_finished", job }).view).toEqual({ name: "idle", reason: idleReason });
  });

  it("keeps the buyer's draft when a later click is on an unsupported page", () => {
    const state = run(review(), {
      type: "capture_finished",
      job: { id: 11, tabId: 1, status: "done", result: { kind: "unsupported", reason: "unsupported_site" } },
    });
    expect(state.draft).not.toBeNull();
  });
});

describe("old captures never overwrite newer work", () => {
  it("ignores a finished job that was already applied", () => {
    const edited = run(review(), { type: "edit_field", key: "title", value: "My edit" });
    // The same job arrives again (for example when the panel is reopened).
    expect(run(edited, { type: "capture_finished", job: listingJob(10) })).toBe(edited);
  });

  it("ignores a job older than one already applied", () => {
    const state = review();
    expect(run(state, { type: "capture_finished", job: listingJob(5) })).toBe(state);
  });

  it("replaces the draft when a newer job arrives", () => {
    const state = run(review(), { type: "capture_finished", job: listingJob(11, sampleListing({ title: { status: "captured", value: "Another listing" } })) });
    expect(state.draft?.fields.title.value).toBe("Another listing");
  });

  it("restores a stored draft, then still accepts a newer capture", () => {
    const stored = draftFromListing(sampleListing());
    const restored = run(initialPanelState, { type: "state_restored", draft: stored, lastDoneJobId: 10 });
    expect(restored.view).toEqual({ name: "review" });
    // The job that produced the stored draft is not replayed over it...
    expect(run(restored, { type: "capture_finished", job: listingJob(10) })).toBe(restored);
    // ...but a newer click is applied.
    expect(run(restored, { type: "capture_finished", job: listingJob(12) }).draft).not.toBe(stored);
  });

  it("does not let a late restore overwrite a capture that already arrived", () => {
    const live = review();
    const stale = draftFromListing(sampleListing({ title: { status: "captured", value: "Old stored draft" } }));
    expect(run(live, { type: "state_restored", draft: stale, lastDoneJobId: 3 })).toBe(live);
  });

  it("restores nothing when no draft was stored", () => {
    expect(run(initialPanelState, { type: "state_restored", draft: null, lastDoneJobId: 0 }).view).toEqual({ name: "idle", reason: "no_capture" });
  });
});

describe("seller page captures", () => {
  const sellerJob = (id: number, pageState: "ready" | "captcha" = "ready"): CaptureJob => ({
    id,
    tabId: 2,
    status: "done",
    result: { kind: "seller", platform: "carousell", seller: sampleSeller(), pageState },
  });

  it("asks for the listing first when there is no draft", () => {
    const state = run(initialPanelState, { type: "capture_finished", job: sellerJob(1) });
    expect(state.view).toEqual({ name: "idle", reason: "no_draft_for_seller" });
  });

  it("adds the seller details to the draft and tells the buyer", () => {
    const state = run(review(), { type: "capture_finished", job: sellerJob(11) });
    expect(state.view).toEqual({ name: "review" });
    expect(state.draft?.fields.rating.value).toBe("4.8");
    expect(state.notice).toBe("Seller details added. Check the listing again to include them.");
  });

  it("does not overwrite what the buyer typed", () => {
    const state = run(review(), { type: "edit_field", key: "rating", value: "3" }, { type: "capture_finished", job: sellerJob(11) });
    expect(state.draft?.fields.rating.value).toBe("3");
  });

  it("keeps the draft and says so when the seller page could not be read", () => {
    const state = run(review(), { type: "capture_finished", job: sellerJob(11, "captcha") });
    expect(state.draft?.fields.rating.value).toBe("");
    expect(state.notice).toBe("The seller page could not be read, so no seller details were added.");
  });
});

describe("editing", () => {
  it("marks the field edited and clears that field's error", () => {
    const failed = run(review(), { type: "check_failed", error: { target: "review", fieldErrors: { title: "Enter the listing title." } } });
    const state = run(failed, { type: "edit_field", key: "title", value: "New" });
    expect(state.draft?.fields.title).toEqual({ value: "New", status: "edited" });
    expect(state.fieldErrors.title).toBeUndefined();
  });

  it("limits the selection to three photos", () => {
    const state = run(review(), { type: "toggle_photo", url: sampleListing().imageUrls[3] });
    expect(state.draft?.photos[3].selected).toBe(false);
  });
});

describe("submitting (Review Focus 5)", () => {
  it("blocks an invalid draft and shows what to fix", () => {
    const blank = run(review(), { type: "edit_field", key: "title", value: "" }, { type: "submit_requested" });
    expect(blank.submitting).toBe(false);
    expect(blank.fieldErrors.title).toBe("Enter the listing title.");
  });

  it("starts a check for a valid draft", () => {
    const state = run(review(), { type: "submit_requested" });
    expect(state.submitting).toBe(true);
  });

  it("ignores a second press while the first check is running", () => {
    const first = run(review(), { type: "submit_requested" });
    // Same object back: no state change, so nothing downstream can start a second request.
    expect(run(first, { type: "submit_requested" })).toBe(first);
  });

  it("ignores a submit outside the Review view", () => {
    const idle = initialPanelState;
    expect(run(idle, { type: "submit_requested" })).toBe(idle);
  });
});

describe("checking and results", () => {
  it("moves through accepted, stage changes, and slow wait", () => {
    let state = run(review(), { type: "submit_requested" }, { type: "submit_accepted", assessmentId: "a1" });
    expect(state.view).toEqual({ name: "checking", assessmentId: "a1", stage: null, slow: false });
    state = run(state, { type: "stage_changed", stage: "textual" }, { type: "slow_wait" });
    expect(state.view).toEqual({ name: "checking", assessmentId: "a1", stage: "textual", slow: true });
  });

  it("shows the result and stops submitting", () => {
    const state = run(review(), { type: "submit_requested" }, { type: "submit_accepted", assessmentId: "a1" }, { type: "check_finished", result: sampleResult(), skippedPhotos: 0 });
    expect(state.view).toMatchObject({ name: "result", feedback: "idle" });
    expect(state.submitting).toBe(false);
    expect(state.notice).toBeNull();
  });

  it("mentions photos that were left out", () => {
    const one = run(review(), { type: "check_finished", result: sampleResult(), skippedPhotos: 1 });
    expect(one.notice).toBe("1 photo could not be read and was left out of this check.");
    const two = run(review(), { type: "check_finished", result: sampleResult(), skippedPhotos: 2 });
    expect(two.notice).toBe("2 photos could not be read and were left out of this check.");
  });

  it("returns to Review with field errors and the draft kept", () => {
    const state = run(review(), { type: "submit_requested" }, { type: "check_failed", error: { target: "review", fieldErrors: { description: "Unsupported." } } });
    expect(state.view).toEqual({ name: "review" });
    expect(state.fieldErrors.description).toBe("Unsupported.");
    expect(state.submitting).toBe(false);
    expect(state.draft).not.toBeNull();
  });

  it("shows a failure screen and keeps the draft for the retry", () => {
    const state = run(review(), { type: "submit_requested" }, { type: "check_failed", error: { target: "failure", kind: "unreachable", message: "Can't reach it." } });
    expect(state.view).toEqual({ name: "failure", kind: "unreachable", message: "Can't reach it." });
    expect(run(state, { type: "back_to_review" }).view).toEqual({ name: "review" });
    expect(run(state, { type: "back_to_review" }).draft).not.toBeNull();
  });

  it("returns to Review when the buyer cancels", () => {
    const state = run(review(), { type: "submit_requested" }, { type: "submit_accepted", assessmentId: "a1" }, { type: "cancelled" });
    expect(state.view).toEqual({ name: "review" });
    expect(state.submitting).toBe(false);
  });

  it("tracks feedback", () => {
    const result = run(review(), { type: "check_finished", result: sampleResult(), skippedPhotos: 0 });
    expect(run(result, { type: "feedback_changed", state: "saved" }).view).toMatchObject({ name: "result", feedback: "saved" });
  });

  it("clears the draft for the next listing", () => {
    const state = run(review(), { type: "check_finished", result: sampleResult(), skippedPhotos: 0 }, { type: "check_another" });
    expect(state.view).toEqual({ name: "idle", reason: "no_capture" });
    expect(state.draft).toBeNull();
  });
});

describe("edits survive a failed check", () => {
  it("keeps typed values through a failure and a retry", () => {
    const edited = run(review(), { type: "edit_field", key: "price", value: "1300" });
    const retried = run(edited, { type: "submit_requested" }, { type: "check_failed", error: { target: "failure", kind: "failed", message: "x" } }, { type: "back_to_review" });
    expect(retried.draft?.fields.price).toEqual(editField(draftFromListing(sampleListing()), "price", "1300").fields.price);
  });
});
```

- [ ] **Step 4: Run the tests to confirm they fail**

```bash
npm run test -w extension
```

Expected: the three new test files fail because their modules do not exist.

- [ ] **Step 5: Implement error mapping**

`extension/lib/panel/errors.ts`:

```ts
// Turns API and network errors into something the buyer can act on.
//
// An error is one of two kinds:
//   - a problem with ONE FIELD ("target: review"): shown next to that field, with all of the
//     buyer's input kept, and a stay in the Review step;
//   - a problem with the WHOLE check ("target: failure"): a calm failure screen with a retry.
// The buyer never sees a raw error, a status code, or a stack trace.
import { GuardianLensApiError } from "@guardianlens/shared";
import type { DraftErrors } from "./draft";

/** Why the whole check failed. */
export type FailureKind = "unreachable" | "rate_limited" | "failed";

/** Where an error is shown and what it says. */
export type MappedError =
  | { target: "review"; fieldErrors: DraftErrors }
  | { target: "failure"; kind: FailureKind; message: string };

/** Shown when none of the selected photos could be prepared. */
export const NO_PHOTOS_MESSAGE =
  "None of the selected photos could be read. Remove them and use the website form instead.";

/** The calm generic failure message. The draft is kept, so the buyer can simply retry. */
export const FAILED_MESSAGE = "The check could not be completed. Your details are saved; try again.";

// The API names form fields in snake_case; the draft uses camelCase.
const FIELD_KEYS: Record<string, keyof DraftErrors> = {
  title: "title",
  description: "description",
  price: "price",
  category: "category",
  rating: "rating",
  account_age_days: "accountAgeDays",
  review_count: "reviewCount",
  active_listing_count: "activeListingCount",
};

/**
 * Maps any error thrown while submitting or polling to a buyer-facing outcome.
 * @param error Whatever was thrown (usually a GuardianLensApiError).
 */
export function mapApiError(error: unknown): MappedError {
  if (error instanceof GuardianLensApiError) {
    if (error.code === "network_unreachable") {
      return {
        target: "failure",
        kind: "unreachable",
        message: "Can't reach the GuardianLens service. Is the local server running?",
      };
    }
    if (error.status === 429) {
      return {
        target: "failure",
        kind: "rate_limited",
        message: "Too many checks were sent in a short time. Wait a minute and try again.",
      };
    }
    if (error.status === 422 && error.field) {
      // Every uploaded image is reported as images[<n>]; they all belong to the photo picker.
      const key = error.field.startsWith("images") ? "photos" : FIELD_KEYS[error.field];
      if (key) return { target: "review", fieldErrors: { [key]: error.message } };
    }
  }
  return { target: "failure", kind: "failed", message: FAILED_MESSAGE };
}
```

- [ ] **Step 6: Implement the check runner**

`extension/lib/panel/check.ts`:

```ts
// Runs one check from "Check listing" to a result: prepare the photos, submit ONCE, then follow
// the five processing stages until the result is ready.
//
// All side effects (the API client, photo preparation, waiting, and the progress callbacks) are
// passed in as `deps`, so this logic is tested with fakes and no real timers.
//
// Behaviour worth knowing:
//   - if no photo can be prepared nothing is submitted;
//   - the buyer is told once, after SLOW_AFTER_MS, that the check is taking longer than usual
//     (no percentages and no fake progress);
//   - polling stops when the buyer cancels and gives up after GIVE_UP_AFTER_MS, so a stuck
//     server can never leave the panel spinning forever.
import type { AssessmentResult, GuardianLensClient, PipelineStage } from "@guardianlens/shared";
import { buildForm, type Draft } from "./draft";
import { FAILED_MESSAGE, NO_PHOTOS_MESSAGE, mapApiError, type MappedError } from "./errors";
import type { PreparedPhotos } from "./photos";

/** How often the status endpoint is polled. */
export const POLL_INTERVAL_MS = 900;
/** After this long the buyer is told the check is taking longer than usual. */
export const SLOW_AFTER_MS = 8_000;
/** After this long the check is abandoned with a failure message. */
export const GIVE_UP_AFTER_MS = 120_000;

/** Everything runCheck needs from the outside world. */
export interface CheckDeps {
  client: Pick<GuardianLensClient, "submit" | "getStatus" | "getResult">;
  preparePhotos(urls: string[]): Promise<PreparedPhotos>;
  /** Resolves after `ms` milliseconds (replaced by an instant fake in tests). */
  wait(ms: number): Promise<void>;
  /** The API accepted the submission. */
  onAccepted(assessmentId: string): void;
  /** The API reported the stage that is running (null when none is). */
  onStage(stage: PipelineStage | null): void;
  /** The check has taken longer than SLOW_AFTER_MS. Called at most once. */
  onSlow(): void;
  /** True once the buyer pressed Cancel. */
  isCancelled(): boolean;
}

/** How a check ended. */
export type CheckOutcome =
  | { status: "done"; result: AssessmentResult; skippedPhotos: number }
  | { status: "error"; error: MappedError }
  | { status: "cancelled" };

/**
 * Runs one check.
 * @param draft A draft that already passed validation.
 * @returns The result, an error for the panel to show, or "cancelled".
 */
export async function runCheck(draft: Draft, deps: CheckDeps): Promise<CheckOutcome> {
  const urls = draft.photos.filter((photo) => photo.selected).map((photo) => photo.url);
  const prepared = await deps.preparePhotos(urls);
  if (prepared.files.length === 0) {
    return { status: "error", error: { target: "review", fieldErrors: { photos: NO_PHOTOS_MESSAGE } } };
  }

  try {
    const accepted = await deps.client.submit(buildForm(draft, prepared.files));
    deps.onAccepted(accepted.assessment_id);

    let waited = 0;
    let slowReported = false;
    while (waited < GIVE_UP_AFTER_MS) {
      if (deps.isCancelled()) return { status: "cancelled" };
      const status = await deps.client.getStatus(accepted.assessment_id);
      deps.onStage(status.stage);
      if (status.status === "complete") {
        const result = await deps.client.getResult(accepted.assessment_id);
        return { status: "done", result, skippedPhotos: prepared.skipped };
      }
      if (status.status === "failed" || status.status === "abandoned") {
        return {
          status: "error",
          error: { target: "failure", kind: "failed", message: status.message ?? FAILED_MESSAGE },
        };
      }
      await deps.wait(POLL_INTERVAL_MS);
      waited += POLL_INTERVAL_MS;
      if (!slowReported && waited >= SLOW_AFTER_MS) {
        slowReported = true;
        deps.onSlow();
      }
    }
    return {
      status: "error",
      error: { target: "failure", kind: "failed", message: "The check is taking too long. Try again." },
    };
  } catch (error) {
    return { status: "error", error: mapApiError(error) };
  }
}
```

- [ ] **Step 7: Implement the state machine**

`extension/lib/panel/reducer.ts`:

```ts
// The side panel's state machine, as a pure reducer.
//
// Views: idle (nothing captured), capturing, review, checking, result, failure.
// Rules this file guarantees (each pinned by a test):
//   - a capture job is applied once: a job that was already applied, or is older than one that
//     was, is ignored, so reopening the panel can never overwrite the buyer's newer edits; and a
//     draft restored from storage never overwrites a capture that arrived while it was loading;
//   - the buyer's draft survives failures, cancels, and seller-page additions;
//   - "submit_requested" is a no-op unless the Review view is showing, nothing is running, and the
//     draft is valid, so pressing the button twice cannot start two checks.
// Side effects (storage, network, timers) live in controller.ts; this file has none.
import type { AssessmentResult, PipelineStage } from "@guardianlens/shared";
import type { CaptureJob } from "../capture/runner";
import type { PageState } from "../capture/types";
import { applySeller, draftFromListing, editField, togglePhoto, validateDraft, type Draft, type DraftErrors, type DraftFieldKey } from "./draft";
import type { FailureKind, MappedError } from "./errors";

/** Why the idle view is showing. */
export type IdleReason =
  | "no_capture"
  | "not_listing"
  | "unsupported_site"
  | "blocked"
  | "capture_failed"
  | "no_draft_for_seller";

/** Progress of the feedback prompt on the result view. */
export type FeedbackState = "idle" | "saving" | "saved";

/** What the panel is showing. */
export type PanelView =
  | { name: "idle"; reason: IdleReason; pageState?: PageState }
  | { name: "capturing" }
  | { name: "review" }
  | { name: "checking"; assessmentId: string; stage: PipelineStage | null; slow: boolean }
  | { name: "result"; result: AssessmentResult; feedback: FeedbackState }
  | { name: "failure"; kind: FailureKind; message: string };

/** Everything the panel knows. */
export interface PanelState {
  view: PanelView;
  /** The buyer's draft; kept through failures and cancels. */
  draft: Draft | null;
  /** Errors to show next to fields (server field errors and failed submit validation). */
  fieldErrors: DraftErrors;
  /** A plain one-line message shown above the form or result, or null. */
  notice: string | null;
  /** True from a valid "Check listing" press until the check ends. */
  submitting: boolean;
  /** Id of the newest finished capture job already applied. Finished jobs with an id at or below it are ignored. */
  lastDoneJobId: number;
}

/** Everything that can happen to the panel. */
export type PanelAction =
  | { type: "capture_finished"; job: CaptureJob }
  | { type: "state_restored"; draft: Draft | null; lastDoneJobId: number }
  | { type: "edit_field"; key: DraftFieldKey; value: string }
  | { type: "toggle_photo"; url: string }
  | { type: "submit_requested" }
  | { type: "submit_accepted"; assessmentId: string }
  | { type: "stage_changed"; stage: PipelineStage | null }
  | { type: "slow_wait" }
  | { type: "check_finished"; result: AssessmentResult; skippedPhotos: number }
  | { type: "check_failed"; error: MappedError }
  | { type: "cancelled" }
  | { type: "feedback_changed"; state: FeedbackState }
  | { type: "check_another" }
  | { type: "back_to_review" };

/** The panel before anything has been captured. */
export const initialPanelState: PanelState = {
  view: { name: "idle", reason: "no_capture" },
  draft: null,
  fieldErrors: {},
  notice: null,
  submitting: false,
  lastDoneJobId: 0,
};

const INCOMPLETE_NOTICE = "Some details could not be read from this page. Check each field.";
const SELLER_ADDED_NOTICE = "Seller details added. Check the listing again to include them.";
const SELLER_UNREADABLE_NOTICE = "The seller page could not be read, so no seller details were added.";

/** True for the page states that mean the page was blocked and not read. */
function isBlocked(state: PageState): boolean {
  return state !== "ready" && state !== "incomplete";
}

/** The notice about photos that were left out of a check, or null when none were. */
function skippedNotice(count: number): string | null {
  if (count === 0) return null;
  return count === 1
    ? "1 photo could not be read and was left out of this check."
    : `${count} photos could not be read and were left out of this check.`;
}

/** Applies a capture job from the service worker. */
function applyCaptureJob(state: PanelState, job: CaptureJob): PanelState {
  if (job.status === "capturing") {
    // A "capturing" job only matters while it is newer than anything already applied.
    return job.id > state.lastDoneJobId ? { ...state, view: { name: "capturing" } } : state;
  }
  if (job.id <= state.lastDoneJobId) return state;
  const base = { ...state, lastDoneJobId: job.id };

  if (job.status === "error" || !job.result) {
    return { ...base, view: { name: "idle", reason: "capture_failed" } };
  }
  const { result } = job;

  if (result.kind === "unsupported") {
    return {
      ...base,
      view: { name: "idle", reason: result.reason === "not_a_listing" ? "not_listing" : "unsupported_site" },
    };
  }

  if (result.kind === "listing") {
    if (isBlocked(result.listing.pageState)) {
      return { ...base, view: { name: "idle", reason: "blocked", pageState: result.listing.pageState } };
    }
    return {
      ...base,
      view: { name: "review" },
      draft: draftFromListing(result.listing),
      fieldErrors: {},
      submitting: false,
      notice: result.listing.pageState === "incomplete" ? INCOMPLETE_NOTICE : null,
    };
  }

  // A seller page: its values are merged into the draft of the listing the buyer already captured.
  if (state.draft === null) return { ...base, view: { name: "idle", reason: "no_draft_for_seller" } };
  if (isBlocked(result.pageState)) return { ...base, view: { name: "review" }, notice: SELLER_UNREADABLE_NOTICE };
  return {
    ...base,
    view: { name: "review" },
    draft: applySeller(state.draft, result.seller),
    fieldErrors: {},
    submitting: false,
    notice: SELLER_ADDED_NOTICE,
  };
}

/** The reducer. Always returns the SAME object when an action changes nothing. */
export function panelReducer(state: PanelState, action: PanelAction): PanelState {
  switch (action.type) {
    case "capture_finished":
      return applyCaptureJob(state, action.job);

    case "state_restored":
      // Restoring reads storage asynchronously, so a live capture may already have arrived. A
      // draft that is already here is newer than the stored one and must never be overwritten.
      if (state.draft !== null) return state;
      return {
        ...state,
        draft: action.draft,
        lastDoneJobId: Math.max(state.lastDoneJobId, action.lastDoneJobId),
        view: action.draft ? { name: "review" } : state.view,
      };

    case "edit_field": {
      if (!state.draft) return state;
      const { [action.key]: _cleared, ...remaining } = state.fieldErrors;
      return { ...state, draft: editField(state.draft, action.key, action.value), fieldErrors: remaining };
    }

    case "toggle_photo": {
      if (!state.draft) return state;
      const { photos: _cleared, ...remaining } = state.fieldErrors;
      return { ...state, draft: togglePhoto(state.draft, action.url), fieldErrors: remaining };
    }

    case "submit_requested": {
      if (state.view.name !== "review" || state.submitting || state.draft === null) return state;
      const errors = validateDraft(state.draft);
      if (Object.keys(errors).length > 0) return { ...state, fieldErrors: errors };
      return { ...state, fieldErrors: {}, submitting: true };
    }

    case "submit_accepted":
      return { ...state, view: { name: "checking", assessmentId: action.assessmentId, stage: null, slow: false } };

    case "stage_changed":
      return state.view.name === "checking" ? { ...state, view: { ...state.view, stage: action.stage } } : state;

    case "slow_wait":
      return state.view.name === "checking" ? { ...state, view: { ...state.view, slow: true } } : state;

    case "check_finished":
      return {
        ...state,
        view: { name: "result", result: action.result, feedback: "idle" },
        submitting: false,
        notice: skippedNotice(action.skippedPhotos),
      };

    case "check_failed":
      if (action.error.target === "review") {
        return {
          ...state,
          view: { name: "review" },
          submitting: false,
          fieldErrors: { ...state.fieldErrors, ...action.error.fieldErrors },
        };
      }
      return {
        ...state,
        view: { name: "failure", kind: action.error.kind, message: action.error.message },
        submitting: false,
      };

    case "cancelled":
      return { ...state, view: { name: "review" }, submitting: false };

    case "feedback_changed":
      return state.view.name === "result" ? { ...state, view: { ...state.view, feedback: action.state } } : state;

    case "check_another":
      return { ...state, view: { name: "idle", reason: "no_capture" }, draft: null, fieldErrors: {}, notice: null, submitting: false };

    case "back_to_review":
      return { ...state, view: { name: "review" } };
  }
}
```

- [ ] **Step 8: Run the tests and the typecheck**

```bash
npm run test -w extension
npm run typecheck -w extension
```

Expected: all pass. TypeScript may warn that the destructured `_cleared` variables in the `edit_field` and `toggle_photo` cases are unused; they are intentional (the destructuring removes one key), so leave them and keep the comment on the reducer accurate.

- [ ] **Step 9: Commit**

```bash
git add extension
git commit -m "feat(extension): add error mapping, the check runner, and the panel state machine"
```

---

### Task 15: Side panel views

**Files:**
- Create: `extension/entrypoints/sidepanel/views/IdleView.tsx`, `ReviewView.tsx`, `CheckingView.tsx`, `ResultView.tsx`, `FailureView.tsx`
- Create: `extension/entrypoints/sidepanel/panel.css`
- Create: `extension/tests/panel/views.test.tsx`

**Interfaces:**
- Consumes: `CategoryField`, `RETENTION_NOTICE`, `StageList`, `SLOW_WAIT_COPY`, `ScoreRegion`, `SignalCardView`, `DevBanner`, `AssessmentResult`, `FeedbackVerdict`, `PipelineStage`, `SignalName` from `@guardianlens/shared`; `Draft`, `DraftErrors`, `DraftField`, `DraftFieldKey`, `LIMITS`, `validateDraft` (Task 12); `IdleReason`, `FeedbackState` (Task 14); `FailureKind` (Task 14); `PageState` (Task 10).
- Produces (each view is a pure component driven only by props):
  - `IdleView({ reason: IdleReason; pageState?: PageState; onOpenSite(path: string): void })`
  - `ReviewView({ draft: Draft; fieldErrors: DraftErrors; notice: string | null; submitting: boolean; onEdit(key: DraftFieldKey, value: string): void; onTogglePhoto(url: string): void; onSubmit(): void })` and the exported `ReviewViewProps`
  - `CheckingView({ stage: PipelineStage | null; slow: boolean; onCancel(): void })`
  - `ResultView({ result: AssessmentResult; feedback: FeedbackState; notice: string | null; onSeeFull(signal?: SignalName): void; onFeedback(verdict: FeedbackVerdict): void; onCheckAnother(): void })`
  - `FailureView({ kind: FailureKind; message: string; onRetry(): void; onOpenSite(path: string): void })`

- [ ] **Step 1: Write the failing view tests**

`extension/tests/panel/views.test.tsx`:

```tsx
// Pins what the buyer sees and can do in each side panel view. The views are pure components
// driven by props, so each test renders one view and checks its text, its controls, and the
// callbacks. The design rules protected (docs/spec/04_Design_Brief_UI_UX.md):
//   - every captured field says in WORDS whether it was captured, edited, or not found;
//   - missing seller details are "unknown, not suspicious", never a blocker;
//   - the submit button explains what is missing instead of failing silently (Review Focus 3:
//     over-limit text is an error, not cut off);
//   - the disclaimer sits INSIDE the score region, and the development-stub warning is shown;
//   - category is free text, with a note when it is not one of the trained categories.
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { UNSEEN_CATEGORY_NOTE } from "@guardianlens/shared";
import { CheckingView } from "@/entrypoints/sidepanel/views/CheckingView";
import { FailureView } from "@/entrypoints/sidepanel/views/FailureView";
import { IdleView } from "@/entrypoints/sidepanel/views/IdleView";
import { ResultView } from "@/entrypoints/sidepanel/views/ResultView";
import { ReviewView, type ReviewViewProps } from "@/entrypoints/sidepanel/views/ReviewView";
import { draftFromListing, editField, togglePhoto, type Draft } from "@/lib/panel/draft";
import { PHOTOS, sampleListing, sampleResult } from "../helpers/samples";

/** Renders the Review view with working spies; `overrides` and `draft` change only what a test needs. */
function renderReview(overrides: Partial<ReviewViewProps> = {}, draft: Draft = draftFromListing(sampleListing())) {
  const props: ReviewViewProps = {
    draft,
    fieldErrors: {},
    notice: null,
    submitting: false,
    onEdit: vi.fn(),
    onTogglePhoto: vi.fn(),
    onSubmit: vi.fn(),
    ...overrides,
  };
  render(<ReviewView {...props} />);
  return props;
}

/** The `.field` container around a labelled control, so a test can look at just that field. */
function fieldOf(label: string): HTMLElement {
  return screen.getByLabelText(label).closest(".field") as HTMLElement;
}

describe("IdleView", () => {
  it("tells the buyer what to do first", () => {
    render(<IdleView reason="no_capture" onOpenSite={vi.fn()} />);
    expect(screen.getByText("Open a Mudah.my or Carousell listing, then click the GuardianLens icon.")).toBeInTheDocument();
  });

  it("explains a blocked page in plain words", () => {
    render(<IdleView reason="blocked" pageState="captcha" onOpenSite={vi.fn()} />);
    expect(screen.getByText("The site is asking for a security check. Complete it, then click the icon again.")).toBeInTheDocument();
  });

  it("explains how to add seller details when there is no listing yet", () => {
    render(<IdleView reason="no_draft_for_seller" onOpenSite={vi.fn()} />);
    expect(screen.getByText(/Open the listing first/)).toBeInTheDocument();
  });

  it("offers the website form and the session history", async () => {
    const onOpenSite = vi.fn();
    render(<IdleView reason="no_capture" onOpenSite={onOpenSite} />);
    await userEvent.click(screen.getByRole("button", { name: "Use the website form" }));
    await userEvent.click(screen.getByRole("button", { name: "This session" }));
    expect(onOpenSite).toHaveBeenNthCalledWith(1, "/assess");
    expect(onOpenSite).toHaveBeenNthCalledWith(2, "/history");
  });
});

describe("ReviewView", () => {
  it("says the data was captured when the buyer clicked, and names the marketplace", () => {
    renderReview();
    expect(screen.getByText("Captured from this page when you clicked.")).toBeInTheDocument();
    expect(screen.getByText("Carousell")).toBeInTheDocument();
  });

  it("labels each field in words: captured, edited, not found", () => {
    const missingPrice = draftFromListing(sampleListing({ price: { status: "not_found", value: null } }));
    renderReview({}, editField(missingPrice, "title", "My own title"));
    expect(within(fieldOf("Description")).getByText("Captured")).toBeInTheDocument();
    expect(within(fieldOf("Title")).getByText("Edited by you")).toBeInTheDocument();
    expect(within(fieldOf("Price")).getByText("Not found. Enter it yourself.")).toBeInTheDocument();
  });

  it("reports an edit through onEdit", async () => {
    const props = renderReview({}, draftFromListing(sampleListing({ price: { status: "not_found", value: null } })));
    await userEvent.type(screen.getByLabelText("Price"), "1");
    expect(props.onEdit).toHaveBeenCalledWith("price", "1");
  });

  it("shows how many photos are included and lets the buyer swap them", async () => {
    const props = renderReview();
    expect(screen.getByText("3 of 3 photos included.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Photo 4: not included" }));
    expect(props.onTogglePhoto).toHaveBeenCalledWith(PHOTOS[3]);
  });

  it("accepts a category outside the trained list and notes how the price is compared", () => {
    const odd = editField(draftFromListing(sampleListing()), "category", "Aquarium supplies");
    renderReview({}, odd);
    expect(screen.getByLabelText("Category")).toHaveValue("Aquarium supplies");
    expect(screen.getByText(UNSEEN_CATEGORY_NOTE)).toBeInTheDocument();
  });

  it("treats missing seller details as unknown, not as a blocker", () => {
    renderReview();
    expect(screen.getByText(/Missing seller details are treated as unknown, not as suspicious/)).toBeInTheDocument();
    expect(within(fieldOf("Rating out of 5")).getByText("Not found. Treated as unknown, not as suspicious.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check listing" })).toBeEnabled();
  });

  it("explains what is missing instead of failing silently", () => {
    renderReview({}, draftFromListing(sampleListing({ price: { status: "not_found", value: null } })));
    expect(screen.getByRole("button", { name: "Check listing" })).toBeDisabled();
    expect(screen.getByText(/To continue, add or fix a valid price/)).toBeInTheDocument();
  });

  it("blocks a description over the limit with a clear message (Review Focus 3)", () => {
    const long = draftFromListing(sampleListing({ description: { status: "captured", value: "d".repeat(6000) } }));
    renderReview({}, long);
    expect(screen.getByText("Use 5000 characters or fewer.")).toBeInTheDocument();
    expect(screen.getByText("6000/5000")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check listing" })).toBeDisabled();
  });

  it("shows an error the server returned next to its field", () => {
    renderReview({ fieldErrors: { description: "Chinese-dominant listings are outside this prototype's supported language scope." } });
    expect(within(fieldOf("Description")).getByText(/outside this prototype's supported language scope/)).toBeInTheDocument();
  });

  it("shows the retention notice beside the submit button, in the same group", () => {
    renderReview();
    const bar = screen.getByRole("button", { name: "Check listing" }).closest(".submit-bar") as HTMLElement;
    expect(within(bar).getByText(/Raw uploaded text is scrubbed before storage/)).toBeInTheDocument();
  });

  it("submits once when the draft is valid", async () => {
    const props = renderReview();
    await userEvent.click(screen.getByRole("button", { name: "Check listing" }));
    expect(props.onSubmit).toHaveBeenCalledTimes(1);
  });

  it("disables the button while a check is running", () => {
    renderReview({ submitting: true });
    expect(screen.getByRole("button", { name: "Checking…" })).toBeDisabled();
  });

  it("shows a notice above the form", () => {
    renderReview({ notice: "Seller details added. Check the listing again to include them." });
    expect(screen.getByText("Seller details added. Check the listing again to include them.")).toBeInTheDocument();
  });

  it("requires at least one photo", () => {
    const noPhotos = togglePhoto(togglePhoto(togglePhoto(draftFromListing(sampleListing()), PHOTOS[0]), PHOTOS[1]), PHOTOS[2]);
    renderReview({}, noPhotos);
    expect(screen.getByText("Select at least one photo.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check listing" })).toBeDisabled();
  });
});

describe("CheckingView", () => {
  it("lists the five stages with no percentages", () => {
    render(<CheckingView stage="textual" slow={false} onCancel={vi.fn()} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("says so honestly when the check is slow", () => {
    render(<CheckingView stage="visual" slow={true} onCancel={vi.fn()} />);
    expect(screen.getByText("This is taking longer than usual. The current stage is still running.")).toBeInTheDocument();
  });

  it("can be cancelled", async () => {
    const onCancel = vi.fn();
    render(<CheckingView stage="visual" slow={false} onCancel={onCancel} />);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});

describe("ResultView", () => {
  /** Renders the result view with spies. */
  function renderResult(overrides: Partial<Parameters<typeof ResultView>[0]> = {}) {
    const props = { result: sampleResult(), feedback: "idle" as const, notice: null, onSeeFull: vi.fn(), onFeedback: vi.fn(), onCheckAnother: vi.fn(), ...overrides };
    render(<ResultView {...props} />);
    return props;
  }

  it("keeps the disclaimer inside the score region and shows the stub warning", () => {
    renderResult();
    const region = screen.getByRole("region", { name: "Risk score 42 out of 100, moderate" });
    expect(within(region).getByText("Decision support only. Verify the seller independently before paying.")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Development stub");
  });

  it("shows only the single most protective check; the rest live on the website", () => {
    renderResult();
    expect(screen.getByText("Verify account or bank details independently using the official Semak Mule service.")).toBeInTheDocument();
    expect(screen.queryByText("Compare the price with similar listings on the same marketplace.")).not.toBeInTheDocument();
  });

  it("opens the full explanation, or one signal's section", async () => {
    const props = renderResult();
    await userEvent.click(screen.getByRole("button", { name: "See full explanation" }));
    expect(props.onSeeFull).toHaveBeenLastCalledWith();
    await userEvent.click(screen.getByRole("link", { name: /Visual/ }));
    expect(props.onSeeFull).toHaveBeenLastCalledWith("visual");
  });

  it("names signals that could not be computed as unknown", () => {
    const base = sampleResult();
    const unavailable = { ...base.signal_cards[2], available: false, status_word: "limited information", summary: "Not enough information. Treated as unknown, not as suspicious." };
    renderResult({ result: sampleResult({ signal_cards: [base.signal_cards[0], base.signal_cards[1], unavailable], missing_data_notices: [unavailable.summary] }) });
    expect(screen.getAllByText("Not enough information. Treated as unknown, not as suspicious.").length).toBeGreaterThan(0);
  });

  it("collects feedback with one tap, and then confirms", async () => {
    const props = renderResult();
    await userEvent.click(screen.getByRole("button", { name: "Helpful" }));
    expect(props.onFeedback).toHaveBeenCalledWith("helpful");
  });

  it("confirms saved feedback and removes the choices", () => {
    renderResult({ feedback: "saved" });
    expect(screen.getByText("Feedback saved.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Helpful" })).not.toBeInTheDocument();
  });

  it("lets the buyer check another listing", async () => {
    const props = renderResult();
    await userEvent.click(screen.getByRole("button", { name: "Check another listing" }));
    expect(props.onCheckAnother).toHaveBeenCalledTimes(1);
  });

  it("mentions photos that were left out", () => {
    renderResult({ notice: "1 photo could not be read and was left out of this check." });
    expect(screen.getByText("1 photo could not be read and was left out of this check.")).toBeInTheDocument();
  });
});

describe("FailureView", () => {
  it("shows the message as an alert and offers a retry", async () => {
    const onRetry = vi.fn();
    render(<FailureView kind="unreachable" message="Can't reach the GuardianLens service. Is the local server running?" onRetry={onRetry} onOpenSite={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Can't reach the GuardianLens service");
    expect(screen.getByText(/Start the GuardianLens API on this computer/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("offers the website form as another way in", async () => {
    const onOpenSite = vi.fn();
    render(<FailureView kind="failed" message="x" onRetry={vi.fn()} onOpenSite={onOpenSite} />);
    await userEvent.click(screen.getByRole("button", { name: "Use the website form" }));
    expect(onOpenSite).toHaveBeenCalledWith("/assess");
  });
});
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
npm run test -w extension
```

Expected: `views.test.tsx` fails because the view modules do not exist.

- [ ] **Step 3: Write the idle and failure views**

`extension/entrypoints/sidepanel/views/IdleView.tsx`:

```tsx
// Shown when the panel has nothing to review: before the first click, on pages that are not a
// listing, on blocked pages, and after a failed capture. Each reason gets one plain sentence
// that says what to do next, and two ways out (the website form and the session history).
import type { PageState } from "@/lib/capture/types";
import type { IdleReason } from "@/lib/panel/reducer";

// One sentence per reason the panel can be idle.
const MESSAGES: Record<IdleReason, string> = {
  no_capture: "Open a Mudah.my or Carousell listing, then click the GuardianLens icon.",
  not_listing: "This page is not a single listing. Open one listing, then click the icon.",
  unsupported_site: "GuardianLens works on Mudah.my and Carousell listings only.",
  blocked: "This page could not be read.",
  capture_failed: "The page could not be read. Reload it and click the icon again, or use the website form.",
  no_draft_for_seller:
    "Open the listing first and click the icon. Then open the seller's page and click it again to add seller details.",
};

// More specific sentences for a blocked page. The extension detects these pages and never
// tries to get around them.
const BLOCKED_MESSAGES: Partial<Record<PageState, string>> = {
  captcha: "The site is asking for a security check. Complete it, then click the icon again.",
  access_denied: "The site blocked this page. Reload it, then click the icon again.",
  login_required: "This page needs you to log in. Log in, then click the icon again.",
  listing_unavailable: "This listing is no longer available.",
};

export interface IdleViewProps {
  reason: IdleReason;
  /** For a blocked page: which kind of block, so the message can be specific. */
  pageState?: PageState;
  /** Opens a path on the GuardianLens website in a new tab (for example "/assess"). */
  onOpenSite(path: string): void;
}

/** The "nothing to review yet" view. */
export function IdleView({ reason, pageState, onOpenSite }: IdleViewProps) {
  const message =
    reason === "blocked" ? ((pageState && BLOCKED_MESSAGES[pageState]) ?? MESSAGES.blocked) : MESSAGES[reason];
  return (
    <section className="panel-section" aria-live="polite">
      <p>{message}</p>
      <div className="panel-links">
        <button type="button" className="button button-text" onClick={() => onOpenSite("/assess")}>
          Use the website form
        </button>
        <button type="button" className="button button-text" onClick={() => onOpenSite("/history")}>
          This session
        </button>
      </div>
    </section>
  );
}
```

`extension/entrypoints/sidepanel/views/FailureView.tsx`:

```tsx
// Shown when a check could not be completed. The tone is calm: it says what happened in plain
// words, confirms the buyer's details are kept, and offers one tap to try again (Design Brief:
// Peak-End rule, errors never discard input). No error codes or technical detail are shown.
import type { FailureKind } from "@/lib/panel/errors";

export interface FailureViewProps {
  kind: FailureKind;
  message: string;
  /** Returns to the Review step with everything the buyer entered still in place. */
  onRetry(): void;
  /** Opens a path on the GuardianLens website in a new tab. */
  onOpenSite(path: string): void;
}

/** The failure screen. */
export function FailureView({ kind, message, onRetry, onOpenSite }: FailureViewProps) {
  return (
    <section className="panel-section">
      <h1 className="panel-title">The check could not be completed</h1>
      <p className="error-text" role="alert">{message}</p>
      {kind === "unreachable" && (
        <p className="helper">Start the GuardianLens API on this computer, then try again.</p>
      )}
      <button type="button" className="button button-primary button-full" onClick={onRetry}>
        Try again
      </button>
      <button type="button" className="button button-text" onClick={() => onOpenSite("/assess")}>
        Use the website form
      </button>
    </section>
  );
}
```

- [ ] **Step 4: Write the review view**

`extension/entrypoints/sidepanel/views/ReviewView.tsx`:

```tsx
// The Review step: shows exactly what the capture script read from the page, so the buyer can fix
// anything before it is checked. This step exists because a fraud-risk check on a wrongly read
// listing would be a wrongly informed check.
//
// Rules this view follows:
//   - every field says in WORDS where its value came from: captured, edited, or not found;
//   - missing seller details are "unknown, not suspicious" and never block the check;
//   - the submit button explains what is missing instead of failing silently, and text over the
//     API limits is an error (with a counter), never silently cut;
//   - the retention notice sits in the same group as the submit button.
import { CategoryField, RETENTION_NOTICE } from "@guardianlens/shared";
import {
  LIMITS,
  validateDraft,
  type Draft,
  type DraftErrors,
  type DraftField,
  type DraftFieldKey,
} from "@/lib/panel/draft";

const PLATFORM_NAMES = { carousell: "Carousell", mudah: "Mudah.my" } as const;

// The status line shown under a field. Optional seller fields use the "unknown" wording.
const STATUS_TEXT: Record<DraftField["status"], string> = {
  captured: "Captured",
  edited: "Edited by you",
  not_found: "Not found. Enter it yourself.",
};
const OPTIONAL_NOT_FOUND = "Not found. Treated as unknown, not as suspicious.";

// What a disabled submit button is waiting for, in the words shown above it.
const NEEDS: Record<DraftFieldKey | "photos", string> = {
  title: "the title",
  description: "the description",
  price: "a valid price",
  category: "a category",
  photos: "at least one photo",
  accountAgeDays: "a valid account age",
  rating: "a valid rating",
  reviewCount: "a valid review count",
  activeListingCount: "a valid listing count",
};

// The optional seller inputs, in display order.
const SELLER_INPUTS: ReadonlyArray<{ key: DraftFieldKey; id: string; label: string; inputMode: "numeric" | "decimal" }> = [
  { key: "accountAgeDays", id: "account-age", label: "Account age in days", inputMode: "numeric" },
  { key: "rating", id: "rating", label: "Rating out of 5", inputMode: "decimal" },
  { key: "reviewCount", id: "review-count", label: "Review count", inputMode: "numeric" },
  { key: "activeListingCount", id: "active-listings", label: "Active listing count", inputMode: "numeric" },
];

interface TextFieldProps {
  id: string;
  label: string;
  field: DraftField;
  error?: string;
  multiline?: boolean;
  /** Maximum length: shows a counter that turns into an error when exceeded. */
  limit?: number;
  optional?: boolean;
  inputMode?: "numeric" | "decimal";
  placeholder?: string;
  onChange(value: string): void;
}

/** A labelled text input or textarea with its status line, optional counter, and error. */
function TextField({ id, label, field, error, multiline, limit, optional, inputMode, placeholder, onChange }: TextFieldProps) {
  const statusId = `${id}-status`;
  const countId = `${id}-count`;
  const errorId = `${id}-error`;
  const describedBy = [statusId, limit !== undefined ? countId : null, error ? errorId : null].filter(Boolean).join(" ");
  const length = field.value.trim().length;
  const over = limit !== undefined && length > limit;
  const status = field.status === "not_found" && optional ? OPTIONAL_NOT_FOUND : STATUS_TEXT[field.status];
  const shared = {
    id,
    value: field.value,
    placeholder,
    "aria-invalid": error ? (true as const) : undefined,
    "aria-describedby": describedBy,
  };
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {multiline ? (
        <textarea {...shared} onChange={(event) => onChange(event.target.value)} />
      ) : (
        <input {...shared} inputMode={inputMode} onChange={(event) => onChange(event.target.value)} />
      )}
      <span id={statusId} className={`field-status status-${field.status}`}>{status}</span>
      {limit !== undefined && (
        <span id={countId} className={`char-count ${over ? "error-text" : ""}`.trim()}>{length}/{limit}</span>
      )}
      {error && <span id={errorId} className="error-text">{error}</span>}
    </div>
  );
}

export interface ReviewViewProps {
  draft: Draft;
  /** Errors from the server or from a rejected submit, keyed by field. */
  fieldErrors: DraftErrors;
  /** A one-line message shown above the form (for example "Seller details added..."). */
  notice: string | null;
  /** True while a check is being started or is running; the button is disabled and relabelled. */
  submitting: boolean;
  onEdit(key: DraftFieldKey, value: string): void;
  onTogglePhoto(url: string): void;
  onSubmit(): void;
}

/** The Review view. */
export function ReviewView({ draft, fieldErrors, notice, submitting, onEdit, onTogglePhoto, onSubmit }: ReviewViewProps) {
  // Live validation drives the button and the helper line. An error is shown next to a field when
  // the server returned one, or when the buyer has put something in the field that is not valid.
  // An EMPTY required field is explained next to the button instead of with a red error.
  const live = validateDraft(draft);
  const blockers = Object.keys(live) as Array<DraftFieldKey | "photos">;
  const errorFor = (key: DraftFieldKey): string | undefined =>
    fieldErrors[key] ?? (draft.fields[key].value.trim() !== "" ? live[key] : undefined);
  const selectedCount = draft.photos.filter((photo) => photo.selected).length;
  const photoError = fieldErrors.photos ?? live.photos;

  return (
    <form
      className="panel-form"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (!submitting && blockers.length === 0) onSubmit();
      }}
    >
      <div>
        <h1 className="panel-title">Review what we captured</h1>
        <p className="helper">
          <span className="platform-chip">{PLATFORM_NAMES[draft.platform]}</span>{" "}
          Captured from this page when you clicked.
        </p>
      </div>

      {notice && <p className="notice" role="status">{notice}</p>}

      <section aria-labelledby="photos-heading">
        <h2 id="photos-heading" className="panel-subtitle">Photos</h2>
        <ul className="photo-strip" aria-label="Listing photos">
          {draft.photos.map((photo, index) => (
            <li key={photo.url} className={`photo-item ${photo.selected ? "photo-selected" : ""}`.trim()}>
              <img src={photo.url} alt={`Listing photo ${index + 1}`} />
              <button type="button" className="photo-toggle" onClick={() => onTogglePhoto(photo.url)}>
                {`Photo ${index + 1}: ${photo.selected ? "included" : "not included"}`}
              </button>
            </li>
          ))}
        </ul>
        <p className="helper">{selectedCount} of {LIMITS.photos} photos included.</p>
        {photoError && <p className="error-text">{photoError}</p>}
      </section>

      <TextField id="title" label="Title" field={draft.fields.title} error={errorFor("title")} limit={LIMITS.title} onChange={(value) => onEdit("title", value)} />
      <TextField id="description" label="Description" field={draft.fields.description} error={errorFor("description")} multiline limit={LIMITS.description} onChange={(value) => onEdit("description", value)} />
      <TextField id="price" label="Price" field={draft.fields.price} error={errorFor("price")} inputMode="decimal" placeholder="RM 1,250" onChange={(value) => onEdit("price", value)} />

      <div>
        <CategoryField id="category" value={draft.fields.category.value} error={errorFor("category")} onChange={(value) => onEdit("category", value)} />
        <span className={`field-status status-${draft.fields.category.status}`}>{STATUS_TEXT[draft.fields.category.status]}</span>
      </div>

      <details className="optional">
        <summary>Seller information (optional)</summary>
        <p className="helper">
          Missing seller details are treated as unknown, not as suspicious. To read them from the
          seller&apos;s page, open that page and click the GuardianLens icon there.
        </p>
        {SELLER_INPUTS.map(({ key, id, label, inputMode }) => (
          <TextField key={key} id={id} label={label} field={draft.fields[key]} error={errorFor(key)} optional inputMode={inputMode} onChange={(value) => onEdit(key, value)} />
        ))}
      </details>

      <div className="submit-bar">
        <p className="retention">{RETENTION_NOTICE}</p>
        {blockers.length > 0 && (
          <p className="helper">To continue, add or fix {blockers.map((key) => NEEDS[key]).join(", ")}.</p>
        )}
        <button type="submit" className="button button-primary button-full" disabled={submitting || blockers.length > 0}>
          {submitting ? "Checking…" : "Check listing"}
        </button>
      </div>
    </form>
  );
}
```

- [ ] **Step 5: Write the checking and result views**

`extension/entrypoints/sidepanel/views/CheckingView.tsx`:

```tsx
// Shown while a check runs: the five real pipeline stages, an honest "taking longer" line after a
// while, and a Cancel button. No percentages and no padded delays (Design Brief: Parkinson's Law).
// The region is a polite live region so screen readers hear each stage change.
import { SLOW_WAIT_COPY, StageList, type PipelineStage } from "@guardianlens/shared";

export interface CheckingViewProps {
  /** The stage currently running, or null before the first stage is reported. */
  stage: PipelineStage | null;
  /** True once the check has taken longer than expected. */
  slow: boolean;
  onCancel(): void;
}

/** The "checking" view. */
export function CheckingView({ stage, slow, onCancel }: CheckingViewProps) {
  return (
    <section className="panel-section" aria-live="polite">
      <h1 className="panel-title">Checking the listing</h1>
      <StageList stage={stage} />
      {slow && <p className="helper">{SLOW_WAIT_COPY}</p>}
      <button type="button" className="button button-text" onClick={onCancel}>
        Cancel
      </button>
    </section>
  );
}
```

`extension/entrypoints/sidepanel/views/ResultView.tsx`:

```tsx
// The result summary in the side panel: the score region (score, band, disclaimer together), the
// three signal cards, any limited-information notice, the single most protective check, and the
// way to the full explanation on the website.
//
// Depth lives on the website (Design Brief: progressive disclosure), so the panel shows only ONE
// manual check: the last in the list, which is the most protective one (independent verification
// of the seller). Feedback is a single tap and is asked only AFTER the result is shown.
import {
  DevBanner,
  ScoreRegion,
  SignalCardView,
  type AssessmentResult,
  type FeedbackVerdict,
  type SignalName,
} from "@guardianlens/shared";
import type { FeedbackState } from "@/lib/panel/reducer";

const FEEDBACK_OPTIONS: ReadonlyArray<readonly [FeedbackVerdict, string]> = [
  ["helpful", "Helpful"],
  ["unclear", "Unclear"],
  ["potentially_incorrect", "Potentially incorrect"],
];

export interface ResultViewProps {
  result: AssessmentResult;
  feedback: FeedbackState;
  /** A one-line message such as "1 photo could not be read and was left out of this check.". */
  notice: string | null;
  /** Opens the website's explanation page; pass a signal to jump to that card's section. */
  onSeeFull(signal?: SignalName): void;
  onFeedback(verdict: FeedbackVerdict): void;
  onCheckAnother(): void;
}

/** The result view. */
export function ResultView({ result, feedback, notice, onSeeFull, onFeedback, onCheckAnother }: ResultViewProps) {
  const mostProtectiveCheck = result.suggested_checks[result.suggested_checks.length - 1];
  return (
    <section className="panel-section">
      {result.development_stub && <DevBanner />}
      <h1 className="panel-title">{result.title}</h1>
      {notice && <p className="notice" role="status">{notice}</p>}

      <ScoreRegion score={result.score} band={result.band} disclaimer={result.disclaimer} />

      <div className="signal-grid">
        {result.signal_cards.map((card) => (
          <SignalCardView key={card.signal} card={card} onOpen={() => onSeeFull(card.signal)} />
        ))}
      </div>

      {result.missing_data_notices.length > 0 && (
        <section className="notice">
          <strong>Limited information</strong>
          {result.missing_data_notices.map((text) => (
            <p key={text}>{text}</p>
          ))}
        </section>
      )}

      {mostProtectiveCheck && (
        <section className="card">
          <h2>Before you pay</h2>
          <p>{mostProtectiveCheck}</p>
        </section>
      )}

      <button type="button" className="button button-primary button-full" onClick={() => onSeeFull()}>
        See full explanation
      </button>

      <section className="card">
        <h2>Was this helpful?</h2>
        {feedback === "saved" ? (
          <p className="success-text">Feedback saved.</p>
        ) : (
          <div className="panel-choices">
            {FEEDBACK_OPTIONS.map(([verdict, label]) => (
              <button
                key={verdict}
                type="button"
                className="button button-secondary"
                disabled={feedback === "saving"}
                onClick={() => onFeedback(verdict)}
              >
                {label}
              </button>
            ))}
          </div>
        )}
      </section>

      <button type="button" className="button button-secondary button-full" onClick={onCheckAnother}>
        Check another listing
      </button>
    </section>
  );
}
```

- [ ] **Step 6: Write the panel stylesheet**

`extension/entrypoints/sidepanel/panel.css`:

```css
/* Side panel layout. It adds only what the panel needs on top of the shared styles
   (@guardianlens/shared/styles.css): a single narrow column (about 360 to 420 px), the review
   form's photo strip and status lines, and a few spacing helpers. Colours come from the shared
   design tokens; nothing here introduces a new colour. */

/* One centred column; the browser decides the panel width, the content never exceeds 420px. */
.panel { max-width: 420px; margin: 0 auto; padding: 0 16px 24px; }
.panel-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 14px 0; margin-bottom: 16px; border-bottom: 1px solid var(--color-border); }
.panel-title { margin: 0 0 8px; font-size: 20px; line-height: 1.3; }
.panel-subtitle { margin: 0 0 8px; font-size: 14px; font-weight: 650; }

/* Vertical rhythm for the views. */
.panel-section, .panel-form { display: grid; gap: 14px; }
.panel-links { display: flex; flex-wrap: wrap; gap: 4px; }
.panel-choices { display: grid; gap: 8px; margin-top: 10px; }

/* Marketplace name next to "Captured from this page". Text, not colour, carries the meaning. */
.platform-chip { display: inline-block; border: 1px solid var(--color-border); border-radius: 999px; padding: 1px 10px; font-size: 13px; font-weight: 650; color: var(--color-ink); }

/* The status line under each field: Captured / Edited by you / Not found. */
.field-status { font-size: 13px; color: var(--color-ink-muted); }
.status-not_found { color: var(--color-risk-moderate); font-weight: 600; }

/* Photo picker: two thumbnails per row, each with a full-width toggle button (44px touch target). */
.photo-strip { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin: 0 0 8px; padding: 0; list-style: none; }
.photo-item { overflow: hidden; border: 1px solid var(--color-border); border-radius: 10px; background: var(--color-surface); }
.photo-item img { display: block; width: 100%; height: 110px; object-fit: cover; background: var(--color-surface-alt); }
.photo-selected { border-color: var(--color-primary); box-shadow: 0 0 0 2px rgb(29 78 216 / .15); }
.photo-toggle { width: 100%; min-height: 44px; border: 0; border-top: 1px solid var(--color-border); background: var(--color-surface); color: var(--color-ink); font-weight: 600; cursor: pointer; }
```

- [ ] **Step 7: Run the tests and the typecheck**

```bash
npm run test -w extension
npm run typecheck -w extension
```

Expected: all pass. If a Testing Library query fails because jsdom treats the closed `<details>` content as inaccessible, change that one query to `getByLabelText` (which ignores accessibility state) and keep the test's comment accurate in the same edit.

- [ ] **Step 8: Commit**

```bash
git add extension
git commit -m "feat(extension): add the side panel views and styles"
```

---

### Task 16: Panel wiring, browser end-to-end test, and manual smoke test

**Files:**
- Create: `extension/lib/panel/storage.ts`, `extension/lib/panel/controller.ts`
- Create: `extension/entrypoints/sidepanel/PanelApp.tsx`
- Modify: `extension/entrypoints/sidepanel/App.tsx`, `extension/entrypoints/sidepanel/main.tsx`
- Create: `extension/tests/panel/app.test.tsx`
- Create: `extension/playwright.config.ts`, `extension/tests/e2e/helpers.ts`, `extension/tests/e2e/panel.spec.ts`

**Interfaces:**
- Consumes: everything from Tasks 3 to 15; `readSession`, `writeSession`, `watchSession`, `tokenStore` (Task 7); `CAPTURE_STATE_KEY`, `CaptureJob` (Task 11); `API_BASE_URL`, `SITE_BASE_URL` (Task 7).
- Produces:
  - from `storage.ts`: `interface SavedPanel { draft: Draft | null; lastDoneJobId: number }`, `interface PanelStorage { readCaptureState(): Promise<CaptureJob | null>; watchCaptureState(listener: (job: CaptureJob | null) => void): () => void; readSaved(): Promise<SavedPanel | null>; writeSaved(saved: SavedPanel): Promise<void> }`, `panelStorage: PanelStorage`
  - from `controller.ts`: `interface ControllerDeps { client: GuardianLensClient; photoDeps: PhotoDeps; storage: PanelStorage; openUrl(url: string): void; siteBaseUrl: string; wait?: (ms: number) => Promise<void> }`, `interface PanelActions { edit; togglePhoto; submit; cancel; retry; checkAnother; sendFeedback; openFullExplanation; openSitePath }`, `usePanelController(deps: ControllerDeps): { state: PanelState; actions: PanelActions }`
  - `PanelApp({ deps }: { deps: ControllerDeps })` from `PanelApp.tsx`
  - A working side panel that follows capture to result and hands off to the website.

- [ ] **Step 1: Write the failing app test**

`extension/tests/panel/app.test.tsx`:

```tsx
// Pins the whole side panel working together, with a fake API client, fake photo downloads, and a
// fake capture store, so no browser or server is needed. These are the journeys a buyer takes:
//   - capture arrives -> Review -> Check listing -> result, with ONE submission even when the
//     button is pressed twice (Review Focus 5);
//   - the server rejects the description (unsupported language): the buyer stays in Review with
//     every typed value kept and the error next to the field;
//   - the service is unreachable: a calm failure screen, and "Try again" returns with the draft intact;
//   - "See full explanation" opens the website with the session handoff in the URL fragment;
//   - a draft saved earlier comes back when the panel is reopened.
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GuardianLensApiError } from "@guardianlens/shared";
import { describe, expect, it, vi } from "vitest";
import { PanelApp } from "@/entrypoints/sidepanel/PanelApp";
import type { CaptureJob } from "@/lib/capture/runner";
import type { ControllerDeps } from "@/lib/panel/controller";
import { draftFromListing } from "@/lib/panel/draft";
import type { PanelStorage, SavedPanel } from "@/lib/panel/storage";
import { sampleListing, sampleResult } from "../helpers/samples";

const SITE = "http://localhost:3000";

/** A finished listing capture, as the service worker would store it. */
const listingJob = (id = 10): CaptureJob => ({ id, tabId: 1, status: "done", result: { kind: "listing", listing: sampleListing() } });

/** A fake capture store: `emit` pushes a job to the panel as if the service worker wrote it. */
function fakeStorage(saved: SavedPanel | null = null) {
  const listeners: Array<(job: CaptureJob | null) => void> = [];
  const storage: PanelStorage = {
    readCaptureState: async () => null,
    watchCaptureState: (listener) => {
      listeners.push(listener);
      return () => listeners.splice(listeners.indexOf(listener), 1);
    },
    readSaved: async () => saved,
    writeSaved: vi.fn(async () => undefined),
  };
  return { storage, emit: (job: CaptureJob) => act(async () => listeners.forEach((listener) => listener(job))) };
}

/** Fake dependencies: a client that succeeds by default, instant waits, and tiny photo downloads. */
function fakeDeps(storage: PanelStorage) {
  const client = {
    ensureSession: vi.fn(async () => undefined),
    submit: vi.fn(async (_form: FormData) => ({ assessment_id: "a1" })),
    getStatus: vi.fn(async () => ({ status: "complete" as const, stage: null, message: null })),
    getResult: vi.fn(async () => sampleResult()),
    cancel: vi.fn(async () => undefined),
    sendFeedback: vi.fn(async () => undefined),
    getHistory: vi.fn(async () => []),
    claimSession: vi.fn(async () => undefined),
    getToken: vi.fn(async () => "tok-123"),
  };
  const openUrl = vi.fn();
  const deps: ControllerDeps = {
    client,
    photoDeps: {
      fetchBlob: async () => new Blob([new Uint8Array(1000)], { type: "image/jpeg" }),
      encodeJpeg: async () => new Blob([new Uint8Array(1000)], { type: "image/jpeg" }),
    },
    storage,
    openUrl,
    siteBaseUrl: SITE,
    wait: async () => undefined,
  };
  return { deps, client, openUrl };
}

describe("PanelApp", () => {
  it("starts with the idle message", async () => {
    const { storage } = fakeStorage();
    render(<PanelApp deps={fakeDeps(storage).deps} />);
    expect(await screen.findByText("Open a Mudah.my or Carousell listing, then click the GuardianLens icon.")).toBeInTheDocument();
  });

  it("goes from capture to result and submits only once when the button is pressed twice", async () => {
    const { storage, emit } = fakeStorage();
    const { deps, client } = fakeDeps(storage);
    render(<PanelApp deps={deps} />);
    await emit(listingJob());
    await screen.findByText("Review what we captured");

    await userEvent.dblClick(screen.getByRole("button", { name: "Check listing" }));

    const region = await screen.findByRole("region", { name: "Risk score 42 out of 100, moderate" });
    expect(within(region).getByText(/Decision support only/)).toBeInTheDocument();
    expect(client.submit).toHaveBeenCalledTimes(1);
    const form = client.submit.mock.calls[0][0] as FormData;
    expect(form.get("source")).toBe("extension");
  });

  it("keeps every typed value and shows the server's error next to the description", async () => {
    const { storage, emit } = fakeStorage();
    const { deps, client } = fakeDeps(storage);
    client.submit.mockRejectedValueOnce(
      new GuardianLensApiError(422, { error: { code: "unsupported_language", message: "Chinese-dominant listings are outside this prototype's supported language scope.", field: "description" } }),
    );
    render(<PanelApp deps={deps} />);
    await emit(listingJob());
    await screen.findByText("Review what we captured");
    await userEvent.clear(screen.getByLabelText("Title"));
    await userEvent.type(screen.getByLabelText("Title"), "My edited title");

    await userEvent.click(screen.getByRole("button", { name: "Check listing" }));

    expect(await screen.findByText(/outside this prototype's supported language scope/)).toBeInTheDocument();
    expect(screen.getByLabelText("Title")).toHaveValue("My edited title");
    expect(screen.getByLabelText("Description")).toHaveValue("Original unit. COD available.");
  });

  it("shows a calm failure when the service is unreachable, and Try again keeps the draft", async () => {
    const { storage, emit } = fakeStorage();
    const { deps, client } = fakeDeps(storage);
    client.submit.mockRejectedValueOnce(new GuardianLensApiError(0, { error: { code: "network_unreachable", message: "x", field: null } }));
    render(<PanelApp deps={deps} />);
    await emit(listingJob());
    await screen.findByText("Review what we captured");
    await userEvent.click(screen.getByRole("button", { name: "Check listing" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Is the local server running?");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Review what we captured")).toBeInTheDocument();
    expect(screen.getByLabelText("Title")).toHaveValue("Used laptop in good condition");
  });

  it("opens the full explanation on the website with the session in the URL fragment", async () => {
    const { storage, emit } = fakeStorage();
    const { deps, openUrl } = fakeDeps(storage);
    render(<PanelApp deps={deps} />);
    await emit(listingJob());
    await userEvent.click(await screen.findByRole("button", { name: "Check listing" }));
    await userEvent.click(await screen.findByRole("button", { name: "See full explanation" }));
    // The URL is built after the client returns the session token, so wait for the call.
    await waitFor(() => expect(openUrl).toHaveBeenLastCalledWith(`${SITE}/assess/a1/explanation#st=tok-123`));
  });

  it("jumps to a signal's section when its card is opened", async () => {
    const { storage, emit } = fakeStorage();
    const { deps, openUrl } = fakeDeps(storage);
    render(<PanelApp deps={deps} />);
    await emit(listingJob());
    await userEvent.click(await screen.findByRole("button", { name: "Check listing" }));
    await userEvent.click(await screen.findByRole("link", { name: /Visual/ }));
    await waitFor(() =>
      expect(openUrl).toHaveBeenLastCalledWith(`${SITE}/assess/a1/explanation#st=tok-123&signal=visual`),
    );
  });

  it("restores a saved draft when the panel is reopened", async () => {
    const draft = draftFromListing(sampleListing({ title: { status: "captured", value: "Saved earlier" } }));
    const { storage } = fakeStorage({ draft, lastDoneJobId: 10 });
    render(<PanelApp deps={fakeDeps(storage).deps} />);
    expect(await screen.findByText("Review what we captured")).toBeInTheDocument();
    expect(screen.getByLabelText("Title")).toHaveValue("Saved earlier");
  });
});
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
npm run test -w extension
```

Expected: `app.test.tsx` fails because `PanelApp`, `controller`, and `storage` do not exist.

- [ ] **Step 3: Write the panel storage adapter**

`extension/lib/panel/storage.ts`:

```ts
// What the side panel remembers between openings, and how it hears about new captures.
//
// Two things are stored in session storage (cleared when the browser closes):
//   - the capture job the service worker wrote (the panel watches it);
//   - the buyer's unsent draft plus the id of the newest capture already applied, so reopening the
//     panel brings the draft back without letting an old capture overwrite newer edits.
// Defined as an interface so the controller can be tested with an in-memory fake.
import { CAPTURE_STATE_KEY, type CaptureJob } from "../capture/runner";
import { readSession, watchSession, writeSession } from "../storage";
import type { Draft } from "./draft";

/** The panel state worth keeping across openings. */
export interface SavedPanel {
  draft: Draft | null;
  lastDoneJobId: number;
}

/** The panel's view of storage. */
export interface PanelStorage {
  /** The newest capture job the service worker wrote, or null. */
  readCaptureState(): Promise<CaptureJob | null>;
  /** Calls the listener for every new capture job. Returns an unsubscribe function. */
  watchCaptureState(listener: (job: CaptureJob | null) => void): () => void;
  readSaved(): Promise<SavedPanel | null>;
  writeSaved(saved: SavedPanel): Promise<void>;
}

const SAVED_KEY = "panelSaved";

/** The real storage, backed by chrome.storage.session. */
export const panelStorage: PanelStorage = {
  readCaptureState: () => readSession<CaptureJob>(CAPTURE_STATE_KEY),
  watchCaptureState: (listener) => watchSession<CaptureJob>(CAPTURE_STATE_KEY, listener),
  readSaved: () => readSession<SavedPanel>(SAVED_KEY),
  writeSaved: (saved) => writeSession(SAVED_KEY, saved),
};
```

- [ ] **Step 4: Write the controller hook**

`extension/lib/panel/controller.ts`:

```ts
// The side panel's controller: connects the pure state machine (reducer.ts) to the outside world.
// It owns every side effect of the panel: reading and saving the draft, listening for captures,
// running a check, cancelling, sending feedback, and opening the website.
//
// Two safety properties live here:
//   - the saved draft is never overwritten by the empty initial state: saving is switched on only
//     after the restore step has finished;
//   - a check is started at most once per "submit": the reducer only sets `submitting` for a valid
//     draft in the Review view, and `running` makes sure the effect cannot start a second run.
import { useEffect, useReducer, useRef } from "react";
import {
  buildHandoffUrl,
  type FeedbackVerdict,
  type GuardianLensClient,
  type SignalName,
} from "@guardianlens/shared";
import { runCheck } from "./check";
import type { DraftFieldKey } from "./draft";
import { preparePhotos, type PhotoDeps } from "./photos";
import { initialPanelState, panelReducer, type PanelState } from "./reducer";
import type { PanelStorage } from "./storage";

/** Everything the controller needs from outside, so tests can supply fakes. */
export interface ControllerDeps {
  client: GuardianLensClient;
  photoDeps: PhotoDeps;
  storage: PanelStorage;
  /** Opens a URL in a new browser tab. */
  openUrl(url: string): void;
  /** The website's origin, for "See full explanation", "This session", and the manual form. */
  siteBaseUrl: string;
  /** Replaceable delay between status polls; defaults to a real timer. */
  wait?: (ms: number) => Promise<void>;
}

/** What the views can do. */
export interface PanelActions {
  edit(key: DraftFieldKey, value: string): void;
  togglePhoto(url: string): void;
  submit(): void;
  cancel(): void;
  retry(): void;
  checkAnother(): void;
  sendFeedback(verdict: FeedbackVerdict): Promise<void>;
  openFullExplanation(signal?: SignalName): Promise<void>;
  openSitePath(path: string): void;
}

const realWait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * The panel's state and actions.
 * @param deps Stable dependencies (create them once, outside the component).
 */
export function usePanelController(deps: ControllerDeps): { state: PanelState; actions: PanelActions } {
  const [state, dispatch] = useReducer(panelReducer, initialPanelState);
  const cancelled = useRef(false);
  const running = useRef(false);
  const restored = useRef(false);

  // On open: restore the saved draft, apply the newest capture if it is newer than the draft,
  // then follow new captures as the service worker writes them.
  useEffect(() => {
    let active = true;
    void (async () => {
      const saved = await deps.storage.readSaved();
      if (!active) return;
      // Switch saving on BEFORE dispatching, so the restored state is saved back unchanged.
      restored.current = true;
      if (saved) dispatch({ type: "state_restored", draft: saved.draft, lastDoneJobId: saved.lastDoneJobId });
      const job = await deps.storage.readCaptureState();
      if (active && job) dispatch({ type: "capture_finished", job });
    })();
    const stop = deps.storage.watchCaptureState((job) => {
      if (job) dispatch({ type: "capture_finished", job });
    });
    return () => {
      active = false;
      stop();
    };
  }, [deps]);

  // Keep the draft (and which capture it came from) so reopening the panel brings it back.
  useEffect(() => {
    if (!restored.current) return;
    void deps.storage.writeSaved({ draft: state.draft, lastDoneJobId: state.lastDoneJobId });
  }, [deps, state.draft, state.lastDoneJobId]);

  // Stop polling if the panel is closed mid-check.
  useEffect(() => {
    return () => {
      cancelled.current = true;
    };
  }, []);

  // Start a check when the reducer says one was requested.
  useEffect(() => {
    if (!state.submitting || running.current || state.draft === null) return;
    running.current = true;
    cancelled.current = false;
    void runCheck(state.draft, {
      client: deps.client,
      preparePhotos: (urls) => preparePhotos(urls, deps.photoDeps),
      wait: deps.wait ?? realWait,
      onAccepted: (assessmentId) => dispatch({ type: "submit_accepted", assessmentId }),
      onStage: (stage) => dispatch({ type: "stage_changed", stage }),
      onSlow: () => dispatch({ type: "slow_wait" }),
      isCancelled: () => cancelled.current,
    })
      .then((outcome) => {
        if (outcome.status === "done") {
          dispatch({ type: "check_finished", result: outcome.result, skippedPhotos: outcome.skippedPhotos });
        } else if (outcome.status === "error") {
          dispatch({ type: "check_failed", error: outcome.error });
        }
        // "cancelled" needs no action: cancel() already returned the panel to Review.
      })
      .finally(() => {
        running.current = false;
      });
  }, [deps, state.submitting, state.draft]);

  const actions: PanelActions = {
    edit: (key, value) => dispatch({ type: "edit_field", key, value }),
    togglePhoto: (url) => dispatch({ type: "toggle_photo", url }),
    submit: () => dispatch({ type: "submit_requested" }),
    cancel: () => {
      cancelled.current = true;
      if (state.view.name === "checking") {
        // Tell the server it can stop; the buyer is already back in Review whatever happens.
        void deps.client.cancel(state.view.assessmentId).catch(() => undefined);
      }
      dispatch({ type: "cancelled" });
    },
    retry: () => dispatch({ type: "back_to_review" }),
    checkAnother: () => dispatch({ type: "check_another" }),
    sendFeedback: async (verdict) => {
      if (state.view.name !== "result") return;
      dispatch({ type: "feedback_changed", state: "saving" });
      try {
        await deps.client.sendFeedback(state.view.result.assessment_id, { verdict, comment: null });
        dispatch({ type: "feedback_changed", state: "saved" });
      } catch {
        // Feedback is optional: on a failure the choices simply come back for another try.
        dispatch({ type: "feedback_changed", state: "idle" });
      }
    },
    openFullExplanation: async (signal) => {
      if (state.view.name !== "result") return;
      const assessmentId = state.view.result.assessment_id;
      const token = await deps.client.getToken();
      // The token travels in the URL fragment so it never reaches a server log; the website
      // removes it from the address bar and claims the session (shared/claim.ts).
      deps.openUrl(
        token
          ? buildHandoffUrl(deps.siteBaseUrl, assessmentId, token, signal)
          : `${deps.siteBaseUrl.replace(/\/+$/, "")}/assess/${assessmentId}/explanation`,
      );
    },
    openSitePath: (path) => deps.openUrl(`${deps.siteBaseUrl.replace(/\/+$/, "")}${path}`),
  };

  return { state, actions };
}
```

- [ ] **Step 5: Write the panel component and the entry**

`extension/entrypoints/sidepanel/PanelApp.tsx`:

```tsx
// The side panel UI, driven entirely by `deps` so tests can run it with fakes and the real panel
// can run it with the real API client. It picks the view for the controller's state and wires
// each view's callbacks to the controller's actions.
import { usePanelController, type ControllerDeps } from "@/lib/panel/controller";
import { CheckingView } from "./views/CheckingView";
import { FailureView } from "./views/FailureView";
import { IdleView } from "./views/IdleView";
import { ResultView } from "./views/ResultView";
import { ReviewView } from "./views/ReviewView";

/** The side panel. `deps` must be a stable object (created once outside the component). */
export function PanelApp({ deps }: { deps: ControllerDeps }) {
  const { state, actions } = usePanelController(deps);
  const { view } = state;

  return (
    <div className="panel">
      <header className="panel-header">
        <span className="wordmark">
          <span className="lens-mark" aria-hidden="true" />
          GuardianLens
        </span>
      </header>
      <main>
        {view.name === "idle" && (
          <IdleView reason={view.reason} pageState={view.pageState} onOpenSite={actions.openSitePath} />
        )}
        {view.name === "capturing" && <p className="helper" role="status">Reading this page{"…"}</p>}
        {view.name === "review" && state.draft && (
          <ReviewView
            draft={state.draft}
            fieldErrors={state.fieldErrors}
            notice={state.notice}
            submitting={state.submitting}
            onEdit={actions.edit}
            onTogglePhoto={actions.togglePhoto}
            onSubmit={actions.submit}
          />
        )}
        {view.name === "checking" && <CheckingView stage={view.stage} slow={view.slow} onCancel={actions.cancel} />}
        {view.name === "result" && (
          <ResultView
            result={view.result}
            feedback={view.feedback}
            notice={state.notice}
            onSeeFull={(signal) => void actions.openFullExplanation(signal)}
            onFeedback={(verdict) => void actions.sendFeedback(verdict)}
            onCheckAnother={actions.checkAnother}
          />
        )}
        {view.name === "failure" && (
          <FailureView kind={view.kind} message={view.message} onRetry={actions.retry} onOpenSite={actions.openSitePath} />
        )}
      </main>
    </div>
  );
}
```

Replace the whole of `extension/entrypoints/sidepanel/App.tsx` with:

```tsx
// Side panel root: builds the REAL dependencies once (the API client with the header session
// transport, real photo downloads, session storage, and the tab opener) and renders the panel.
// Tests render PanelApp with fakes instead, so nothing here needs a browser to be verified.
import { createClient } from "@guardianlens/shared";
import { API_BASE_URL, SITE_BASE_URL } from "@/lib/config";
import type { ControllerDeps } from "@/lib/panel/controller";
import { browserPhotoDeps } from "@/lib/panel/photos";
import { panelStorage } from "@/lib/panel/storage";
import { tokenStore } from "@/lib/storage";
import { PanelApp } from "./PanelApp";

// Created once at module load, so the object stays the same for the life of the panel and the
// controller's effects do not restart.
const deps: ControllerDeps = {
  client: createClient({ baseUrl: API_BASE_URL, transport: { kind: "header", store: tokenStore } }),
  photoDeps: browserPhotoDeps,
  storage: panelStorage,
  openUrl: (url) => void browser.tabs.create({ url }),
  siteBaseUrl: SITE_BASE_URL,
};

/** The side panel's root component. */
export function App() {
  return <PanelApp deps={deps} />;
}
```

Replace the whole of `extension/entrypoints/sidepanel/main.tsx` with:

```tsx
// Side panel entry point: loads the shared design styles, then the panel's own styles, and mounts
// the React app into #root.
import "@guardianlens/shared/styles.css";
import "./panel.css";
import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

- [ ] **Step 6: Run the unit tests and the typecheck**

```bash
npm run test -w extension
npm run typecheck -w extension
```

Expected: all pass. If the double-click test submits twice, the reducer's `submitting` guard is not reaching the effect: check that `usePanelController` starts the check only from the `state.submitting` effect and that `running.current` is set before `runCheck` is called, then fix the code and update the controller's header comment in the same edit.

- [ ] **Step 7: Write the browser end-to-end tests**

`extension/playwright.config.ts`:

```ts
// Playwright settings for the browser end-to-end tests (tests/e2e). They load the BUILT extension
// into Chromium, so run them with `npm run test:e2e`, which builds first. One worker only: each
// test launches its own Chromium with the extension, and extensions need a full profile.
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: { trace: "retain-on-failure" },
});
```

`extension/tests/e2e/helpers.ts`:

```ts
// Helpers for the browser end-to-end tests: launching Chromium with the built extension loaded,
// mocking the GuardianLens API, the website, and the photo CDN (so no server is needed), and
// seeding a capture the way the service worker would.
import { chromium, type BrowserContext, type Page } from "@playwright/test";
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
export async function launchWithExtension(): Promise<{ context: BrowserContext; extensionId: string }> {
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

/** Counters a test can read to check what the mocked API received. */
export interface ApiCalls {
  assess: number;
}

/** Mocks the GuardianLens API on localhost:8000: session, assess, status, result. */
export async function mockApi(context: BrowserContext): Promise<ApiCalls> {
  const calls: ApiCalls = { assess: 0 };
  await context.route("http://localhost:8000/**", async (route) => {
    const { pathname } = new URL(route.request().url());
    const reply = (status: number, body: unknown) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (pathname === "/api/v1/session") return reply(201, { session_token: "e2e-token" });
    if (pathname === "/api/v1/assess") {
      calls.assess += 1;
      return reply(202, { assessment_id: "e2e-1" });
    }
    if (pathname.endsWith("/status")) return reply(200, { status: "complete", stage: null, message: null });
    if (pathname.endsWith("/result")) return reply(200, sampleResult({ assessment_id: "e2e-1" }));
    return reply(404, { error: { code: "not_found", message: "Not found.", field: null } });
  });
  return calls;
}

/** Serves a blank page for the website, so the handoff tab opens without a real server. */
export async function mockSite(context: BrowserContext): Promise<void> {
  await context.route("http://localhost:3000/**", (route) =>
    route.fulfill({ status: 200, contentType: "text/html", body: "<html><body>site</body></html>" }),
  );
}

/** Serves a tiny JPEG for every photo request, or fails them all when `fail` is true. */
export async function mockPhotos(context: BrowserContext, fail = false): Promise<void> {
  await context.route("https://media.karousell.com/**", (route) =>
    fail ? route.abort() : route.fulfill({ status: 200, contentType: "image/jpeg", body: TINY_JPEG }),
  );
}

/** A finished listing capture, as the service worker would store it. */
export function listingJob(): unknown {
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
        description: { status: "captured", value: "Original unit. COD available." },
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
    const chromeApi = (globalThis as unknown as { chrome: { storage: { session: { set(items: object): Promise<void> } } } }).chrome;
    await chromeApi.storage.session.set({ captureState: value });
  }, job);
}
```

`extension/tests/e2e/panel.spec.ts`:

```ts
// End-to-end tests in a real Chromium with the BUILT extension. They open the side panel page
// directly as a tab (Playwright cannot click the toolbar icon) and seed a capture, then drive the
// real UI against a mocked API. What they prove that unit tests cannot: the built manifest and
// permissions let the panel fetch photos and the API, the real storage events reach the panel, and
// the handoff tab opens with the session in the URL fragment.
import { expect, test } from "@playwright/test";
import { launchWithExtension, listingJob, mockApi, mockPhotos, mockSite, seedCapture } from "./helpers";

test("capture to result to website handoff", async () => {
  const { context, extensionId } = await launchWithExtension();
  await mockApi(context);
  await mockPhotos(context);
  await mockSite(context);
  const page = await context.newPage();
  await page.goto(`chrome-extension://${extensionId}/sidepanel.html`);

  await expect(page.getByText("Open a Mudah.my or Carousell listing")).toBeVisible();
  await seedCapture(page, listingJob());
  await expect(page.getByText("Review what we captured")).toBeVisible();
  await page.getByRole("button", { name: "Check listing" }).click();

  const region = page.getByRole("region", { name: "Risk score 42 out of 100, moderate" });
  await expect(region).toBeVisible();
  await expect(region.getByText(/Decision support only/)).toBeVisible();

  const opened = context.waitForEvent("page");
  await page.getByRole("button", { name: "See full explanation" }).click();
  expect((await opened).url()).toBe("http://localhost:3000/assess/e2e-1/explanation#st=e2e-token");
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
```

- [ ] **Step 8: Run the browser tests**

```bash
npx playwright install chromium
npm run test:e2e -w extension
```

Expected: both tests pass. If Chromium cannot load the extension headlessly on this machine, run the same command with `--headed` added to the Playwright invocation (`npx playwright test --headed` from `extension/`), and note the result in the commit message. If a test fails, fix the cause in the production code or the test and update the nearby comments in the same edit.

- [ ] **Step 9: Manual smoke test on live pages**

Start the backend and the website in two terminals:

```bash
.venv/Scripts/python -m uvicorn api.main:app --port 8000
npm run dev -w frontend
```

Rebuild and reload the extension (`npm run build -w extension`, then Reload on `chrome://extensions`). Then:

1. On three live Carousell and three live Mudah.my listings, click the icon. Expected: the panel shows Review with the real title, price, photos, and category. Fix any field the page shows differently, then click Check listing. Expected: the five stages, then a score region with the disclaimer and the development-stub banner.
2. Click a signal card and See full explanation. Expected: a new tab on the website at the same result, with no `#st=` left in the address bar.
3. On a seller page, click the icon. Expected: back in Review with the seller fields filled and the notice "Seller details added. Check the listing again to include them."
4. Stop the API and press Check listing. Expected: the calm failure screen mentioning the local server; Try again returns to Review with everything intact.
5. Open `chrome-extension://<id>/sidepanel.html` in a normal tab, open DevTools device mode, and check the panel at 360 px and 420 px wide: no horizontal scroll, buttons at least 44 px tall, focus ring visible on every control, and the score region readable.
6. Tab through the whole panel with the keyboard only and confirm every control is reachable and labelled.

Write any surprises into `extension/docs/SPIKE_NOTES.md` under a `Smoke test (Task 16)` heading, and turn each real defect into a failing test before fixing it.

- [ ] **Step 10: Commit**

```bash
git add extension
git commit -m "feat(extension): wire the side panel to the API, with unit and browser tests"
```

---

### Task 17: Website adopts the shared components and completes the session handoff

**Files:**
- Create: `frontend/lib/useSessionClaim.ts`, `scripts/dev_handoff_demo.py`
- Modify: `frontend/app/layout.tsx`, `frontend/app/globals.css`, `frontend/app/page.tsx`, `frontend/app/assess/[id]/page.tsx`, `frontend/app/assess/[id]/explanation/page.tsx`, `frontend/app/assess/[id]/processing/page.tsx`
- Delete: `frontend/components/BandChip.tsx`, `frontend/components/DevBanner.tsx`, `frontend/components/SignalCardView.tsx`

**Interfaces:**
- Consumes: `claimSessionFromHash` (Task 3), `DevBanner`, `ScoreRegion`, `SignalCardView`, `StageList`, `SLOW_WAIT_COPY`, `PipelineStage` and the stylesheet (Task 6); `apiFetch` (existing, `frontend/lib/api.ts`); the backend `POST /api/v1/session/claim` (Task 4).
- Produces: `useSessionClaim(): boolean` in `frontend/lib/useSessionClaim.ts` (true once any handoff in the URL has been completed, or when there was none); result and explanation pages that load only after that; a website that renders the shared components and styles; a developer script that plays the extension's part of the handoff.

The website has no automated test runner. The handoff logic itself is covered by the shared package's tests (Task 3); this task is verified by the type check, lint, build, and the manual steps below.

- [ ] **Step 1: Write the session claim hook**

`frontend/lib/useSessionClaim.ts`:

```ts
// Completes the extension-to-website session handoff once per page load, and tells the page when it
// is safe to load data.
//
// When the buyer clicks "See full explanation" in the extension, the website opens at
// ".../explanation#st=<token>". This hook (1) removes the token from the address bar, then
// (2) asks the API to turn it into this browser's session cookie, using the shared
// claimSessionFromHash (shared/src/claim.ts, which also pins the order of those two steps).
// A page must wait for `true` before fetching the result, or the first request would arrive
// without the cookie and be refused.
import { useEffect, useState } from "react";
import { claimSessionFromHash } from "@guardianlens/shared";
import { apiFetch } from "@/lib/api";

// Module-level on purpose. React StrictMode (development only) runs every effect twice; sharing one
// in-flight claim lets the second run wait for the same request, instead of reading an address bar
// that was already cleaned and loading data before the cookie exists.
let pendingClaim: Promise<unknown> | null = null;

/**
 * @returns false while a handoff in the URL is still being completed, then true. It is true almost
 *          immediately when the URL carries no handoff.
 */
export function useSessionClaim(): boolean {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let active = true;
    pendingClaim ??= claimSessionFromHash({
      hash: window.location.hash,
      claim: (token) =>
        apiFetch<void>("/api/v1/session/claim", { method: "POST", body: JSON.stringify({ token }) }),
      // Keeps the current path and query; only the fragment changes, and no history entry is added.
      replaceHash: (hash) =>
        window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}${hash}`),
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
```

- [ ] **Step 2: Load the shared styles and replace the website stylesheet**

Replace the whole of `frontend/app/layout.tsx` with:

```tsx
// Root layout: loads the shared design styles first, then the website's own page styles, and wraps
// every page in the site header. The shared stylesheet holds the design tokens and the styles of the
// shared components (also used by the browser extension's side panel).
import type { Metadata } from "next";
import "@guardianlens/shared/styles.css";
import { Header } from "@/components/Header";
import "./globals.css";

export const metadata: Metadata = {
  title: "GuardianLens",
  description: "Explainable fraud-risk decision support for Malaysian C2C marketplace listings.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <Header />
        {children}
      </body>
    </html>
  );
}
```

Replace the whole of `frontend/app/globals.css` with the following. It keeps only the website's page layout; every rule that moved to `shared/src/styles.css` in Task 6 is deliberately absent, so nothing is defined twice:

```css
/* GuardianLens website styles: PAGE LAYOUT ONLY.

   Design tokens, base elements, form controls, buttons, notices, and the styles of the shared
   components (score region, signal cards, stage list, ...) come from
   @guardianlens/shared/styles.css, which layout.tsx loads first. Only rules that belong to a
   website page live here, so the same component looks identical in the extension's side panel. */

/* ---- Site header ---------------------------------------------------------------------- */
.site-header {
  position: sticky;
  top: 0;
  z-index: 20;
  border-bottom: 1px solid var(--color-border);
  background: rgb(255 255 255 / 0.94);
  backdrop-filter: blur(10px);
}
.header-inner {
  width: min(100% - 32px, 960px);
  min-height: 64px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

/* ---- Page frame (a single centred column) ---------------------------------------------- */
.page { width: min(100% - 32px, 720px); margin: 0 auto; padding: 40px 0 72px; }
.page-wide { width: min(100% - 32px, 1120px); }
.page-title { margin: 0 0 8px; font-size: 28px; line-height: 1.2; }
.page-lead { margin: 0 0 28px; color: var(--color-ink-muted); }

/* ---- Landing page ---------------------------------------------------------------------- */
.hero { padding: 56px 0 36px; }
.hero h1 { max-width: 680px; margin: 0; font-size: clamp(34px, 7vw, 52px); line-height: 1.08; letter-spacing: -.025em; }
.hero p { max-width: 620px; margin: 20px 0 28px; color: var(--color-ink-muted); font-size: 18px; }
.hero-actions { display: flex; flex-wrap: wrap; gap: 12px; }
.explainer-grid { display: grid; gap: 12px; margin: 24px 0 48px; }

/* ---- Manual submission form ------------------------------------------------------------ */
.form-stack { display: grid; gap: 20px; }
.form-section { border: 1px solid var(--color-border); border-radius: var(--radius-card); background: var(--color-surface); padding: 20px; }
.form-section h2 { margin: 0 0 16px; font-size: 20px; }
.field-row { display: grid; gap: 16px; }
.uploader { min-height: 132px; border: 2px dashed #9ca8b7; border-radius: var(--radius-card); display: grid; place-items: center; padding: 20px; text-align: center; background: #fbfcfd; }
.uploader input { border: 0; padding: 8px; }
.file-list { margin: 12px 0 0; padding: 0; list-style: none; display: grid; gap: 8px; }
.file-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; border: 1px solid var(--color-border); border-radius: 8px; padding: 10px 12px; }
.file-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ---- Processing, result, and explanation pages ----------------------------------------- */
.processing-card { text-align: center; }
.action-row { display: grid; gap: 10px; margin-top: 20px; }
.explanation-section { scroll-margin-top: 88px; margin-bottom: 16px; }
.reason-list { margin: 14px 0 0; padding: 0; list-style: none; display: grid; gap: 10px; }
.reason { border-left: 3px solid var(--color-border); padding-left: 12px; }
.reason-raises { border-color: var(--color-risk-high); }
.reason-lowers { border-color: var(--color-risk-low); }
.scope-note { margin-top: 14px; padding: 12px; border-radius: 8px; background: #f5f7fa; color: var(--color-ink-muted); font-size: 14px; }

/* ---- Session history ------------------------------------------------------------------- */
.history-list { display: grid; gap: 10px; }
.history-item { display: grid; grid-template-columns: 1fr auto; gap: 12px; align-items: center; border: 1px solid var(--color-border); border-radius: 12px; background: var(--color-surface); padding: 16px; color: var(--color-ink); }
.history-item:hover { text-decoration: none; border-color: #9eb5df; }
.history-title { font-weight: 650; }
.history-meta { color: var(--color-ink-muted); font-size: 14px; }
.history-score { font-size: 24px; font-weight: 750; font-variant-numeric: tabular-nums; }
.empty-state { text-align: center; padding: 40px 20px; }

/* ---- Admin (the one surface where density beats simplicity) ---------------------------- */
.admin-grid { display: grid; gap: 16px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { padding: 10px 12px; border-bottom: 1px solid var(--color-border); text-align: left; vertical-align: top; }
th { color: var(--color-ink-muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
.code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }

.footer-note { margin-top: 36px; color: var(--color-ink-muted); font-size: 14px; }

/* ---- Responsive ------------------------------------------------------------------------ */
@media (min-width: 680px) {
  .explainer-grid { grid-template-columns: repeat(3, 1fr); }
  .field-row { grid-template-columns: 1fr 1fr; }
  .action-row { grid-template-columns: 1fr 1fr; }
  .admin-grid { grid-template-columns: 260px 1fr; }
}

@media (max-width: 480px) {
  .page { padding-top: 28px; }
  .hero { padding-top: 36px; }
  .hero-actions .button { width: 100%; }
  .site-header nav a { font-size: 14px; }
  .form-section { padding: 16px; }
}
```

- [ ] **Step 3: Switch the pages to the shared components**

Delete the old local components (the shared versions replace them):

```bash
git rm frontend/components/BandChip.tsx frontend/components/DevBanner.tsx frontend/components/SignalCardView.tsx
```

In `frontend/app/page.tsx`, replace the line `import { DevBanner } from "@/components/DevBanner";` with `import { DevBanner } from "@guardianlens/shared";` (Task 18 rewrites this page; this keeps the build working in between).

Replace the whole of `frontend/app/assess/[id]/page.tsx` with:

```tsx
// Assessment result page: the detail surface for a finished check, whether it was started from the
// browser extension or from the manual form.
//
// It first completes any extension handoff in the URL (useSessionClaim), so a check made in the
// extension can be opened here without a login, and only then loads the result. The score, band,
// and disclaimer render together in the shared ScoreRegion, and the three signal cards link to
// their sections of the explanation page.
"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { DevBanner, ScoreRegion, SignalCardView } from "@guardianlens/shared";
import { apiFetch } from "@/lib/api";
import type { AssessmentResult } from "@/lib/types";
import { useSessionClaim } from "@/lib/useSessionClaim";

// The three feedback choices a buyer can give (value sent to the API, label shown).
const feedbackOptions = [
  ["helpful", "Helpful"],
  ["unclear", "Unclear"],
  ["potentially_incorrect", "Potentially incorrect"],
] as const;

export default function ResultPage() {
  const params = useParams<{ id: string }>();
  const claimed = useSessionClaim();
  const [result, setResult] = useState<AssessmentResult | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showFeedback, setShowFeedback] = useState(false);
  const [verdict, setVerdict] = useState<string>("");
  const [comment, setComment] = useState("");
  const [feedbackState, setFeedbackState] = useState<"idle" | "saving" | "saved">("idle");

  // Load the result once any session handoff has finished.
  useEffect(() => {
    if (!claimed) return;
    apiFetch<AssessmentResult>(`/api/v1/assess/${params.id}/result`)
      .then(setResult)
      .catch(() => setLoadError("The assessment result could not be loaded for this browser session."));
  }, [params.id, claimed]);

  async function submitFeedback(event: FormEvent) {
    event.preventDefault();
    if (!verdict) return;
    setFeedbackState("saving");
    await apiFetch<void>(`/api/v1/assess/${params.id}/feedback`, {
      method: "POST",
      body: JSON.stringify({ verdict, comment: comment || null }),
    });
    setFeedbackState("saved");
  }

  if (loadError) {
    return (
      <main className="page">
        <div className="card">
          <h1 className="page-title">Result unavailable</h1>
          <p className="error-text">{loadError}</p>
          <Link className="button button-primary" href="/assess">Check another listing</Link>
        </div>
      </main>
    );
  }
  if (!result) return <main className="page"><div className="loading">Loading result…</div></main>;

  return (
    <main className="page">
      {result.development_stub && <DevBanner />}
      <p className="eyebrow">Assessment result</p>
      <h1 className="page-title">{result.title}</h1>
      <p className="page-lead">Completed in {result.total_latency_ms} ms using {result.model_bundle_label}.</p>

      <ScoreRegion score={result.score} band={result.band} disclaimer={result.disclaimer} />

      <section className="signal-grid" aria-label="Signal summaries">
        {result.signal_cards.map((card) => (
          <SignalCardView
            card={card}
            href={`/assess/${result.assessment_id}/explanation#${card.signal}`}
            LinkComponent={Link}
            key={card.signal}
          />
        ))}
      </section>

      {result.missing_data_notices.length > 0 && (
        <section className="notice">
          <strong>Limited information</strong>
          {result.missing_data_notices.map((notice) => <p key={notice}>{notice}</p>)}
        </section>
      )}

      <section className="card">
        <h2>Checks to do before paying</h2>
        <ol className="check-list">
          {result.suggested_checks.map((check) => <li key={check}>{check}</li>)}
        </ol>
      </section>

      <section className="card" style={{ marginTop: 16 }}>
        <h2>Was this result helpful?</h2>
        {!showFeedback && (
          <button className="button button-secondary" onClick={() => setShowFeedback(true)}>Give feedback</button>
        )}
        {showFeedback && feedbackState !== "saved" && (
          <form onSubmit={submitFeedback}>
            <div className="feedback-options">
              {feedbackOptions.map(([value, label]) => (
                <label className="option-row" key={value}>
                  <input type="radio" name="verdict" value={value} checked={verdict === value} onChange={() => setVerdict(value)} />
                  {label}
                </label>
              ))}
            </div>
            <div className="field" style={{ marginTop: 14 }}>
              <label htmlFor="feedback-comment">Optional comment</label>
              <textarea id="feedback-comment" maxLength={1000} value={comment} onChange={(event) => setComment(event.target.value)} />
              <span className="helper">Do not include names, phone numbers, account details, or other personal information.</span>
            </div>
            <button className="button button-primary" disabled={!verdict || feedbackState === "saving"}>
              {feedbackState === "saving" ? "Saving…" : "Submit feedback"}
            </button>
          </form>
        )}
        {feedbackState === "saved" && <p className="success-text">Feedback saved.</p>}
      </section>

      <div className="action-row">
        <Link className="button button-primary" href="/assess">Check another listing</Link>
        <Link className="button button-secondary" href="/history">This session</Link>
      </div>
    </main>
  );
}
```

Replace the whole of `frontend/app/assess/[id]/explanation/page.tsx` with:

```tsx
// Explanation page: the depth behind a result, grouped by signal, plus the full list of manual
// checks. The browser extension's side panel links here ("See full explanation"), optionally to
// one signal's section (#visual, #textual, #behavioural).
//
// Like the result page it first completes any extension handoff in the URL, then loads the result.
// Because the content loads after the page opens, the browser's own jump to "#visual" would find
// nothing; the second effect scrolls to that section once the content is on screen.
"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { DevBanner } from "@guardianlens/shared";
import { apiFetch } from "@/lib/api";
import type { AssessmentResult } from "@/lib/types";
import { useSessionClaim } from "@/lib/useSessionClaim";

// Section headings, one per signal.
const labels = { visual: "Visual signal", textual: "Textual signal", behavioural: "Behavioural signal" };

export default function ExplanationPage() {
  const params = useParams<{ id: string }>();
  const claimed = useSessionClaim();
  const [result, setResult] = useState<AssessmentResult | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Load the result once any session handoff has finished.
  useEffect(() => {
    if (!claimed) return;
    apiFetch<AssessmentResult>(`/api/v1/assess/${params.id}/result`)
      .then(setResult)
      .catch(() => setLoadError("The explanation could not be loaded for this browser session."));
  }, [params.id, claimed]);

  // Scroll to the section named in the address (for example #visual) once the content exists.
  useEffect(() => {
    if (!result) return;
    const target = window.location.hash.slice(1);
    if (target) document.getElementById(target)?.scrollIntoView();
  }, [result]);

  if (loadError) return <main className="page"><p className="error-text">{loadError}</p></main>;
  if (!result) return <main className="page"><div className="loading">Loading explanation…</div></main>;

  return (
    <main className="page">
      {result.development_stub && <DevBanner />}
      <p className="eyebrow">Explanation details</p>
      <h1 className="page-title">Why this result was shown</h1>
      <p className="page-lead">Reasons are grouped by signal. Missing fields stay unknown.</p>

      {result.signal_cards.map((card) => (
        <section className="card explanation-section" id={card.signal} key={card.signal}>
          <h2>{labels[card.signal]}</h2>
          <p><strong>{card.status_word}</strong>. {card.summary}</p>
          {card.reasons.length > 0 ? (
            <ul className="reason-list">
              {card.reasons.map((reason) => (
                <li className={`reason reason-${reason.direction}`} key={`${reason.feature_key}-${reason.rank}`}>
                  {reason.display_text}
                </li>
              ))}
            </ul>
          ) : <p className="helper">No detailed reason is available for this signal.</p>}
          {card.scope_note && <p className="scope-note">{card.scope_note}</p>}
        </section>
      ))}

      <section className="card">
        <h2>Manual checks</h2>
        <ol className="check-list">{result.suggested_checks.map((check) => <li key={check}>{check}</li>)}</ol>
        <p className="disclaimer">{result.disclaimer}</p>
      </section>

      <Link className="button button-secondary button-full" href={`/assess/${params.id}`}>Back to result</Link>
    </main>
  );
}
```

Replace the whole of `frontend/app/assess/[id]/processing/page.tsx` with:

```tsx
// Processing page for the website's manual form: shows the five pipeline stages while the check
// runs, polling the status endpoint until the result is ready, then opens the result page. (The
// browser extension shows the same stages inside its side panel.) Stage labels, the stage list, and
// the "taking longer than usual" sentence come from @guardianlens/shared so both surfaces match.
"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { SLOW_WAIT_COPY, StageList, type PipelineStage } from "@guardianlens/shared";
import { apiFetch } from "@/lib/api";

export default function ProcessingPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [stage, setStage] = useState<PipelineStage | null>("visual");
  const [failure, setFailure] = useState<string | null>(null);
  const [longWait, setLongWait] = useState(false);

  useEffect(() => {
    let active = true;
    // After 8 seconds the page says so honestly; there is no percentage or fake progress.
    const slowTimer = window.setTimeout(() => setLongWait(true), 8000);

    async function poll() {
      try {
        const result = await apiFetch<{ status: string; stage: PipelineStage | null; message: string | null }>(
          `/api/v1/assess/${params.id}/status`,
        );
        if (!active) return;
        setStage(result.stage);
        if (result.status === "complete") {
          router.replace(`/assess/${params.id}`);
          return;
        }
        if (result.status === "failed" || result.status === "abandoned") {
          setFailure(result.message ?? "The check could not be completed.");
          return;
        }
        window.setTimeout(poll, 900);
      } catch {
        if (active) setFailure("The processing status could not be loaded. Your form draft is still saved.");
      }
    }

    void poll();
    return () => {
      active = false;
      window.clearTimeout(slowTimer);
    };
  }, [params.id, router]);

  // Cancel tells the server to stop, then returns to the saved form whatever the server says.
  async function cancel() {
    try {
      await apiFetch<void>(`/api/v1/assess/${params.id}/cancel`, { method: "POST" });
    } finally {
      router.push("/assess");
    }
  }

  return (
    <main className="page">
      <section className="card processing-card" aria-live="polite">
        <p className="eyebrow">Assessment in progress</p>
        <h1 className="page-title">Checking the listing</h1>
        {failure ? (
          <>
            <p className="error-text" role="alert">{failure}</p>
            <button className="button button-primary button-full" onClick={() => router.push("/assess")}>
              Return to saved form
            </button>
          </>
        ) : (
          <>
            <StageList stage={stage} />
            {longWait && <p className="helper">{SLOW_WAIT_COPY}</p>}
            <button className="button button-text" type="button" onClick={cancel}>Cancel</button>
          </>
        )}
      </section>
    </main>
  );
}
```

- [ ] **Step 4: Add the developer handoff demo script**

`scripts/dev_handoff_demo.py`:

```python
"""Developer helper: play the browser extension's part of the session handoff.

Why it exists: the handoff (extension session -> website cookie) is hard to see without the
extension and a real listing. This script does what the extension does against a running API:

  1. mints an anonymous session token (POST /api/v1/session),
  2. submits a stub assessment identified by that token in the X-Session-Token header,
  3. prints the URL the extension would open for "See full explanation".

Open the printed URL in a browser (website running on port 3000). The explanation page should load
with no login, and "#st=..." should disappear from the address bar.

Usage, with the API running on port 8000:
    .venv/Scripts/python scripts/dev_handoff_demo.py [--api http://localhost:8000] [--site http://localhost:3000]
"""

from __future__ import annotations

import argparse
import io

import httpx
from PIL import Image


def make_photo() -> bytes:
    """A small valid JPEG, so the upload passes the API's image validation."""
    buffer = io.BytesIO()
    Image.new("RGB", (640, 480), (200, 210, 220)).save(buffer, format="JPEG")
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description="Print a website handoff URL for a stub assessment.")
    parser.add_argument("--api", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--site", default="http://localhost:3000", help="website base URL")
    args = parser.parse_args()

    with httpx.Client(base_url=args.api, timeout=30) as client:
        # Step 1: the extension's first call, creating an anonymous session.
        token = client.post("/api/v1/session").raise_for_status().json()["session_token"]
        # Step 2: a submission owned by that token (no cookie involved).
        response = client.post(
            "/api/v1/assess",
            headers={"X-Session-Token": token},
            data={
                "platform": "carousell",
                "title": "Demo laptop",
                "description": "Demo listing created by scripts/dev_handoff_demo.py.",
                "price": "RM 1,250",
                "category": "Laptops",
                "source": "extension",
            },
            files=[("images", ("photo.jpg", make_photo(), "image/jpeg"))],
        )
        response.raise_for_status()
        assessment_id = response.json()["assessment_id"]

    # Step 3: the URL the extension opens. The token is in the fragment so it never reaches a server log.
    print(f"{args.site.rstrip('/')}/assess/{assessment_id}/explanation#st={token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Check the website builds**

```bash
npm run typecheck -w frontend
npm run lint -w frontend
npm run build -w frontend
.venv/Scripts/python -m ruff check scripts
```

Expected: all succeed. If lint reports `react-hooks/set-state-in-effect` for a new line, move that state update into a callback or promise handler (as the existing pages do) and keep the surrounding comment accurate in the same edit.

- [ ] **Step 6: Verify the handoff in a real browser (manual)**

In three terminals:

```bash
.venv/Scripts/python -m uvicorn api.main:app --port 8000
npm run dev -w frontend
.venv/Scripts/python scripts/dev_handoff_demo.py
```

Expected from the script: one URL of the form `http://localhost:3000/assess/<id>/explanation#st=<uuid>`. Then check:

1. Open the URL in Chrome. Expected: "Why this result was shown" with the three signal sections and the development-stub banner; the address bar shows `.../explanation` with no `#st=`.
2. Reload the page. Expected: it still loads (the session cookie is now set).
3. Open `http://localhost:3000/history` in the same browser. Expected: the demo listing is listed.
4. Open `http://localhost:3000/assess/<id>/explanation` (no fragment) in a private window. Expected: "The explanation could not be loaded for this browser session." (no cookie, so no access).
5. Open the first URL with `&signal=visual` appended in a fresh window. Expected: the page scrolls to "Visual signal" once loaded.

Write any defect up as a failing automated test where the logic is in `shared/` or `api/` before fixing it.

- [ ] **Step 7: Commit**

```bash
git add frontend scripts/dev_handoff_demo.py
git commit -m "feat(web): use the shared components and complete the extension session handoff"
```

---

### Task 18: Manual form with a free-text category, and an install-first landing page

**Files:**
- Modify: `frontend/app/assess/page.tsx`, `frontend/app/globals.css`
- Replace: `frontend/app/page.tsx`

**Interfaces:**
- Consumes: `CategoryField`, `DevBanner` from `@guardianlens/shared` (Task 6); the backend `source` and category rules (Task 5).
- Produces: a manual form whose category is free text (the 12 trained categories are only suggestions) and that sends `source=manual`; a landing page whose primary action is to get the extension, with the manual form as the secondary action. The extension zip is expected at `/downloads/guardianlens-extension.zip` (produced in Task 20).

- [ ] **Step 1: Update the manual form**

In `frontend/app/assess/page.tsx`, make these edits.

1. Replace the first line `"use client";` and the blank line after it, so the file starts with a header comment:

```tsx
// Manual listing form: the fallback and study entry for a listing that cannot be captured by the
// browser extension (a saved or stored listing, a changed page layout, or a browser the extension
// does not support). It sends `source=manual` so research records can tell the two paths apart.
// Category is FREE TEXT: the 12 categories the models were trained on are only suggestions.
"use client";
```

2. Add this import after the existing `import { apiFetch, GuardianLensApiError } from "@/lib/api";` line:

```tsx
import { CategoryField } from "@guardianlens/shared";
```

3. Delete the line `const categories = ["Electronics", "Phones and tablets", "Fashion", "Home and living", "Hobbies and games"];` (the fixed list is gone).

4. Replace the line

```tsx
    () => Boolean(files.length && draft.title.trim() && draft.description.trim() && draft.price.trim() && draft.category),
```

with

```tsx
    () => Boolean(files.length && draft.title.trim() && draft.description.trim() && draft.price.trim() && draft.category.trim()),
```

5. Replace the line `    body.append("category", draft.category);` with:

```tsx
    body.append("category", draft.category.trim());
    // Tells the API (and the research export) that this listing was typed in, not captured.
    body.append("source", "manual");
```

6. Replace the whole `<div className="field">` block that contains `<label htmlFor="category">Category</label>` and the `<select id="category" ...>` (it ends with the `category-error` span) by:

```tsx
            <CategoryField
              id="category"
              value={draft.category}
              onChange={(value) => update("category", value)}
              error={error?.field === "category" ? error.message : null}
            />
```

- [ ] **Step 2: Add the install styles**

Append to `frontend/app/globals.css` (before the `/* ---- Responsive` section is not required; appending at the end of the file is fine):

```css

/* ---- Landing page: extension install steps --------------------------------------------- */
.install-card { margin: 0 0 24px; }
.install-steps { margin: 12px 0 16px; padding-left: 22px; }
.install-steps li { margin: 8px 0; }
.install-steps code { background: var(--color-surface-alt); border-radius: 6px; padding: 1px 6px; font-size: 14px; }
```

- [ ] **Step 3: Replace the landing page**

Replace the whole of `frontend/app/page.tsx` with:

```tsx
// Landing page (S1): says what GuardianLens checks, what it cannot guarantee, and how data is
// handled, and leads with the browser extension, the main way to use the product. The manual form
// stays available as the secondary action.
//
// Install steps describe loading the extension unpacked, because this is a research prototype that
// is not published on a web store. The zip is produced by `npm run package:site -w extension`.
import Link from "next/link";
import { DevBanner } from "@guardianlens/shared";

export default function HomePage() {
  return (
    <main className="page">
      <section className="hero">
        <p className="eyebrow">Pre-purchase decision support</p>
        <h1>Check a marketplace listing before you pay.</h1>
        <p>
          GuardianLens reviews listing photos, wording, and visible seller details, then explains
          the warning signs it found and what you should verify yourself.
        </p>
        <DevBanner />
        <div className="hero-actions">
          <a className="button button-primary" href="/downloads/guardianlens-extension.zip" download>
            Get the extension
          </a>
          <Link className="button button-secondary" href="/assess">Enter a listing manually</Link>
        </div>
      </section>

      <section className="card install-card" aria-labelledby="install-heading">
        <h2 id="install-heading">Install the extension</h2>
        <ol className="install-steps">
          <li>Download the extension zip above and unzip it.</li>
          <li>Open <code>chrome://extensions</code> (or <code>edge://extensions</code>) and turn on Developer mode.</li>
          <li>Choose Load unpacked and select the unzipped folder.</li>
          <li>Open a Mudah.my or Carousell listing and click the GuardianLens icon. The result appears beside the page.</li>
        </ol>
        <p className="helper">
          The extension reads a listing only when you click its icon, and only that one page. This
          prototype is loaded unpacked rather than from a web store.
        </p>
      </section>

      <section id="how-it-works" className="explainer-grid" aria-label="How GuardianLens works">
        <article className="explainer-card">
          <h2>What it checks</h2>
          <p>Photos, listing text, and the seller details that are visible to you.</p>
        </article>
        <article className="explainer-card">
          <h2>What it cannot guarantee</h2>
          <p>A score is a second opinion. It cannot confirm that a seller or listing is safe.</p>
        </article>
        <article className="explainer-card">
          <h2>How data is handled</h2>
          <p>Raw text is scrubbed for contact details before storage. The retention period is still awaiting approval.</p>
        </article>
      </section>

      <Link className="button button-primary button-full" href="/assess">Enter a listing manually</Link>
      <p className="footer-note">Designed for Mudah.my and Carousell product listings in English, Malay, or mixed text.</p>
    </main>
  );
}
```

- [ ] **Step 4: Check the website builds**

```bash
npm run typecheck -w frontend
npm run lint -w frontend
npm run build -w frontend
```

Expected: all succeed.

- [ ] **Step 5: Verify in a browser (manual)**

With the API and website running:

1. Open `http://localhost:3000/`. Expected: "Get the extension" is the primary button, the install steps are visible, and "Enter a listing manually" is secondary. Check at 375, 768, and 1440 px wide: no horizontal scroll, buttons at least 48 px tall.
2. Open `/assess`. Type a category that is not in the suggestion list, such as `Aquarium supplies`. Expected: the note "Price is compared with the overall average, not this category's average." appears, and the form submits with the other fields filled in.
3. In the API's admin records (`GET /api/v1/admin/records` with your dev token) the new record has `source: "manual"`.

- [ ] **Step 6: Commit**

```bash
git add frontend
git commit -m "feat(web): free-text category on the manual form and an install-first landing page"
```

---

### Task 19: Show the submission source in the admin records

**Files:**
- Modify: `frontend/app/admin/page.tsx`

**Interfaces:**
- Consumes: `AdminRecordSummary.source` from the API (Task 5).
- Produces: a `Source` column in the admin records table.

- [ ] **Step 1: Add the column**

In `frontend/app/admin/page.tsx`:

1. Replace the first line `"use client";` and the blank line after it with a header comment followed by the directive:

```tsx
// Research administration page (development token gate). Lists model bundles and the anonymised
// assessment records, including where each record came from (browser extension or manual form),
// so the research export can be read against the way each listing was captured.
"use client";
```

2. In the `RecordRow` interface, add one line after `status: string;`:

```tsx
  // Where the submission came from: "extension" or "manual".
  source: string;
```

3. In the records table header, replace `<th>Status</th><th>Score</th><th>Band</th>` with `<th>Status</th><th>Source</th><th>Score</th><th>Band</th>`.

4. In the records table row, replace `<td>{record.status}</td><td>{record.score ?? ""}</td>` with `<td>{record.status}</td><td>{record.source}</td><td>{record.score ?? ""}</td>`.

- [ ] **Step 2: Check the website builds**

```bash
npm run typecheck -w frontend
npm run lint -w frontend
npm run build -w frontend
```

Expected: all succeed.

- [ ] **Step 3: Verify in a browser (manual)**

Create one listing through the manual form and one through `scripts/dev_handoff_demo.py`. Open `http://localhost:3000/admin`, enter the development admin token from `.env`, and load the data. Expected: the records table has a `Source` column showing `manual` for the first record and `extension` for the second.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/admin/page.tsx
git commit -m "feat(web): show the submission source in the admin records"
```

---

### Task 20: Packaging, documentation, CI, and final verification

**Files:**
- Create: `extension/scripts/package-for-site.mjs`
- Modify: `README.md`, `FIRST_DRAFT_STATUS.md`, `.github/workflows/ci.yml`, `docs/superpowers/plans/2026-10-05-extension-and-detail-site.md` (tick the checklist as you go)
- Create: `docs/superpowers/audits/2026-10-extension-ux-audit.md`

**Interfaces:**
- Consumes: the zip `wxt zip` writes to `extension/.output/`; every earlier task.
- Produces: `npm run package:site -w extension` (zips the extension and copies it to `frontend/public/downloads/guardianlens-extension.zip`, which the landing page links to); updated README and status notes; a CI definition for the workspaces; recorded audit results; a fully verified branch.

- [ ] **Step 1: Write the packaging script**

`extension/scripts/package-for-site.mjs`:

```js
// Copies the extension zip built by `wxt zip` into the website's public downloads folder, so the
// landing page's "Get the extension" button has something to download.
// Run it through `npm run package:site -w extension`, which zips first and then runs this file.
// The destination is git-ignored (and so is every *.zip), because it is a build product.
import { copyFileSync, existsSync, mkdirSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const extensionRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const outputDir = join(extensionRoot, ".output");

// wxt names the file guardianlens-extension-<version>-chrome.zip; pick the newest one.
const zips = existsSync(outputDir)
  ? readdirSync(outputDir)
      .filter((name) => name.endsWith("-chrome.zip"))
      .map((name) => ({ name, modified: statSync(join(outputDir, name)).mtimeMs }))
      .sort((a, b) => b.modified - a.modified)
  : [];

if (zips.length === 0) {
  console.error("No *-chrome.zip found in extension/.output. Run `npm run zip -w extension` first.");
  process.exit(1);
}

const target = resolve(extensionRoot, "..", "frontend", "public", "downloads");
mkdirSync(target, { recursive: true });
copyFileSync(join(outputDir, zips[0].name), join(target, "guardianlens-extension.zip"));
console.log(`Copied ${zips[0].name} to frontend/public/downloads/guardianlens-extension.zip`);
```

Run it:

```bash
npm run package:site -w extension
```

Expected: the last line reads `Copied guardianlens-extension-<version>-chrome.zip to frontend/public/downloads/guardianlens-extension.zip`, and `git status --short frontend/public` shows nothing (ignored). If `wxt zip` names the file differently, adjust the `endsWith` filter in the script and update the comment above it in the same edit.

- [ ] **Step 2: Update the README**

In `README.md`, make three edits (the file must keep containing no em dash or en dash).

1. In the repository map code block, add two lines after the `frontend/` line:

```text
  extension/            Browser extension (WXT): captures a listing on click, result in a side panel
  shared/               Types, API client, design tokens, and components used by the site and the extension
```

2. Replace the whole section from `## Quick start on Windows` up to (not including) `## Quick start on Linux or macOS` with:

```markdown
## Quick start on Windows

Prerequisites: Python 3.12 or 3.13 (3.14 is not supported by `pyproject.toml`), Node.js 22 or newer, npm, Git, and `uv` (it downloads Python 3.13 for you).

```powershell
cd GuardianLens_codebase
uv venv --python 3.13 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements-dev.txt
npm install
Copy-Item .env.example .env
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

`npm install` at the repository root installs all three JavaScript packages (`shared`, `extension`, `frontend`) as npm workspaces.

Open:

- Web: `http://localhost:3000`
- API health: `http://localhost:8000/health`
- OpenAPI: `http://localhost:8000/docs`
```

3. Add this new section directly before `## Verification commands`:

```markdown
## Browser extension

The extension captures one listing when you click its icon on a Mudah.my or Carousell listing, lets you review the captured fields, and shows the result in the browser side panel. "See full explanation" opens the website on the same result without a login.

Build and load it:

```bash
npm run build -w extension
```

Then open `chrome://extensions` (or `edge://extensions`), turn on Developer mode, choose Load unpacked, and select `extension/.output/chrome-mv3`.

Settings are build-time environment variables: `WXT_API_BASE_URL` (default `http://localhost:8000`) and `WXT_SITE_BASE_URL` (default `http://localhost:3000`). Changing the API origin is a rebuild, because the origin is also written into the extension's host permissions.

To offer the extension from the website's landing page, run `npm run package:site -w extension`.

Capture boundary: the extension reads a page only on the buyer's click, only that one page, and only on the two marketplaces. It never crawls, never runs in the background, and never navigates by itself. Its permissions are `activeTab`, `scripting`, `storage`, and `sidePanel`, and it has no standing access to the marketplace sites.

Developer helper: `python scripts/dev_handoff_demo.py` plays the extension's part of the session handoff and prints a website URL that should open the result without a login.
```

4. Replace the code block under `## Verification commands` with:

```bash
pytest -q
python -m compileall -q api ml scripts
python scripts/secret_scan.py
python scripts/check_prose.py

npm run lint
npm run typecheck
npm test
npm run build
npm run test:e2e -w extension
```

Then run:

```bash
.venv/Scripts/python scripts/check_prose.py
```

Expected: `Prose punctuation check passed`.

- [ ] **Step 3: Correct the status note**

In `FIRST_DRAFT_STATUS.md`, replace the line

```markdown
1. No marketplace scraper, crawler, URL fetcher, OCR pipeline, browser extension, Facebook Marketplace support, community reporting, or guaranteed-fraud feature was added.
```

with

```markdown
1. No marketplace scraper, crawler, URL fetcher, OCR pipeline, Facebook Marketplace support, community reporting, or guaranteed-fraud feature was added. A browser extension was added on 2026-10-05 after supervisor approval; it reads one listing only when the buyer clicks it (see docs/superpowers/specs/2026-10-05-extension-and-detail-site-design.md). The PRD and Chapter 3 documents in docs/spec still list the extension as out of scope and are updated in the documentation phase.
```

- [ ] **Step 4: Update the CI definition**

In `.github/workflows/ci.yml`, replace the whole `frontend:` job (from `  frontend:` to the end of the file) with:

```yaml
  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      # One install at the repository root covers the shared, extension, and frontend workspaces.
      - run: npm ci
      - run: npm run lint
      - run: npm run typecheck
      - run: npm test
      - run: npm run build
```

Add a one-line comment above the `jobs:` key: `# Note: GitHub reads workflows only from the repository root, so this file takes effect once the codebase folder is the repository root or the file is copied there.`

- [ ] **Step 5: Run the full verification**

```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check api ml scripts
.venv/Scripts/python -m mypy api ml/src/guardianlens_ml
.venv/Scripts/python scripts/check_prose.py
.venv/Scripts/python scripts/secret_scan.py
npm run lint
npm run typecheck
npm test
npm run build
npm run test:e2e -w extension
```

Expected: every command succeeds. Fix any failure at its cause, with its comment updated in the same edit, and rerun the full list until it is clean.

- [ ] **Step 6: Audit the comments**

Every code file added on this branch must start with a header comment (the rule in Global Constraints). Run:

```bash
for f in $(git diff --name-only --relative main...HEAD -- '*.ts' '*.tsx' '*.py' '*.js' '*.mjs' '*.css'); do
  head -3 "$f" | grep -qE '^(//|#|/\*|""")' || echo "missing header comment: $f"
done
```

Expected: no output. For each file it names, add the missing header comment now (and the missing doc comments on its exported symbols), in a normal commit of that file's change, never as a separate comment-only commit. Generated files and `package*.json` are out of scope. Then skim each changed file once for stale comments: any comment that describes behaviour the code no longer has is rewritten in place, with no "updated" note beside it.

- [ ] **Step 7: Run the security review**

Dispatch the `security-reviewer` agent with this brief and fix every confirmed finding (each as a failing test first):

```text
Review the session handling added on branch feat/extension-and-detail-site in GuardianLens_codebase/api:
api/dependencies.py (parse_session, session_header_value), api/routers/session.py (POST /api/v1/session,
POST /api/v1/session/claim), api/routers/assess.py (session_invalid, source and capture_meta handling,
category length), api/services/capture_meta.py, and the CORS change in api/main.py. Check: ownership
checks cannot be bypassed by mixing header and cookie, the claim endpoint cannot be used to enumerate
tokens, capture_meta cannot store free text or a listing URL, session minting abuse (unbounded sessions)
is described accurately, and nothing logs the token. Report findings by severity with file and line.
```

- [ ] **Step 8: Run the UX-laws and accessibility audit**

Invoke the `/ux-laws` skill against the side panel (at 360 and 420 px) and the website pages S1, S2, S4, and S5 (at 375, 768, and 1440 px). Write the results to `docs/superpowers/audits/2026-10-extension-ux-audit.md` as a table with one row per law that applies, using this shape (no em or en dashes):

```markdown
# Extension and detail site UX audit

Run after Task 20. Result per law: pass, fail with the finding, or waived with the reason.

| Law | Surface | Result | Finding |
| --- | --- | --- | --- |
| Hick's Law | Panel result view | pass | One primary action and two secondary choices |
```

Also run the browser's Lighthouse accessibility audit on `/`, `/assess`, a result page, and the side panel page opened as a tab, and record the scores in the same file. Any `fail` or any Lighthouse issue rated serious is fixed (test first where there is logic) and the audit is rerun before the next step.

- [ ] **Step 9: Commit**

```bash
git add extension/scripts README.md FIRST_DRAFT_STATUS.md .github docs/superpowers/audits
git commit -m "docs: package the extension for the site, update the README, and record the audits"
```

- [ ] **Step 10: Whole-branch review**

Run `/code-review` on `git diff main...HEAD` (or dispatch a fresh reviewer on the most capable model) and address every finding that survives verification, each as a failing test first where the problem is in logic. Then hand the branch back to the developer for the supervisor demo.
