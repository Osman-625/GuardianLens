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
// "RM" must start a word: the letters inside "Form 4" or "warm 2" are not a currency prefix.
const RM_AMOUNT = /\b(?:RM|MYR)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)/gi;

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
    const digits = match[1];
    if (digits === undefined) continue;
    const value = Number(digits.replace(/,/g, ""));
    if (Number.isFinite(value)) amounts.add(value);
  }
  const [only] = amounts;
  return amounts.size === 1 && only !== undefined ? only : null;
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
