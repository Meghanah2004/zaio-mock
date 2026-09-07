import { CheckIcon, CrossIcon, WarningIcon } from "./icons";

export type StatusTone = "success" | "warning" | "danger" | "neutral";

const ICON: Record<StatusTone, typeof CheckIcon | null> = {
  success: CheckIcon,
  warning: WarningIcon,
  danger: CrossIcon,
  neutral: null,
};

/**
 * A pass/warn/fail chip. Never communicates status by color alone - every
 * tone pairs a distinct icon with its own text label.
 */
export function StatusBadge({ tone, label }: { tone: StatusTone; label: string }) {
  const Icon = ICON[tone];
  return (
    <span className={`badge badge--${tone}`}>
      {Icon && <Icon />}
      {label}
    </span>
  );
}
