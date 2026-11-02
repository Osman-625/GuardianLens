// The result summary in the side panel: the score region (score, band, disclaimer together), the
// three signal cards, any limited-information notice, the single most protective check, and the
// way to the full explanation on the website.
//
// Depth lives on the website (Design Brief: progressive disclosure), so the panel shows only ONE
// manual check: the last in the list, which is the most protective one (independent verification
// of the seller). Feedback is a single tap and is asked only AFTER the result is shown.
import {
  DevBanner,
  FEEDBACK_HEADING,
  FEEDBACK_OPTIONS,
  ScoreRegion,
  SignalCardView,
  type AssessmentResult,
  type FeedbackVerdict,
  type SignalName,
} from "@guardianlens/shared";
import type { FeedbackState } from "@/lib/panel/reducer";

/** Props of the result view: the result, the feedback progress, a notice, and the actions. */
export interface ResultViewProps {
  result: AssessmentResult;
  feedback: FeedbackState;
  /** A one-line message such as "1 photo could not be read and was left out of this check.". */
  notice: string | null;
  /** Opens the website's explanation page; pass a signal to jump to that card's section. */
  onSeeFull(signal?: SignalName): void;
  onFeedback(verdict: FeedbackVerdict): void;
  onCheckAnother(): void;
}

/** The result view. */
export function ResultView({
  result,
  feedback,
  notice,
  onSeeFull,
  onFeedback,
  onCheckAnother,
}: ResultViewProps) {
  const mostProtectiveCheck = result.suggested_checks[result.suggested_checks.length - 1];
  // True when the API could not compute the behavioural signal (no seller details were given).
  const behaviouralUnknown = result.signal_cards.some(
    (card) => card.signal === "behavioural" && !card.available,
  );
  return (
    <section className="panel-section">
      {result.development_stub && <DevBanner />}
      <h1 className="panel-title">{result.title}</h1>
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}

      <ScoreRegion
        id={result.assessment_id}
        score={result.score}
        band={result.band}
        disclaimer={result.disclaimer}
      />

      <div className="signal-grid">
        {result.signal_cards.map((card) => (
          <SignalCardView key={card.signal} card={card} onOpen={() => onSeeFull(card.signal)} />
        ))}
      </div>

      {/* One notice for missing information. When the seller's details are what is missing, it
          says how to add them (the panel keeps the draft, so a seller-page capture returns to
          Review); the card above already says the signal is unknown, so it is not repeated. */}
      {behaviouralUnknown ? (
        <section className="notice">
          <strong>Seller details were not included</strong>
          {result.missing_data_notices.map((text) => (
            <p key={text}>{text}</p>
          ))}
          <p>
            To add them, open the seller&apos;s page, click the GuardianLens icon there, then press
            Check listing again.
          </p>
        </section>
      ) : (
        result.missing_data_notices.length > 0 && (
          <section className="notice">
            <strong>Limited information</strong>
            {result.missing_data_notices.map((text) => (
              <p key={text}>{text}</p>
            ))}
          </section>
        )
      )}

      {mostProtectiveCheck && (
        <section className="card">
          <h2>Before you pay</h2>
          <p>{mostProtectiveCheck}</p>
        </section>
      )}

      <button
        type="button"
        className="button button-primary button-full"
        onClick={() => onSeeFull()}
      >
        See full explanation
      </button>

      <section className="card">
        <h2>{FEEDBACK_HEADING}</h2>
        {feedback === "saved" ? (
          <p className="success-text">Feedback saved.</p>
        ) : (
          <div className="panel-choices">
            {FEEDBACK_OPTIONS.map(([verdict, label]) => (
              <button
                key={verdict}
                type="button"
                className={`button button-secondary feedback-${verdict}`}
                disabled={feedback === "saving"}
                onClick={() => onFeedback(verdict)}
              >
                {label}
              </button>
            ))}
          </div>
        )}
      </section>

      <button
        type="button"
        className="button button-secondary button-full"
        onClick={onCheckAnother}
      >
        Check another listing
      </button>
    </section>
  );
}
