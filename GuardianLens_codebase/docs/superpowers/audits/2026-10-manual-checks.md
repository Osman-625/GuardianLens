# Manual checks still needed for the extension and detail site

These checks need a person, live marketplace pages, or a real browser profile. Everything that can
be automated has been (unit tests, browser end-to-end tests, an automated accessibility and
handoff audit; see the other files in this folder). Tick each item and write surprises into
`extension/docs/SPIKE_NOTES.md` under a "Smoke test" heading. Turn any real defect into a failing
test before fixing it.

## 1. Record real pages (blocks the real-page tests)

Follow `extension/fixtures/README.md` to record three Carousell listings, three Mudah listings, and
one seller page for each. Until they exist the two `*.real.test.ts` files are skipped, and the
marketplace selectors in `extension/lib/capture/selectors.ts` are empty (the adapters work from
JSON-LD, meta tags, headings, and price text only). Record which selectors each site needed.

- [ ] Carousell listing pages recorded and `listing.real.test.ts` passes
- [ ] Mudah listing pages recorded and `listing.real.test.ts` passes
- [ ] Seller pages recorded and `seller.real.test.ts` passes
- [ ] The photo hosts in `extension/lib/hosts.ts` (`IMAGE_HOST_PATTERNS`) match the hosts the real pages use

## 2. Click capture in a real browser

Build and load the extension (see the README), then:

- [ ] On a live Carousell and a live Mudah listing, click the icon: the panel shows Review with the real title, price, photos, and category
- [ ] `chrome.storage.session` shows the capture job (service worker console)
- [ ] On a non-marketplace page, clicking the icon injects nothing and the panel says the site is unsupported
- [ ] On a seller page, clicking the icon adds the seller details to the draft and shows the notice
- [ ] Photo thumbnails load in the panel (the photo hosts may refuse a `chrome-extension://` referrer)
- [ ] Stop the API and press Check listing: the calm failure screen appears; Try again keeps everything typed
- [ ] The panel at 360 and 420 px, keyboard only (every control reachable, focus ring visible), and with a screen reader

## 3. Website screens

- [ ] Landing page at 375, 768, and 1440 px looks right (the automated audit found no overflow, but not whether it looks right)
- [ ] An unseen category such as "Aquarium supplies" shows the overall-average note on the manual form and submits
- [ ] After one manual and one extension check, `sqlite3 data/guardianlens.sqlite3 "select source, count(*) from assessments group by source"` shows `manual` and `extension`

## 4. Trained models (why a running API shows the "Test mode" banner)

Done on 2026-10-06 (see "Status on this machine" in `docs/TRAINED_MODELS.md`): the fitted files are installed, `.env` is set to `trained`, and the dependencies are installed. Still needed from you:

- [ ] Stop the running API and start it again (a first start takes several minutes), then open `GET /health` and confirm it names the bundle `20261002_062026_colab_v3_noMeta`
- [ ] Run a NEW check (old results stay as saved snapshots) and confirm the banner and the "Test mode" line in the disclaimer are gone and all three check cards show a real reason (model names are hidden from buyers on purpose)
- [ ] Time a check with many photos: the first two-photo check took 7.4 seconds against a 10 second budget, and the limit is now 10 photos
