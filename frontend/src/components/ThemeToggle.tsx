import type { ThemePreference } from "../hooks/useTheme";
import { MoonIcon, SunIcon } from "./icons";

const OPTIONS: { value: ThemePreference; label: string; icon: typeof SunIcon }[] = [
  { value: "light", label: "Light theme", icon: SunIcon },
  { value: "dark", label: "Dark theme", icon: MoonIcon },
];

export function ThemeToggle({ preference, onChange }: { preference: ThemePreference; onChange: (next: ThemePreference) => void }) {
  // "system" has no dedicated button - it's the initial state before a
  // viewer picks one explicitly. Once they click either option we track
  // their explicit choice (see useTheme).
  const active = preference === "system" ? "dark" : preference;

  return (
    <div className="theme-toggle" role="group" aria-label="Theme">
      {OPTIONS.map(({ value, label, icon: Icon }) => (
        <button
          key={value}
          type="button"
          className={`theme-toggle__option${active === value ? " is-active" : ""}`}
          aria-label={label}
          aria-pressed={active === value}
          onClick={() => onChange(value)}
        >
          <Icon width={15} height={15} />
        </button>
      ))}
    </div>
  );
}
