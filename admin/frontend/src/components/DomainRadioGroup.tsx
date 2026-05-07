/**
 * DomainRadioGroup — compact radio button group for domain selection.
 *
 * Used in the TaskSubmitPage. Marks the field as required (*).
 */

import { DOMAINS, getDomainLabel, type DomainValue } from "./domain-constants";
import { useI18n } from "../hooks/useI18n";

interface DomainRadioGroupProps {
  value: string;
  onChange: (v: DomainValue) => void;
  disabled?: boolean;
}

export function DomainRadioGroup({ value, onChange, disabled }: DomainRadioGroupProps) {
  const { t } = useI18n();

  return (
    <fieldset>
      <legend className="block text-sm text-text-secondary mb-1">
        {t.domainLabel || "Domain"} <span className="text-accent-pink">*</span>
      </legend>
      <div className="flex flex-wrap gap-3">
        {DOMAINS.map((d) => {
          const isSelected = value === d.value;
          return (
            <label
              key={d.value}
              className={`
                inline-flex items-center gap-1.5 cursor-pointer rounded-md px-3 py-1.5 text-sm border transition-colors
                ${
                  isSelected
                    ? "border-accent-cyan/40 bg-accent-cyan/10 text-accent-cyan"
                    : "border-border/40 bg-surface/50 text-text-secondary hover:border-border/70"
                }
              `}
            >
              <input
                type="radio"
                name="domain"
                value={d.value}
                checked={isSelected}
                disabled={disabled}
                onChange={() => onChange(d.value)}
                className="sr-only"
              />
              {getDomainLabel(t, d.labelKey)}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
