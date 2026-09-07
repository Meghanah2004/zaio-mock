import { useLayoutEffect, useRef, useState } from "react";
import type { GenerateResponse, PaperDocument, ResultResponse } from "../types/api";
import { MemoView } from "./MemoView";
import { PaperView } from "./PaperView";
import { PdfActions } from "./PdfActions";
import { ValidationReport } from "./ValidationReport";

type Tab = "paper" | "memo" | "validation";

const TABS: { id: Tab; label: string }[] = [
  { id: "paper", label: "Assessment" },
  { id: "memo", label: "Marking Memo" },
  { id: "validation", label: "Validation" },
];

/** All figures are counted directly off the real paper document - never invented. */
function overviewLine(paper: PaperDocument): string {
  const sectionCount = paper.sections.length;
  const subPartCount = paper.sections.reduce(
    (sum, section) => sum + section.questions.reduce((qSum, question) => qSum + (question.sub_questions?.length ?? 0), 0),
    0,
  );
  const sectionWord = sectionCount === 1 ? "section" : "sections";
  const subPartWord = subPartCount === 1 ? "sub-part" : "sub-parts";
  return `${paper.total_marks} marks · ${sectionCount} ${sectionWord} · ${subPartCount} ${subPartWord}`;
}

export function ResultTabs({ result, summary }: { result: ResultResponse; summary?: GenerateResponse }) {
  const [tab, setTab] = useState<Tab>("paper");
  const pdfAvailable = result.available_formats.includes("pdf");

  const tabRefs = useRef<Partial<Record<Tab, HTMLButtonElement>>>({});
  const [indicator, setIndicator] = useState<{ left: number; width: number } | null>(null);

  // Only recomputes on a discrete tab change or a window resize - never on
  // a continuous event - so this never causes excess re-rendering.
  useLayoutEffect(() => {
    function measure() {
      const el = tabRefs.current[tab];
      if (el) setIndicator({ left: el.offsetLeft, width: el.offsetWidth });
    }
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [tab]);

  return (
    <div className="stack stack--lg">
      <div className="cluster">
        <div className="tabs" role="tablist" aria-label="Result views">
          {indicator && (
            <span
              className="tabs__indicator"
              aria-hidden="true"
              style={{ transform: `translateX(${indicator.left}px)`, width: indicator.width }}
            />
          )}
          {TABS.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              className={`tab${tab === id ? " is-active" : ""}`}
              ref={(el) => {
                if (el) tabRefs.current[id] = el;
              }}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </div>
        <p className="overview-line">{overviewLine(result.paper)}</p>
      </div>

      <PdfActions resultId={result.result_id} available={pdfAvailable} />

      <div role="tabpanel">
        {tab === "paper" && <PaperView paper={result.paper} />}
        {tab === "memo" && <MemoView memo={result.memo} />}
        {tab === "validation" && <ValidationReport paper={result.paper} memo={result.memo} summary={summary} />}
      </div>
    </div>
  );
}
