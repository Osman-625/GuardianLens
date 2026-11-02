// Layout checks for the side panel, measured in a real browser on the BUILT extension.
// Unit tests (jsdom) have no layout engine, so spacing and alignment can only be pinned here. They
// protect the panel's rhythm so it matches the website: consistent gaps between blocks, fields that
// never touch each other, and text buttons whose label lines up with the text above them.
import { expect, test, type Page } from "@playwright/test";
import { launchWithExtension, listingJob, mockApi, mockPhotos, seedCapture } from "./helpers";

/** The vertical space between the bottom of one element and the top of the next, in pixels. */
async function gapBetween(page: Page, upper: string, lower: string): Promise<number> {
  return page.evaluate(
    ([a, b]) => {
      const first = document.querySelector(a as string)?.getBoundingClientRect();
      const second = document.querySelector(b as string)?.getBoundingClientRect();
      if (!first || !second) throw new Error(`missing element: ${a} or ${b}`);
      return Math.round((second.top - first.bottom) * 10) / 10;
    },
    [upper, lower],
  );
}

/**
 * Launches Chromium with the extension, mocks the API and photo host, and opens the side panel
 * page as a tab (410 px wide when `narrow`, like the real panel, otherwise 1280 px).
 */
async function openPanel(narrow = true) {
  const { context, extensionId } = await launchWithExtension();
  await mockApi(context);
  await mockPhotos(context);
  const page = await context.newPage();
  await page.setViewportSize({ width: narrow ? 410 : 1280, height: 900 });
  await page.goto(`chrome-extension://${extensionId}/sidepanel.html`);
  return { context, page };
}

test("the seller fields in Review are spaced apart, like the website's form", async () => {
  const { context, page } = await openPanel();
  await seedCapture(page, listingJob());
  await page.getByText("Seller details (recommended)").waitFor();
  const fields = page.locator("details.optional .field");
  expect(await fields.count()).toBe(4);
  const boxes = await fields.evaluateAll((nodes) =>
    nodes.map((node) => {
      const rect = node.getBoundingClientRect();
      return { top: rect.top, bottom: rect.bottom };
    }),
  );
  for (let index = 1; index < boxes.length; index += 1) {
    const gap = (boxes[index]?.top ?? 0) - (boxes[index - 1]?.bottom ?? 0);
    expect(gap, `gap above seller field ${index + 1}`).toBeGreaterThanOrEqual(12);
  }
  await context.close();
});

test("text buttons line up with the text above them", async () => {
  const { context, page } = await openPanel();
  await page.getByRole("button", { name: "Use the website form" }).waitFor();
  const offsets = await page.evaluate(() => {
    const paragraph = document.querySelector(".panel-section p")?.getBoundingClientRect();
    const button = document.querySelector(".panel-links .button-text") as HTMLElement | null;
    if (!paragraph || !button) throw new Error("idle view not found");
    // Where the button's LABEL starts: its box plus its left padding.
    const labelLeft =
      button.getBoundingClientRect().left + parseFloat(getComputedStyle(button).paddingLeft);
    return { paragraphLeft: paragraph.left, labelLeft };
  });
  expect(Math.abs(offsets.labelLeft - offsets.paragraphLeft)).toBeLessThanOrEqual(1);
  await context.close();
});

test("the result view has one steady rhythm between its blocks", async () => {
  const { context, page } = await openPanel();
  await seedCapture(page, listingJob());
  await page.getByRole("button", { name: "Check listing" }).click();
  await page.getByRole("region", { name: /^Score \d+ out of 100/ }).waitFor();
  const aboveCards = await gapBetween(page, ".score-region", ".signal-grid");
  const belowCards = await page.evaluate(() => {
    const grid = document.querySelector(".signal-grid")?.getBoundingClientRect();
    const next = document
      .querySelector(".signal-grid")
      ?.nextElementSibling?.getBoundingClientRect();
    if (!grid || !next) throw new Error("blocks not found");
    return next.top - grid.bottom;
  });
  // The same gap above and below the cards, and no larger than the panel's normal block gap.
  expect(Math.abs(aboveCards - belowCards)).toBeLessThanOrEqual(1);
  expect(aboveCards).toBeLessThanOrEqual(16);
  await context.close();
});
