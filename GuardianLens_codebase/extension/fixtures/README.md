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

`recordedOn` is the date you recorded the page; account-age tests use it as "today" so a stated
join date still gives the same number of days later.

## How to record a page

1. Open a listing in your own browser as a normal buyer. Scroll through the whole photo gallery so
   lazy images load.
2. Open DevTools (F12), paste `record-fixture.js` into the console, and run `recordFixture("listing")`.
3. Open that listing's seller or profile page from its own seller link, scroll until the listings
   section has loaded, and run `recordFixture("seller")`.
4. Move the two downloaded files into `fixtures/real/<platform>/<slug>/` as `listing.html` and
   `seller.html`, and write `expected.json` by reading the values off the live page.

Pick three listings per platform: a complete one with at least three photos and a visible seller
card, one with a single photo, and one whose category is outside the 12 trained categories.
Stop and report if a platform shows a CAPTCHA or blocks you. Do not bypass it.
