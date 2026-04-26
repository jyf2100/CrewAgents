interface LoadingSpinnerProps {
  size?: "sm" | "md" | "lg";
}

export function LoadingSpinner({ size = "md" }: LoadingSpinnerProps) {
  const sizeMap = { sm: "h-4 w-4", md: "h-6 w-6", lg: "h-10 w-10" };

  return (
    <div className="flex items-center justify-center py-24">
      <div className="relative flex items-center justify-center">
        {/* Outer glow ring */}
        <div
          className={`${sizeMap[size]} rounded-full border border-accent-cyan/20 animate-spin`}
          style={{ animationDuration: "2s" }}
        />
        {/* Inner spinning arc */}
        <div
          className={`absolute ${sizeMap[size]} rounded-full border-2 border-transparent border-t-accent-cyan animate-spin`}
        />
      </div>
    </div>
  );
}
