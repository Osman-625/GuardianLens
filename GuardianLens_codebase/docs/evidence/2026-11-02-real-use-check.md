# Real-use check, 2 November 2026

A functional check of the finished system as one piece: the **built extension**, the **trained models** and the **production website**, run together on **real listings**. It is evidence that the parts work together and that buyers never see model names. It is not an accuracy measurement: six listings say nothing about accuracy, which is the job of the sealed test (Chapter 4 and 6).

## What was run

| Part | Version |
| --- | --- |
| API | `GUARDIANLENS_INFERENCE_MODE=trained`, bundle `20261002_062026_colab_v3_noMeta`, `/health` reported `stub_mode: false` and `visual_model_ready: true` |
| Website | `next build` then `next start`, Next.js 16.4.3 |
| Extension | `wxt build` output (`chrome-mv3`) loaded into Chromium |

**Listings.** Six listings from the **validation split** of the approved dataset (not the sealed test split), chosen with a fixed seed: two labelled scam or fraud, one suspicious, three legitimate; four from Carousell and two from Mudah; each with at least two photos. The two Mudah listings carry no seller details, which is the normal case on Mudah. The text and photos of these listings are third-party content and are not copied here; they are identified by label and platform only.

**Paths.**
1. *Website, manual form:* each listing was typed into `/assess` with its real photos, then the result and explanation pages were read.
2. *Extension panel:* two listings (one Carousell with seller details, one Mudah without) were loaded into the built extension's Review step, checked against the real API, and "See full explanation" was followed to the real website, including the session handoff confirmation.

What is **not** automated here: the toolbar-icon click, and capture from a live marketplace page. Playwright cannot press the extension icon, and the extension has no standing access to the marketplace sites by design. The capture code is covered by unit tests on synthetic pages; the two real-page fixture files stay skipped until pages are recorded by hand (`extension/fixtures/README.md`).

## Results

| # | Label (annotation) | Platform | Score | Band | Time | Seller details given |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | scam or fraud | Carousell | 82 | Moderate | 4.8 s | partly (1 field unknown) |
| 2 | scam or fraud | Mudah | 85 | Low | 3.5 s | none |
| 3 | suspicious | Carousell | 75 | Moderate | 3.6 s | yes |
| 4 | legitimate | Carousell | 53 | High | 3.7 s | yes |
| 5 | legitimate | Mudah | 86 | Low | 3.4 s | none |
| 6 | legitimate | Carousell | 62 | Moderate | 3.7 s | yes |

Through the extension panel, listing 4 scored 53 (High) in 2.7 s and listing 2 scored 85 (Low) in 2.6 s: the same scores as through the website, so the two paths agree. Every check finished inside the 10-second budget.

## What the check confirmed

- All six checks completed and produced a score, a band with icon and words, three cards with a main factor each, the checks to do before paying, and the disclaimer.
- No model or method name reached the screen. A scan of the visible text of the result page, the explanation page and the panel for `CLIP`, `SSCD`, `XGBoost`, `TF-IDF`, "Analysed using", "model check", the bundle label and millisecond timings found none. The bundle label is still in the explanation page's markup, hidden (the `SHOW_MODEL_DETAILS` switch).
- The extension-to-website handoff opened the explanation page for the right result.

## What the check found, and what was done

| Finding | Action |
| --- | --- |
| The third card was named "Seller details", but its reasons were often about the price ("The listing price (RM 2,100) raised the risk estimate"), including for listings with no seller details at all. | Renamed to "Seller and price" in the cards, the stage list and the start screens. |
| "1 seller fields are unknown." | The sentence now agrees in number ("1 seller field is unknown."). |
| The website had no tab icon, so the first page load logged a 404. | Added `frontend/app/icon.svg`, the same lens ring as the extension icon. |
| `npm audit --omit=dev` reported a critical advisory in Next.js 16.4.0. | Patched to 16.4.3; the audit now reports 0 vulnerabilities in the shipped dependencies. |
| While photographing the screens, a second check in the same browser tab showed 75 for a listing that had scored 82. The manual form had kept the previous listing's draft, so an empty seller field inherited the last listing's rating. The model itself is deterministic: the same listing scored 82 three times in a row. | The processing page now clears the saved form draft when a check completes (a failed or cancelled check still keeps it, so the buyer can retry). One test added; the history in the final screenshots shows 82. |

## Observations for the report (not fixed, because they are model behaviour)

- Several wording reasons are single words that read as arbitrary to a buyer ("yang", "pro", "256gb"). They are real TF-IDF contributions; the scope note says other wording also counts. The reasons are honest about the model, not about the listing.
- For the seller and price check, a rating of 5 or 4.9 raised the risk estimate on two legitimate listings. The card's scope note already says that a higher rating did not lower risk in the annotated data and that a good profile does not mean a safe listing.
- The six outcomes are mixed (one scam listing scored Low, two legitimate listings scored Moderate or High). Six listings cannot say how often this happens; the sealed test is the accuracy evidence. It is also why the interface says "supports your judgement" and never "safe".
