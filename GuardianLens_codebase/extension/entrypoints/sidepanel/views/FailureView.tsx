// Shown when a check could not be completed. The tone is calm: it says what happened in plain
// words, confirms the buyer's details are kept, and offers one tap to try again (Design Brief:
// Peak-End rule, errors never discard input). No error codes or technical detail are shown.
import type { FailureKind } from "@/lib/panel/errors";

/** Props of the failure screen: what kind of failure it was, its message, and the two actions. */
export interface FailureViewProps {
  kind: FailureKind;
  message: string;
  /** Returns to the Review step with everything the buyer entered still in place. */
  onRetry(): void;
  /** Opens a path on the GuardianLens website in a new tab. */
  onOpenSite(path: string): void;
}

/** The failure screen. */
export function FailureView({ kind, message, onRetry, onOpenSite }: FailureViewProps) {
  return (
    <section className="panel-section">
      <h1 className="panel-title">The check could not be completed</h1>
      <p className="error-text" role="alert">
        {message}
      </p>
      {kind === "unreachable" && (
        <p className="helper">Ask the researcher to check that it is running, then try again.</p>
      )}
      <button type="button" className="button button-primary button-full" onClick={onRetry}>
        Try again
      </button>
      <button type="button" className="button button-text" onClick={() => onOpenSite("/assess")}>
        Use the website form
      </button>
    </section>
  );
}
