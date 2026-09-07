import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { GenerateForm } from "./GenerateForm";

describe("GenerateForm", () => {
  it("renders the qualification selector, paper number, seed, PDF option, and generate button", () => {
    render(<GenerateForm onSubmit={vi.fn()} disabled={false} />);

    expect(screen.getByLabelText(/qualification/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/paper number/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/seed/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/render pdf/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /generate assessment/i })).toBeInTheDocument();
  });

  it("submits the exact request shape the API expects", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<GenerateForm onSubmit={onSubmit} disabled={false} />);

    await user.clear(screen.getByLabelText(/paper number/i));
    await user.type(screen.getByLabelText(/paper number/i), "5");
    await user.clear(screen.getByLabelText(/seed/i));
    await user.type(screen.getByLabelText(/seed/i), "123");
    await user.click(screen.getByLabelText(/render pdf/i));
    await user.click(screen.getByRole("button", { name: /generate assessment/i }));

    expect(onSubmit).toHaveBeenCalledWith({ qualification: "software_developer", paper_number: 5, seed: 123, pdf: false });
  });

  it("rejects an out-of-range paper number without calling onSubmit", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<GenerateForm onSubmit={onSubmit} disabled={false} />);

    await user.clear(screen.getByLabelText(/paper number/i));
    await user.type(screen.getByLabelText(/paper number/i), "999999");
    await user.click(screen.getByRole("button", { name: /generate assessment/i }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText(/enter a whole number between 1 and 9999/i)).toBeInTheDocument();
  });

  it("disables all controls while a generation is in progress", () => {
    render(<GenerateForm onSubmit={vi.fn()} disabled />);

    expect(screen.getByLabelText(/paper number/i)).toBeDisabled();
    expect(screen.getByRole("button", { name: /generating/i })).toBeDisabled();
  });
});
