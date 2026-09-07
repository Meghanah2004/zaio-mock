import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RouterProvider } from "../router";
import { ApiError } from "../services/api";
import type { GenerateResponse, ResultResponse } from "../types/api";
import { Dashboard } from "./Dashboard";

/** Dashboard reads/writes the URL via useRoute() - every render needs the provider. */
function renderDashboard() {
  return render(
    <RouterProvider>
      <Dashboard />
    </RouterProvider>,
  );
}

const { generateAssessmentMock, getResultMock, checkHealthMock } = vi.hoisted(() => ({
  generateAssessmentMock: vi.fn(),
  getResultMock: vi.fn(),
  // AppShell always renders a SystemStatus pill that calls checkHealth() on
  // mount - stub it so Dashboard tests never make a real network call.
  checkHealthMock: vi.fn().mockResolvedValue({ status: "ok", service: "zaio-mock-eisa-api" }),
}));

vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>("../services/api");
  return {
    ...actual,
    generateAssessment: generateAssessmentMock,
    getResult: getResultMock,
    checkHealth: checkHealthMock,
    paperPdfUrl: (id: number) => `http://localhost:8000/api/results/${id}/paper.pdf`,
    memoPdfUrl: (id: number) => `http://localhost:8000/api/results/${id}/memo.pdf`,
  };
});

const generateResponse: GenerateResponse = {
  result_id: 2,
  paper_id: "mock-eisa-paper-02",
  qualification: "software_developer",
  total_marks: 100,
  validation_passed: true,
  deterministic_checks_passed: 90,
  deterministic_checks_total: 90,
  novelty_status: "pass",
  quality_review_approved: true,
  pdf_available: true,
};

const resultResponse: ResultResponse = {
  result_id: 2,
  available_formats: ["json", "md", "pdf"],
  paper: {
    paper_id: "mock-eisa-paper-02",
    qualification: "software_developer",
    nqf_level: 6,
    status_disclaimer: "This is a mock practice paper, not an official EISA/QCTO instrument.",
    duration_minutes: 180,
    total_marks: 100,
    instructions: ["Answer all questions."],
    sections: [
      {
        id: "A",
        title: "Section A",
        marks: 100,
        outcomes: ["O1"],
        competencies: ["C1"],
        difficulty: "intermediate",
        question_types: ["short_answer"],
        questions: [
          {
            id: "A1",
            section_id: "A",
            question_number: "A1",
            type: "short_answer",
            scenario: null,
            question: "What does TypeError mean in Python?",
            marks: 100,
            difficulty: "intermediate",
            outcomes: ["O1"],
            competencies: ["C1"],
            expected_response_type: "text",
          },
        ],
      },
    ],
  },
  memo: {
    memo_id: "mock-eisa-memo-02",
    paper_id: "mock-eisa-paper-02",
    status_disclaimer: "This is a mock practice memo, not an official EISA/QCTO instrument.",
    total_marks: 100,
    sections: [
      {
        id: "A",
        questions: [
          {
            question_id: "A1",
            total_marks: 100,
            model_answer: "It raises a TypeError.",
            criteria: [{ description: "Names TypeError", marks: 100 }],
          },
        ],
      },
    ],
  },
};

describe("Dashboard", () => {
  beforeEach(() => {
    generateAssessmentMock.mockReset();
    getResultMock.mockReset();
    checkHealthMock.mockReset().mockResolvedValue({ status: "ok", service: "zaio-mock-eisa-api" });
    // window.history is a real global shared by every test in this file -
    // a previous test's successful generate navigates to /assessments/:id
    // (see Dashboard.tsx), which would otherwise leak into the next test
    // and make it mount as if that assessment were already in the URL.
    window.history.pushState({}, "", "/");
  });

  it("shows an honest in-progress status while a generation request is pending, then the result", async () => {
    let resolveGenerate!: (value: GenerateResponse) => void;
    generateAssessmentMock.mockReturnValue(new Promise<GenerateResponse>((resolve) => (resolveGenerate = resolve)));
    getResultMock.mockResolvedValue(resultResponse);

    const user = userEvent.setup();
    renderDashboard();

    await user.click(screen.getByRole("button", { name: /generate assessment/i }));

    expect(screen.getByRole("status")).toHaveTextContent(/generating assessment/i);

    resolveGenerate(generateResponse);

    await waitFor(() => expect(screen.getByText(/mock-eisa-paper-02/i)).toBeInTheDocument());
    expect(screen.getByText("Approved")).toBeInTheDocument();

    // The top summary intentionally no longer shows a Validation card -
    // that detail now lives only in the Validation tab - so its "Passed"/
    // "Failed" wording must not appear in the summary region.
    const summarySection = screen.getByLabelText(/generation result summary/i);
    expect(within(summarySection).queryByText(/validation/i)).not.toBeInTheDocument();

    // Once the full paper document has also loaded, the summary gains a
    // Structure card counted directly from real section/sub-question data.
    await waitFor(() => expect(within(summarySection).getByText("1 section")).toBeInTheDocument());
    expect(within(summarySection).getByText("0 sub-parts")).toBeInTheDocument();
  });

  it("renders the paper content and PDF download links once the full result loads", async () => {
    generateAssessmentMock.mockResolvedValue(generateResponse);
    getResultMock.mockResolvedValue(resultResponse);

    const user = userEvent.setup();
    renderDashboard();
    await user.click(screen.getByRole("button", { name: /generate assessment/i }));

    await waitFor(() => expect(screen.getByText(/what does typeerror mean in python/i)).toBeInTheDocument());

    expect(screen.getByRole("link", { name: /download paper pdf/i })).toHaveAttribute(
      "href",
      "http://localhost:8000/api/results/2/paper.pdf",
    );
    expect(screen.getByRole("link", { name: /download marking memo pdf/i })).toHaveAttribute(
      "href",
      "http://localhost:8000/api/results/2/memo.pdf",
    );
  });

  it("shows a clean rate-limit message instead of a raw error when generation is throttled", async () => {
    generateAssessmentMock.mockRejectedValue(new ApiError("rate_limited", "Rate limit exceeded.", { retryAfterSeconds: 15 }));

    const user = userEvent.setup();
    renderDashboard();
    await user.click(screen.getByRole("button", { name: /generate assessment/i }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/too many requests/i));
    expect(screen.getByRole("alert")).toHaveTextContent(/15s/);
  });

  it("shows a clean server-error message on a 500 without leaking backend detail", async () => {
    generateAssessmentMock.mockRejectedValue(new ApiError("server", "Traceback: /app/src/generation.py line 42"));

    const user = userEvent.setup();
    renderDashboard();
    await user.click(screen.getByRole("button", { name: /generate assessment/i }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/something went wrong/i));
    expect(screen.getByRole("alert")).not.toHaveTextContent(/traceback/i);
  });

  it("shows a network-failure message when the API cannot be reached at all", async () => {
    generateAssessmentMock.mockRejectedValue(new ApiError("network", "unreachable"));

    const user = userEvent.setup();
    renderDashboard();
    await user.click(screen.getByRole("button", { name: /generate assessment/i }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/could not be reached/i));
  });

  it("looks up an existing result by paper number without requiring generation", async () => {
    getResultMock.mockResolvedValue(resultResponse);

    const user = userEvent.setup();
    renderDashboard();

    const lookupSection = screen.getByRole("region", { name: /open an existing assessment/i });
    await user.type(within(lookupSection).getByLabelText(/paper number/i), "2");
    await user.click(within(lookupSection).getByRole("button", { name: /open result/i }));

    await waitFor(() => expect(screen.getByText(/what does typeerror mean in python/i)).toBeInTheDocument());
    expect(generateAssessmentMock).not.toHaveBeenCalled();
  });

  it("gives a successfully generated result a real, shareable URL", async () => {
    generateAssessmentMock.mockResolvedValue(generateResponse);
    getResultMock.mockResolvedValue(resultResponse);

    const user = userEvent.setup();
    renderDashboard();
    await user.click(screen.getByRole("button", { name: /generate assessment/i }));

    await waitFor(() => expect(window.location.pathname).toBe("/assessments/2"));
  });

  it("loads the result directly when mounted on its URL (a shared link or a refresh)", async () => {
    window.history.pushState({}, "", "/assessments/2");
    getResultMock.mockResolvedValue(resultResponse);

    renderDashboard();

    await waitFor(() => expect(screen.getByText(/what does typeerror mean in python/i)).toBeInTheDocument());
    expect(getResultMock).toHaveBeenCalledWith(2);
    expect(generateAssessmentMock).not.toHaveBeenCalled();
  });

  it("shows a clean error, not a blank workspace, for a malformed assessment URL", () => {
    window.history.pushState({}, "", "/assessments/not-a-number");

    renderDashboard();

    expect(screen.getByRole("alert")).toHaveTextContent(/valid assessment id/i);
    expect(getResultMock).not.toHaveBeenCalled();
  });
});
