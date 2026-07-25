# GuardianLens: Design Brief (UI/UX)

**Status:** Working draft for supervisor review. Section 3 tokens are proposal P-7 (document 00) and may be adjusted without touching frozen requirements, provided every binding rule in section 1 still holds. Section 6 is the requested UX-laws audit, applied prescriptively to the seven Chapter 3 screens using the 30-law Laws of UX set (Yablonski, lawsofux.com).

---

## 1. Binding design rules (fixed by Chapter 3; not style preferences)

1. Plain language throughout; written for a non-expert buyer (s.3.3.6, NFR-01).
2. Progressive disclosure: summary on S4, depth on S5 (s.3.3.6).
3. Mobile responsive; verified at 375 px, 768 px, 1440 px (NFR-03, Table 3.9).
4. Risk communicated by text, number, and iconography; colour is never the only carrier (s.3.3.6, NFR-08).
5. Visible uncertainty: unavailable signals are named and framed as unknown (FR-06, NFR-04).
6. No false precision: integer score, no decimals (s.3.3.6).
7. Disclaimer visible wherever a score is shown; GuardianLens is decision support, not a verdict (NFR-10).
8. Data retention explained next to the submission control (s.3.3.6; wording pends open item O-4).
9. Errors identify what to fix and never discard valid input (s.3.3.6).
10. WCAG 2.1 AA contrast and labelled controls, audited (NFR-08).

---

## 2. Look and feel

**Tone:** calm, factual, and slightly institutional. The product's whole value rests on the buyer trusting an uncomfortable message, so the register is closer to a lab report written in plain words than to a consumer security product. Nothing alarmist: a High band should read as serious information, not a siren. Nothing celebratory: a Low band is "no strong warning signs found", never "safe to buy" (that phrasing would violate NFR-10 by implication).

**Brand identity basics:** wordmark "GuardianLens" set in the interface typeface, semibold, with a simple lens-ring mark. No mascots, no shield-and-padlock clichés (they overpromise protection), no imagery of money or handcuffs. Illustration is limited to small neutral glyphs for the three signals: an image glyph (visual), a text-lines glyph (textual), a person-with-clock glyph (behavioural).

**Language:** interface copy in English for the FYP2 prototype. Rationale: every survey respondent encountered English listings and the study protocol is English-based; a Malay UI translation is a candidate future-work item, not a silent addition. This is a scoping statement, not a claim about user preference.

---

## 3. Design system basics (proposal P-7)

### 3.1 Colour palette

CSS custom properties (code identifiers keep the `color` spelling by convention). All text-background pairs must pass the WCAG 2.1 AA check (4.5:1 normal text, 3:1 large text) in the NFR-08 audit before release; the pairs below are chosen to pass but the audit, not this table, is the proof.

| Token | Hex | Use |
| --- | --- | --- |
| `--color-ink` | #1A2332 | Primary text on light surfaces |
| `--color-ink-muted` | #4A5568 | Secondary text, captions |
| `--color-surface` | #FFFFFF | Cards, sheets |
| `--color-surface-alt` | #F4F6F8 | Page background |
| `--color-border` | #D7DEE6 | Card borders, dividers |
| `--color-primary` | #1D4ED8 | Primary actions, links, focus ring base |
| `--color-primary-ink` | #FFFFFF | Text on primary |
| `--color-risk-low` | #1E7A46 | Low band accents (with icon + label) |
| `--color-risk-moderate` | #9A5B00 | Moderate band accents (with icon + label) |
| `--color-risk-high` | #B42318 | High band accents (with icon + label) |
| `--color-risk-unknown` | #4A5568 | Missing-signal state |
| `--color-danger` | #B42318 | Destructive admin actions only |

Band colours are deliberately dark enough to work as text on white; tinted backgrounds (band colour at low alpha over `--color-surface`) carry the band ink colour for text. Never place band colour on band colour.

### 3.2 Typography

System-safe stack with one webfont: Inter (covers Malay diacritics for listing text display), fallback `system-ui, -apple-system, Segoe UI, Roboto, sans-serif`. Tabular numerals for the score.

| Level | Size / line height | Weight | Use |
| --- | --- | --- | --- |
| Display | 44 / 48 | 700 | The score number on S4 only |
| H1 | 28 / 34 | 650 | Screen titles |
| H2 | 20 / 28 | 600 | Card titles, S5 section heads |
| Body | 16 / 24 | 400 | Default copy; never below 16 px for body on mobile |
| Small | 14 / 20 | 400 | Captions, retention notice, timestamps |
| Label | 13 / 16 | 550, +0.02em | Band chips, field labels |

### 3.3 Spacing, radius, elevation

4 px base grid; component padding 16; card gap 12; page gutter 16 (mobile) / 24 (tablet) / centred 720 px content column (desktop, single-column by design). Radius: 12 cards, 10 buttons, 8 inputs. Elevation: borders first, one soft shadow level for sheets and the sticky submit bar only.

### 3.4 Key components

| Component | Spec |
| --- | --- |
| Primary button | Full-width on mobile, min height 48 px, `--color-primary`; disabled state keeps label readable and explains why via helper text above it |
| Score dial | Integer 0 to 100, Display type, band chip directly beneath (icon + band word + one-line meaning), single count-up on first render, none on revisit |
| Band chip | Icon + text label + tinted background; identical shape for all bands so colour is never the sole differentiator; distinct icons per band (tick-circle, alert-triangle, alert-octagon) plus a question-circle for unknown |
| Signal card | Header (glyph + name + status word: "clear", "warning signs", "limited information"), one-sentence reason, chevron; states: available, degraded, unavailable; unavailable copy is fixed: "Not enough information. Treated as unknown, not as suspicious." |
| Suggested-checks list | Checklist styling but not persisted checkboxes (avoids implying completion is tracked); each item one imperative sentence; Semak Mule item links out with an external-link icon |
| Uploader | Tap-or-drop target min 120 px tall; per-file thumbnail, name, size, remove; per-file inline errors |
| Progress stages (S3) | Five labelled stages with three states (done, active, pending); active stage animates; honest "taking longer than usual" line after a threshold; no percentages |
| Disclaimer block | Small type, `--color-ink-muted`, border-top; identical text everywhere it appears |
| Toast | Bottom, auto-dismiss 4 s, never carries information available nowhere else |
| Empty states | History: "No listings checked this session yet" + primary CTA to S2 |

### 3.5 Motion and feedback

Every tap acknowledges within 100 ms (state change or skeleton). Transitions 150 to 200 ms, ease-out, opacity and small translate only. Respect `prefers-reduced-motion`: disable the count-up and stage pulse. No looping attention-seeking animation anywhere near the score.

---

## 4. Screen style guidelines

| Screen | Structure (top to bottom) | Notes |
| --- | --- | --- |
| S1 Landing | Wordmark bar → one-sentence purpose → primary CTA → three explainer blocks (checks / cannot guarantee / data handling) → footer | CTA appears once above the fold and once after the blocks; both go to S2 |
| S2 Submission | Title bar → uploader → title, description (textarea with counter), price + category row → collapsible "Seller information (optional)" group → retention notice → sticky submit bar | Optional seller group is collapsed by default with the FR-06 reassurance line in its summary |
| S3 Processing | Centered card: listing thumbnail + title → five stages → cancel (text button) | Nothing else competes for attention |
| S4 Result | Score dial + band chip → disclaimer one-liner → three signal cards → missing-data notice (if any) → suggested checks → feedback prompt → "Check another" + "This session" | Order is fixed: judgement aids (cards, checks) come before exits |
| S5 Explanation | Per-signal sections in the S4 card order; each: status, reasons (max 3 shown, "more" reveals rest), evidence scope note (visual section always carries the reference-corpus scope sentence) → checks → disclaimer | Anchored deep-links from S4 cards |
| S6 Feedback | Sheet: question → three large option rows → optional comment (with "no personal details" hint) → submit | Single-tap selection, submit enabled on selection |
| S7 Admin | Left tab rail (desktop) / top tabs (mobile): Bundles, Corpus, Records, Exports; dense tables allowed here; destructive actions require typed confirmation | Admin is the only surface where information density beats simplicity |

---

## 5. Accessibility specifics (feeds the NFR-08 audit)

Focus visible on every interactive element (2 px ring, `--color-primary`, offset 2 px). All controls labelled; uploader and dial have text alternatives ("Risk score 62 out of 100, Moderate"). Touch targets at least 44 by 44 px. S3 stage changes announced via a polite live region. Band meaning is always readable with colour vision deficiency because rule 1.4 makes colour redundant by construction. Form errors are associated to fields programmatically, not colour-only.

---

## 6. UX-laws audit (/ux-laws)

Applied prescriptively before build: each row is a named law from the 30-law Laws of UX set, the place it bites in this product, and the binding rule that satisfies it. During Phase D review, this table is re-run as a compliance check (Finding column then records pass or the observed violation).

| Law | Where it applies | Rule (pre-build fix) |
| --- | --- | --- |
| Jakob's Law | S2 form, header, history | Follow marketplace-adjacent conventions the sample already knows: labelled fields with placeholders as examples only, uploader that looks like every classifieds uploader, back behaviour that never loses input |
| Fitts's Law | S2 submit, S4 primary paths, mobile | Primary actions full-width, min 48 px tall, inside the thumb zone; sticky submit bar on S2 so the target is never far from the last field |
| Hick's Law | S2, S4 | S2 asks only what the pipelines consume; S4 offers exactly three onward choices (explanation, feedback, check another); no menus of options around the score |
| Choice Overload | Category picker on S2 | Curated category list matching the dataset's categories, searchable, most-used first; no free-text taxonomy |
| Doherty Threshold | Every tap; S2→S3 | Sub-100 ms acknowledgement everywhere; S3 skeleton and first stage render immediately on 202, before any model has run |
| Cognitive Load | S2, S4 | Field hints say what to copy from the listing so nothing is held in memory; S4 puts meaning next to every number (band word beside score, status word on every card) |
| Miller's Law | S4, S5 | S4 holds one score plus three cards plus one checks block; S5 shows at most three reasons per signal before "more" |
| Chunking | S2, S5 | S2 grouped into media / details / optional seller info; S5 sectioned per signal in the same order as S4 cards |
| Serial Position Effect | S4 vertical order, checks list | Score first, disclaimer immediately after, checks list ends with the single most protective action (independent seller verification) so it is the last thing read |
| Selective Attention | S4 | The disclaimer is styled as content within the result column, not as a banner or footer chrome, because banner-shaped elements get filtered out |
| Von Restorff Effect | S2, S4 | Exactly one visually distinct element per screen: the submit button on S2, the score-plus-band unit on S4; band colour appears nowhere else on S4 so the distinctive element is unambiguous |
| Peak-End Rule | S3→S4 reveal, failure state | The reveal is the peak: dial, band, and first reason land together, calmly; the end of a failed run is designed with equal care (calm copy, preserved input, one-tap retry) |
| Zeigarnik Effect | S3, S2 draft | Five named stages make the open loop legible and finite; unsubmitted S2 input persists for the session so an interrupted attempt invites completion |
| Goal-Gradient Effect | S2, S3 | Optional seller group is last and collapsed so the form visibly shortens near the end; S3's final stage ("explanation") is genuinely the shortest, so perceived acceleration is honest |
| Postel's Law | S2 inputs | Accept messy pasted titles and descriptions (whitespace, emoji, mixed language), prices with "RM", commas, or spaces; normalise server-side; output stays strict (integer score, fixed band vocabulary) |
| Paradox of the Active User | Onboarding | No tutorial; S1 sets expectations in three glances and S2 teaches itself via hints; nothing critical depends on reading first |
| Tesler's Law | Whole system | Irreducible complexity (fusion, calibration, SHAP) is absorbed by the system; the buyer supplies only what is on the listing page; the one complexity that must surface (uncertainty from missing signals) surfaces in fixed plain sentences, not raw numbers |
| Aesthetic-Usability Effect | All buyer screens | Polish is a trust requirement, not decoration: a scruffy fraud tool reads as a scam itself; the token system and spacing grid exist to make polish cheap and consistent |
| Occam's Razor | Layout | Single-column buyer flow at every breakpoint; no dashboard patterns outside S7 |
| Pareto Principle | Effort allocation | J1 (submit → result) carries almost all usage; S2, S3, S4 get the deepest design and test effort; S7 accepts utilitarian density |
| Parkinson's Law | S3 | Stage progression reflects real pipeline stages; no padded delays, no fake progress easing; if the run finishes early, S3 finishes early |
| Flow | S2, S3 | No interruptions mid-task: no toasts, prompts, or feedback asks before S4; the feedback prompt appears only after the result is absorbed |
| Proximity (Gestalt) | S2, S4 | Retention notice sits inside the submit group (required adjacency, rule 1.8); each card's status, reason, and chevron are tighter to each other than to neighbouring cards |
| Similarity (Gestalt) | S4, S5 | The three signal cards share one template exactly; band chips share one shape; nothing unrelated borrows the card or chip styling |
| Common Region (Gestalt) | S4 | Score + band + disclaimer share one bounded region so the caveat is perceived as part of the verdict, not detached small print |
| Uniform Connectedness (Gestalt) | S4→S5 | Tapping a card opens S5 anchored to that card's section with a matching header glyph, making the link explicit; no connector lines implying relationships that do not exist |
| Prägnanz (Gestalt) | Score dial, band icons | The dial is a plain arc and number, not a speedometer (a speedometer's simplest reading is "how fast", which is the wrong model); band icons are standard, unambiguous glyphs |

Laws intentionally recorded as not applicable at this stage: none of the 30 are excluded outright, but the foundational concepts (Cognitive Bias, Mental Model, Working Memory) are treated per the source as explanatory background for the rows above rather than separate checklist items.

**Audit protocol for Phase D:** re-run this table against the built screens at 375 px and 1440 px; every row gets pass, fail with finding, or waived with reason; failures block the usability test task, since testing a screen with known law violations wastes participants.
