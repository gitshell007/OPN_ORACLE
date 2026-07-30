import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EuCountryMultiSelect } from "./eu-country-multiselect";

describe("EuCountryMultiSelect", () => {
  afterEach(cleanup);

  it("muestra los países prioritarios primero y marca la selección", () => {
    render(<EuCountryMultiSelect label="Países" value={["ES", "DE"]} onChange={vi.fn()} />);

    const group = screen.getByRole("group", { name: "Países" });
    const checkboxes = within(group).getAllByRole("checkbox");
    expect(checkboxes).toHaveLength(27);
    const names = within(group)
      .getAllByRole("checkbox")
      .map((checkbox) => checkbox.closest("label")?.textContent ?? "");
    expect(names[0]).toContain("España");
    expect(names[0]).toContain("prioritario");
    expect(names[1]).toContain("Alemania");
    expect(within(group).getByRole("checkbox", { name: /España/ })).toBeChecked();
    expect(within(group).getByRole("checkbox", { name: /Portugal/ })).not.toBeChecked();
  });

  it("permite añadir por lista y quitar desde los chips", () => {
    const onChange = vi.fn();
    render(<EuCountryMultiSelect label="Países" value={["ES"]} onChange={onChange} />);

    fireEvent.click(screen.getByRole("checkbox", { name: /Portugal/ }));
    expect(onChange).toHaveBeenCalledWith(["ES", "PT"]);

    fireEvent.click(screen.getByRole("button", { name: "Quitar España" }));
    expect(onChange).toHaveBeenCalledWith([]);
  });

  it("filtra por nombre o código", () => {
    render(<EuCountryMultiSelect label="Países" value={[]} onChange={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Filtrar Países"), { target: { value: "portu" } });
    const group = screen.getByRole("group", { name: "Países" });
    expect(within(group).getAllByRole("checkbox")).toHaveLength(1);
    expect(within(group).getByRole("checkbox", { name: /Portugal/ })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Filtrar Países"), { target: { value: "zz" } });
    expect(screen.getByText("Sin coincidencias.")).toBeInTheDocument();
  });
});
