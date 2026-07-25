"use client";

import {
  api,
  ApiError,
  type InvestigationEntity,
  type InvestigationReportPreview,
  type InvestigationRun,
} from "@oracle/api-client";
import {
  FileText,
  Network,
  Play,
  RefreshCw,
  SearchCheck,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { PermissionGate } from "@/components/auth/auth-boundary";
import { AsyncActionButton } from "@/components/ui/async-action-button";
import { idempotencyKey } from "@/components/reporting/reporting-utils";

function message(reason: unknown, fallback: string): string {
  if (reason instanceof ApiError) return reason.problem.detail || fallback;
  if (reason instanceof Error) return reason.message;
  return fallback;
}

function statusLabel(status: InvestigationRun["status"]): string {
  return {
    awaiting_review: "Revisión",
    ready: "Lista",
    running: "Ejecutando",
    paused: "Pausada",
    completed: "Completada",
    failed: "Fallida",
    cancelled: "Cancelada",
  }[status];
}

function entityStatusLabel(status: InvestigationEntity["resolution_status"]): string {
  return {
    candidate: "Candidata",
    verified: "Verificada",
    ambiguous: "Ambigua",
    rejected: "Rechazada",
  }[status];
}

function entityKindLabel(kind: InvestigationEntity["kind"]): string {
  return { company: "Sociedad", person: "Persona", unknown: "Sin clasificar" }[kind];
}

function formatDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("es-ES", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function DossierInvestigationsSection({ dossierId }: { dossierId: string }) {
  const [runs, setRuns] = useState<InvestigationRun[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [report, setReport] = useState<{
    runId: string;
    data: InvestigationReportPreview;
  } | null>(null);
  const [question, setQuestion] = useState(
    "Investigar nexos empresariales, cargos registrales y adjudicaciones relacionadas.",
  );
  const [seedName, setSeedName] = useState("");
  const [seedKind, setSeedKind] =
    useState<InvestigationRun["seed"]["kind"]>("company");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selected = useMemo(
    () => runs.find((run) => run.id === selectedId) ?? runs[0] ?? null,
    [runs, selectedId],
  );
  const activeReport = report && selected && report.runId === selected.id ? report.data : null;
  const pendingEntities = selected
    ? selected.entities.filter((entity) => entity.resolution_status === "candidate")
    : [];
  const verifiedEntities = selected
    ? selected.entities.filter((entity) => entity.resolution_status === "verified")
    : [];

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.investigations.list(dossierId);
      setRuns(result.items);
      setSelectedId((current) =>
        current && result.items.some((item) => item.id === current)
          ? current
          : (result.items[0]?.id ?? null),
      );
    } catch (reason) {
      setError(message(reason, "No se pudieron cargar las investigaciones."));
    } finally {
      setLoading(false);
    }
  }, [dossierId]);

  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    const runId = selected.id;
    api.investigations
      .reportPreview(runId)
      .then((result) => {
        if (!cancelled) setReport({ runId, data: result });
      })
      .catch(() => {
        if (!cancelled) setReport((current) => (current?.runId === runId ? null : current));
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  async function createRun(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const run = await api.investigations.create(
        dossierId,
        {
          question,
          seed_name: seedName,
          seed_kind: seedKind,
          limits: { max_depth: 2, max_entities: 150 },
        },
        idempotencyKey("investigation-create"),
      );
      toast.success("Investigación creada", {
        description: "Confirma la entidad raíz antes de ejecutar la primera pasada.",
      });
      setSeedName("");
      setRuns((current) => [run, ...current.filter((item) => item.id !== run.id)]);
      setSelectedId(run.id);
    } catch (reason) {
      setError(message(reason, "No se pudo crear la investigación."));
    } finally {
      setBusy(false);
    }
  }

  async function review(entity: InvestigationEntity, decision: "verify" | "reject") {
    if (!selected) return;
    setBusy(true);
    try {
      const run = await api.investigations.reviewEntity(selected.id, entity.id, { decision });
      setRuns((current) => current.map((item) => (item.id === run.id ? run : item)));
      toast.success(decision === "verify" ? "Identidad verificada" : "Identidad rechazada");
    } catch (reason) {
      setError(message(reason, "No se pudo revisar la identidad."));
    } finally {
      setBusy(false);
    }
  }

  async function execute() {
    if (!selected) return;
    setBusy(true);
    try {
      const result = await api.investigations.execute(
        selected.id,
        idempotencyKey("investigation-run"),
      );
      setRuns((current) =>
        current.map((item) => (item.id === result.investigation.id ? result.investigation : item)),
      );
      toast.success("Pasada en cola", {
        description: "El worker continuará la investigación fuera de la petición web.",
      });
    } catch (reason) {
      setError(message(reason, "No se pudo ejecutar la investigación."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="investigation-section">
      <header className="investigation-heading">
        <div>
          <span className="section-kicker">Investigación empresarial</span>
          <h1>Red, licitaciones y evidencia</h1>
          <p>
            Pasadas reanudables con revisión humana de identidad antes de expandir nodos.
          </p>
        </div>
        <AsyncActionButton
          className="vector-secondary"
          loading={loading}
          onClick={() => void load()}
        >
          <RefreshCw size={15} /> Actualizar
        </AsyncActionButton>
      </header>

      {error && <p className="form-error" role="alert">{error}</p>}

      <div className="investigation-grid">
        <div className="investigation-list-panel">
          <PermissionGate permission="dossier.write">
            <form className="investigation-create" onSubmit={createRun}>
              <label>
                Entidad semilla
                <input
                  value={seedName}
                  onChange={(event) => setSeedName(event.target.value)}
                  placeholder="Ej. ITURRI SA"
                />
              </label>
              <label>
                Tipo
                <select
                  value={seedKind}
                  onChange={(event) =>
                    setSeedKind(event.target.value as InvestigationRun["seed"]["kind"])
                  }
                >
                  <option value="company">Sociedad</option>
                  <option value="person">Persona</option>
                  <option value="unknown">Sin clasificar</option>
                </select>
              </label>
              <label className="investigation-question">
                Pregunta
                <textarea
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                />
              </label>
              <AsyncActionButton
                className="vector-primary"
                type="submit"
                loading={busy}
                disabled={seedName.trim().length < 2 || question.trim().length < 10}
              >
                <Network size={15} /> Crear investigación
              </AsyncActionButton>
            </form>
          </PermissionGate>

          <div className="investigation-runs" aria-live="polite">
            {loading ? (
              <p role="status">Cargando investigaciones…</p>
            ) : runs.length === 0 ? (
              <p>Aún no hay investigaciones en este expediente.</p>
            ) : (
              runs.map((run) => (
                <button
                  key={run.id}
                  type="button"
                  className={run.id === selected?.id ? "selected" : undefined}
                  onClick={() => setSelectedId(run.id)}
                >
                  <strong>{run.seed.name}</strong>
                  <small>
                    {statusLabel(run.status)} · {run.stage} · {run.progress} %
                  </small>
                  <span>{formatDate(run.updated_at)}</span>
                </button>
              ))
            )}
          </div>
        </div>

        <div className="investigation-detail-panel">
          {selected ? (
            <>
              <header>
                <div>
                  <span className={`status ${selected.status}`}>
                    {statusLabel(selected.status)}
                  </span>
                  <h2>{selected.seed.name}</h2>
                  <p>{selected.question}</p>
                </div>
                <PermissionGate permission="dossier.write">
                  <AsyncActionButton
                    className="vector-ai"
                    loading={busy}
                    disabled={
                      selected.status === "running" ||
                      selected.status === "cancelled" ||
                      selected.status === "completed"
                    }
                    onClick={() => void execute()}
                  >
                    <Play size={15} /> Ejecutar pasada
                  </AsyncActionButton>
                </PermissionGate>
              </header>

              <dl className="investigation-metrics">
                <div><dt>Entidades</dt><dd>{selected.counts.entities ?? 0}</dd></div>
                <div><dt>Verificadas</dt><dd>{selected.counts.verified_entities ?? 0}</dd></div>
                <div><dt>Relaciones</dt><dd>{selected.counts.relations ?? 0}</dd></div>
                <div><dt>Adjudicaciones</dt><dd>{selected.counts.procurement_participations ?? 0}</dd></div>
              </dl>

              <div className="investigation-columns">
                <section>
                  <h3><SearchCheck size={15} /> Revisión de identidad</h3>
                  {pendingEntities.length === 0 ? (
                    <p>No hay candidatos pendientes.</p>
                  ) : (
                    <div className="investigation-entity-list">
                      {pendingEntities.map((entity) => (
                        <article key={entity.id}>
                          <div>
                            <strong>{entity.name}</strong>
                            <small>
                              {entityKindLabel(entity.kind)} · profundidad {entity.depth}
                            </small>
                          </div>
                          <PermissionGate permission="actor.write">
                            <div className="document-actions">
                              <AsyncActionButton
                                className="icon-button bordered"
                                aria-label={`Verificar ${entity.name}`}
                                loading={busy}
                                onClick={() => void review(entity, "verify")}
                              >
                                <ShieldCheck size={15} />
                              </AsyncActionButton>
                              <AsyncActionButton
                                className="icon-button bordered"
                                aria-label={`Rechazar ${entity.name}`}
                                loading={busy}
                                onClick={() => void review(entity, "reject")}
                              >
                                <XCircle size={15} />
                              </AsyncActionButton>
                            </div>
                          </PermissionGate>
                        </article>
                      ))}
                    </div>
                  )}
                </section>

                <section>
                  <h3><FileText size={15} /> Informe</h3>
                  {activeReport ? (
                    <div className="investigation-report-preview">
                      <strong>{activeReport.report.title}</strong>
                      <p>{activeReport.report.sections.executive_summary}</p>
                      <pre>{activeReport.report.markdown}</pre>
                    </div>
                  ) : (
                    <p>El borrador aparecerá cuando exista corpus de la pasada.</p>
                  )}
                </section>
              </div>

              <section className="investigation-table-block">
                <h3>Entidades verificadas</h3>
                <div className="document-table-wrap">
                  <table className="document-table">
                    <thead>
                      <tr><th>Entidad</th><th>Tipo</th><th>Confianza</th><th>Estado</th></tr>
                    </thead>
                    <tbody>
                      {verifiedEntities.map((entity) => (
                        <tr key={entity.id}>
                          <td><strong>{entity.name}</strong></td>
                          <td>{entityKindLabel(entity.kind)}</td>
                          <td>{entity.identity_confidence} %</td>
                          <td>{entityStatusLabel(entity.resolution_status)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          ) : (
            <p className="global-inventory-state">Selecciona o crea una investigación.</p>
          )}
        </div>
      </div>
    </section>
  );
}
