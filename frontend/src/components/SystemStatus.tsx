import { useEffect, useState } from "react";
import { checkHealth } from "../services/api";

type HealthState = "checking" | "online" | "offline";

const POLL_INTERVAL_MS = 30_000;

const LABEL: Record<HealthState, string> = {
  checking: "Checking...",
  online: "Backend Online",
  offline: "Backend Offline",
};

export function SystemStatus() {
  const [state, setState] = useState<HealthState>("checking");

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        await checkHealth();
        if (!cancelled) setState("online");
      } catch {
        if (!cancelled) setState("offline");
      }
    }

    void poll();
    const id = window.setInterval(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  // Not role="status": that role is reserved for the generation LoadingState
  // (the meaningful, user-triggered live region) - a second status region
  // for passive backend connectivity would compete with it for screen
  // reader announcements without being clearly useful to interrupt for.
  return (
    <span className="system-status" aria-live="off">
      <span className={`status-dot status-dot--${state}`} aria-hidden="true" />
      {LABEL[state]}
    </span>
  );
}
