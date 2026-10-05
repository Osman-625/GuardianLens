# Real-page spike notes (2026-10)

**Status: UNVERIFIED.** Every entry below was seeded on 2026-10-05 from code the project already
has (the Data Collector's extension and extraction contract, and the URL crawler). None of it has
been checked against recorded pages yet. After recording pages with `fixtures/record-fixture.js`
(see `fixtures/README.md`), replace each entry with what was observed and remove this notice.

## Listing fields
Seeded from the Collector's `extension/background.js` (`collectPageData`):

- Title: the first sensible `h1`. Other candidates: JSON-LD `Product.name`, `og:title`.
- Price: JSON-LD `offers.price`, then `meta[property="product:price:amount"]` and `itemprop="price"`,
  then elements whose own text is `RM <amount>`.
- Photos: JSON-LD `Product.image`, then large images inside `main` or a gallery element.
- Description and category: the Collector did NOT read these from the DOM (an LLM extracted them from
  page text), so where they live on each platform is unknown. Candidates: JSON-LD `Product.description`,
  `og:description`, a breadcrumb trail for the category.

## Description and category selectors
None known yet. `PLATFORM_SELECTORS` in `lib/capture/selectors.ts` starts empty and is filled only
where a recorded page shows the generic strategies are not enough.

## Image hosts
Unverified guesses currently in `lib/hosts.ts`:

- media.karousell.com (Carousell photos)
- *.mudah.my (Mudah.my photos)

## Seller page URL shapes
From the URL crawler and the Collector's seller-link scoring:

- Carousell listing: `/p/<slug>-<id>/`. Carousell seller profile: `/u/<username>/`.
- Mudah.my listing: `/<slug>-<id>.htm`. Mudah.my seller pages: a path segment such as `seller`,
  `profile`, `user`, `shop`, or `dealer` (the Collector's scoring words; exact shape unknown).

## Seller page phrases
From the Collector's extraction rules (`extraction_contract.py`); the exact page wording is unknown:

- Account age as a duration ("11 years", "3 years 2 months", "8 months") or as a join date
  ("Joined Since 21 May 2020").
- "No review(s) yet" together with an "N/A" rating.
- A "Listings" section whose cards may be marked "SOLD".

## Seller data on the listing page
By the Collector's contract, account age, rating, review count, and listing count come from the
seller or profile page, not the listing page. Whether any seller text appears on the listing page is
unknown.

## Blocking and login behaviour
The Collector detects, and never bypasses, CAPTCHA, access-denied, and login pages. Which pages on
each platform trigger them is unknown.
