"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { BandChip } from "@/components/BandChip";
import { DevBanner } from "@/components/DevBanner";
import { SignalCardView } from "@/components/SignalCardView";
import { apiFetch } from "@/lib/api";
import type { AssessmentResult } from "@/lib/types";

const feedbackOptions = [
  ["helpful", "Helpful"],
  ["unclear", "Unclear"],
  ["potentially_incorrect", "Potentially incorrect"],
] as const;

export default function ResultPage() {
  const params = useParams<{ id: string }>();
  const [result, setResult] = useState<AssessmentResult | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showFeedback, setShowFeedback] = useState(false);
  const [verdict, setVerdict] = useState<string>("");
  const [comment, setComment] = useState("");
  const [feedbackState, setFeedbackState] = useState<"idle" | "saving" | "saved">("idle");

  useEffect(() => {
    apiFetch<AssessmentResult>(`/api/v1/assess/${params.id}/result`)
      .then(setResult)
      .catch(() => setLoadError("The assessment result could not be loaded for this browser session."));
  }, [params.id]);

  async function submitFeedback(event: FormEvent) {
    event.preventDefault();
    if (!verdict) return;
    setFeedbackState("saving");
    await apiFetch<void>(`/api/v1/assess/${params.id}/feedback`, {
      method: "POST",
      body: JSON.stringify({ verdict, comment: comment || null }),
    });
    setFeedbackState("saved");
  }

  if (loadError) {
    return <main className="page"><div className="card"><h1 className="page-title">Result unavailable</h1><p className="error-text">{loadError}</p><Link className="button button-primary" href="/assess">Check another listing</Link></div></main>;
  }
  if (!result) return <main className="page"><div className="loading">Loading result…</div></main>;

  return (
    <main className="page">
      {result.development_stub && <DevBanner />}
      <p className="eyebrow">Assessment result</p>
      <h1 className="page-title">{result.title}</h1>
      <p className="page-lead">Completed in {result.total_latency_ms} ms using {result.model_bundle_label}.</p>

      <section className="score-region" aria-label={`Risk score ${result.score} out of 100, ${result.band}`}>
        <div className="score-number">{result.score}</div>
        <div className="score-total">out of 100</div>
        <BandChip band={result.band} />
        <p className="disclaimer">{result.disclaimer}</p>
      </section>

      <section className="signal-grid" aria-label="Signal summaries">
        {result.signal_cards.map((card) => <SignalCardView card={card} assessmentId={result.assessment_id} key={card.signal} />)}
      </section>

      {result.missing_data_notices.length > 0 && (
        <section className="notice">
          <strong>Limited information</strong>
          {result.missing_data_notices.map((notice) => <p key={notice}>{notice}</p>)}
        </section>
      )}

      <section className="card">
        <h2>Checks to do before paying</h2>
        <ol className="check-list">
          {result.suggested_checks.map((check) => <li key={check}>{check}</li>)}
        </ol>
      </section>

      <section className="card" style={{ marginTop: 16 }}>
        <h2>Was this result helpful?</h2>
        {!showFeedback && <button className="button button-secondary" onClick={() => setShowFeedback(true)}>Give feedback</button>}
        {showFeedback && feedbackState !== "saved" && (
          <form onSubmit={submitFeedback}>
            <div className="feedback-options">
              {feedbackOptions.map(([value, label]) => (
                <label className="option-row" key={value}>
                  <input type="radio" name="verdict" value={value} checked={verdict === value} onChange={() => setVerdict(value)} />
                  {label}
                </label>
              ))}
            </div>
            <div className="field" style={{ marginTop: 14 }}>
              <label htmlFor="feedback-comment">Optional comment</label>
              <textarea id="feedback-comment" maxLength={1000} value={comment} onChange={(event) => setComment(event.target.value)} />
              <span className="helper">Do not include names, phone numbers, account details, or other personal information.</span>
            </div>
            <button className="button button-primary" disabled={!verdict || feedbackState === "saving"}>
              {feedbackState === "saving" ? "Saving…" : "Submit feedback"}
            </button>
          </form>
        )}
        {feedbackState === "saved" && <p className="success-text">Feedback saved.</p>}
      </section>

      <div className="action-row">
        <Link className="button button-primary" href="/assess">Check another listing</Link>
        <Link className="button button-secondary" href="/history">This session</Link>
      </div>
    </main>
  );
}
