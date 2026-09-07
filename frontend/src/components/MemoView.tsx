import type { MemoDocument, MemoQuestion } from "../types/api";
import { WarningIcon } from "./icons";

function CriteriaList({ criteria }: { criteria: MemoQuestion["criteria"] }) {
  return (
    <ul className="criteria-list">
      {criteria.map((criterion, index) => (
        <li key={index} className="criteria-list__item">
          <div>
            <span className="criteria-list__desc">{criterion.description}</span>
            {criterion.non_awarding_notes && <p className="criteria-list__note">Does not earn marks: {criterion.non_awarding_notes}</p>}
          </div>
          <span className="marks-tag">{criterion.marks} marks</span>
        </li>
      ))}
    </ul>
  );
}

function MemoQuestionBlock({ question }: { question: MemoQuestion }) {
  return (
    <article className="question-card" aria-label={`Memo for ${question.question_id}`}>
      <header className="question-card__header">
        <span className="question-card__number">{question.question_id}</span>
        <span className="marks-tag">{question.total_marks} marks</span>
      </header>

      <div className="memo-block">
        <span className="memo-block__label">Expected answer</span>
        <p className="memo-block__text">{question.model_answer}</p>
      </div>

      <div className="memo-block">
        <span className="memo-block__label">Marking criteria</span>
        <CriteriaList criteria={question.criteria} />
      </div>

      {question.accepted_alternatives && question.accepted_alternatives.length > 0 && (
        <div className="memo-block">
          <span className="memo-block__label">Accepted alternatives</span>
          <ul className="instructions-list">
            {question.accepted_alternatives.map((alt, index) => (
              <li key={index}>{alt}</li>
            ))}
          </ul>
        </div>
      )}

      {question.partial_credit_guidance && (
        <div className="memo-block">
          <span className="memo-block__label">Partial credit</span>
          <p className="memo-block__text">{question.partial_credit_guidance}</p>
        </div>
      )}

      {question.penalties && (
        <div className="memo-block">
          <span className="memo-block__label">Penalties</span>
          <p className="memo-block__text">{question.penalties}</p>
        </div>
      )}

      {question.sub_questions && question.sub_questions.length > 0 && (
        <ol className="sub-question-list">
          {question.sub_questions.map((sub) => (
            <li key={sub.id} className="sub-question">
              <div className="sub-question__body">
                <p className="sub-question__prompt">{sub.model_answer}</p>
                <CriteriaList criteria={sub.criteria} />
              </div>
              <span className="marks-tag">{sub.total_marks} marks</span>
            </li>
          ))}
        </ol>
      )}
    </article>
  );
}

export function MemoView({ memo }: { memo: MemoDocument }) {
  return (
    <div className="fade-in stack stack--xl">
      <p className="document-disclaimer">
        <WarningIcon width={15} height={15} />
        {memo.status_disclaimer}
      </p>
      <dl className="document-meta">
        <div className="document-meta__item">
          <dt>Total marks</dt>
          <dd>{memo.total_marks}</dd>
        </div>
      </dl>

      {memo.sections.map((section) => (
        <section key={section.id} className="paper-section" aria-labelledby={`memo-section-${section.id}`}>
          <div className="paper-section__heading">
            <h3 className="paper-section__title" id={`memo-section-${section.id}`}>
              Section {section.id}
            </h3>
          </div>
          {section.questions.map((question) => (
            <MemoQuestionBlock key={question.question_id} question={question} />
          ))}
        </section>
      ))}
    </div>
  );
}
