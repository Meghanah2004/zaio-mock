import { useCallback, useEffect, useState } from "react";

export type ThemePreference = "system" | "light" | "dark";

const STORAGE_KEY = "zaio-theme-preference";

function readStoredPreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // Private mode / storage blocked - fall back to following the OS.
  }
  return "system";
}

/** Applies the preference to the document root so styles/index.css tokens pick it up. */
function applyPreference(preference: ThemePreference) {
  const root = document.documentElement;
  if (preference === "system") {
    // No explicit choice yet - leave data-theme unset so the
    // prefers-color-scheme media query in styles/index.css decides.
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", preference);
  }
}

export function useTheme() {
  const [preference, setPreferenceState] = useState<ThemePreference>(() => readStoredPreference());

  useEffect(() => {
    applyPreference(preference);
  }, [preference]);

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Nothing to persist to - the in-memory state still applies for this session.
    }
  }, []);

  return { preference, setPreference };
}
