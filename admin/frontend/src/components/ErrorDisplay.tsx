interface ErrorDisplayProps {
  error: string;
  onRetry?: () => void;
}

export function ErrorDisplay({ error, onRetry }: ErrorDisplayProps) {
  return (
    <div className="flex flex-col items-center justify-center py-24 gap-4 animate-page-enter">
      <div className="rounded-lg bg-surface border border-border-cyan/30 border-l-[3px] border-l-accent-pink p-6 max-w-md text-center">
        <p className="text-sm text-accent-pink font-[family-name:var(--font-mono)]">
          {error}
        </p>
      </div>
      {onRetry && (
        <button
          onClick={onRetry}
          className="h-9 px-4 text-sm border border-accent-cyan text-accent-cyan rounded-lg hover:bg-accent-cyan/10 transition-colors"
        >
          Retry
        </button>
      )}
    </div>
  );
}
