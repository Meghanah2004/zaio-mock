import { SectionCard } from "../components/SectionCard";

interface Section {
  title: string;
  body: string[];
}

const SECTIONS: Section[] = [
  {
    title: "Overview",
    body: [
      "Mock EISA Generator produces practice occupational assessments for the QCTO “Occupational Certificate: Software Developer” qualification (SAQA ID 118707). It is practice material only, not an official EISA/QCTO instrument - every generated paper and memo says so explicitly.",
    ],
  },
  {
    title: "How the generator works",
    body: [
      "A fixed pipeline turns the supplied reference corpus into a blueprint, a paper, a marking memo, and a validation report. Deterministic stages - reference analysis, blueprint construction, schema/marks/coverage validation, novelty screening, and PDF rendering - never call a language model. Only question generation, memo generation, and the final quality review do.",
    ],
  },
  {
    title: "Reference corpus",
    body: [
      "The reference material lives in a read-only directory and is analyzed once into a structured summary. It is never modified and never used as a question bank to copy from - it establishes the topics, outcomes and competencies a generated assessment must cover, nothing more.",
    ],
  },
  {
    title: "Assessment generation",
    body: [
      "One provider call produces each section's question, scoped to that section's declared outcomes and competencies from the blueprint. The model's response is treated as untrusted input: IDs, marks, and structure are all checked deterministically afterward rather than assumed correct.",
    ],
  },
  {
    title: "Validation",
    body: [
      "A battery of deterministic checks confirms JSON Schema conformance, mark arithmetic (question and section totals reconcile exactly), and outcome coverage - each question must declare real outcomes drawn from the blueprint, not the section's entire outcome list copied wholesale.",
    ],
  },
  {
    title: "Marking memo",
    body: [
      "One provider call per question produces a model answer and a set of marking criteria whose marks sum to that question's total. A memo can never claim more or fewer marks than the paper does for the same question - that's enforced, not just expected.",
    ],
  },
  {
    title: "Novelty screening",
    body: [
      "Generated questions are compared against the reference corpus using lexical (TF-IDF/cosine) similarity. This is a screen for accidental overlap with the source material, not a formal plagiarism proof.",
    ],
  },
  {
    title: "Quality review",
    body: [
      "A single provider call reviews the completed paper and memo together and returns an approval decision. It's separate from deterministic validation and from novelty screening - three independent checks, not one combined score.",
    ],
  },
  {
    title: "PDF generation",
    body: [
      "The paper and memo can optionally be rendered to PDF. All model-derived text is escaped before rendering so it can't be interpreted as markup by the PDF renderer.",
    ],
  },
  {
    title: "API overview",
    body: [
      "A thin FastAPI layer exposes GET /api/health, POST /api/generate, GET /api/results/{id}, GET /api/results/{id}/paper.pdf and GET /api/results/{id}/memo.pdf. The API does not duplicate generation logic - it calls directly into the same pipeline the command-line tool uses.",
    ],
  },
  {
    title: "Security & validation notes",
    body: [
      "Requests are rate-limited per client, CORS is an explicit origin allow-list (never a wildcard), result IDs are bounded integers so path traversal isn't possible through them, and error responses never include stack traces, filesystem paths, or provider exception details.",
    ],
  },
];

export function Documentation() {
  return (
    <>
      <div className="hero__content">
        <span className="hero__eyebrow">Documentation</span>
        <h1 className="text-page-title">How Mock EISA works</h1>
        <p className="hero__lede">A concise technical reference for the assessment-generation pipeline and its API.</p>
      </div>

      {SECTIONS.map((section) => (
        <SectionCard key={section.title} title={section.title}>
          {section.body.map((paragraph, index) => (
            <p key={index} className={index > 0 ? "mt-2" : undefined}>
              {paragraph}
            </p>
          ))}
        </SectionCard>
      ))}
    </>
  );
}
