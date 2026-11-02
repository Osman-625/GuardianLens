# Where the build differs from the specification

Written 2026-10-15, updated 2026-11-02 after the final design pass. The documents in `docs/spec/` are the supplied pre-implementation specification and are kept as supplied, except the design brief (typeface, tokens, components, wording) and the app-flow button names, which were brought up to date on 2026-11-02. This file lists where the code now differs from the specification.

| Area | Specification | Now |
| --- | --- | --- |
| Storage | Supabase Postgres with RLS, buckets, a research schema and a hold-out trigger | One SQLite file, `data/guardianlens.sqlite3` (`api/repositories/assessments.py`). Only the scrubbed title, the structured inputs and the result are stored. The description, the raw wording and the photos are never written. |
| Admin | Admin page, bundle list, record list, CSV export | Removed, with the admin token and every Supabase key. The research data is read from the SQLite file with any SQLite tool. |
| Browser extension | Out of scope | Added, approved by the supervisor on 2026-10-05. It reads one listing only when the buyer clicks. |
| Text model | XLM-RoBERTa fine-tune | TF-IDF word and character features plus text cues with logistic regression (the XLM-R run collapsed). |
| Behavioural signal | Plain seller-risk explanation | The card states that the model learned "has a full seller profile", which in the annotated data mostly separates the two marketplaces, so a good profile does not mean a safe listing. |
| Language gate | Chinese-dominant text refused | Text mostly in any non-Latin script (Chinese, Tamil, Thai, Arabic and similar) is refused. |
| Latency evidence | Harness in `ml/` | `scripts/time_checks.py` times real checks over HTTP. The server warms its models at start-up so the first check is not slow. |
| Typeface | Inter, named in the styles but never loaded | Public Sans for text and Newsreader for titles, both bundled with the website and the extension (Chrome blocks remote fonts in an extension). The design direction and the choice are recorded in `.impeccable.md`. |
| Visual language | Cool grey page, blue primary buttons, an eye in a navy tile as the mark | Ink navy on warm paper, navy primary buttons, a lens-ring mark that matches the score dial, flat cards with no resting shadow, no eyebrow labels, the three checks in one bordered group. Light only. |
| Names of the checks | Visual, Textual, Behavioural | Photos, Wording, Seller and price. The third also reads the listing price. The report and the code keep the original names. Set in `shared/src/copy.ts`. |
| Method names | Not specified | Never shown to buyers: no model bundle, timing or "analysed using" line, and the scope notes use plain words. The data stays in the API response and the explanation page keeps the elements, hidden. One switch, `SHOW_MODEL_DETAILS`, shows them again. The test-mode warning is still shown. |
| Buttons and labels | "Assess listing", "Seller information (optional)" | "Check listing" on the site and in the panel. "Seller details (recommended)", open by default, because the third check needs it. |
| Notices | Retention: "... remains an open supervisor item ..."; disclaimer: "cannot confirm whether a listing is fraudulent" | Retention: "Contact details are removed from your text before it is stored. How long results are kept has not been decided yet." Disclaimer: "It cannot confirm that a listing is fraudulent or safe." The meaning is unchanged; the period is still open item O-4. |
| Form draft | The unsubmitted draft persists for the session | It persists until a check completes, then it is cleared, so the next listing does not inherit the last one's seller details. A failed or cancelled check keeps it. |
| Result cards | A scope note under every card | The scope note appears on the explanation page only, so a card stays one finding long. |
| Security patch | Next.js 16.4.0 | Next.js 16.4.3 (and `eslint-config-next`), because `npm audit` reported a critical advisory in 16.0.0 to 16.4.0. The app uses none of the affected features; the gate had to pass. |
| Reasons | A general sentence per feature | Each reason states the listing's own value ("The seller rating (4.8) raised the risk estimate"), with plain numbers ("1 day", "1,500,000"). |
| Seller page text | Not specified | The number patterns in `extension/lib/capture/seller.ts` run in linear time. A page of 100,000 digits used to freeze the panel for about 100 seconds; the slowest input now takes under 0.3 seconds, pinned by a test. |
| Request time limit | Not specified | The API client ends a request that gets no answer (30 seconds, 120 for the photo upload) and treats it as "could not be reached". The panel tries a lost request up to three times, then shows a failure, so a hung server cannot leave it spinning. |
| Score direction | A 0 to 100 risk score, higher is riskier | The score shown is 100 minus the estimated risk, so 100 is the lowest estimated risk and 0 the highest. The conversion is done once in the API (`api/services/trained_models.py`, `api/services/orchestrator.py`); the models, signal probabilities and band cut-offs are unchanged, and the band is still decided from the unrounded risk. Checks saved before 2026-10-20 keep the old direction. |

Open items that are unchanged: the retention period (O-4), the ethics workflow (O-3), and the user study, which waits.
