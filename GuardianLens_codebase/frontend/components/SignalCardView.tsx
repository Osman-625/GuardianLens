import Link from "next/link";
import type { SignalCard } from "@/lib/types";

const names = { visual: "Visual", textual: "Textual", behavioural: "Behavioural" };
const icons = { visual: "▧", textual: "≡", behavioural: "◷" };

export function SignalCardView({ card, assessmentId }: { card: SignalCard; assessmentId: string }) {
  return (
    <Link
      className={`signal-card ${card.available ? "" : "signal-unavailable"}`}
      href={`/assess/${assessmentId}/explanation#${card.signal}`}
    >
      <div className="signal-heading">
        <span className="signal-icon" aria-hidden="true">{icons[card.signal]}</span>
        <div>
          <h2>{names[card.signal]}</h2>
          <span className="signal-status">{card.status_word}</span>
        </div>
        <span className="chevron" aria-hidden="true">›</span>
      </div>
      <p>{card.summary}</p>
    </Link>
  );
}
