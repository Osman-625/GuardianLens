// Session history: the listings checked in this browser's session, from the website or from the
// browser extension.
//
// The extension's "This session" link opens this page with the extension's session in the URL
// fragment. Like the result pages, it first completes that handoff (useSessionClaim, which asks
// the visitor to confirm), and only then loads the list, so checks made in the extension appear.
"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { BAND_COPY, formatDateTime, Icon } from "@guardianlens/shared";
import { apiFetch } from "@/lib/api";
import type { HistoryItem } from "@/lib/types";
import { useSessionClaim } from "@/lib/useSessionClaim";

/** Renders this session's checks, newest first, once any extension handoff has finished. */
export default function HistoryPage() {
  const claimed = useSessionClaim();
  const [items, setItems] = useState<HistoryItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Load the list once any session handoff has finished.
  useEffect(() => {
    if (!claimed) return;
    apiFetch<HistoryItem[]>("/api/v1/session/history")
      .then(setItems)
      .catch(() => setError("This list could not be loaded. Try again shortly."));
  }, [claimed]);

  return (
    <main className="page">
      <h1 className="page-title">Listings checked this session</h1>
      <p className="page-lead">
        Checks from this browser session, on the website or in the extension. Nothing is saved to an
        account.
      </p>
      {error && <p className="error-text">{error}</p>}
      {items === null && !error && <div className="loading">Loading history…</div>}
      {items?.length === 0 && (
        <section className="card empty-state">
          <h2>No listings checked this session yet</h2>
          <p>Checks you run will appear here.</p>
          <Link className="button button-primary" href="/assess">
            Check a listing
          </Link>
        </section>
      )}
      {items && items.length > 0 && (
        <div className="history-list">
          {items.map((item) => (
            <Link
              className="history-item"
              href={`/assess/${item.assessment_id}`}
              key={item.assessment_id}
            >
              <div>
                <div className="history-title">{item.title}</div>
                <div className="history-meta">
                  {formatDateTime(item.created_at)} · {item.band} risk
                </div>
              </div>
              <div
                className={`history-score band-${item.band}`}
                aria-label={`Score ${item.score} out of 100`}
              >
                <Icon name={BAND_COPY[item.band].icon} />
                {item.score}
              </div>
            </Link>
          ))}
        </div>
      )}
    </main>
  );
}
