// The five labelled processing stages with three states: done, active, pending.
// There are deliberately no percentages: progress reflects the real pipeline stage only.
import { STAGES } from "../copy";
import type { PipelineStage } from "../types";
import { Icon } from "./Icon";

/**
 * Renders the stage list. A finished stage shows a check icon, the others show their number, and
 * the current stage is marked with aria-current so screen readers can follow it.
 * @param stage The stage currently running, or null before the first stage is reported
 *              (every stage then shows as pending).
 */
export function StageList({ stage }: { stage: PipelineStage | null }) {
  const activeIndex = STAGES.findIndex((item) => item.key === stage);
  return (
    <ol className="stage-list">
      {STAGES.map((item, index) => {
        const state =
          index < activeIndex ? "stage-done" : index === activeIndex ? "stage-active" : "";
        return (
          <li
            className={`stage-item ${state}`.trim()}
            key={item.key}
            aria-current={index === activeIndex ? "step" : undefined}
          >
            <span className="stage-dot" aria-hidden="true">
              {index < activeIndex ? <Icon name="check" /> : index + 1}
            </span>
            {item.label}
          </li>
        );
      })}
    </ol>
  );
}
