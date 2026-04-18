interface ErrorDisplayProps {
  error: string;
  onRetry?: () => void;
}

export function ErrorDisplay({ error, onRetry }: ErrorDisplayProps) {
  return (
    <div className="flex flex-col items-center justify-center py-24 gap-4">
      <div className="rounded-md bg-destructive/10 border border-destructive/20 p-6 max-w-md text-center">
        <p className="text-sm text-destructive">{error}</p>
      </div>
      {onRetry && (
        <button
          onClick={onRetry}
          className="h-8 px-3 text-sm border border-border hover:bg-accent"
        >
          Retry
        </button>
      )}
    </div>
  );
}
