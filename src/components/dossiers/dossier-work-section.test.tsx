import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  actorLinks: vi.fn(),
  actorGet: vi.fn(),
  actorList: vi.fn(),
  actorAttach: vi.fn(),
  actorCandidates: vi.fn(),
  actorImportCandidate: vi.fn(),
  actorUpdateLink: vi.fn(),
  meetingsList: vi.fn(),
  meetingCreate: vi.fn(),
  meetingUpdate: vi.fn(),
  meetingComplete: vi.fn(),
  briefings: vi.fn(),
  createBriefing: vi.fn(),
  tasksList: vi.fn(),
  taskCreate: vi.fn(),
  taskUpdate: vi.fn(),
  decisionsList: vi.fn(),
  decisionCreate: vi.fn(),
  decisionUpdate: vi.fn(),
  replace: vi.fn(),
  params: new URLSearchParams(),
  success: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/app/dossiers/dossier-1/tasks",
  useRouter: () => ({ replace: mocks.replace }),
  useSearchParams: () => mocks.params,
}));

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    actors: {
      listDossier: mocks.actorLinks,
      get: mocks.actorGet,
      list: mocks.actorList,
      attach: mocks.actorAttach,
      candidates: mocks.actorCandidates,
      importCandidate: mocks.actorImportCandidate,
      updateLink: mocks.actorUpdateLink,
    },
    meetings: {
      list: mocks.meetingsList,
      create: mocks.meetingCreate,
      update: mocks.meetingUpdate,
      complete: mocks.meetingComplete,
      briefings: mocks.briefings,
      createBriefing: mocks.createBriefing,
    },
    tasks: {
      list: mocks.tasksList,
      create: mocks.taskCreate,
      update: mocks.taskUpdate,
    },
    decisions: {
      list: mocks.decisionsList,
      create: mocks.decisionCreate,
      update: mocks.decisionUpdate,
    },
  },
}));

vi.mock("sonner", () => ({ toast: { success: mocks.success } }));
vi.mock("@/components/auth/auth-boundary", () => ({
  PermissionGate: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => ({
    identity: { user: { id: "user-1" } },
  }),
}));

import { DossierWorkSection } from "./dossier-work-section";

describe("DossierWorkSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.params = new URLSearchParams();
    mocks.tasksList.mockResolvedValue({
      data: [{
        id: "task-1",
        tenant_id: "tenant-1",
        dossier_id: "dossier-1",
        title: "Preparar propuesta",
        status: "open",
        priority: "high",
        version: 3,
        updated_at: "2026-07-11T09:00:00Z",
      }],
      meta: { page: 1, size: 25, total: 1 },
    });
    mocks.taskUpdate.mockResolvedValue({ id: "task-1", status: "done", version: 4 });
    mocks.actorLinks.mockResolvedValue({ data: [], meta: { page: 1, size: 25, total: 0 } });
    mocks.actorList.mockResolvedValue({
      data: [{ id: "actor-1", tenant_id: "tenant-1", canonical_name: "Consorcio Lumen" }],
      meta: { page: 1, size: 100, total: 1 },
    });
    mocks.actorAttach.mockResolvedValue({ id: "link-1", tenant_id: "tenant-1" });
    mocks.actorCandidates.mockResolvedValue({ data: [], meta: { total: 0 } });
    mocks.meetingsList.mockResolvedValue({ data: [], meta: { page: 1, size: 25, total: 0 } });
    mocks.meetingComplete.mockResolvedValue({
      meeting: { id: "meeting-1", status: "completed", version: 2 },
      decisions: [],
      tasks: [],
      replayed: false,
    });
    mocks.briefings.mockResolvedValue({ data: [], meta: { page: 1, size: 25, total: 0 } });
    mocks.decisionsList.mockResolvedValue({ data: [], meta: { page: 1, size: 25, total: 0 } });
  });

  afterEach(cleanup);

  it("carga tareas reales y completa una mediante transición versionada", async () => {
    mocks.params = new URLSearchParams("selected=task-1");
    render(<DossierWorkSection dossierId="dossier-1" kind="tasks" />);

    const detail = await screen.findByRole("dialog", { name: "Preparar propuesta" });
    fireEvent.click(within(detail).getByRole("button", { name: "Completada" }));

    await waitFor(() => expect(mocks.taskUpdate).toHaveBeenCalledWith(
      "task-1",
      { status: "done", version: 3 },
      3,
    ));
    expect(mocks.replace).toHaveBeenCalledWith(
      "/app/dossiers/dossier-1/tasks",
      { scroll: false },
    );
  });

  it("cierra una reunión creando resultados, decisiones y tareas vinculadas", async () => {
    mocks.params = new URLSearchParams("selected=meeting-1");
    mocks.meetingsList.mockResolvedValue({
      data: [{
        id: "meeting-1",
        tenant_id: "tenant-1",
        dossier_id: "dossier-1",
        title: "Reunión con Gobierno de Aragón",
        status: "planned",
        objective: "Validar encaje",
        version: 1,
        updated_at: "2026-07-11T09:00:00Z",
      }],
      meta: { page: 1, size: 25, total: 1 },
    });
    render(<DossierWorkSection dossierId="dossier-1" kind="meetings" />);

    const detail = await screen.findByRole("dialog", { name: "Reunión con Gobierno de Aragón" });
    fireEvent.click(within(detail).getByRole("button", { name: "Completada" }));
    fireEvent.change(within(detail).getByLabelText("Resultados de la reunión"), {
      target: { value: "Se valida preparar una propuesta ejecutiva." },
    });
    const titleInputs = within(detail).getAllByLabelText("Título");
    fireEvent.change(titleInputs[0], { target: { value: "Priorizar encaje territorial" } });
    fireEvent.change(within(detail).getByLabelText("Justificación"), {
      target: { value: "El interlocutor confirma interés en enfoque industrial." },
    });
    fireEvent.change(titleInputs[1], { target: { value: "Enviar propuesta ejecutiva" } });
    fireEvent.change(within(detail).getByLabelText("Vencimiento"), {
      target: { value: "2026-07-24" },
    });
    fireEvent.click(within(detail).getByRole("button", { name: "Cerrar reunión y crear seguimiento" }));

    await waitFor(() => expect(mocks.meetingComplete).toHaveBeenCalledWith(
      "meeting-1",
      {
        version: 1,
        notes: "Se valida preparar una propuesta ejecutiva.",
        decisions: [{
          title: "Priorizar encaje territorial",
          rationale: "El interlocutor confirma interés en enfoque industrial.",
        }],
        tasks: [{
          title: "Enviar propuesta ejecutiva",
          due_date: "2026-07-24",
          priority: "medium",
          owner_user_id: "user-1",
        }],
      },
      1,
      expect.any(String),
    ));
  });

  it("vincula un actor existente sin enviar tenant desde el navegador", async () => {
    render(<DossierWorkSection dossierId="dossier-1" kind="actors" />);
    fireEvent.click(await screen.findByRole("button", { name: "Nuevo actor" }));
    fireEvent.click(screen.getByRole("button", { name: "Vincular existente" }));
    await screen.findByRole("option", { name: "Consorcio Lumen" });
    fireEvent.change(screen.getByLabelText("Actor existente"), { target: { value: "actor-1" } });
    fireEvent.change(screen.getByLabelText("Roles (separados por comas)"), { target: { value: "socio, prescriptor" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));

    await waitFor(() => expect(mocks.actorAttach).toHaveBeenCalledWith("dossier-1", {
      actor_id: "actor-1",
      roles: ["socio", "prescriptor"],
      influence: 50,
      relevance_to_dossier: 50,
    }));
  });

  it("ofrece candidatos detectados aunque todavía no haya actores vinculados", async () => {
    render(<DossierWorkSection dossierId="dossier-1" kind="actors" />);
    fireEvent.click(await screen.findByRole("button", { name: "Ver candidatos detectados" }));

    expect(await screen.findByText("No hay candidatos detectados")).toBeVisible();
    expect(screen.getByText(
      "Las empresas, personas y organismos mencionados en las señales vinculadas aparecerán aquí con su procedencia.",
    )).toBeVisible();
  });

  it("explica la creación de tareas con lenguaje de negocio", async () => {
    render(<DossierWorkSection dossierId="dossier-1" kind="tasks" />);

    fireEvent.click(await screen.findByRole("button", { name: "Nueva tarea" }));

    const dialog = screen.getByRole("dialog", { name: "Nueva tarea" });
    expect(within(dialog).getByText(
      "Quedará incorporado al expediente activo y será visible para las personas autorizadas.",
    )).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Cerrar" })).toBeInTheDocument();
    expect(within(dialog).queryByText(/Flask|tenant/i)).not.toBeInTheDocument();
  });

  it("crea y vincula un actor nuevo con tipo, etiquetas y roles", async () => {
    render(<DossierWorkSection dossierId="dossier-1" kind="actors" />);
    fireEvent.click(await screen.findByRole("button", { name: "Nuevo actor" }));

    fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "CATL" } });
    fireEvent.change(screen.getByLabelText("Tipo"), { target: { value: "organization" } });
    fireEvent.change(screen.getByLabelText("Etiquetas (separadas por comas)"), {
      target: { value: "fabricante, baterías" },
    });
    fireEvent.change(screen.getByLabelText("Roles (separados por comas)"), {
      target: { value: "competidor, socio potencial" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));

    await waitFor(() => expect(mocks.actorAttach).toHaveBeenCalledWith("dossier-1", {
      canonical_name: "CATL",
      actor_type: "organization",
      tags: ["fabricante", "baterías"],
      provenance: { source: "manual" },
      roles: ["competidor", "socio potencial"],
      influence: 50,
      relevance_to_dossier: 50,
    }));
  });

  it("crea una tarea manual con título y prioridad", async () => {
    mocks.taskCreate.mockResolvedValue({ id: "task-2", title: "Llamar a socio" });
    render(<DossierWorkSection dossierId="dossier-1" kind="tasks" />);
    fireEvent.click(await screen.findByRole("button", { name: "Nueva tarea" }));
    fireEvent.change(screen.getByLabelText("Título"), { target: { value: "Llamar a socio" } });
    fireEvent.change(screen.getByLabelText("Prioridad"), { target: { value: "high" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));

    await waitFor(() => expect(mocks.taskCreate).toHaveBeenCalledWith("dossier-1", {
      title: "Llamar a socio",
      priority: "high",
    }));
  });
});
