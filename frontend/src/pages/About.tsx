import { SectionCard } from "../components/SectionCard";

export function About() {
  return (
    <>
      <div className="hero__content">
        <span className="hero__eyebrow">About</span>
        <h1 className="text-page-title">What Mock EISA is</h1>
        <p className="hero__lede">
          A practice-assessment generator for the QCTO Occupational Certificate: Software Developer qualification.
        </p>
      </div>

      <SectionCard title="Purpose">
        <p>
          Mock EISA Generator creates practice occupational assessments - a paper, its marking memo, and a validation report - for
          candidates and educators preparing for the real External Integrated Summative Assessment. It is a study aid, not the
          official instrument, and every document it produces states that clearly.
        </p>
      </SectionCard>

      <SectionCard title="Reference-driven generation">
        <p>
          Every assessment is generated against a supplied reference corpus - the actual training material for the qualification.
          Questions are scoped to that material's outcomes and competencies rather than written from a generic template, and the
          reference material itself is never modified or exposed as a question bank.
        </p>
      </SectionCard>

      <SectionCard title="Deterministic validation">
        <p>
          Every generated paper passes through the same fixed set of checks: schema conformance, mark arithmetic, and outcome
          coverage. These run in plain code, not in a model, so the same paper produces the same validation result every time.
        </p>
      </SectionCard>

      <SectionCard title="Marking memo">
        <p>
          Each assessment ships with a complete marking memo - a model answer and marking criteria for every question, with marks
          that reconcile exactly against the paper.
        </p>
      </SectionCard>

      <SectionCard title="PDF outputs">
        <p>The paper and memo are both available as PDF downloads alongside their on-screen views, generated from the same data.</p>
      </SectionCard>
    </>
  );
}
