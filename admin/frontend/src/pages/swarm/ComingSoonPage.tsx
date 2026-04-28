import { useI18n } from "../../hooks/useI18n";

interface ComingSoonPageProps {
  title: string;
}

export function ComingSoonPage({ title }: ComingSoonPageProps) {
  const { t } = useI18n();

  return (
    <div className="flex flex-col items-center justify-center py-24 gap-4">
      <svg
        className="h-16 w-16 text-accent-cyan/40 mb-2"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={1}
        aria-hidden="true"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z"
        />
      </svg>
      <h1 className="text-2xl font-semibold text-text-primary">{title}</h1>
      <p className="text-lg text-accent-cyan font-medium">{t.comingSoon}</p>
      <p className="text-sm text-text-secondary">{t.comingSoonDescription}</p>
    </div>
  );
}
