import { useId, useState } from "react";
import { SUPPORTED_QUALIFICATIONS } from "../types/api";
import type { GenerateRequest } from "../types/api";

interface FieldErrors {
  paperNumber?: string;
  seed?: string;
}

const MIN_PAPER_NUMBER = 1;
const MAX_PAPER_NUMBER = 9999;
const MIN_SEED = 0;
const MAX_SEED = 2147483647;

function validate(paperNumber: string, seed: string): FieldErrors {
  const errors: FieldErrors = {};
  const paperNumberValue = Number(paperNumber);
  if (paperNumber.trim() === "" || !Number.isInteger(paperNumberValue) || paperNumberValue < MIN_PAPER_NUMBER || paperNumberValue > MAX_PAPER_NUMBER) {
    errors.paperNumber = `Enter a whole number between ${MIN_PAPER_NUMBER} and ${MAX_PAPER_NUMBER}.`;
  }
  const seedValue = Number(seed);
  if (seed.trim() === "" || !Number.isInteger(seedValue) || seedValue < MIN_SEED || seedValue > MAX_SEED) {
    errors.seed = `Enter a whole number between ${MIN_SEED} and ${MAX_SEED}.`;
  }
  return errors;
}

export function GenerateForm({ onSubmit, disabled }: { onSubmit: (request: GenerateRequest) => void; disabled: boolean }) {
  const [qualification, setQualification] = useState<string>(SUPPORTED_QUALIFICATIONS[0]);
  const [paperNumber, setPaperNumber] = useState("2");
  const [seed, setSeed] = useState("20260906");
  const [pdf, setPdf] = useState(true);
  const [errors, setErrors] = useState<FieldErrors>({});

  const qualificationId = useId();
  const paperNumberId = useId();
  const seedId = useId();
  const pdfId = useId();

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fieldErrors = validate(paperNumber, seed);
    setErrors(fieldErrors);
    if (Object.keys(fieldErrors).length > 0) return;

    onSubmit({
      qualification,
      paper_number: Number(paperNumber),
      seed: Number(seed),
      pdf,
    });
  }

  return (
    <form onSubmit={handleSubmit} noValidate>
      <div className="generate-form-row">
        <div className="field-grid field-grid--inline">
          <div className="field">
            <label className="field__label" htmlFor={qualificationId}>
              Qualification
            </label>
            <select id={qualificationId} className="select" value={qualification} onChange={(e) => setQualification(e.target.value)} disabled={disabled}>
              {SUPPORTED_QUALIFICATIONS.map((q) => (
                <option key={q} value={q}>
                  {q.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label className="field__label" htmlFor={paperNumberId}>
              Paper number
            </label>
            <input
              id={paperNumberId}
              className="input"
              type="number"
              inputMode="numeric"
              min={MIN_PAPER_NUMBER}
              max={MAX_PAPER_NUMBER}
              value={paperNumber}
              onChange={(e) => setPaperNumber(e.target.value)}
              disabled={disabled}
              aria-invalid={Boolean(errors.paperNumber)}
              aria-describedby={errors.paperNumber ? `${paperNumberId}-error` : undefined}
            />
            {errors.paperNumber && (
              <p className="field__error" id={`${paperNumberId}-error`}>
                {errors.paperNumber}
              </p>
            )}
          </div>

          <div className="field">
            <label className="field__label" htmlFor={seedId}>
              Seed
            </label>
            <input
              id={seedId}
              className="input"
              type="number"
              inputMode="numeric"
              min={MIN_SEED}
              max={MAX_SEED}
              value={seed}
              onChange={(e) => setSeed(e.target.value)}
              disabled={disabled}
              aria-invalid={Boolean(errors.seed)}
              aria-describedby={errors.seed ? `${seedId}-error` : undefined}
            />
            {errors.seed && (
              <p className="field__error" id={`${seedId}-error`}>
                {errors.seed}
              </p>
            )}
          </div>

          <div className="field field--checkbox">
            <input id={pdfId} className="checkbox" type="checkbox" checked={pdf} onChange={(e) => setPdf(e.target.checked)} disabled={disabled} />
            <label className="field__label" htmlFor={pdfId}>
              Also render PDF versions
            </label>
          </div>

          <div className="field field--action">
            <button type="submit" className="btn btn--primary btn--cta" disabled={disabled}>
              {disabled && <span className="spinner" aria-hidden="true" />}
              {disabled ? "Generating..." : "Generate Assessment"}
              {!disabled && (
                <span className="btn__arrow" aria-hidden="true">
                  →
                </span>
              )}
            </button>
          </div>
        </div>
      </div>
    </form>
  );
}
