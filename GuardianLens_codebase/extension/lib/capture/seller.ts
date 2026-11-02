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
//   - active listings: the "N AVAILABLE ADS" figure when the page states one (Mudah); otherwise
//     the listing cards NOT marked SOLD. A "Listings" heading with no cards is 0; no heading and
//     no cards is "not found" (null), never 0. Mudah shows no ratings, so rating and review count
//     stay "not found" there rather than 0.
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

// Month number (January is 0) for the first three letters of an English month name.
const MONTHS: Record<string, number> = {
  jan: 0,
  feb: 1,
  mar: 2,
  apr: 3,
  may: 4,
  jun: 5,
  jul: 6,
  aug: 7,
  sep: 8,
  oct: 9,
  nov: 10,
  dec: 11,
};

// Words that introduce the account-age statement. A duration or date is read only when it
// follows one of these, so an unrelated "3 months" elsewhere on the page is ignored.
const AGE_ANCHOR =
  /(joined(?:\s+since)?|member\s+since|been\s+on\s+(?:carousell|mudah)(?:\s+for)?|account\s+(?:age|created))/i;

// The wording of Carousell's seller card, seen on real saved pages (2026-09): "Profile details
// 4.7 66 reviews 5 years on Carousell" and "N/A No review yet 2 months on Carousell". The duration
// comes BEFORE "on Carousell", so the anchor words above never see it.
// `(?<![\d,])` and `\d{1,3}` keep the match linear: without them a page full of digits made the
// engine retry from every digit (100,000 digits took ~100 s in the stress test).
const DURATION_ON_SITE =
  /(?<![\d,])(?:(\d{1,3})\s*(?:years?|yrs?))?\s*(?:(\d{1,3})\s*(?:months?|mths?))?\s+on\s+(?:carousell|mudah)\b/i;

// Carousell's profile header (seen 2026-10): "5.0 52 reviews 10m 22d Joined". The abbreviated
// duration (y, m, d) comes BEFORE the word "Joined", and the text after it is the seller's own bio.
const DURATION_BEFORE_JOINED =
  /(?<![\d.,])(?=\d)(?:(\d+)\s*y\s*)?(?:(\d+)\s*m\s*)?(?:(\d+)\s*d\s*)?joined\b/i;

/** 1 year = 365 days and 1 month = 30 days (the training convention); null when none is given. */
function durationToDays(
  years: string | undefined,
  months: string | undefined,
  days?: string,
): number | null {
  if (years === undefined && months === undefined && days === undefined) return null;
  return Number(years ?? 0) * 365 + Number(months ?? 0) * 30 + Number(days ?? 0);
}

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

/** The join date written as "21 May 2020" or "May 21, 2020" in `text`, or null. */
function statedJoinDate(text: string): Date | null {
  const dayFirst = /(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})/.exec(text);
  if (dayFirst) {
    const [, day, monthName, year] = dayFirst;
    return day && monthName && year ? utcDate(year, monthName, day) : null;
  }
  const monthFirst = /([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})/.exec(text);
  if (monthFirst) {
    const [, monthName, day, year] = monthFirst;
    return day && monthName && year ? utcDate(year, monthName, day) : null;
  }
  return null;
}

/**
 * Reads the account age in days from seller-page text.
 * @param text Visible text of the page.
 * @param now "Today", used when the page states a join date instead of a duration.
 * @returns Days, or null when the page states neither a duration nor a full join date after an
 *          account-age phrase (a bare year such as "Member since 2019" is not enough), nor a
 *          duration before "on Carousell".
 */
export function parseAccountAgeDays(text: string, now: Date): number | null {
  // The card's duration is the fallback, so a page that also has a "Joined since: Nov 2022" line
  // (month and year: deliberately unread) still gets its "5 years on Carousell".
  const onSite = DURATION_ON_SITE.exec(text);
  const beforeJoined = DURATION_BEFORE_JOINED.exec(text);
  // Tried first: the text after "Joined" on that header is the bio, which may mention "5 years".
  return (
    durationToDays(beforeJoined?.[1], beforeJoined?.[2], beforeJoined?.[3]) ??
    ageAfterAnchor(text, now) ??
    durationToDays(onSite?.[1], onSite?.[2])
  );
}

/** The age stated right after an account-age phrase ("Joined ...", "Member since ..."), or null. */
function ageAfterAnchor(text: string, now: Date): number | null {
  const anchor = AGE_ANCHOR.exec(text);
  if (!anchor) return null;
  const start = anchor.index + anchor[0].length;
  // Only the 80 characters after the anchor are read, so later text on the page cannot leak in.
  const nearby = text.slice(start, start + 80);

  // A stated join date: days from that date to today (a future or impossible date is not used).
  const joined = statedJoinDate(nearby);
  if (joined) {
    const days = daysBetween(joined, now);
    return days >= 0 ? days : null;
  }

  // A stated duration: "3 years 2 months", "11 years", "8 months".
  const years = /(\d+)\s*(?:years?|yrs?)\b/i.exec(nearby)?.[1];
  const months = /(\d+)\s*(?:months?|mths?)\b/i.exec(nearby)?.[1];
  return durationToDays(years, months);
}

/** A rating from 0 to 5, or null when the text is missing or the number is outside that range. */
function boundedRating(value: string | undefined): number | null {
  if (value === undefined) return null;
  const rating = Number(value);
  return Number.isFinite(rating) && rating >= 0 && rating <= 5 ? rating : null;
}

/** An integer written possibly with thousands separators ("1,120"), or null when missing. */
function toInt(value: string | undefined): number | null {
  if (value === undefined) return null;
  const parsed = Number(value.replace(/,/g, ""));
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * Reads the rating and the number of reviews from seller-page text.
 * Follows the training convention: "No reviews yet" is 0 reviews, and a 0.0 rating when no
 * rating is otherwise shown (an "N/A" rating beside it means there is nothing to average).
 */
export function parseReviewStats(text: string): {
  rating: number | null;
  reviewCount: number | null;
} {
  // "4.8 (17 reviews)", or Carousell's seller card: "4.7 66 reviews", "5.0 1 review"
  const combined =
    /(\d(?:\.\d{1,2})?)\s*\(\s*(\d[\d,]*)\s*reviews?\s*\)/i.exec(text) ??
    /(?<![\d.,])(\d(?:\.\d{1,2})?)\s+(\d[\d,]*)\s+reviews?\b/i.exec(text);
  if (combined)
    return {
      rating: boundedRating(combined[1]),
      reviewCount: toInt(combined[2]),
    };

  const noReviews = /\bno\s+reviews?(?:\s+yet)?\b/i.test(text);
  const counted = /(?<![\d,])(\d[\d,]*)\s+reviews?\b/i.exec(text);
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
 * True when a listing card is marked SOLD. A SOLD badge is usually its own element right next to
 * the title, so the card's joined text can read "ItemSOLD" with no word boundary. The card text
 * is therefore checked as a whole AND element by element (an element whose entire text is "SOLD").
 */
function isMarkedSold(card: Element): boolean {
  // Only an upper-case SOLD counts as a badge in the joined text. A title that merely contains the
  // word ("Table, not sold separately") is an active listing.
  if (/\bSOLD\b/.test(textOf(card))) return true;
  return Array.from(card.querySelectorAll("*")).some((element) => /^sold$/i.test(textOf(element)));
}

/**
 * Counts the seller's listing cards that are not marked SOLD.
 * @param baseUrl The page's URL, used to resolve relative links.
 * @returns The count; 0 when a Listings heading exists with no cards; null when the page shows
 *          no listings section at all.
 */
export function countActiveListings(
  doc: Document,
  platform: Platform,
  baseUrl: string,
): number | null {
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
    const sold = isMarkedSold(card);
    // A listing is often linked twice (photo and title); it is sold if any of its cards says so.
    seen.set(ref.listingId, (seen.get(ref.listingId) ?? false) || sold);
  }
  if (seen.size > 0) return [...seen.values()].filter((sold) => !sold).length;
  return hasListingsHeading(doc) ? 0 : null;
}

/**
 * The "N AVAILABLE ADS" figure that some seller pages (Mudah) state outright, or null.
 * It is preferred over counting cards because Mudah puts sold ads in their own section without a
 * SOLD badge on each card, so the cards alone cannot tell sold from available.
 */
function statedAvailableAds(text: string): number | null {
  // `\s*` (not `\s+`) and `(?![a-z])` (not `\b`): in a real browser the number and the label are
  // separate blocks with a line break between them, but text read without layout joins them
  // ("3AVAILABLE ADS32SOLD"), where a word boundary would not fall between "ADS" and "32".
  return toInt(/(?<![\d,])(\d[\d,]*)\s*available\s+ads?(?![a-z])/i.exec(text)?.[1]);
}

/**
 * Reads all four seller values from a seller / profile page.
 * @param doc The seller page document.
 * @param platform Which marketplace the page belongs to.
 * @param baseUrl The page's URL, used to resolve listing links.
 * @param now "Today", for join-date calculations.
 */
export function parseSellerPage(
  doc: Document,
  platform: Platform,
  baseUrl: string,
  now: Date,
): SellerValues {
  const text = normalizeText(textOf(doc.body));
  const { rating, reviewCount } = parseReviewStats(text);
  return {
    accountAgeDays: parseAccountAgeDays(text, now),
    rating,
    reviewCount,
    activeListingCount: statedAvailableAds(text) ?? countActiveListings(doc, platform, baseUrl),
  };
}
