// Pins the text helpers and, above all, the price rules.
// A fraud-risk model compares the price with the category average, so a WRONG price is worse
// than a missing one. The rules are therefore conservative:
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
    // Built with DOM calls (not innerHTML) so the test needs no HTML parsing of a string.
    const div = document.createElement("div");
    const paragraph = document.createElement("p");
    const bold = document.createElement("b");
    bold.textContent = "world";
    paragraph.append("Hello   ", bold);
    div.append(paragraph);
    expect(textOf(div)).toBe("Hello world");
  });

  it("returns an empty string for a missing element", () => {
    expect(textOf(null)).toBe("");
  });
});

describe("parsePriceRm", () => {
  // "RM" must be a word of its own: letters inside another word ("Form 4", "warm 2") are not a price.
  it.each(["Form 4 students", "warm 2 layers", "Perform 10 times"])(
    "does not read a price inside the word in '%s'",
    (text) => {
      expect(parsePriceRm(text)).toBeNull();
    },
  );

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

  it.each([["abc"], [""], [-5], [Number.NaN], [null], [undefined]])(
    "returns null for %s",
    (value) => {
      expect(parsePriceValue(value)).toBeNull();
    },
  );
});
