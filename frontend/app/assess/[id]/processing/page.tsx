"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import type { PipelineStage } from "@/lib/types";

const stages: { key: PipelineStage; label: string }[] = [
  { key: "visual", label: "Checking photos" },
  { key: "textual", label: "Checking listing wording" },
  { key: "behavioural", label: "Checking visible seller details" },
  { key: "fusion", label: "Combining available signals" },
  { key: "explanation", label: "Preparing plain-language reasons" },
];

export default function ProcessingPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [stage, setStage] = useState<PipelineStage | null>("visual");
  const [failure, setFailure] = useState<string | null>(null);
  const [longWait, setLongWait] = useState(false);
  const activeIndex = useMemo(() => stages.findIndex((item) => item.key === stage), [stage]);

  useEffect(() => {
    let active = true;
    const slowTimer = window.setTimeout(() => setLongWait(true), 8000);

    async function poll() {
      try {
        const result = await apiFetch<{ status: string; stage: PipelineStage | null; message: string | null }>(`/api/v1/assess/${params.id}/status`);
        if (!active) return;
        setStage(result.stage);
        if (result.status === "complete") {
          router.replace(`/assess/${params.id}`);
          return;
        }
        if (result.status === "failed" || result.status === "abandoned") {
          setFailure(result.message ?? "The check could not be completed.");
          return;
        }
        window.setTimeout(poll, 900);
      } catch {
        if (active) setFailure("The processing status could not be loaded. Your form draft is still saved.");
      }
    }

    void poll();
    return () => {
      active = false;
      window.clearTimeout(slowTimer);
    };
  }, [params.id, router]);

  async function cancel() {
    try {
      await apiFetch<void>(`/api/v1/assess/${params.id}/cancel`, { method: "POST" });
    } finally {
      router.push("/assess");
    }
  }

  return (
    <main className="page">
      <section className="card processing-card" aria-live="polite">
        <p className="eyebrow">Assessment in progress</p>
        <h1 className="page-title">Checking the listing</h1>
        {failure ? (
          <>
            <p className="error-text" role="alert">{failure}</p>
            <button className="button button-primary button-full" onClick={() => router.push("/assess")}>Return to saved form</button>
          </>
        ) : (
          <>
            <ol className="stage-list">
              {stages.map((item, index) => {
                const state = index < activeIndex ? "stage-done" : index === activeIndex ? "stage-active" : "";
                return (
                  <li className={`stage-item ${state}`} key={item.key}>
                    <span className="stage-dot" aria-hidden="true">{index < activeIndex ? "✓" : index + 1}</span>
                    {item.label}
                  </li>
                );
              })}
            </ol>
            {longWait && <p className="helper">This is taking longer than usual. The current stage is still running.</p>}
            <button className="button button-text" type="button" onClick={cancel}>Cancel</button>
          </>
        )}
      </section>
    </main>
  );
}
