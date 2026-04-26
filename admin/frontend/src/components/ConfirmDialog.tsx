interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "destructive" | "default";
  onConfirm: () => void;
  onCancel: () => void;
  loading?: boolean;
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  variant = "default",
  onConfirm,
  onCancel,
  loading = false,
}: ConfirmDialogProps) {
  if (!open) return null;

  const confirmClass =
    variant === "destructive"
      ? "bg-accent-pink text-white hover:bg-accent-pink/90"
      : "border border-accent-cyan text-accent-cyan hover:bg-accent-cyan/10";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Glass backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onCancel}
      />
      {/* Dialog */}
      <div
        className={`animate-modal-enter relative bg-surface-elevated border border-border rounded-lg shadow-lg max-w-md w-full mx-4 p-6 ${
          variant === "destructive" ? "border-t-2 border-t-accent-pink" : ""
        }`}
      >
        <h3 className="text-lg font-semibold text-text-primary mb-2">
          {title}
        </h3>
        <p className="text-sm text-text-secondary mb-6">{message}</p>
        <div className="flex justify-end gap-3">
          <button
            onClick={onCancel}
            className="h-9 px-4 text-sm text-text-secondary hover:bg-surface rounded-lg transition-colors"
            disabled={loading}
          >
            {cancelLabel}
          </button>
          <button
            onClick={onConfirm}
            className={`h-9 px-4 text-sm rounded-lg transition-colors ${confirmClass}`}
            disabled={loading}
          >
            {loading ? "..." : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
