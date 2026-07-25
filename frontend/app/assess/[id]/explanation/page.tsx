"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { DevBanner } from "@/components/DevBanner";
import { apiFetch } from "@/lib/api";
import type { AssessmentResult } from "@/lib/types";

const labels = { visual: "Visual signal", textual: "Textual signal", behavioural: "Behavioural signal" };

export default function ExplanationPage() {
  const params = useParams<{ id: string }>();
  const [result, setResult] = useState<AssessmentResult | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<AssessmentResult>(`/api/v1/assess/${params.id}/result`)
      .then(setResult)
      .catch(() => setLoadError("The explanation could not be loaded for this browser session."));
  }, [params.id]);

  if (loadError) return <main className="page"><p className="error-text">{loadError}</p></main>;
  if (!result) return <main className="page"><div className="loading">Loading explanation…</div></main>;

  return (
    <main className="page">
      {result.development_stub && <DevBanner />}
      <p className="eyebrow">Explanation details</p>
      <h1 className="page-title">Why this result was shown</h1>
      <p className="page-lead">Reasons are grouped by signal. Missing fields stay unknown.</p>

      {result.signal_cards.map((card) => (
        <section className="card explanation-section" id={card.signal} key={card.signal}>
          <h2>{labels[card.signal]}</h2>
          <p><strong>{card.status_word}</strong>. {card.summary}</p>
          {card.reasons.length > 0 ? (
            <ul className="reason-list">
              {card.reasons.map((reason) => (
                <li className={`reason reason-${reason.direction}`} key={`${reason.feature_key}-${reason.rank}`}>
                  {reason.display_text}
                </li>
              ))}
            </ul>
          ) : <p className="helper">No detailed reason is available for this signal.</p>}
          {card.scope_note && <p className="scope-note">{card.scope_note}</p>}
        </section>
      ))}

      <section className="card">
        <h2>Manual checks</h2>
        <ol className="check-list">{result.suggested_checks.map((check) => <li key={check}>{check}</li>)}</ol>
        <p className="disclaimer">{result.disclaimer}</p>
      </section>

      <Link className="button button-secondary button-full" href={`/assess/${params.id}`}>Back to result</Link>
    </main>
  );
}
