# GuardianLens Rule-Based Weak-Labeling: Rule Documentation

Every rule below corresponds 1:1 to an entry in `scam_rules.yaml` by `rule_id`. This file is a
narrative companion, not the source of truth for thresholds/weights (those live in the YAML).
`enabled: false` rules are disabled deliberately (missing evidence, or a matching method that is
a stub pending a follow-up task) — never silently faked to look implemented.

## A. Critical fraud indicators

### A1_SEMAK_MULE_PHONE / A2_SEMAK_MULE_BANK
- **What it detects:** a phone number or bank account confirmed on Semak Mule's public
  scam-database lookup.
- **Why relevant:** direct confirmation from Malaysia's national mule-account registry, the same
  authority Mudah.my's own Help Center tells sellers/buyers to check suspicious bank accounts
  against ("Verify suspicious bank account numbers with CCID for assurance").
- **Strength:** critical.
- **Fields used:** `semak_mule_phone_hit`, `semak_mule_bank_hit` (currently always NULL).
- **Limitations:** **disabled** — this dataset was never checked against Semak Mule; the spec
  forbids scraping or fabricating this at annotation-prep time.
- **Possible false positives:** N/A while disabled.
- **Source:** [Mudah.my - How to protect yourself from scam?](https://mudah.zendesk.com/hc/en-us/articles/900002244066-How-to-protect-yourself-from-scam-);
  [National Scam Response Centre (NSRC)](https://nfcc.jpm.gov.my/index.php/en/about-nsrc).

### A3_A7_CREDENTIAL_REQUEST
- **What it detects:** text asking for OTP, TAC, PIN, CVV, bank password/login.
- **Why relevant:** Carousell's own Help Centre names this explicitly: "an honest buyer or
  seller will never need this information outside of the app."
- **Strength:** critical.
- **Fields used:** `description` (via `keyword_patterns.yaml: credential_request`).
- **Limitations:** literal keyword match only; a scammer paraphrasing without these exact terms
  is missed.
- **Possible false positives:** a seller warning buyers *not* to share OTP/PIN could false-fire;
  the review queue surfaces every match for exactly this reason.
- **Source:** [Carousell - How to Stay Safe on Carousell](https://support.carousell.com/hc/en-us/articles/48856945791641-How-to-Stay-Safe-on-Carousell);
  [Carousell - Phishing Scam Awareness & Prevention Guide](https://support.carousell.com/hc/en-us/articles/45586149269657-Phishing-Scam-Awareness-Prevention-Guide).

### A8_A9_PHISHING_URL / A10_IMPERSONATION_PLUS_PAYMENT
- **What it detects:** suspicious/phishing URLs, or platform/bank impersonation paired with a
  payment or credential ask.
- **Strength:** critical.
- **Limitations:** **disabled** — `url_suspicious` and `keyword_combo:*` matching methods are
  stubbed to always-false in `evaluator.py` pending a follow-up domain-heuristics/multi-category
  re-check task; disabled is more honest than a fabricated implementation.
- **Source:** [Carousell - Phishing Scam Awareness & Prevention Guide](https://support.carousell.com/hc/en-us/articles/45586149269657-Phishing-Scam-Awareness-Prevention-Guide).

## B. Payment scam patterns

### B1_ADVANCE_PAYMENT_WEAK / B2_ADVANCE_PAYMENT_STRONG
- **What it detects:** deposit/advance-payment language, weak when bare ("deposit"), strong
  when qualified with urgency/amount/pre-inspection framing.
- **Why relevant:** advance-payment-then-vanish is the most common Malaysian marketplace scam
  pattern; Mudah.my's own Trust & Safety page leads with this exact warning ("Beware of scammers
  requesting for an upfront deposit").
- **Fields used:** `description`.
- **Limitations:** legitimate sellers also sometimes request deposits for high-value/custom
  items — hence weak alone, never scam alone.
- **Source:** [Mudah.my Trust and Safety](https://www.mudah.my/trust-and-safety);
  [Carousell - For Buyers: Common scams to look out for](https://support.carousell.com/hc/en-us/articles/8233371527833-For-Buyers-Common-scams-to-look-out-for).

## C. Agent/courier/release fee

### C1_RELEASE_FEE
- **What it detects:** any fee framed as required to *receive* or *release* money.
- **Why relevant:** no legitimate payment flow ever requires the *payee* to pay to receive
  funds — this is close to a definitional scam pattern.
- **Strength:** strong.
- **Source:** general Bank Negara Malaysia / NSRC public advisories on release-fee scams
  (no single article URL found during this pass — TODO(source): revisit with a more targeted
  search when time allows).

## D. Fake payment confirmation

### D1_FAKE_PAYMENT_CONFIRMATION / D2_FAKE_PAYMENT_CONFIRMATION_PLUS_LINK
- **What it detects:** claims of a completed/pending payment (including "here's the payment
  screenshot"), escalated when paired with a link or credential request.
- **Limitations:** D2 (the combo escalation) is **disabled** — same `keyword_combo` stub
  limitation as A10.
- **Source:** [Carousell - How to Stay Safe on Carousell](https://support.carousell.com/hc/en-us/articles/48856945791641-How-to-Stay-Safe-on-Carousell)
  ("Never ship an item based on a screenshot of a payment confirmation; always log in to your
  bank account independently to confirm funds have cleared.");
  [Vinted scams explained (Norton)](https://us.norton.com/blog/online-scams/vinted-scams)
  (fake payment-confirmation screenshots are a named Vinted-specific pattern too, confirming this
  is cross-platform, not Malaysia-specific).

## E. Off-platform activity

### E1_OFF_PLATFORM_WEAK / E2_OFF_PLATFORM_PLUS_PAYMENT
- **What it detects:** WhatsApp/Telegram/off-platform contact mentions; weak alone (extremely
  common and legitimate), strong only combined with payment/fee/credential pressure.
- **Limitations:** E2 (the combo escalation) is **disabled** — same `keyword_combo` stub
  limitation as A10; only E1 (weak alone) is live.
- **Source:** [Carousell - How to Stay Safe on Carousell](https://support.carousell.com/hc/en-us/articles/48856945791641-How-to-Stay-Safe-on-Carousell)
  ("Scammers often try to move conversations to other chat platforms... if a user insists on
  switching apps, it's a red flag" — note the flag is the *insistence*, not the mention, which is
  exactly why this rule is weak-alone);
  [Vinted Buyer Scams: 9 Red Flags](https://www.zipsale.co.uk/blog/red-flags-of-fake-buyers-on-vinted).

## F. Platform/staff impersonation

### F1_IMPERSONATION_WEAK / F2_IMPERSONATION_PLUS_VERIFICATION
- **What it detects:** claims of being Carousell/Mudah/bank/courier staff.
- **Limitations:** F2 (the combo escalation) is **disabled** — same stub limitation as A10.
- **Source:** [Carousell - For Sellers: Common scams to look out for](https://support.carousell.com/hc/en-us/articles/8234913048217-For-Sellers-Common-scams-to-look-out-for).

## G. Suspicious links

### G1_SUSPICIOUS_URL
- **What it detects:** URL shorteners/IP-literal/typosquat domains in listing text.
- **Limitations:** **disabled** — stubbed to always-false pending a follow-up domain-heuristics
  task (see A8_A9 above) — not implemented with fabricated logic.
- **Source:** common public phishing-URL heuristics; [Facebook Marketplace scam guide (Empeople)](https://empeople.com/learn/empeople-insights/facebook-marketplace-scams/)
  (reverse image search / suspicious-link guidance, cross-platform pattern).

## H. Price anomalies

### H1_PRICE_ANOMALY
- **What it detects:** price far below the same-category/platform median, tiered by
  `price_ratio`.
- **Limitations:** requires >=5 comparable listings (category x platform); many category
  buckets in this 2,209-row dataset will not meet that bar and simply won't get a
  `price_ratio` — this is intentional, not a bug.
- **Source:** [Mudah.my - How to protect yourself from scam?](https://mudah.zendesk.com/hc/en-us/articles/900002244066-How-to-protect-yourself-from-scam-)
  ("Watch Out for Suspicious Offers... if the vehicle is significantly under-priced, it might not
  be similar to the condition listed in photos");
  [Carousell - For Buyers: Common scams](https://support.carousell.com/hc/en-us/articles/8233371527833-For-Buyers-Common-scams-to-look-out-for)
  ("A brand-new iPhone for half the retail price is a massive red flag").

## I. Image reuse/duplication

### I1_CROSS_LISTING_IMAGE_REUSE / I2_IMAGE_REUSED_MANY_LISTINGS
- **What it detects:** a listing's image(s) perceptually matching image(s) in unrelated
  listings (from the existing `dataset_validation_summary.json` pHash audit).
- **Limitations:** cannot distinguish "same seller re-listing their own item" from "different
  seller reusing a stock photo" without reliable cross-platform seller-identity linkage —
  evidence includes the related listing IDs so a human reviewer makes that call.
- **Source:** internal pHash audit (`reports/dataset_validation_summary.json`);
  [Facebook Marketplace scam guide (Empeople)](https://empeople.com/learn/empeople-insights/facebook-marketplace-scams/)
  ("Multiple posts of the same item using the same picture across different locations" — an
  independent platform confirming this exact pattern).

## J. Description duplication

### J1_DESCRIPTION_NEAR_DUPLICATE
- **What it detects:** near-identical description text (5-word shingle Jaccard >= 0.6) across
  unrelated listings.
- **Limitations:** threshold (0.6) is a starting default, not validated against labeled data
  yet — tune after some human review/override history accumulates.
- **Source:** internal text-similarity heuristic; no external citation applies.

## K. Seller behavioural signals

### K1_NEW_ACCOUNT / K2_YOUNG_ACCOUNT / K3_ZERO_REVIEWS / K4_POOR_RATING_SUFFICIENT_REVIEWS
- **What it detects:** young accounts, confirmed-zero reviews, or poor rating with enough
  reviews to be meaningful.
- **Limitations:** each is explicitly weak/medium alone per the spec's stated rule
  ("new_account alone != scam") — corroborated by every platform's guidance reviewed (none of
  them treat a new account alone as disqualifying).
- **Source:** [Vinted Buyer Scams: 9 Red Flags](https://www.zipsale.co.uk/blog/red-flags-of-fake-buyers-on-vinted)
  ("Check account age... number of positive ratings... an empty profile created recently is a
  red flag" — always framed as one factor among several).

## L. Trust signals

### L1_OLD_ACCOUNT / L1B_MODERATELY_OLD_ACCOUNT / L2_STRONG_RATING / L3_REASONABLE_PRICE
- **What it detects:** positive counter-evidence that reduces (never zeroes out) risk.
- **L1 vs L1B:** two tiers instead of one cliff at 365 days — Vinted's own stated trust
  threshold is 6 months, not 1 year, so `L1B_MODERATELY_OLD_ACCOUNT` (180-364 days) contributes a
  smaller trust weight than the full-strength `L1_OLD_ACCOUNT` (>=365 days).
- **Limitations:** per spec, trust signals must never override a critical rule match — enforced
  in `evaluator.py` by checking `critical_rule_count` first, independent of `trust_score`.
- **Source:** [Vinted scams explained (Norton)](https://us.norton.com/blog/online-scams/vinted-scams);
  [Is Vinted Legit? (TopBubbleIndex)](https://www.topbubbleindex.com/blog/is-vinted-legit/)
  ("Check account age (>6 months)...").

## M. Contradictions

### M1_CATEGORY_KEYWORD_MISMATCH
- **What it detects:** a small, hand-curated set of unambiguous category/title conflicts.
- **Limitations:** **disabled** — ships with no curated conflict pairs yet, ready to extend, but
  deliberately not populated with guessed pairs.
- **Source:** internal conservative heuristic; no external citation applies.

---

## Signals confirmed relevant by external sources but NOT yet encodable from GuardianLens's schema

These are documented here rather than faked as rules, per the Phase-1 gap analysis:

- **Seller "goes missing" or blocks the buyer after payment** (Carousell, Vinted) — requires
  conversation/message-thread data; GuardianLens only captures a single listing snapshot, not a
  conversation history.
- **Bank account name differs from the seller/company name** (Mudah.my) — GuardianLens does not
  capture a bank-account-holder-name field at all.
- **Buyer pressuring urgency in live conversation** (Facebook Marketplace, Carousell) — distinct
  from `has_urgency_language` (listing-text urgency), which IS encoded; conversation-level
  urgency pressure is not captured by this dataset.
