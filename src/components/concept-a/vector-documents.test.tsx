import { api } from "@oracle/api-client";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DossierDocuments } from "./vector-documents";

describe("DossierDocuments", () => {
  afterEach(() => vi.restoreAllMocks());

  it("no llama a documentos para un slug sintético", async () => {
    const list = vi.spyOn(api.documents, "list").mockResolvedValue({ items: [] });
    render(<DossierDocuments dossierId="dach-2027" />);
    expect(screen.getByText(/ficha comparativa/i)).toBeInTheDocument();
    await new Promise((resolve) => window.setTimeout(resolve, 1));
    expect(list).not.toHaveBeenCalled();
  });

  it("carga documentos para un UUID persistente", async () => {
    const id = "11111111-1111-4111-8111-111111111111";
    const list = vi.spyOn(api.documents, "list").mockResolvedValue({ items: [] });
    render(<DossierDocuments dossierId={id} />);
    await waitFor(() => expect(list).toHaveBeenCalledWith(id));
    expect(screen.getByRole("heading", { name: "Documentos" })).toBeInTheDocument();
  });
});
