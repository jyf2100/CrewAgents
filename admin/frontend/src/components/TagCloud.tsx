/**
 * TagCloud — read-only tag display with capsule styling.
 *
 * Renders tags as inline pill badges with the accent-cyan theme.
 * Optionally shows a label and hint text.
 */

import { useI18n } from "../hooks/useI18n";

interface TagCloudProps {
  tags: string[];
  label?: string;
  hint?: string;
}

export function TagCloud({ tags, label, hint }: TagCloudProps) {
  const { t } = useI18n();

  if (tags.length === 0 && !label) return null;

  return (
    <div>
      {(label || hint) && (
        <div className="flex items-center gap-2 mb-1.5">
          {label && (
            <span className="text-xs font-medium text-text-secondary">{label}</span>
          )}
          {hint && (
            <span className="text-[10px] text-text-muted">
              {hint}
            </span>
          )}
        </div>
      )}
      <div className="flex flex-wrap gap-1.5">
        {tags.map((tag) => (
          <span
            key={tag}
            className="inline-block px-2 py-0.5 text-xs rounded-full bg-accent-cyan/10 text-accent-cyan border border-accent-cyan/30"
          >
            {tag}
          </span>
        ))}
      </div>
      {tags.length === 0 && label && (
        <p className="text-xs text-text-muted">-</p>
      )}
    </div>
  );
}
