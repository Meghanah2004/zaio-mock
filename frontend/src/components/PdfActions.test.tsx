import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PdfActions } from "./PdfActions";

describe("PdfActions", () => {
  it("renders no download links when PDFs were not generated for this result", () => {
    render(<PdfActions resultId={2} available={false} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText(/not requested/i)).toBeInTheDocument();
  });

  it("renders paper and memo PDF links pointing at the API's own endpoints when available", () => {
    render(<PdfActions resultId={2} available />);
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAttribute("href", expect.stringContaining("/api/results/2/paper.pdf"));
    expect(links[1]).toHaveAttribute("href", expect.stringContaining("/api/results/2/memo.pdf"));
  });
});
