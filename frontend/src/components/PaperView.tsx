import type { PaperDocument, PaperQuestion } from "../types/api";
import { WarningIcon } from "./icons";

function QuestionCard({ question }: { question: PaperQuestion }) {
  return (
    <article className="question-card" aria-label={`Question ${question.question_number}`}>
      <header className="question-card__header">
        <span className="question-card__number">Question {question.question_number}</span>
        <span className="question-card__badges">
          <span className="difficulty-tag">{question.difficulty}</span>
          <span className="marks-tag">{question.marks} marks</span>
        </span>
      </header>

      {question.scenario && <p className="question-card__scenario">{question.scenario}</p>}
      <p className="question-card__prompt">{question.question}</p>

      {question.sub_questions && question.sub_questions.length > 0 && (
        <ol className="sub-question-list">
          {question.sub_questions.map((sub, index) => (
            <li key={sub.id} className="sub-question">
              <div className="sub-question__body">
                <p className="sub-question__prompt">
                  <strong>{question.question_number}.{index + 1}</strong> {sub.prompt}
                </p>
              </div>
              <span className="marks-tag">{sub.marks} marks</span>
            </li>
          ))}
        </ol>
      )}
    </article>
  );
}

export function PaperView({ paper }: { paper: PaperDocument }) {
  return (
    <div className="fade-in stack stack--xl">
      <p className="document-disclaimer">
        <WarningIcon width={15} height={15} />
        {paper.status_disclaimer}
      </p>

      <dl className="document-meta">
        <div className="document-meta__item">
          <dt>Duration</dt>
          <dd>{paper.duration_minutes} minutes</dd>
        </div>
        <div className="document-meta__item">
          <dt>Total marks</dt>
          <dd>{paper.total_marks}</dd>
        </div>
      </dl>

      <section aria-label="Instructions">
        <h3 className="text-card-title mb-2">Instructions</h3>
        <ol className="instructions-list">
          {paper.instructions.map((instruction, index) => (
            <li key={index}>{instruction}</li>
          ))}
        </ol>
      </section>

      {paper.sections.map((section) => (
        <section key={section.id} className="paper-section" aria-labelledby={`section-${section.id}`}>
          <div className="paper-section__heading">
            <h3 className="paper-section__title" id={`section-${section.id}`}>
              {section.title}
            </h3>
            <span className="marks-tag">{section.marks} marks</span>
          </div>
          {section.questions.map((question) => (
            <QuestionCard key={question.id} question={question} />
          ))}
        </section>
      ))}
    </div>
  );
}
