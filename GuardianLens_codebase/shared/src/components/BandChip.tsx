// Risk band chip: icon + band word + one-line meaning, so colour is never the only signal.
import { BAND_COPY } from "../copy";
import type { RiskBand } from "../types";
import { Icon } from "./Icon";

/**
 * Shows a risk band. The icon is decorative (hidden from screen readers) because the band is also
 * written as words, and each band has its own icon SHAPE; the colour comes from the
 * `band-<name>` class and only reinforces the text and the icon.
 */
export function BandChip({ band }: { band: RiskBand }) {
  const item = BAND_COPY[band];
  return (
    <div className={`band-unit band-${band}`}>
      <span className="band-chip">
        <Icon name={item.icon} />
        {/* charAt (not band[0]) so the code also compiles under noUncheckedIndexedAccess, which the extension enables. */}
        {band.charAt(0).toUpperCase() + band.slice(1)} risk
      </span>
      <span className="band-meaning">{item.meaning}</span>
    </div>
  );
}
