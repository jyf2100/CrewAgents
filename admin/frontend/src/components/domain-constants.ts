/**
 * Shared domain definitions for the Domain + Skills system.
 *
 * Used by DomainCardSelector, DomainRadioGroup, and any component that
 * needs to render domain-related UI.
 */

export const DOMAINS = [
  { value: "generalist", labelKey: "domainGeneralist", color: "cyan" },
  { value: "code", labelKey: "domainCode", color: "blue" },
  { value: "data", labelKey: "domainData", color: "purple" },
  { value: "ops", labelKey: "domainOps", color: "orange" },
  { value: "creative", labelKey: "domainCreative", color: "pink" },
] as const;

export type DomainValue = typeof DOMAINS[number]["value"];

/**
 * Resolve an i18n key to its translated string, falling back to the key itself.
 * Accepts the Translations object from useI18n() or any string-keyed record.
 */
export function getDomainLabel(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  t: any,
  key: string,
): string {
  return t[key] || key;
}

/** Get the DOMAIN_COLORS entry for a domain value. Returns undefined if not found. */
export function getDomainColorSet(domainValue: string): { bg: string; text: string; border: string } | undefined {
  const entry = DOMAINS.find((d) => d.value === domainValue);
  return entry ? DOMAIN_COLORS[entry.color] : undefined;
}

/** Tailwind color map keyed by domain color name. */
export const DOMAIN_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  cyan: {
    bg: "bg-accent-cyan/15",
    text: "text-accent-cyan",
    border: "border-accent-cyan/30",
  },
  blue: {
    bg: "bg-blue-500/15",
    text: "text-blue-400",
    border: "border-blue-500/30",
  },
  purple: {
    bg: "bg-purple-500/15",
    text: "text-purple-400",
    border: "border-purple-500/30",
  },
  orange: {
    bg: "bg-orange-500/15",
    text: "text-orange-400",
    border: "border-orange-500/30",
  },
  pink: {
    bg: "bg-accent-pink/15",
    text: "text-accent-pink",
    border: "border-accent-pink/30",
  },
};
