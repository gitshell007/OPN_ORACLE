import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LanguageMultiSelect } from "./language-multiselect";

describe("LanguageMultiSelect", () => {
  it("filtra por alias y permite marcar alemán sin saber el código", () => {
    const onChange = vi.fn();
    render(
      <LanguageMultiSelect
        label="Idiomas de la vigilancia"
        value={["es"]}
        onChange={onChange}
      />,
    );

    fireEvent.change(screen.getByLabelText(/Filtrar Idiomas/), {
      target: { value: "ale" },
    });
    expect(screen.getByText("Alemán")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /Alemán/i }));
    expect(onChange).toHaveBeenCalledWith(["es", "de"]);
  });

  it("quita un idioma desde el chip", () => {
    const onChange = vi.fn();
    render(
      <LanguageMultiSelect
        label="Idiomas de la vigilancia"
        value={["es", "de"]}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Quitar Alemán" }));
    expect(onChange).toHaveBeenCalledWith(["es"]);
  });
});
