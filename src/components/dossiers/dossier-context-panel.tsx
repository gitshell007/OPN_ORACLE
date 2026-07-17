"use client";

import * as Dialog from "@radix-ui/react-dialog";
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import {
  ApiError,
  api,
  type OracleEvidence,
  type OracleHypothesis,
  type OracleObjective,
} from "@oracle/api-client";
import { Pencil, Plus, RefreshCw, Search, Trash2, X } from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { PermissionGate } from "@/components/auth/auth-boundary";

const HYPOTHESIS_STATUS: Record<string, string> = {
  open: "Activa",
  supported: "Validada",
  contradicted: "Contradicha",
  discarded: "Descartada",
};

function failure(reason: unknown, fallback: string) {
  return reason instanceof ApiError ? reason.problem.detail : fallback;
}

function formatDate(value?: string | null): string {
  if (!value) return "Sin fecha";
  return new Intl.DateTimeFormat("es-ES", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

export function DossierContextPanel({ dossierId }: { dossierId: string }) {
  const [objectives, setObjectives] = useState<OracleObjective[]>([]);
  const [hypotheses, setHypotheses] = useState<OracleHypothesis[]>([]);
  const [evidence, setEvidence] = useState<OracleEvidence[]>([]);
  const [linkedEvidence, setLinkedEvidence] = useState<OracleEvidence[] | null>(null);
  const [selected, setSelected] = useState<OracleHypothesis | null>(null);
  const [contextOpen, setContextOpen] = useState(false);
  const [statement, setStatement] = useState("");
  const [rationale, setRationale] = useState("");
  const [confidence, setConfidence] = useState(50);
  const [hypothesisStatus, setHypothesisStatus] = useState("open");
  const [evidenceId, setEvidenceId] = useState("");
  const [filter, setFilter] = useState("");
  const [sorting, setSorting] = useState<SortingState>([{ id: "updated_at", desc: true }]);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [objectiveResult, hypothesisResult, evidenceResult] = await Promise.all([
        api.objectives.list(dossierId, { page: 1, size: 25, sort: "position" }),
        api.hypotheses.list(dossierId, { page: 1, size: 100, sort: "-updated_at" }),
        api.dossierEvidence.list(dossierId),
      ]);
      setObjectives(objectiveResult.data);
      setHypotheses(hypothesisResult.data);
      setEvidence(evidenceResult.data);
    } catch (reason) {
      setError(failure(reason, "No se pudo cargar el contexto estratégico."));
    } finally {
      setLoading(false);
    }
  }, [dossierId]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  const openEditor = useCallback((item?: OracleHypothesis) => {
    setSelected(item ?? null);
    setContextOpen(true);
    setStatement(item?.statement ?? "");
    setRationale(item?.rationale ?? "");
    setConfidence(item?.confidence ?? 50);
    setHypothesisStatus(item?.status ?? "open");
    setEvidenceId("");
    setConfirmDelete(false);
    setLinkedEvidence(null);
    setError(null);
    if (item) {
      void api.hypotheses
        .evidence(item.id)
        .then((result) => setLinkedEvidence(result.data))
        .catch(() => setLinkedEvidence([]));
    }
  }, []);

  const columns = useMemo<ColumnDef<OracleHypothesis>[]>(
    () => [
      {
        accessorKey: "statement",
        header: "Hipótesis",
        cell: ({ row }) => (
          <div className="hypothesis-statement-cell">
            <strong>{row.original.statement}</strong>
            <small>{row.original.rationale || "Sin razonamiento documentado."}</small>
          </div>
        ),
      },
      {
        accessorKey: "status",
        header: "Estado",
        cell: ({ row }) => (
          <span className={`status ${row.original.status ?? "open"}`}>
            {HYPOTHESIS_STATUS[row.original.status ?? "open"] ?? "Activa"}
          </span>
        ),
      },
      {
        accessorKey: "confidence",
        header: "Confianza",
        cell: ({ row }) => `${row.original.confidence ?? 0} %`,
      },
      {
        accessorKey: "updated_at",
        header: "Actualización",
        cell: ({ row }) => formatDate(row.original.updated_at),
      },
      {
        id: "actions",
        header: "Acciones",
        enableSorting: false,
        cell: ({ row }) => (
          <PermissionGate permission="dossier.write">
            <button
              className="icon-button bordered"
              type="button"
              aria-label={`Ver o editar hipótesis: ${row.original.statement}`}
              onClick={() => openEditor(row.original)}
            >
              <Pencil size={15} />
            </button>
          </PermissionGate>
        ),
      },
    ],
    [openEditor],
  );

  const table = useReactTable({
    data: hypotheses,
    columns,
    state: { sorting, globalFilter: filter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setFilter,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  async function saveHypothesis(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const input = {
        statement: statement.trim(),
        rationale: rationale.trim(),
        confidence,
        status: hypothesisStatus,
      };
      if (selected) {
        await api.hypotheses.update(
          selected.id,
          { ...input, version: selected.version },
          selected.version ?? 1,
        );
      } else {
        await api.hypotheses.create(dossierId, input);
      }
      toast.success(selected ? "Hipótesis actualizada" : "Hipótesis creada");
      setContextOpen(false);
      setSelected(null);
      await load();
    } catch (reason) {
      setError(failure(reason, "No se pudo guardar la hipótesis."));
    } finally {
      setBusy(false);
    }
  }

  async function linkEvidence() {
    if (!selected || !evidenceId) return;
    setBusy(true);
    try {
      await api.hypotheses.linkEvidence(selected.id, evidenceId);
      const linked = await api.hypotheses.evidence(selected.id);
      setLinkedEvidence(linked.data);
      toast.success("Evidencia vinculada");
      setEvidenceId("");
    } catch (reason) {
      setError(failure(reason, "No se pudo vincular la evidencia."));
    } finally {
      setBusy(false);
    }
  }

  async function deleteHypothesis() {
    if (!selected) return;
    setBusy(true);
    try {
      await api.hypotheses.remove(selected.id, selected.version ?? 1);
      toast.success("Hipótesis eliminada", {
        description: "Las evidencias originales se conservan en el expediente.",
      });
      setContextOpen(false);
      setSelected(null);
      await load();
    } catch (reason) {
      setError(
        failure(
          reason,
          "No se pudo eliminar la hipótesis. Si tiene evidencia vinculada, revisa las reglas del expediente.",
        ),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="dossier-context-panel" aria-labelledby="dossier-context-title">
      <header>
        <div>
          <span className="section-kicker">Marco de trabajo</span>
          <h2 id="dossier-context-title">Objetivos e hipótesis</h2>
          <p>
            Las hipótesis son supuestos de trabajo que se contrastan con evidencia.
            Usa estado y confianza para separar intuiciones abiertas de conclusiones ya soportadas.
          </p>
        </div>
        <button className="icon-button bordered" type="button" aria-label="Actualizar contexto" onClick={() => void load()}>
          <RefreshCw size={15} />
        </button>
      </header>
      {loading ? <p role="status">Cargando objetivos e hipótesis…</p> : error ? <p className="form-error" role="alert">{error}</p> : <div className="dossier-context-grid">
        <section>
          <h3>Objetivos</h3>
          {objectives.length ? <ul>{objectives.map((item) => <li key={item.id}><strong>{item.title}</strong><span>{item.status === "achieved" ? "Alcanzado" : item.status === "in_progress" ? "En curso" : "Abierto"}</span><p>{item.description || "Sin descripción adicional."}</p></li>)}</ul> : <p>No hay objetivos registrados todavía.</p>}
        </section>
        <section className="hypotheses-workspace" aria-labelledby="hypotheses-title">
          <header>
            <div>
              <h3 id="hypotheses-title">Hipótesis</h3>
              <p>Lista editable para validar, contradecir o descartar supuestos del expediente.</p>
            </div>
            <PermissionGate permission="dossier.write">
              <button className="vector-primary" type="button" onClick={() => openEditor()}>
                <Plus size={15} />
                Nueva hipótesis
              </button>
            </PermissionGate>
          </header>
          <label className="search-field hypothesis-filter">
            <Search size={15} aria-hidden="true" />
            <input
              aria-label="Filtrar hipótesis"
              placeholder="Filtrar por texto, estado o razonamiento"
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
            />
          </label>
          <div className="table-scroll">
            <table className="admin-table hypotheses-table">
              <thead>
                {table.getHeaderGroups().map((headerGroup) => (
                  <tr key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <th key={header.id}>
                        {header.column.getCanSort() ? (
                          <button type="button" onClick={header.column.getToggleSortingHandler()}>
                            {flexRender(header.column.columnDef.header, header.getContext())}
                            {header.column.getIsSorted() === "asc" ? " ↑" : header.column.getIsSorted() === "desc" ? " ↓" : ""}
                          </button>
                        ) : (
                          flexRender(header.column.columnDef.header, header.getContext())
                        )}
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody>
                {table.getRowModel().rows.map((row) => (
                  <tr key={row.id}>
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                    ))}
                  </tr>
                ))}
                {!table.getRowModel().rows.length && (
                  <tr><td colSpan={columns.length}>No hay hipótesis para este filtro.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>}
      <Dialog.Root open={contextOpen} onOpenChange={(open) => { if (!open) setContextOpen(false); }}>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="dialog-content work-dialog hypothesis-dialog">
            <div className="dialog-header">
              <div>
                <span className="section-kicker">Hipótesis del expediente</span>
                <Dialog.Title>{selected ? "Ver o editar hipótesis" : "Nueva hipótesis"}</Dialog.Title>
                <Dialog.Description>
                  Documenta la suposición, su razonamiento, el estado de contraste y la confianza actual.
                </Dialog.Description>
              </div>
              <Dialog.Close className="icon-button" aria-label="Cerrar"><X /></Dialog.Close>
            </div>
            <form onSubmit={saveHypothesis}>
              <label>Hipótesis<textarea required minLength={3} value={statement} onChange={(event) => setStatement(event.target.value)} /></label>
              <label>Razonamiento<textarea value={rationale} onChange={(event) => setRationale(event.target.value)} /></label>
              <label>Estado<select value={hypothesisStatus} onChange={(event) => setHypothesisStatus(event.target.value)}>{Object.entries(HYPOTHESIS_STATUS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
              <label>Confianza<input type="number" min="0" max="100" value={confidence} onChange={(event) => setConfidence(Number(event.target.value))} /></label>
              {selected && (
                <section className="hypothesis-evidence-box" aria-label="Evidencia vinculada">
                  <strong>Evidencia vinculada</strong>
                  <p>
                    {linkedEvidence === null
                      ? "Cargando evidencias vinculadas…"
                      : linkedEvidence.length
                        ? `${linkedEvidence.length} evidencia${linkedEvidence.length === 1 ? "" : "s"} vinculada${linkedEvidence.length === 1 ? "" : "s"}. Al eliminar la hipótesis solo se retiran estos vínculos; la evidencia original permanece en el expediente.`
                        : "Sin evidencia vinculada todavía."}
                  </p>
                  <label>Vincular evidencia<select value={evidenceId} onChange={(event) => setEvidenceId(event.target.value)}><option value="">Seleccionar evidencia…</option>{evidence.map((item) => <option key={item.id} value={item.id}>{item.extract || item.id}</option>)}</select></label>
                  <button className="vector-secondary" type="button" disabled={!evidenceId || busy} onClick={() => void linkEvidence()}>Vincular</button>
                </section>
              )}
              {error && <p className="form-error" role="alert">{error}</p>}
              <div className="dialog-actions split-actions">
                {selected && (
                  <div className="destructive-inline">
                    {confirmDelete ? (
                      <button className="vector-danger" type="button" disabled={busy} onClick={() => void deleteHypothesis()}>
                        <Trash2 size={15} />
                        Confirmar borrado
                      </button>
                    ) : (
                      <button className="vector-secondary" type="button" disabled={busy} onClick={() => setConfirmDelete(true)}>
                        <Trash2 size={15} />
                        Eliminar
                      </button>
                    )}
                  </div>
                )}
                <div>
                  <Dialog.Close className="vector-secondary" type="button">Cancelar</Dialog.Close>
                  <button className="vector-primary" disabled={busy || statement.trim().length < 3}>{busy ? "Guardando…" : "Guardar"}</button>
                </div>
              </div>
            </form>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </section>
  );
}
