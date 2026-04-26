interface GaugeChartProps {
  value: number;
  max: number;
  label: string;
  displayValue: string;
  color?: "cyan" | "pink";
}

export function GaugeChart({
  value,
  max,
  label,
  displayValue,
  color = "cyan",
}: GaugeChartProps) {
  const pct = max > 0 ? Math.min(value / max, 1) : 0;
  const radius = 40;
  const circumference = Math.PI * radius;
  const offset = circumference - pct * circumference;
  const strokeColor =
    color === "cyan" ? "var(--color-accent-cyan)" : "var(--color-accent-pink)";

  return (
    <div className="flex flex-col items-center gap-1">
      <svg
        width="100"
        height="56"
        viewBox="0 0 100 56"
        className="overflow-visible"
      >
        {/* Background arc */}
        <path
          d="M 10 50 A 40 40 0 0 1 90 50"
          fill="none"
          stroke="rgba(123,45,142,0.2)"
          strokeWidth="6"
          strokeLinecap="round"
        />
        {/* Value arc */}
        <path
          d="M 10 50 A 40 40 0 0 1 90 50"
          fill="none"
          stroke={strokeColor}
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className="transition-all duration-500 ease-out"
          style={{
            filter: `drop-shadow(0 0 4px ${strokeColor})`,
          }}
        />
      </svg>
      <span className="text-lg font-semibold font-[family-name:var(--font-mono)] text-text-primary">
        {displayValue}
      </span>
      <span className="text-xs text-text-secondary">{label}</span>
    </div>
  );
}
