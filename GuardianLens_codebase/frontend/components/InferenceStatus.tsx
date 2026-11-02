"use client";

// Tells the visitor which kind of scores the running API produces, by reading its /health answer:
// nothing for trained models, the development-stub warning for stub scores, and a short status
// line while loading or when the API cannot be reached.
import { useEffect, useState } from "react";
import { DevBanner } from "@guardianlens/shared";
import { apiFetch } from "@/lib/api";

/** What the page knows about the API: still asking, stub scores, trained scores, or no answer. */
type ServiceState = "loading" | "stub" | "trained" | "unavailable";

/** The parts of the /health answer this component reads. */
interface InferenceHealth {
  status: string;
  stub_mode: boolean;
  inference_mode: string;
}

/** The landing page follows the running API; saved results retain their own provenance. */
export function InferenceStatus() {
  const [state, setState] = useState<ServiceState>("loading");

  useEffect(() => {
    // `active` stops a late answer from updating the page after it has been left; the timeout
    // gives up on an API that does not answer within ten seconds.
    let active = true;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 10_000);

    apiFetch<InferenceHealth>("/health", {
      cache: "no-store",
      signal: controller.signal,
    })
      .then((health) => {
        if (!active) return;
        if (health.status !== "ok") {
          setState("unavailable");
        } else if (health.stub_mode === true && health.inference_mode === "stub") {
          setState("stub");
        } else if (health.stub_mode === false && health.inference_mode === "trained") {
          setState("trained");
        } else {
          setState("unavailable");
        }
      })
      .catch(() => {
        if (active) setState("unavailable");
      })
      .finally(() => window.clearTimeout(timeout));

    return () => {
      active = false;
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, []);

  if (state === "trained") return null;
  if (state === "stub") return <DevBanner />;

  return (
    <p className="helper" role="status">
      {state === "loading"
        ? "Checking service availability…"
        : "The assessment service could not be reached. Try again shortly."}
    </p>
  );
}
