# Real-page spike notes (2026-10)

**Status: PARTLY VERIFIED.** The entries were seeded on 2026-10-05 from code the project already
has (the Data Collector's extension and extraction contract, and the URL crawler). On 2026-10-10
the seller URL shapes and the seller wording on LISTING pages were checked against the Collector's
real saved captures (see the two seller sections below). Everything else, including the wording of
the seller PROFILE pages, is still unchecked. After recording pages with
`fixtures/record-fixture.js` (see `fixtures/README.md`), replace each remaining entry with what
was observed and remove this notice.

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
Checked on 2026-10-10 against the Data Collector's own database (real captures, usernames not
read): 1,469 Carousell seller URLs and 28 Mudah ones, ALL of the form `/u/<username>`.

- Carousell listing: `/p/<slug>-<id>/`. Carousell seller profile: `/u/<username>/`.
- Mudah.my listing: `/<slug>-<id>.htm`. Mudah.my seller profile: `/u/<username>`, and few Mudah
  listings link to one (28 of 858). PRO Niaga stores are said to use `/<shopname>`; no real
  example was seen, and that shape is not recognised.
- A Carousell listing page links to the seller's `/u/<username>/` almost every time (1,469 of
  1,471), which is what lets the panel offer "Open seller page".

## Seller page phrases
The wording below is from listing-page text the Collector saved. Carousell's SELLER PROFILE page
itself was not saved as text (only screenshots), so its wording is still unverified.

- Carousell seller card, shown on the listing page: `Meet the seller <name> Profile details 4.7 66
  reviews 5 years on Carousell`; with orders: `4.9 78 reviews 61 Orders 12 years on Carousell`;
  one review: `5.0 1 review 4 years on Carousell`; none: `N/A No review yet 2 months on Carousell`.
  The duration comes BEFORE "on Carousell" (1 year = 365 days, 1 month = 30 days).
- Mudah listing page: `Company <name> Joined since: Nov 2022` or `Private <name> Joined since:
  Apr 2015`. A month and a year, no day, so no account age is computed (the training data had an
  age for only 29 of 858 Mudah rows). The Mudah page also shows the Mudah APP's rating
  (`4.7 200K+ reviews`), which is not the seller's and is not read.
- From the Collector's extraction rules: "Joined Since 21 May 2020" style dates, and a "Listings"
  section whose cards may be marked "SOLD".

## Seller data on the listing page
On Carousell the listing page already shows rating, review count, and account age (the seller
card above); only the active-listing count needs the profile page. On Mudah the listing page shows
the join month and year, and nothing else about the seller. The extension still reads seller
details from the seller's own page (the second capture), because that is what the training data
used. Reading the card on the listing page would be a change to what a "seller capture" means, so
it was left out.

## Blocking and login behaviour
The Collector detects, and never bypasses, CAPTCHA, access-denied, and login pages. Which pages on
each platform trigger them is unknown.
