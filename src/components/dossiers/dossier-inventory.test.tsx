import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  replace: vi.fn(),
  params: "",
}));

vi.mock("@oracle/api-client", () => {
  class ApiError extends Error {
    constructor(
      public status: number,
      public problem: { detail: string },
    ) {
      super(problem.detail);
    }
  }
  return { ApiError, api: { dossiers: { list: mocks.list } } };
});

vi.mock("next/navigation", () => ({
  usePathname: () => "/app/dossiers",
  useRouter: () => ({ replace: mocks.replace }),
  useSearchParams: () => new URLSearchParams(mocks.params),
}));

vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => ({
    identity: { user: { id: "11111111-1111-4111-8111-111111111111" } },
  }),
}));

vi.mock("@/components/auth/auth-boundary", () => ({
  PermissionGate: ({ children }: { children: React.ReactNode }) => children,
}));

vi.mock("@/components/navigation/create-product-dossier-dialog", () => ({
  CreateProductDossierDialog: ({ open }: { open: boolean }) =>
    open ? <div role="dialog">Crear expediente real</div> : null,
}));

import { ApiError } from "@oracle/api-client";
import { DossierInventory } from "./dossier-inventory";

const dossier = {
  id: "22222222-2222-4222-8222-222222222222",
  title: "Expansión Delta",
  description: "Seguimiento de una expansión regional.",
  dossier_type: "project",
  status: "active",
  strategic_goal: "Validar alianzas antes del siguiente hito.",
  health_score: 78,
  opportunity_score: 86,
  risk_score: 31,
  owner_user_id: "11111111-1111-4111-8111-111111111111",
  updated_at: "2026-07-11T08:30:00Z",
};

describe("DossierInventory", () => {
  beforeEach(() => {
    const values = new Map<string, string>();
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
        removeItem: (key: string) => values.delete(key),
        clear: () => values.clear(),
        key: (index: number) => [...values.keys()][index] ?? null,
        get length() { return values.size; },
      },
    });
    vi.clearAllMocks();
    mocks.params = "";
    mocks.list.mockResolvedValue({
      data: [dossier],
      meta: { page: 1, size: 25, total: 1 },
    });
  });
  afterEach(cleanup);

  it("carga el listado server-side desde el estado validado de la URL", async () => {
    mocks.params =
      "q=Delta&status=active&type=project&owner=me&page=2&size=10&sort=-risk_score";
    render(<DossierInventory />);

    await waitFor(() =>
      expect(mocks.list).toHaveBeenCalledWith({
        page: 2,
        size: 10,
        sort: "-risk_score",
        status: "active",
        type: "project",
        owner: "11111111-1111-4111-8111-111111111111",
        search: "Delta",
      }),
    );
    expect(screen.getAllByRole("heading", { name: "Expansión Delta" })).toHaveLength(1);
    expect(screen.getAllByText("86")).not.toHaveLength(0);
  });

  it("acepta el filtro enlazado por el read model de inicio", async () => {
    mocks.params = "filter%5Bstatus%5D=active";
    render(<DossierInventory />);

    await waitFor(() =>
      expect(mocks.list).toHaveBeenCalledWith(
        expect.objectContaining({ status: "active" }),
      ),
    );
    expect(screen.getByLabelText("Filtrar por estado")).toHaveValue("active");
  });

  it("codifica búsqueda y sort en una URL compartible", async () => {
    render(<DossierInventory />);
    await screen.findAllByText("Expansión Delta");

    fireEvent.change(screen.getByLabelText("Buscar expedientes"), {
      target: { value: "  alianza norte " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Buscar" }));
    expect(mocks.replace).toHaveBeenCalledWith(
      "/app/dossiers?q=alianza+norte",
      { scroll: false },
    );

    fireEvent.click(screen.getByRole("button", { name: /Expediente/ }));
    expect(mocks.replace).toHaveBeenCalledWith(
      "/app/dossiers?sort=title",
      { scroll: false },
    );
  });

  it("ofrece selección accesible, densidad y columnas sin acciones masivas ficticias", async () => {
    render(<DossierInventory />);
    await screen.findAllByText("Expansión Delta");

    fireEvent.click(
      screen.getByLabelText("Seleccionar todos los expedientes de esta página"),
    );
    expect(screen.getByText("1 seleccionados")).toBeVisible();
    expect(screen.getByText("La selección se limita a esta página.")).toBeVisible();

    fireEvent.change(screen.getByLabelText("Densidad de filas"), {
      target: { value: "compact" },
    });
    expect(screen.getByLabelText("Densidad de filas")).toHaveValue("compact");
    expect(screen.getByText("Columnas")).toBeVisible();
  });

  it("distingue 403 de un fallo recuperable", async () => {
    mocks.list.mockRejectedValueOnce(
      new ApiError(403, { detail: "Permiso denegado" } as never),
    );
    render(<DossierInventory />);

    expect(await screen.findByRole("heading", { name: "Acceso restringido" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Reintentar" })).not.toBeInTheDocument();
  });

  it("reutiliza el diálogo productivo de creación", async () => {
    render(<DossierInventory />);
    await screen.findAllByText("Expansión Delta");
    fireEvent.click(screen.getByRole("button", { name: "Nuevo expediente" }));
    expect(screen.getByRole("dialog", { name: "" })).toHaveTextContent(
      "Crear expediente real",
    );
  });
});
