import { useEffect, useState } from "react";
import { ErrorBanner } from "../components/ErrorBanner";
import { ExistingResultForm } from "../components/ExistingResultForm";
import { GenerateForm } from "../components/GenerateForm";
import { Hero } from "../components/Hero";
import { LoadingState } from "../components/LoadingState";
import { ResultSummary } from "../components/ResultSummary";
import { ResultTabs } from "../components/ResultTabs";
import { SectionCard } from "../components/SectionCard";
import { useGenerate } from "../hooks/useGenerate";
import { useResult } from "../hooks/useResult";
import { matchAssessmentId, useRoute } from "../hooks/useRoute";
import { ApiError } from "../services/api";
import type { GenerateRequest } from "../types/api";

/** True for a URL that looks like it's trying to open a specific
 * assessment (/assessments/...) but the id segment isn't a valid one. */
function isMalformedAssessmentUrl(pathname: string): boolean {
  return pathname.startsWith("/assessments/") && matchAssessmentId(pathname) === null;
}

function SlidersIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="18" height="18">
      <path d="M3 6h6M13 6h4M3 14h4M11 14h6M9 4v4M7 12v4" />
    </svg>
  );
}

function FolderIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" width="18" height="18">
      <path d="M2.5 5.5A1.5 1.5 0 014 4h4l1.5 2h6.5A1.5 1.5 0 0117.5 7.5v7a1.5 1.5 0 01-1.5 1.5h-12A1.5 1.5 0 012.5 14.5v-9z" />
    </svg>
  );
}

/**
 * The one shared workspace: it renders identically for /, /assessments and
 * /assessments/:id (see App.tsx) rather than duplicating the generate/
 * lookup/result UI across three page components. The only thing that
 * differs is whether an :id was in the URL when this mounted.
 */
export function Dashboard() {
  const generate = useGenerate();
  const result = useResult();
  const { load: loadResult, reset: resetResult } = result;
  const { navigate } = useRoute();
  const [lastSeed, setLastSeed] = useState<number | undefined>(undefined);

  const busy = generate.state.status === "loading" || result.state.status === "loading";

  // A direct visit to /assessments/:id (a shared link, or a refresh) loads
  // that result once on mount. Read via a lazy initializer, not a reactive
  // dependency, since the navigate() below updates the URL itself and must
  // not re-trigger this fetch.
  const [initialResultId] = useState(() => matchAssessmentId(window.location.pathname));
  const [malformedUrl] = useState(() => isMalformedAssessmentUrl(window.location.pathname));
  useEffect(() => {
    if (initialResultId !== null) {
      void loadResult(initialResultId);
    }
  }, [initialResultId, loadResult]);

  // Once a generation succeeds, fetch the full paper/memo content for it -
  // the /api/generate response is a summary only (see api/models.py,
  // GenerateResponse); the full documents live behind /api/results/{id}.
  const generatedResultId = generate.state.status === "success" ? generate.state.data.result_id : null;
  useEffect(() => {
    if (generatedResultId !== null) {
      void loadResult(generatedResultId);
    }
  }, [generatedResultId, loadResult]);

  // Give the result a real, shareable, refresh-safe URL once it's loaded -
  // this only rewrites the address bar (see router.tsx), it never re-fetches
  // data that's already in state.
  const loadedResultId = result.state.status === "success" ? result.state.data.result_id : null;
  useEffect(() => {
    if (loadedResultId !== null) {
      navigate(`/assessments/${loadedResultId}`);
    }
  }, [loadedResultId, navigate]);

  function handleGenerate(request: GenerateRequest) {
    resetResult();
    setLastSeed(request.seed);
    void generate.run(request);
  }

  function handleLookup(resultId: number) {
    generate.reset();
    setLastSeed(undefined);
    void loadResult(resultId);
  }

  return (
    <>
      <section className="hero-section">
        <Hero />
      </section>

      {malformedUrl && (
        <>
          <ErrorBanner error={new ApiError("validation", "That doesn't look like a valid assessment ID.")} />
          <button type="button" className="btn btn--secondary" onClick={() => navigate("/assessments")}>
            Back to Assessments
          </button>
        </>
      )}

      <div className="console-layer">
        <SectionCard
          titleIcon={<SlidersIcon />}
          title="Create an assessment"
          tagline="Same standards. New questions."
          className={`console-panel${busy ? " card--sent" : ""}`}
        >
          <GenerateForm onSubmit={handleGenerate} disabled={busy} />
        </SectionCard>
      </div>

      {generate.state.status === "loading" && <LoadingState />}
      {generate.state.status === "error" && <ErrorBanner error={generate.state.error} />}
      {generate.state.status === "success" && (
        <ResultSummary
          result={generate.state.data}
          seed={lastSeed}
          paper={result.state.status === "success" ? result.state.data.paper : undefined}
        />
      )}

      <div className="console-layer">
        <SectionCard
          titleIcon={<FolderIcon />}
          title="Open an existing assessment"
          className="console-panel console-panel--secondary"
        >
          <ExistingResultForm onLookup={handleLookup} disabled={busy} />
        </SectionCard>
      </div>

      {result.state.status === "loading" && generate.state.status !== "loading" && (
        <LoadingState title="Loading result" hint="Fetching the generated paper and memo." />
      )}
      {result.state.status === "error" && <ErrorBanner error={result.state.error} />}
      {result.state.status === "success" && (
        <section className="workspace-transition fade-in-up" aria-label="Generated assessment workspace">
          <ResultTabs result={result.state.data} summary={generate.state.status === "success" ? generate.state.data : undefined} />
        </section>
      )}
    </>
  );
}
