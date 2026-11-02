// The three signals and what each one looks at, as a short list. It shows no score or result, so
// it is safe on the landing page and on the side panel's start screen.
import { SIGNAL_ICONS, SIGNAL_LOOKS_AT, SIGNAL_NAMES } from "../copy";
import type { SignalName } from "../types";
import { Icon } from "./Icon";

// The order the three checks are listed in, as on the result page.
const ORDER: SignalName[] = ["visual", "textual", "behavioural"];

/** Renders the list: the signal's icon, its name, and one line on what it looks at. */
export function LooksAt() {
  return (
    // role="list" keeps list semantics in Safari, which drops them when list-style is none.
    <ul className="looks-list" role="list">
      {ORDER.map((signal) => (
        <li key={signal}>
          <span className="signal-icon">
            <Icon name={SIGNAL_ICONS[signal]} />
          </span>
          <div>
            <strong>{SIGNAL_NAMES[signal]}</strong>
            <p>{SIGNAL_LOOKS_AT[signal]}</p>
          </div>
        </li>
      ))}
    </ul>
  );
}
