"use client";

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  ApiError,
  api,
  type BackendDossier,
  type OracleExport,
} from "@oracle/api-client";
import {
  Check,
  ChevronDown,
  Download,
  FileDown,
  RefreshCw,
} from "lucide-react";
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { AsyncActionButton } from "@/components/ui/async-action-button";
import { JobProgress } from "./job-progress";
import {
  formatBytes,
  formatDateTime,
  idempotencyKey,
  triggerDownload,
} from "./reporting-utils";

export type ExportDataset =
  | "signals"
  | "opportunities"
  | "risks"
  | "actors"
  | "tasks"
  | "reports"
  | "audit";

const datasetLabel: Record<ExportDataset, string> = {
  signals: "Señales",
  opportunities: "Oportunidades",
  risks: "Riesgos",
  actors: "Actores",
  tasks: "Tareas",
  reports: "Informes",
  audit: "Auditoría",
};

const columns: Record<ExportDataset, string[]> = {
  signals: [
    "id",
    "title",
    "summary",
    "source_type",
    "source_name",
    "source_url",
    "published_at",
    "credibility",
  ],
  opportunities: [
    "id",
    "dossier_id",
    "title",
    "status",
    "overall_score",
    "confidence",
    "deadline",
    "recommended_next_action",
  ],
  risks: [
    "id",
    "dossier_id",
    "title",
    "status",
    "category",
    "overall_score",
    "confidence",
    "mitigation",
  ],
  actors: ["id", "canonical_name", "actor_type", "created_at"],
  tasks: [
    "id",
    "dossier_id",
    "title",
    "status",
    "priority",
    "owner_user_id",
    "due_date",
  ],
  reports: [
    "id",
    "dossier_id",
    "title",
    "status",
    "template_key",
    "template_version",
    "generation_version",
    "classification",
    "published_at",
  ],
  audit: [
    "id",
    "created_at",
    "actor_type",
    "actor_id",
    "action",
    "resource_type",
    "resource_id",
    "result",
    "request_id",
  ],
};

const initialColumns: Record<ExportDataset, string[]> = {
  signals: ["id", "title", "source_type", "source_name", "published_at"],
  opportunities: ["id", "title", "status", "overall_score", "deadline"],
  risks: ["id", "title", "status", "overall_score", "confidence"],
  actors: ["id", "canonical_name", "actor_type", "created_at"],
  tasks: ["id", "title", "status", "priority", "due_date"],
  reports: [
    "id",
    "title",
    "status",
    "template_key",
    "generation_version",
    "published_at",
  ],
  audit: [
    "id",
    "created_at",
    "actor_type",
    "action",
    "resource_type",
    "result",
  ],
};

const exportStatusLabel: Record<OracleExport["status"], string> = {
  queued: "En cola",
  generating: "Generando",
  ready: "Disponible",
  failed: "Fallida",
  expired: "Caducada",
  purged: "Purgada",
};

async function download(item: OracleExport): Promise<void> {
  const link = await api.exports.downloadLink(item.id);
  triggerDownload(link.url);
}

export function ExportMenu({
  dataset = "reports",
  dossierId,
  routeBase = "/app",
}: {
  dataset?: ExportDataset;
  dossierId?: string;
  routeBase?: "/app" | "/concept-a";
}) {
  const [item, setItem] = useState<OracleExport | null>(null);
  const [busy, setBusy] = useState(false);

  const start = async () => {
    setBusy(true);
    try {
      const result = await api.exports.create(
        { dataset, dossier_id: dossierId ?? null, columns: [], filters: {} },
        idempotencyKey(`export-${dataset}`),
      );
      setItem(result.export);
      toast.success("Exportación solicitada", {
        description: "El CSV se prepara en segundo plano.",
      });
    } catch (reason) {
      toast.error("No se pudo iniciar la exportación", {
        description:
          reason instanceof ApiError
            ? reason.problem.detail
            : "Comprueba tus permisos y vuelve a intentarlo.",
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="export-menu-wrap">
      <DropdownMenu.Root>
        <DropdownMenu.Trigger className="vector-secondary">
          <FileDown size={16} /> Exportar <ChevronDown size={14} />
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content className="vector-menu" align="end">
            <DropdownMenu.Item disabled={busy} onSelect={() => void start()}>
              <FileDown size={16} /> Exportar {datasetLabel[dataset]} en CSV
            </DropdownMenu.Item>
            <DropdownMenu.Item asChild>
              <Link href={`${routeBase}/exports`}>
                <RefreshCw size={16} /> Ver exportaciones
              </Link>
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
      {item?.job_id && ["queued", "generating"].includes(item.status) && (
        <div className="export-inline-progress">
          <JobProgress
            jobId={item.job_id}
            label="Preparando CSV"
            allowActions
            onTerminal={() =>
              void api.exports.get(item.id).then((next) => {
                setItem(next);
                if (next.status === "ready")
                  toast.success("Exportación disponible");
              })
            }
          />
        </div>
      )}
      {item?.status === "ready" && (
        <button className="text-button" onClick={() => void download(item)}>
          Descargar CSV
        </button>
      )}
    </div>
  );
}

export function ExportCenter({
  initialDataset = "reports",
}: {
  initialDataset?: ExportDataset;
}) {
  const [items, setItems] = useState<OracleExport[]>([]);
  const [dossiers, setDossiers] = useState<BackendDossier[]>([]);
  const [dataset, setDataset] = useState<ExportDataset>(initialDataset);
  const [selectedColumns, setSelectedColumns] = useState<string[]>(
    initialColumns[initialDataset],
  );
  const [dossierId, setDossierId] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [exportsResult, dossiersResult] = await Promise.all([
        api.exports.list(1, 100),
        api.dossiers.list(),
      ]);
      setItems(exportsResult.data);
      setDossiers(dossiersResult.data);
    } catch {
      setError("No se pudieron cargar las exportaciones.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  const active = useMemo(
    () => items.filter((item) => ["queued", "generating"].includes(item.status)),
    [items],
  );

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!selectedColumns.length) {
      setError("Selecciona al menos una columna.");
      return;
    }
    setBusy(true);
    setError(null);
    const filters: Record<string, string> = {};
    if (search.trim()) filters.search = search.trim();
    if (status.trim()) filters.status = status.trim();
    try {
      const result = await api.exports.create(
        {
          dataset,
          dossier_id: dossierId || null,
          columns: selectedColumns,
          filters,
        },
        idempotencyKey(`export-${dataset}`),
      );
      setItems((current) => [
        result.export,
        ...current.filter((item) => item.id !== result.export.id),
      ]);
      toast.success("Exportación en cola");
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.problem.detail
          : "No se pudo iniciar la exportación.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="reporting-page export-center">
      <header className="page-heading">
        <div>
          <span className="section-kicker">Salidas seguras · CSV</span>
          <h1>Exportaciones</h1>
          <p>
            Los ficheros grandes se generan en segundo plano, respetando el
            ámbito del expediente, los filtros y tus permisos.
          </p>
        </div>
      </header>

      <form className="vector-panel export-builder" onSubmit={create}>
        <header>
          <div>
            <span className="section-kicker">Nueva exportación</span>
            <h2>Configurar CSV</h2>
          </div>
          <AsyncActionButton className="vector-primary" type="submit" loading={busy}>
            <FileDown size={16} /> {busy ? "Solicitando…" : "Generar CSV"}
          </AsyncActionButton>
        </header>
        <div className="export-fields">
          <label>
            Dataset
            <select
              value={dataset}
              onChange={(event) => {
                const next = event.target.value as ExportDataset;
                setDataset(next);
                setSelectedColumns(initialColumns[next]);
              }}
            >
              {(Object.keys(datasetLabel) as ExportDataset[]).map((value) => (
                <option key={value} value={value}>
                  {datasetLabel[value]}
                </option>
              ))}
            </select>
          </label>
          <label>
            Expediente (opcional)
            <select value={dossierId} onChange={(event) => setDossierId(event.target.value)}>
              <option value="">Todo mi ámbito accesible</option>
              {dossiers.map((dossier) => (
                <option key={dossier.id} value={dossier.id}>
                  {dossier.title}
                </option>
              ))}
            </select>
          </label>
          <label>
            Buscar (opcional)
            <input
              value={search}
              maxLength={200}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Texto incluido en el filtro"
            />
          </label>
          <label>
            Estado (opcional)
            <input
              value={status}
              maxLength={80}
              onChange={(event) => setStatus(event.target.value)}
              placeholder="p. ej. published"
            />
          </label>
        </div>
        <fieldset className="export-columns">
          <legend>Columnas incluidas</legend>
          {columns[dataset].map((column) => (
            <label key={column}>
              <input
                type="checkbox"
                checked={selectedColumns.includes(column)}
                onChange={(event) =>
                  setSelectedColumns((current) =>
                    event.target.checked
                      ? [...current, column]
                      : current.filter((item) => item !== column),
                  )
                }
              />
              <span>{column}</span>
            </label>
          ))}
        </fieldset>
      </form>

      {error && (
        <div className="reporting-error" role="alert">
          <strong>No se pudo completar la operación</strong>
          <p>{error}</p>
          <button className="vector-secondary" onClick={() => void load()}>
            Reintentar
          </button>
        </div>
      )}

      <section className="vector-panel export-history" aria-labelledby="export-history-title">
        <header>
          <div>
            <span className="section-kicker">Historial personal</span>
            <h2 id="export-history-title">Exportaciones recientes</h2>
          </div>
          <button className="icon-button bordered" aria-label="Actualizar" onClick={() => void load()}>
            <RefreshCw size={16} />
          </button>
        </header>
        {loading ? (
          <div className="reporting-loading" role="status">Cargando exportaciones…</div>
        ) : !items.length ? (
          <div className="reporting-empty">
            <FileDown size={28} />
            <strong>Aún no hay exportaciones</strong>
            <p>Configura la primera salida CSV con las columnas necesarias.</p>
          </div>
        ) : (
          <div className="report-table-wrap">
            <table className="report-table">
              <thead>
                <tr>
                  <th>Dataset</th>
                  <th>Estado</th>
                  <th>Creada</th>
                  <th>Tamaño</th>
                  <th><span className="sr-only">Acciones</span></th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <strong>{datasetLabel[item.dataset as ExportDataset] ?? item.dataset}</strong>
                      <small>{item.columns.length} columnas</small>
                    </td>
                    <td>
                      <span className={`report-status ${item.status}`}>
                        {item.status === "ready" && <Check size={13} />}
                        {exportStatusLabel[item.status]}
                      </span>
                      {item.job_id && ["queued", "generating"].includes(item.status) && (
                        <JobProgress
                          jobId={item.job_id}
                          label="Generando exportación"
                          allowActions
                          onTerminal={() => void load()}
                        />
                      )}
                    </td>
                    <td>{formatDateTime(item.created_at)}</td>
                    <td>{formatBytes(item.byte_size)}</td>
                    <td>
                      {item.status === "ready" && (
                        <button
                          className="icon-button bordered"
                          aria-label={`Descargar exportación de ${item.dataset}`}
                          onClick={() =>
                            void download(item).catch(() =>
                              toast.error("El enlace ha caducado. Actualiza y vuelve a intentarlo."),
                            )
                          }
                        >
                          <Download size={15} />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {!!active.length && (
          <p className="reporting-hint" aria-live="polite">
            {active.length} exportación{active.length === 1 ? "" : "es"} en curso.
          </p>
        )}
      </section>
    </div>
  );
}
