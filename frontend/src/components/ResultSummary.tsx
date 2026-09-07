import type { GenerateResponse, PaperDocument } from "../types/api";
import { MetricCard } from "./MetricCard";
import { StatusBadge } from "./StatusBadge";

function noveltyLabel(status: GenerateResponse["novelty_status"]): string {
  if (status === "pass") return "Pass";
  if (status === "flag_for_review") return "Flagged for review";
  if (status === "regenerate") return "Regenerate recommended";
  return "Not available";
}

/** Counted directly off the real paper document - never invented. */
function structureText(paper: PaperDocument): { value: string; detail: string } {
  const sectionCount = paper.sections.length;
  const subPartCount = paper.sections.reduce(
    (sum, section) => sum + section.questions.reduce((qSum, question) => qSum + (question.sub_questions?.length ?? 0), 0),
    0,
  );
  return {
    value: `${sectionCount} ${sectionCount === 1 ? "section" : "sections"}`,
    detail: `${subPartCount} ${subPartCount === 1 ? "sub-part" : "sub-parts"}`,
  };
}

/**
 * seed is optional and only ever known right after a fresh /api/generate
 * call (the Dashboard's own submitted value) - the API never returns it,
 * so it's simply omitted rather than guessed when a result was opened via
 * "existing result" lookup instead of a fresh generation.
 *
 * paper is optional too: it only exists once the separate GET
 * /api/results/{id} fetch completes (see api/models.py, GenerateResponse
 * vs ResultResponse) - the Structure card is simply omitted until then,
 * rather than showing a placeholder or guessed figure.
 */
export function ResultSummary({ result, seed, paper }: { result: GenerateResponse; seed?: number; paper?: PaperDocument }) {
  const structure = paper ? structureText(paper) : null;

  return (
    <section className="fade-in-up stack stack--lg" aria-label="Generation result summary">
      <div>
        <h2 className="text-page-title">Assessment generated</h2>
        <dl className="document-meta mt-2">
          <div className="document-meta__item">
            <dt>Qualification</dt>
            <dd>{result.qualification.replace(/_/g, " ")}</dd>
          </div>
          <div className="document-meta__item">
            <dt>Paper</dt>
            <dd>{result.paper_id}</dd>
          </div>
          {seed !== undefined && (
            <div className="document-meta__item">
              <dt>Seed</dt>
              <dd>{seed}</dd>
            </div>
          )}
        </dl>
      </div>

      <div className="metric-grid">
        <MetricCard label="Total Marks" value={result.total_marks} />
        <MetricCard
          label="Novelty"
          value={<StatusBadge tone={result.novelty_status === "pass" ? "success" : "warning"} label={noveltyLabel(result.novelty_status)} />}
          tone={result.novelty_status === "pass" ? "success" : "warning"}
        />
        <MetricCard
          label="Quality Review"
          value={<StatusBadge tone={result.quality_review_approved ? "success" : "warning"} label={result.quality_review_approved ? "Approved" : "Not approved"} />}
          tone={result.quality_review_approved ? "success" : "warning"}
        />
        {structure && <MetricCard label="Structure" value={structure.value} detail={structure.detail} />}
      </div>
    </section>
  );
}
