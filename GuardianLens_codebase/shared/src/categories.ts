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
// Tablets is tested before Phones, "Smart Watches" must not fall into Phones, and "Toys &
// Games" must reach Collectibles before the bare word "games" sends it to Gaming. A plain
// "watch" or "computer" is NOT a keyword (a fashion watch or a PC part is priced unlike a
// smart watch or a laptop), and accessories are never prefilled as the category (see resolveCategory).
// "Other" has no keywords: it is only ever chosen by the buyer.
const KEYWORDS: ReadonlyArray<readonly [Exclude<TrainedCategory, "Other">, RegExp]> = [
  ["Tablets", /\b(tablet|tablets|ipad)\b/i],
  ["Phones", /\b(phone|phones|mobile|smartphone|iphone|android)\b/i],
  ["Wearables", /\b(wearable|wearables|smart ?watch(?:es)?|fitbit)\b/i],
  ["Laptops", /\b(laptop|laptops|notebook|macbook)\b/i],
  ["Cameras", /\b(camera|cameras|lens|lenses|dslr|mirrorless|photography)\b/i],
  ["Audio", /\b(audio|headphones?|earphones?|earbuds|speakers?|hi-?fi)\b/i],
  [
    "Home Appliances",
    /\b(appliance|appliances|kitchen|washing|refrigerator|fridge|air ?con|vacuum)\b/i,
  ],
  ["Fashion", /\b(fashion|clothing|clothes|shoes|bags?|apparel|dress|jewell?ery)\b/i],
  ["Sports", /\b(sport|sports|bicycle|bike|fitness|golf|badminton|outdoor)\b/i],
  ["Collectibles", /\b(collectible|collectibles|hobby|hobbies|toys?|figures?|trading cards?)\b/i],
  ["Gaming", /\b(gaming|game|games|console|consoles|playstation|xbox|nintendo)\b/i],
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
  // A phone case is not priced like a phone: accessories keep the platform's own wording. The
  // rule lives here, not in matchTrainedCategory, so the Mudah capture can still prefer a
  // specific sub-category such as "Mobile Phone Accessories" over its wider top-level name.
  if (/\baccessor(?:y|ies)\b/i.test(text)) return text.trim();
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
