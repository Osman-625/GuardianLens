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
