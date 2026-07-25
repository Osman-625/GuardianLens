import type { RiskBand } from "@/lib/types";

const labels: Record<RiskBand, { icon: string; meaning: string }> = {
  low: { icon: "✓", meaning: "No strong warning signs found by this check" },
  moderate: { icon: "!", meaning: "Some warning signs need closer checking" },
  high: { icon: "×", meaning: "Several warning signs need serious attention" },
};

export function BandChip({ band }: { band: RiskBand }) {
  const item = labels[band];
  return (
    <div className={`band-unit band-${band}`}>
      <span className="band-chip">
        <span aria-hidden="true">{item.icon}</span>
        {band[0].toUpperCase() + band.slice(1)} risk
      </span>
      <span className="band-meaning">{item.meaning}</span>
    </div>
  );
}
