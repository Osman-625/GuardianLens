// Assessment result page: the detail surface for a finished check, whether it was started from the
// browser extension or from the manual form.
//
// It first completes any extension handoff in the URL (useSessionClaim), so a check made in the
// extension can be opened here without a login, and only then loads the result. The score, band,
// and disclaimer render together in the shared ScoreRegion, and the three signal cards link to
// their sections of the explanation page.
"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  DevBanner,
  FEEDBACK_HEADING,
  FEEDBACK_OPTIONS,
  formatDateTime,
  Icon,
  ScoreRegion,
  SignalCardView,
} from "@guardianlens/shared";
import { apiFetch } from "@/lib/api";
import type { AssessmentResult } from "@/lib/types";
import { useSessionClaim } from "@/lib/useSessionClaim";

/** Renders the finished result: score region, signal cards, notices, checks, and feedback. */
export default function ResultPage() {
  const params = useParams<{ id: string }>();
  const claimed = useSessionClaim();
  const [result, setResult] = useState<AssessmentResult | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showFeedback, setShowFeedback] = useState(false);
  const [verdict, setVerdict] = useState<string>("");
  const [comment, setComment] = useState("");
  const [feedbackState, setFeedbackState] = useState<"idle" | "saving" | "saved">("idle");
  const [feedbackFailed, setFeedbackFailed] = useState(false);

  // Load the result once any session handoff has finished.
  useEffect(() => {
    if (!claimed) return;
    apiFetch<AssessmentResult>(`/api/v1/assess/${params.id}/result`)
      .then(setResult)
      .catch(() =>
        setLoadError(
          "This result could not be loaded. It may belong to a different browser session.",
        ),
      );
  }, [params.id, claimed]);

  // Sends the chosen verdict and optional comment, then shows the thank-you state.
  async function submitFeedback(event: FormEvent) {
    event.preventDefault();
    if (!verdict) return;
    setFeedbackState("saving");
    setFeedbackFailed(false);
    try {
      await apiFetch<void>(`/api/v1/assess/${params.id}/feedback`, {
        method: "POST",
        body: JSON.stringify({ verdict, comment: comment || null }),
      });
      setFeedbackState("saved");
    } catch {
      // Feedback is optional: the form comes back with the choices kept, so the buyer can retry.
      setFeedbackState("idle");
      setFeedbackFailed(true);
    }
  }

  if (loadError) {
    return (
      <main className="page">
        <div className="card">
          <h1 className="page-title">Result unavailable</h1>
          <p className="error-text">{loadError}</p>
          <Link className="button button-primary" href="/assess">
            Check another listing
          </Link>
        </div>
      </main>
    );
  }
  if (!result)
    return (
      <main className="page">
        <div className="loading">Loading result…</div>
      </main>
    );

  return (
    <main className="page page-wide result-page">
      <Link className="back-link" href="/history">
        <Icon name="arrow-left" />
        This session
      </Link>
      {result.development_stub && <DevBanner />}
      <h1 className="page-title">{result.title}</h1>
      <p className="page-lead">Checked {formatDateTime(result.created_at)}.</p>

      <ScoreRegion
        id={result.assessment_id}
        score={result.score}
        band={result.band}
        disclaimer={result.disclaimer}
      />

      <div className="result-grid">
        <section aria-labelledby="signals-heading">
          <div className="section-head">
            <div>
              <h2 id="signals-heading">What shaped this result</h2>
            </div>
            <Link href={`/assess/${result.assessment_id}/explanation`}>
              Full explanation
              <Icon name="arrow-right" />
            </Link>
          </div>
          <div className="signal-grid" aria-label="Check summaries">
            {result.signal_cards.map((card) => (
              <SignalCardView
                card={card}
                href={`/assess/${result.assessment_id}/explanation#${card.signal}`}
                LinkComponent={Link}
                key={card.signal}
              />
            ))}
          </div>
        </section>

        <section className="card checks-card">
          <h2>Before you pay</h2>
          <ol className="check-list">
            {result.suggested_checks.map((check) => (
              <li key={check}>{check}</li>
            ))}
          </ol>
        </section>
      </div>

      {result.missing_data_notices.length > 0 && (
        <section className="notice">
          <strong>Limited information</strong>
          {result.missing_data_notices.map((notice) => (
            <p key={notice}>{notice}</p>
          ))}
        </section>
      )}

      <section className="card feedback-card">
        <h2>{FEEDBACK_HEADING}</h2>
        {!showFeedback && (
          <button className="button button-secondary" onClick={() => setShowFeedback(true)}>
            Give feedback
          </button>
        )}
        {showFeedback && feedbackState !== "saved" && (
          <form onSubmit={submitFeedback}>
            <div className="feedback-options">
              {FEEDBACK_OPTIONS.map(([value, label]) => (
                <label className="option-row" key={value}>
                  <input
                    type="radio"
                    name="verdict"
                    value={value}
                    checked={verdict === value}
                    onChange={() => setVerdict(value)}
                  />
                  {label}
                </label>
              ))}
            </div>
            <div className="field">
              <label htmlFor="feedback-comment">Comment (optional)</label>
              <textarea
                id="feedback-comment"
                maxLength={1000}
                value={comment}
                onChange={(event) => setComment(event.target.value)}
              />
              <span className="helper">
                Please leave out names, phone numbers and account details.
              </span>
            </div>
            {feedbackFailed && (
              <p className="error-text" role="alert">
                Feedback could not be saved. Try again.
              </p>
            )}
            <button
              className="button button-primary"
              disabled={!verdict || feedbackState === "saving"}
            >
              {feedbackState === "saving" ? "Saving…" : "Submit feedback"}
            </button>
          </form>
        )}
        {feedbackState === "saved" && <p className="success-text">Feedback saved.</p>}
      </section>

      <div className="action-row">
        <Link className="button button-primary" href="/assess">
          Check another listing
        </Link>
        <Link className="button button-secondary" href="/history">
          This session
          <Icon name="arrow-right" />
        </Link>
      </div>
    </main>
  );
}
