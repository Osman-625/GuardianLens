// Explanation page: the depth behind a result, grouped by signal, plus the full list of manual
// checks. The browser extension's side panel links here ("See full explanation"), optionally to
// one signal's section (#visual, #textual, #behavioural).
//
// Like the result page it first completes any extension handoff in the URL, then loads the result.
// Because the content loads after the page opens, the browser's own jump to "#visual" would find
// nothing; the second effect scrolls to that section once the content is on screen.
"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  BAND_ROUNDING_NOTE,
  DevBanner,
  Icon,
  NO_REASON_COPY,
  SHOW_MODEL_DETAILS,
  SIGNAL_ICONS,
  SIGNAL_NAMES,
  sentenceCase,
} from "@guardianlens/shared";
import { apiFetch } from "@/lib/api";
import type { AssessmentResult } from "@/lib/types";
import { useSessionClaim } from "@/lib/useSessionClaim";

/** Renders the explanation: one section per signal, then the manual checks and the disclaimer. */
export default function ExplanationPage() {
  const params = useParams<{ id: string }>();
  const claimed = useSessionClaim();
  const [result, setResult] = useState<AssessmentResult | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Load the result once any session handoff has finished.
  useEffect(() => {
    if (!claimed) return;
    apiFetch<AssessmentResult>(`/api/v1/assess/${params.id}/result`)
      .then(setResult)
      .catch(() =>
        setLoadError(
          "This explanation could not be loaded. It may belong to a different browser session.",
        ),
      );
  }, [params.id, claimed]);

  // Scroll to the section named in the address (for example #visual) once the content exists.
  useEffect(() => {
    if (!result) return;
    const target = window.location.hash.slice(1);
    if (target) document.getElementById(target)?.scrollIntoView();
  }, [result]);

  if (loadError)
    return (
      <main className="page">
        <p className="error-text">{loadError}</p>
      </main>
    );
  if (!result)
    return (
      <main className="page">
        <div className="loading">Loading explanation…</div>
      </main>
    );

  return (
    <main className="page">
      <Link className="back-link" href={`/assess/${params.id}`}>
        <Icon name="arrow-left" />
        Back to result
      </Link>
      {result.development_stub && <DevBanner />}
      <h1 className="page-title">Why you got this result</h1>
      <p className="page-lead">Reasons are grouped by check. Anything missing counts as unknown.</p>

      {result.signal_cards.map((card) => (
        <section className="card explanation-section" id={card.signal} key={card.signal}>
          <h2>
            <span className="signal-icon">
              <Icon name={SIGNAL_ICONS[card.signal]} />
            </span>
            {SIGNAL_NAMES[card.signal]}
          </h2>
          {/* A check that ran names its model in the summary: kept in the page, hidden from buyers. */}
          <p hidden={card.available && !SHOW_MODEL_DETAILS}>
            {!card.available && <strong>{sentenceCase(card.status_word)}. </strong>}
            {card.summary}
          </p>
          {card.reasons.length > 0 ? (
            <ul className="reason-list">
              {card.reasons.map((reason) => (
                <li
                  className={`reason reason-${reason.direction}`}
                  key={`${reason.feature_key}-${reason.rank}`}
                >
                  <span className="reason-direction">
                    <Icon name={reason.direction === "raises" ? "arrow-up" : "arrow-down"} />
                    {sentenceCase(`${reason.direction} risk`)}
                  </span>
                  {reason.display_text}
                </li>
              ))}
            </ul>
          ) : (
            <p className="helper">{NO_REASON_COPY}</p>
          )}
          {card.scope_note && <p className="scope-note">{card.scope_note}</p>}
        </section>
      ))}

      {/* Same card spacing as the signal sections above, so "Back to result" does not touch it. */}
      <section className="card explanation-section">
        <h2>Before you pay</h2>
        <ol className="check-list">
          {result.suggested_checks.map((check) => (
            <li key={check}>{check}</li>
          ))}
        </ol>
        <p className="disclaimer">{result.disclaimer}</p>
        <p className="helper">{BAND_ROUNDING_NOTE}</p>
      </section>

      <div className="action-row">
        <Link className="button button-secondary" href={`/assess/${params.id}`}>
          <Icon name="arrow-left" />
          Back to result
        </Link>
      </div>
      {/* Model name and timing: kept for the researcher, hidden from buyers. */}
      <p className="footer-note" hidden={!SHOW_MODEL_DETAILS}>
        Model {result.model_bundle_label} · {result.total_latency_ms} ms
      </p>
    </main>
  );
}
