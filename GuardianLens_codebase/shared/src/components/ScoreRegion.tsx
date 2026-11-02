// The score region: score, band chip, and disclaimer as ONE bounded region, so the caveat is
// read as part of the verdict (Design Brief: Common Region and Selective Attention rules).
"use client";

import { useLayoutEffect, useState } from "react";
import { BandChip } from "./BandChip";
import { SCORE_HINT } from "../copy";
import type { RiskBand } from "../types";

/** Results whose count-up has already played in this page's lifetime (no replay on revisit). */
const revealed = new Set<string>();
// How long the first-time count-up of the score runs, in milliseconds.
const COUNT_MS = 700;

/**
 * The number shown in the dial: counts up from 0 to `score` once, the first time a result is
 * shown, with a strong ease-out. It shows `score` straight away on a revisit, when the reader
 * prefers reduced motion, and where matchMedia is missing (tests, old browsers).
 */
function useCountUp(score: number, key: string): number {
  const [shown, setShown] = useState(score);
  useLayoutEffect(() => {
    const motionOk = window.matchMedia?.("(prefers-reduced-motion: no-preference)").matches;
    // Reduced motion, a revisit and a zero score all show the final number at once.
    if (!motionOk || revealed.has(key) || score <= 0) {
      setShown(score);
      return;
    }
    let frame = 0;
    const start = performance.now();
    const step = (now: number) => {
      const t = Math.min((now - start) / COUNT_MS, 1);
      // Ease-out (quartic): a fast start and a soft landing on the final number.
      setShown(Math.round(score * (1 - (1 - t) ** 4)));
      if (t < 1) frame = requestAnimationFrame(step);
      else revealed.add(key);
    };
    setShown(0);
    frame = requestAnimationFrame(step);
    // Leaving mid-count restores the final value, so a half-counted score is never left on screen.
    return () => {
      cancelAnimationFrame(frame);
      setShown(score);
    };
  }, [score, key]);
  return shown;
}

/** Props of the score dial: the already-rounded score, its band, and the result's identity. */
interface ScoreDialProps {
  score: number;
  band: RiskBand;
  revealKey: string;
}

/**
 * A ring that fills in proportion to the score, with the number inside. The ring is decoration:
 * the number and the band are also written as text. `pathLength=100` makes the dash length equal
 * to the score, so no circumference maths is needed.
 */
function ScoreDial({ score, band, revealKey }: ScoreDialProps) {
  const shown = useCountUp(score, revealKey);
  return (
    <div className={`score-dial band-${band}`}>
      <svg viewBox="0 0 120 120" aria-hidden="true" focusable="false">
        <circle className="dial-track" cx="60" cy="60" r="52" />
        {shown > 0 && (
          <circle
            className="dial-arc"
            cx="60"
            cy="60"
            r="52"
            pathLength={100}
            strokeDasharray={`${Math.min(shown, 100)} 100`}
            transform="rotate(-90 60 60)"
          />
        )}
      </svg>
      <div className="score-readout">
        <div className="score-number">{shown}</div>
        <div className="score-total">out of 100</div>
      </div>
    </div>
  );
}

/** Props of the score region: the numeric score, its band, and the disclaimer shown with it. */
export interface ScoreRegionProps {
  /** The score, 0 to 100, where 100 is the lowest estimated risk. Rounded for display; decimals are never shown. */
  score: number;
  band: RiskBand;
  /** Must be shown wherever a score is shown, so it is a required part of this component. */
  disclaimer: string;
  /** The assessment id, so the count-up plays only the first time this result is shown. */
  id?: string;
}

/** Renders the score, its band, and the disclaimer inside one labelled region. */
export function ScoreRegion({ score, band, disclaimer, id }: ScoreRegionProps) {
  const shown = Math.round(score);
  return (
    <section className="score-region" aria-label={`Score ${shown} out of 100, ${band} risk`}>
      <div className="score-main">
        <ScoreDial score={shown} band={band} revealKey={id ?? `${shown}-${band}`} />
        <div className="score-side">
          <BandChip band={band} />
          <p className="score-hint">{SCORE_HINT}</p>
        </div>
      </div>
      <p className="disclaimer">{disclaimer}</p>
    </section>
  );
}
