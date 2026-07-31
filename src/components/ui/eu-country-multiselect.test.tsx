import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EuCountryMultiSelect } from "./eu-country-multiselect";
import { PRESET_COUNTRIES } from "@/lib/eu-countries";

describe("EuCountryMultiSelect", () => {
  afterEach(cleanup);

  it("muestra los países prioritarios primero y marca la selección", () => {
    render(<EuCountryMultiSelect label="Países" value={["ES", "DE"]} onChange={vi.fn()} />);

    const group = screen.getByRole("group", { name: "Países" });
    const checkboxes = within(group).getAllByRole("checkbox");
    expect(checkboxes).toHaveLength(PRESET_COUNTRIES.length);
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
    expect(screen.getByText("Sin coincidencias en el catálogo.")).toBeInTheDocument();
  });

  it("permite añadir un país no listado por código ISO global", () => {
    const onChange = vi.fn();
    render(<EuCountryMultiSelect label="Países" value={["ES"]} onChange={onChange} />);

    fireEvent.change(screen.getByLabelText("Código ISO de país no listado"), {
      target: { value: "us" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Añadir país" }));
    expect(onChange).toHaveBeenCalledWith(["ES", "US"]);
  });

  it("rechaza códigos ISO mal formados", () => {
    const onChange = vi.fn();
    render(<EuCountryMultiSelect label="Países" value={[]} onChange={onChange} />);

    fireEvent.change(screen.getByLabelText("Código ISO de país no listado"), {
      target: { value: "USA" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Añadir país" }));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/dos letras/);
  });
});
