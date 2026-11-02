// Shown while a check runs: the five real pipeline stages, an honest "taking longer" line after a
// while, and a Cancel button. No percentages and no padded delays (Design Brief: Parkinson's Law).
// The region is a polite live region so screen readers hear each stage change.
import { SLOW_WAIT_COPY, StageList, type PipelineStage } from "@guardianlens/shared";

/** Props of the checking view: the running stage, whether the wait is slow, and the cancel action. */
export interface CheckingViewProps {
  /** The stage currently running, or null before the first stage is reported. */
  stage: PipelineStage | null;
  /** True once the check has taken longer than expected. */
  slow: boolean;
  onCancel(): void;
}

/** The "checking" view. */
export function CheckingView({ stage, slow, onCancel }: CheckingViewProps) {
  return (
    <section className="panel-section" aria-live="polite">
      <h1 className="panel-title">Checking the listing</h1>
      <StageList stage={stage} />
      {slow && <p className="helper">{SLOW_WAIT_COPY}</p>}
      <button type="button" className="button button-text" onClick={onCancel}>
        Cancel
      </button>
    </section>
  );
}
