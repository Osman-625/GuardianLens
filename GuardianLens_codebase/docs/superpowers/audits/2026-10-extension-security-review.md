# Extension and detail site security review

Date: 2026-10-05. Scope: the session handling added for the browser extension (header session
token, session minting and claim, capture metadata, CORS) in `api/`, plus the website handoff
confirmation. Method: an independent review by the `security-reviewer` agent, which read the code
and drove the real app through its test client with throwaway probes. It found no critical or high
issue. Every finding is listed here with what was done.

## Fixed on this branch (each with a test that failed first)

| Finding | Severity | What was wrong | Fix and test |
| --- | --- | --- | --- |
| M1 | Medium (latent) | `POST /session/claim` ran for a request from any origin when the body carried no Content-Type, because the browser treats that as a simple request and skips the CORS preflight. A page on another site could make a visitor's browser adopt the page's session (login CSRF and session fixation), skipping the website's confirmation dialog. It was held back only by `SameSite=Lax` on the cookie, which would have to be loosened for a hosted deployment on two domains. The same gap existed on the cookie-authenticated writes: submit, cancel, and feedback. | `require_trusted_origin` in `api/dependencies.py`, called first in claim, submit, cancel, and feedback. A browser request whose `Origin` is not a configured website origin gets 403 `origin_not_allowed`. No `Origin` (scripts) and requests carrying `X-Session-Token` (the extension) pass. Tests in `api/tests/test_sessions.py`. |
| L1 | Low | `capture_meta.adapter_version` accepted 40 characters of free text (a URL, a phone number, an email), stored unscrubbed, contradicting the "no free text in capture metadata" promise used in the privacy statement. | The field now accepts only a plain version number (`1`, `1.2`, `1.2.3`). Tests in `api/tests/test_capture_meta.py`. |
| L2 | Low | The claim route's docstring said it could not be used to test which tokens exist; a 204 versus a 404 does exactly that. | Docstring corrected. The real protection is the token's size (a random UUID, 122 bits), and the route now also refuses foreign origins. No behaviour change. |
| L5 (note 2) | Low | Nothing stopped `GUARDIANLENS_ALLOWED_ORIGINS=*` while the API sends credentials, which would let any site read a visitor's results. | The settings refuse a wildcard origin at startup. Test in `api/tests/test_sessions.py`. |

## Accepted for the laptop prototype, required before any hosted deployment

| Finding | Severity | Detail | Required before hosting |
| --- | --- | --- | --- |
| M2 | Medium once reachable beyond localhost | Session minting is unauthenticated and unthrottled, and the rate limit is keyed by session, so it does not bound a determined client (15 submissions with 15 fresh tokens were all accepted). Cost: image processing and memory per submission, polluted research records, unbounded growth of the limiter's dictionary, and unbounded session rows in a hosted database. | A coarse per-IP limit or global cap on minting and submission; eviction or expiry for sessions and limiter entries. The spec (section 4.3) now states the real impact. |
| M2 (related, low) | Low | A cookie-less submit creates its session before the fields are validated, so an invalid submission still mints a session. | Create the session after validation, or just before the record is saved. |
| L3 | Low, contingent on hosting | Tokens are long-lived bearer secrets with no expiry, rotation, or revocation. A token an attacker keeps from a fixation attempt never expires; with a hosted database, read access to the sessions table exposes every live token. The `#st=` fragment may also remain in the browser history entry for the original navigation (not verified). | Session expiry; store a hash of the token; consider a single-use short-lived handoff code. |
| L4 | Low | `source` and `capture_meta` are client-asserted, so any script can claim to be the extension. They never feed the score. | Treat them as self-reported telemetry when reading the extension versus manual comparison. Stated in the spec. |
| L5 (note 1) | Low | `X-Session-Token` is in the CORS allowed headers although the website uses cookies and the extension bypasses CORS through its host permission, so nothing needs it. It is harmless because only configured origins can use it. | Optional least-privilege cleanup; a test currently pins it. |

## Questions asked and answers

1. Header and cookie mixing cannot bypass ownership: exactly one session id is resolved per request, a present but invalid header never falls back to the cookie, and other-owner, nonexistent, and unknown-session reads return identical 404 bodies.
2. Enumeration and brute force are not feasible (122-bit random tokens, malformed tokens get a field-name-only 422), but the claim route is an existence oracle and unthrottled; see L2 and M2.
3. `capture_meta` cannot carry a listing URL through any field except `adapter_version`, which is now constrained (L1).
4. Session minting: see M2.
5. No code logs the token. The only place a token is printed is the developer script `scripts/dev_handoff_demo.py`.
6. CORS does not widen access beyond the configured origins.

## Is the website confirmation enough?

For the crafted-link scenario at prototype scale, yes: the token is removed from the address bar
first, a dialog that cannot be shown counts as a "no", and the text states the consequence. It was
not a server-enforced control, which is what M1 exposed; the origin guard now backs it on the
server. The remaining weakness is that a token an attacker holds does not expire (L3).
