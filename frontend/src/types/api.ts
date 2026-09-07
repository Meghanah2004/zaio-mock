/**
 * Request/response shapes for the ZAIO Mock EISA API.
 *
 * These types mirror `api/models.py` field-for-field. Do not add fields
 * here that the backend does not send/accept - this file is a reflection
 * of the API contract, not a place to invent new shape.
 */

export const SUPPORTED_QUALIFICATIONS = ["software_developer"] as const;
export type Qualification = (typeof SUPPORTED_QUALIFICATIONS)[number];

export interface GenerateRequest {
  qualification: string;
  paper_number: number;
  seed: number;
  pdf: boolean;
}

export type NoveltyStatus = "pass" | "flag_for_review" | "regenerate" | null;

export interface GenerateResponse {
  result_id: number;
  paper_id: string;
  qualification: string;
  total_marks: number;
  validation_passed: boolean;
  deterministic_checks_passed: number;
  deterministic_checks_total: number;
  novelty_status: NoveltyStatus;
  quality_review_approved: boolean;
  pdf_available: boolean;
}

export interface ResultResponse {
  result_id: number;
  available_formats: string[];
  paper: PaperDocument;
  memo: MemoDocument;
}

export interface HealthResponse {
  status: "ok";
  service: string;
}

export interface ErrorDetail {
  code: string;
  message: string;
  request_id: string | null;
}

export interface ErrorResponse {
  error: ErrorDetail;
}

/** Mirrors schemas/paper.schema.json. */
export interface PaperSubQuestion {
  id: string;
  prompt: string;
  marks: number;
  expected_response_type?: string;
}

export type QuestionDifficulty = "foundational" | "intermediate" | "advanced";

export interface PaperQuestion {
  id: string;
  section_id: string;
  question_number: string;
  type: string;
  scenario?: string | null;
  question: string;
  sub_questions?: PaperSubQuestion[];
  marks: number;
  difficulty: QuestionDifficulty;
  outcomes: string[];
  competencies: string[];
  expected_response_type: string;
}

export interface PaperSection {
  id: string;
  title: string;
  marks: number;
  outcomes: string[];
  competencies: string[];
  difficulty: QuestionDifficulty;
  question_types: string[];
  questions: PaperQuestion[];
}

export interface PaperDocument {
  paper_id: string;
  qualification: string;
  nqf_level: number | number[];
  status_disclaimer: string;
  duration_minutes: number;
  total_marks: number;
  instructions: string[];
  generation_meta?: Record<string, unknown>;
  sections: PaperSection[];
}

/** Mirrors schemas/memo.schema.json. */
export interface MemoCriterion {
  description: string;
  marks: number;
  non_awarding_notes?: string;
}

export interface MemoSubQuestion {
  id: string;
  total_marks: number;
  model_answer: string;
  criteria: MemoCriterion[];
  accepted_alternatives?: string[];
}

export interface MemoQuestion {
  question_id: string;
  total_marks: number;
  model_answer: string;
  criteria: MemoCriterion[];
  accepted_alternatives?: string[];
  partial_credit_guidance?: string;
  penalties?: string;
  sub_questions?: MemoSubQuestion[];
}

export interface MemoSection {
  id: string;
  questions: MemoQuestion[];
}

export interface MemoDocument {
  memo_id: string;
  paper_id: string;
  status_disclaimer: string;
  total_marks: number;
  generation_meta?: Record<string, unknown>;
  sections: MemoSection[];
}
