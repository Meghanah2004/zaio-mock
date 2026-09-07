/**
 * The API generates a paper synchronously and returns one response - it
 * does not expose a per-stage progress endpoint (see docs/API.md, "Why
 * generation is synchronous"). This component deliberately shows a single
 * honest "in progress" state rather than fabricating a fake step-by-step
 * progress bar or percentage the backend cannot actually report.
 */
export function LoadingState({
  title = "Generating assessment",
  hint = "Validating content and preparing your result. This runs the full generation pipeline on the server and can take a little while.",
}: {
  title?: string;
  hint?: string;
}) {
  return (
    <div className="loading-state fade-in" role="status" aria-live="polite">
      <span className="loading-state__spinner" aria-hidden="true" />
      <div>
        <p className="loading-state__title">{title}</p>
        <p className="loading-state__hint">{hint}</p>
      </div>
    </div>
  );
}
