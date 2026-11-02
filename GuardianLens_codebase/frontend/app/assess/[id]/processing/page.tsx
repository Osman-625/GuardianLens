// Processing page for the website's manual form: shows the five pipeline stages while the check
// runs, polling the status endpoint until the result is ready, then opens the result page. (The
// browser extension shows the same stages inside its side panel.) Stage labels, the stage list, and
// the "taking longer than usual" sentence come from @guardianlens/shared so both surfaces match.
"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { SLOW_WAIT_COPY, StageList, type PipelineStage } from "@guardianlens/shared";
import { apiFetch, GuardianLensApiError } from "@/lib/api";
import { DRAFT_KEY } from "@/lib/draft";

// How many times in a row a status request may never reach the server before the page gives up.
// The check keeps running on the server, so one dropped request (a Wi-Fi blip) must not end it.
const LOST_REQUESTS_ALLOWED = 3;

/** Renders the progress screen and follows the check until it completes, fails, or is cancelled. */
export default function ProcessingPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [stage, setStage] = useState<PipelineStage | null>("visual");
  const [failure, setFailure] = useState<string | null>(null);
  const [longWait, setLongWait] = useState(false);

  useEffect(() => {
    let active = true;
    let lostRequests = 0;
    // After 8 seconds the page says so honestly; there is no percentage or fake progress.
    const slowTimer = window.setTimeout(() => setLongWait(true), 8000);
    // The pending "ask again" timer, kept so leaving the page cancels it.
    let nextPoll: number | undefined;

    // Asks for the status, shows the current stage, and asks again 900 ms later until the check
    // is complete (open the result) or has failed or been abandoned (show the reason).
    async function poll() {
      try {
        const result = await apiFetch<{
          status: string;
          stage: PipelineStage | null;
          message: string | null;
        }>(`/api/v1/assess/${params.id}/status`);
        if (!active) return;
        lostRequests = 0;
        setStage(result.stage);
        if (result.status === "complete") {
          // A finished check clears its draft, so the next listing starts with an empty form.
          window.sessionStorage.removeItem(DRAFT_KEY);
          router.replace(`/assess/${params.id}`);
          return;
        }
        if (result.status === "failed" || result.status === "abandoned") {
          setFailure(result.message ?? "The check could not be completed.");
          return;
        }
        nextPoll = window.setTimeout(poll, 900);
      } catch (caught) {
        if (!active) return;
        // A request that never reached the server (fetch's own error, not an answer from the
        // API) is tried again a few times; an answer from the API, even an error, is final.
        if (!(caught instanceof GuardianLensApiError) && lostRequests < LOST_REQUESTS_ALLOWED) {
          lostRequests += 1;
          nextPoll = window.setTimeout(poll, 900);
          return;
        }
        setFailure("We could not get the status of this check. Your form is still saved.");
      }
    }

    void poll();
    return () => {
      active = false;
      window.clearTimeout(slowTimer);
      window.clearTimeout(nextPoll);
    };
  }, [params.id, router]);

  // Cancel tells the server to stop, then returns to the saved form whatever the server says.
  async function cancel() {
    try {
      await apiFetch<void>(`/api/v1/assess/${params.id}/cancel`, {
        method: "POST",
      });
    } finally {
      router.push("/assess");
    }
  }

  return (
    <main className="page">
      <section className="card processing-card" aria-live="polite">
        <h1 className="page-title">Checking the listing</h1>
        {failure ? (
          <>
            <p className="error-text" role="alert">
              {failure}
            </p>
            <button
              className="button button-primary button-full"
              onClick={() => router.push("/assess")}
            >
              Return to saved form
            </button>
          </>
        ) : (
          <>
            <StageList stage={stage} />
            {longWait && <p className="helper">{SLOW_WAIT_COPY}</p>}
            <button className="button button-text" type="button" onClick={cancel}>
              Cancel
            </button>
          </>
        )}
      </section>
    </main>
  );
}
