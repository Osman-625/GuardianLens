// The side panel UI, driven entirely by `deps` so tests can run it with fakes and the real panel
// can run it with the real API client. It picks the view for the controller's state and wires
// each view's callbacks to the controller's actions.
import { Wordmark } from "@guardianlens/shared";
import { usePanelController, type ControllerDeps } from "@/lib/panel/controller";
import { CheckingView } from "./views/CheckingView";
import { FailureView } from "./views/FailureView";
import { IdleView } from "./views/IdleView";
import { ResultView } from "./views/ResultView";
import { ReviewView } from "./views/ReviewView";

/** The side panel. `deps` must be a stable object (created once outside the component). */
export function PanelApp({ deps }: { deps: ControllerDeps }) {
  const { state, actions } = usePanelController(deps);
  const { view } = state;

  return (
    <div className="panel">
      <header className="panel-header">
        <span className="wordmark">
          <Wordmark />
        </span>
      </header>
      <main>
        {view.name === "idle" && (
          <IdleView
            reason={view.reason}
            pageState={view.pageState}
            onOpenSite={actions.openSitePath}
            onCapture={actions.capture}
          />
        )}
        {view.name === "capturing" && (
          // A polite live region with a heading, like the other views, so the wait is announced.
          <section className="panel-section" aria-live="polite">
            <h1 className="panel-title">Reading this page{"…"}</h1>
          </section>
        )}
        {view.name === "review" && state.draft && (
          <ReviewView
            draft={state.draft}
            fieldErrors={state.fieldErrors}
            notice={state.notice}
            submitting={state.submitting}
            onEdit={actions.edit}
            onTogglePhoto={actions.togglePhoto}
            onSubmit={actions.submit}
            onOpenSeller={actions.openSellerPage}
            onCapture={actions.capture}
            onOpenSite={actions.openSitePath}
          />
        )}
        {view.name === "checking" && (
          <CheckingView stage={view.stage} slow={view.slow} onCancel={actions.cancel} />
        )}
        {view.name === "result" && (
          <ResultView
            result={view.result}
            feedback={view.feedback}
            notice={state.notice}
            onSeeFull={(signal) => void actions.openFullExplanation(signal)}
            onFeedback={(verdict) => void actions.sendFeedback(verdict)}
            onCheckAnother={actions.checkAnother}
          />
        )}
        {view.name === "failure" && (
          <FailureView
            kind={view.kind}
            message={view.message}
            onRetry={actions.retry}
            onOpenSite={actions.openSitePath}
          />
        )}
      </main>
    </div>
  );
}
