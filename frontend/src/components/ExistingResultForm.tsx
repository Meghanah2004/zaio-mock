import { useId, useState } from "react";

export function ExistingResultForm({ onLookup, disabled }: { onLookup: (resultId: number) => void; disabled: boolean }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const inputId = useId();

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsed = Number(value);
    if (value.trim() === "" || !Number.isInteger(parsed) || parsed < 1) {
      setError("Enter a valid paper number.");
      return;
    }
    setError(null);
    onLookup(parsed);
  }

  return (
    <form onSubmit={handleSubmit}>
      <div className="existing-form-fields">
        <div className="field">
          <label className="field__label" htmlFor={inputId}>
            Paper number
          </label>
          <input
            id={inputId}
            className="input"
            type="number"
            inputMode="numeric"
            min={1}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            disabled={disabled}
            placeholder="e.g. 2"
            aria-invalid={Boolean(error)}
            aria-describedby={error ? `${inputId}-error` : undefined}
          />
        </div>
        <button type="submit" className="btn btn--secondary" disabled={disabled}>
          Open Result
          <span className="btn__arrow" aria-hidden="true">
            →
          </span>
        </button>
      </div>
      {error && (
        <p className="field__error mt-2" id={`${inputId}-error`}>
          {error}
        </p>
      )}
    </form>
  );
}
