import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { AsyncActionButton } from "./async-action-button";

describe("AsyncActionButton", () => {
  it("renders as unavailable until React has hydrated the action", async () => {
    const onClick = vi.fn();

    const serverMarkup = renderToString(
      <AsyncActionButton onClick={onClick}>Ejecutar acción</AsyncActionButton>,
    );

    expect(serverMarkup).toContain("Cargando…");
    expect(serverMarkup).toContain("disabled");
    expect(serverMarkup).toContain('aria-busy="true"');
    expect(serverMarkup).toContain('data-action-ready="false"');

    render(<AsyncActionButton onClick={onClick}>Ejecutar acción</AsyncActionButton>);

    const readyButton = await screen.findByRole("button", { name: "Ejecutar acción" });
    await waitFor(() => expect(readyButton).toBeEnabled());

    fireEvent.click(readyButton);
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(readyButton).toHaveAttribute("aria-busy", "false");
    expect(readyButton).toHaveAttribute("data-action-ready", "true");
  });

  it("keeps async actions visibly blocked while loading", async () => {
    const onClick = vi.fn();

    render(
      <AsyncActionButton loading loadingLabel="Encolando…" onClick={onClick}>
        Informe documental
      </AsyncActionButton>,
    );

    const button = await screen.findByRole("button", { name: "Encolando…" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button).toHaveAttribute("aria-disabled", "true");

    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("exposes business disabled states as non-ready actions", async () => {
    render(<AsyncActionButton disabled>Incorporar a expediente</AsyncActionButton>);

    const button = await screen.findByRole("button", { name: "Incorporar a expediente" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAttribute("data-action-ready", "false");
  });
});
