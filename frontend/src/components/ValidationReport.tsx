import type { GenerateResponse, MemoDocument, PaperDocument } from "../types/api";
import { StatusBadge } from "./StatusBadge";

function noveltyLabel(status: GenerateResponse["novelty_status"]): string {
  if (status === "pass") return "All questions passed similarity screening against the reference corpus.";
  if (status === "flag_for_review") return "One or more questions were flagged for review.";
  if (status === "regenerate") return "Regeneration was recommended.";
  return "Not available.";
}

/**
 * Marks reconciliation is always derivable from the paper/memo documents
 * themselves (both come back from GET /api/results/{id}), so it's shown
 * regardless of how the result was opened. The fuller validation/novelty/
 * quality-review report only exists in the response of a fresh
 * POST /api/generate (see api/models.py, GenerateResponse) - when a result
 * was opened via "existing result" lookup instead, that data was simply
 * never returned by the API, so it is honestly omitted rather than guessed.
 */
export function ValidationReport({ paper, memo, summary }: { paper: PaperDocument; memo: MemoDocument; summary?: GenerateResponse }) {
  const reconciled = paper.total_marks === memo.total_marks;

  return (
    <div className="card fade-in">
      <div className="card__body">
        {summary ? (
          <>
            <div className="report-section">
              <div className="report-section__heading">
                <h3 className="text-card-title">Deterministic validation</h3>
                <StatusBadge tone={summary.validation_passed ? "success" : "danger"} label={summary.validation_passed ? "Passed" : "Failed"} />
              </div>
              <p className="report-section__desc">
                {summary.deterministic_checks_passed} / {summary.deterministic_checks_total} deterministic checks passed.
              </p>
            </div>

            <div className="report-section">
              <div className="report-section__heading">
                <h3 className="text-card-title">Novelty screening</h3>
                <StatusBadge tone={summary.novelty_status === "pass" ? "success" : "warning"} label={summary.novelty_status ?? "unknown"} />
              </div>
              <p className="report-section__desc">{noveltyLabel(summary.novelty_status)}</p>
            </div>

            <div className="report-section">
              <div className="report-section__heading">
                <h3 className="text-card-title">Quality review</h3>
                <StatusBadge tone={summary.quality_review_approved ? "success" : "warning"} label={summary.quality_review_approved ? "Approved" : "Not approved"} />
              </div>
              <p className="report-section__desc">
                {summary.quality_review_approved
                  ? "An automated quality-review pass approved this paper and memo."
                  : "This paper and memo did not pass the automated quality-review pass."}
              </p>
            </div>
          </>
        ) : (
          <div className="report-section">
            <p className="report-section__desc">
              Deterministic validation, novelty, and quality-review results are only returned at the moment a paper is generated.
              This result was opened by paper number, so that information isn't available here - the marks reconciliation below
              still is, since it's read directly from the paper and memo documents.
            </p>
          </div>
        )}

        <div className="report-section">
          <h3 className="text-card-title mb-2">Marks reconciliation</h3>
          <div className="report-row">
            <span className="report-row__label">Paper total</span>
            <span className="report-row__value">{paper.total_marks}</span>
          </div>
          <div className="report-row">
            <span className="report-row__label">Memo total</span>
            <span className="report-row__value">{memo.total_marks}</span>
          </div>
          <div className="report-row">
            <span className="report-row__label">Reconciled</span>
            <span className="report-row__value">
              <StatusBadge tone={reconciled ? "success" : "danger"} label={reconciled ? "Yes" : "Mismatch"} />
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
