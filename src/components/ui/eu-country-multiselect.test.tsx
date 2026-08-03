import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EuCountryMultiSelect } from "./eu-country-multiselect";
import { PRESET_GEOGRAPHIES } from "@/lib/eu-countries";

describe("EuCountryMultiSelect", () => {
  afterEach(cleanup);

  it("muestra los países prioritarios primero y marca la selección", () => {
    render(<EuCountryMultiSelect label="Países" value={["ES", "DE"]} onChange={vi.fn()} />);

    const group = screen.getByRole("group", { name: "Países" });
    expect(group).toHaveAttribute("tabindex", "0");
    const checkboxes = within(group).getAllByRole("checkbox");
    expect(checkboxes).toHaveLength(PRESET_GEOGRAPHIES.length);
    const names = within(group)
      .getAllByRole("checkbox")
      .map((checkbox) => checkbox.closest("label")?.textContent ?? "");
    expect(names[0]).toContain("España");
    expect(names[0]).toContain("prioritario");
    expect(names[1]).toContain("Alemania");
    expect(within(group).getByRole("checkbox", { name: /España/ })).toBeChecked();
    expect(within(group).getByRole("checkbox", { name: /Portugal/ })).not.toBeChecked();
  });

  it("ofrece comunidades autónomas españolas (ISO 3166-2)", () => {
    render(<EuCountryMultiSelect label="Ámbito" value={[]} onChange={vi.fn()} />);

    const group = screen.getByRole("group", { name: "Ámbito" });
    expect(within(group).getByRole("checkbox", { name: /Comunidad Valenciana/ })).toBeInTheDocument();
    expect(within(group).getByText("ES-VC")).toBeInTheDocument();
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

    fireEvent.change(screen.getByLabelText("Código ISO de país o subdivisión no listado"), {
      target: { value: "us" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Añadir ámbito" }));
    expect(onChange).toHaveBeenCalledWith(["ES", "US"]);
  });

  it("permite añadir subdivisión ISO 3166-2 por código custom", () => {
    const onChange = vi.fn();
    render(<EuCountryMultiSelect label="Ámbito" value={["ES"]} onChange={onChange} />);

    fireEvent.change(screen.getByLabelText("Código ISO de país o subdivisión no listado"), {
      target: { value: "es-vc" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Añadir ámbito" }));
    expect(onChange).toHaveBeenCalledWith(["ES", "ES-VC"]);
  });

  it("muestra chips de valores API que no están en el catálogo sin rechazarlos", () => {
    const onChange = vi.fn();
    render(<EuCountryMultiSelect label="Ámbito" value={["ES-XX"]} onChange={onChange} />);

    expect(screen.getByRole("button", { name: "Quitar ES-XX" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Quitar ES-XX" }));
    expect(onChange).toHaveBeenCalledWith([]);
  });

  it("rechaza códigos ISO mal formados", () => {
    const onChange = vi.fn();
    render(<EuCountryMultiSelect label="Países" value={[]} onChange={onChange} />);

    fireEvent.change(screen.getByLabelText("Código ISO de país o subdivisión no listado"), {
      target: { value: "USA" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Añadir ámbito" }));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/ISO de país|subdivisión/);
  });
});
