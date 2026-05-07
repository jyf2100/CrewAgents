/**
 * DomainCardSelector — visual card-based domain picker.
 *
 * Renders 5 horizontal cards (grid-cols-5) with accessible aria-pressed.
 * Used in the Agent detail page MetadataCard.
 */

import { DOMAINS, getDomainLabel, type DomainValue } from "./domain-constants";
import { useI18n } from "../hooks/useI18n";

interface DomainCardSelectorProps {
  value: string;
  onChange: (v: DomainValue) => void;
  disabled?: boolean;
}

export function DomainCardSelector({ value, onChange, disabled }: DomainCardSelectorProps) {
  const { t } = useI18n();

  return (
    <div className="grid grid-cols-5 gap-3">
      {DOMAINS.map((d) => {
        const isSelected = value === d.value;
        return (
          <button
            key={d.value}
            type="button"
            disabled={disabled}
            onClick={() => onChange(d.value)}
            aria-pressed={isSelected}
            className={`
              flex flex-col items-center gap-1 rounded-lg border p-3 text-center transition-colors
              focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-cyan/50
              disabled:opacity-50 disabled:cursor-not-allowed
              ${
                isSelected
                  ? "border-accent-cyan/50 bg-accent-cyan/5 text-accent-cyan"
                  : "border-border bg-surface text-text-secondary hover:border-border/80 hover:bg-surface/80"
              }
            `}
          >
            <span className="text-sm font-medium">
              {getDomainLabel(t, d.labelKey)}
            </span>
          </button>
        );
      })}
    </div>
  );
}
