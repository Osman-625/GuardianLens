# Extension and detail site UX audit

Run after Task 20 on 2026-10-05. Result per law: pass, fail with the finding (fixed unless stated),
or waived with the reason. Surfaces: the side panel at 360 and 420 px, and the website screens S1
(landing), S2 (manual form), S4 (result), and S5 (explanation) at 375, 768, and 1440 px.

## Measurements

| Check | Surface | Result |
| --- | --- | --- |
| Lighthouse accessibility score | `/` (S1) | 100 |
| Lighthouse accessibility score | `/assess` (S2) | 100 |
| Lighthouse accessibility score | `/assess/<id>` (S4, opened with a session cookie) | 100 |
| axe-core violations, after the fixes below | Panel: idle, review, review with seller group open, result at 360 and 420 px; failure at 360 px | 0 |
| axe-core violations, after the fixes below | Website S1, S2, S4, S5 at 375, 768, 1440 px | 0 |
| Horizontal overflow | Every panel and website state above | 0 px |
| Touch targets under 44 px, after the fixes below | Every panel and website state above | none |
| Session handoff in a real browser | Confirmation dialog shown; `#st=` removed and `#visual` kept; reload works; `/history` lists the check; cookie is httpOnly; declining sets no cookie; a private window without the link cannot read the result | pass |

Notes on the method. Lighthouse ran against the production build before the touch-target and heading
fixes below; those fixes cannot lower the score, and axe-core (the rules engine behind Lighthouse's
accessibility audit) was rerun after them. Lighthouse cannot load a `chrome-extension://` page, so
the side panel was audited with axe-core in Playwright, opening the built panel page as a tab.
Not covered here: a keyboard-only walkthrough and a screen-reader pass, which need a person (listed
in the manual checks).

## Findings fixed during the audit

| Finding | Where | Fix |
| --- | --- | --- |
| Page had no level-one heading (axe `page-has-heading-one`) | Panel idle view | The idle view now has a heading, and the "reading this page" state is a headed live region. Tests added first. |
| "Seller information" summary was 24 px tall | Panel review view, website S2 | Padded to 44 px in `shared/src/styles.css`. |
| Header links were 19 to 24 px tall | Website header on every screen | Header links are 44 px tall (`frontend/app/globals.css`). |
| Two primary buttons competed at the end of the landing page | Website S1 | The closing pair repeats the one primary action ("Get the extension") with the manual form secondary. |

## Laws

| Law | Surface | Result | Finding |
| --- | --- | --- | --- |
| Hick's Law | Panel result view | pass | One primary action, one protective check, three feedback choices, and one exit. |
| Hick's Law | Website S1 | fail, fixed | Two primary calls to action at the page end (see above). |
| Fitts's Law | Panel and website | fail, fixed | Summary and header links under 44 px (see above). Primary buttons are 48 px tall and full width in the panel. |
| Cognitive Load | Panel review view | pass | Four required fields and a collapsed optional group; each field says in words whether it was captured, edited, or not found. |
| Miller's Law | Panel review view | pass | Six groups at most on screen (photos, title, description, price, category, seller group). |
| Chunking | Panel and S2 | pass | Fields are grouped; the optional seller group is collapsed. |
| Serial Position Effect | Panel result view | pass | The score region is first; the exits ("See full explanation", "Check another listing") sit at the end. |
| Peak-End Rule | Panel failure and result views | pass | Failure is calm, keeps the draft, and ends with "Try again". The result ends with one-tap feedback. |
| Von Restorff Effect | Panel views | pass | One filled primary button per view; the development stub banner is the only tinted block. |
| Von Restorff Effect | Website S1 | fail, fixed | See above. |
| Similarity | Signal cards | pass | The three cards share one template (icon, status word, summary, chevron). |
| Common Region | Score region | pass | Score, band, and disclaimer sit in one bounded region, so the disclaimer cannot be separated from the score. |
| Proximity | Review submit bar | pass | The retention notice, the "what is missing" line, and the button are one group. |
| Prägnanz | Band icons | pass | Each band has a distinct simple shape plus text, so colour is never the only signal. |
| Jakob's Law | Panel and website | pass | Toolbar icon opens the browser side panel; labelled fields; standard unpacked-extension install steps. |
| Postel's Law | Price and category | pass | Price accepts `RM 1,250`, `1250.50`, `rm99`; category is free text with suggestions. Minor note, deferred: the seller number fields accept digits only and reject units such as "2 years". |
| Doherty Threshold | Panel checking view | pass | The stage list appears at once; there are no percentages or padded delays. |
| Zeigarnik Effect | Panel | pass | The unsent draft is restored when the panel is reopened. |
| Goal-Gradient Effect | Panel checking view | pass | Five labelled stages show how far the check has come. |
| Parkinson's Law | Panel checking view | pass | The "taking longer than usual" line appears only after 8 seconds, and only once. |
| Tesler's Law | Panel review view | pass | Capture, category mapping, and "unknown, not suspicious" handling absorb complexity instead of asking the buyer. |
| Selective Attention | Panel and result | pass | The disclaimer is inside the score region, not a footer that people filter out. |
| Aesthetic-Usability Effect | Both surfaces | pass | One shared token set and component set; no second visual language. |
| Occam's Razor | Panel flow | pass | The review step is an extra click, kept because a check on a wrongly read listing would be wrongly informed. |
| Pareto Principle | Panel flow | pass | Effort went to capture, review, and result; seller details are an optional second click. |
| Choice Overload | Category field | pass | The 12 trained categories are only suggestions in a datalist. |
| Paradox of the Active User | Panel review and result views | fail, fixed | Adding seller details (open the seller page and click the icon again) was only explained inside a collapsed group, so a buyer who skipped reading got a result with the behavioural signal unknown and no hint why. The seller group is now open by default with a prompt that says why the details matter and how to add them, and the result view says how to include them when the behavioural signal is unknown. The website form got the same open group and wording. Tests added first. |
| Flow | Website handoff | waived | The handoff shows a browser confirmation dialog, which interrupts the task. Accepted: it is the security control for session fixation (see the security review) and appears only when following an extension link. |
| Uniform Connectedness | n/a | not applicable | No connectors are used. |

## Follow-up, 2026-11-02

The final design pass changed the wording and the look of both surfaces; the findings above still hold. What moved: the "Seller information" summary is now "Seller details (recommended)" (still 44 px tall), the signal cards are called Photos, Wording and Seller and price and sit in one bordered group, the review form no longer repeats "Captured" or "Not found" beside every field, and the panel's start screen lists what the three checks look at. The extension was run against the trained API and the production website on real listings (`docs/evidence/2026-11-02-real-use-check.md`); the e2e layout tests (6) pass.
