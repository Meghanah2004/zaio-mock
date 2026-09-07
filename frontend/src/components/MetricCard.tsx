import type { ReactNode } from "react";
import { useTilt } from "../hooks/useTilt";
import type { StatusTone } from "./StatusBadge";

export function MetricCard({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: Extract<StatusTone, "success" | "warning" | "danger">;
}) {
  const tiltRef = useTilt<HTMLDivElement>(3);
  const toneClass = tone ? ` metric-card--accent-${tone}` : "";

  return (
    <div ref={tiltRef} className={`metric-card${toneClass}`}>
      <span className="metric-card__label">{label}</span>
      <span className="metric-card__value">{value}</span>
      {detail && <span className="metric-card__detail">{detail}</span>}
    </div>
  );
}
