/**
 * SkillList — read-only list of installed skills.
 *
 * Each row shows skill name (monospace) and description (muted).
 * Includes a refresh button in the top-right corner.
 */

import type { SkillEntry } from "../lib/admin-api";
import { useI18n } from "../hooks/useI18n";

interface SkillListProps {
  skills: SkillEntry[];
  loading?: boolean;
  onRefresh?: () => void;
}

export function SkillList({ skills, loading, onRefresh }: SkillListProps) {
  const { t } = useI18n();

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-text-secondary">
          {t.installedSkills || "Installed Skills"}
        </span>
        {onRefresh && (
          <button
            type="button"
            onClick={onRefresh}
            disabled={loading}
            className="text-xs text-text-muted hover:text-accent-cyan transition-colors disabled:opacity-50"
            title={t.refresh}
          >
            {loading ? "..." : t.refresh}
          </button>
        )}
      </div>

      {skills.length === 0 ? (
        <p className="text-xs text-text-muted py-2">
          {t.noInstalledSkills || "No installed skills"}
        </p>
      ) : (
        <div className="space-y-1">
          {skills.map((skill) => (
            <div
              key={skill.name}
              className="flex items-baseline gap-2 py-1"
            >
              <span className="text-xs font-mono text-text-primary shrink-0">
                {skill.name}
              </span>
              {skill.description && (
                <span className="text-xs text-text-muted truncate">
                  {skill.description}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
