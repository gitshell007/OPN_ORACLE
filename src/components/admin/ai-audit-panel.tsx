"use client";

import {
  ApiError,
  api,
  type AiAuditDetail,
  type AiAuditListItem,
} from "@oracle/api-client";
import { RefreshCw } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { PageHeader } from "@/components/ui/page-header";

const STATUS_OPTIONS = [
  { value: "", label: "Todos los estados" },
  { value: "failed", label: "Fallidas" },
  { value: "denied", label: "Denegadas" },
  { value: "succeeded", label: "Correctas" },
  { value: "running", label: "En curso" },
  { value: "pending", label: "Pendientes" },
] as const;

function dash(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

/** Coste en micros → importe con 6 decimales fijos (como el panel de Signal). */
export function formatAuditCost(
  micros: number | null | undefined,
  currency?: string | null,
): string {
  if (micros === null || micros === undefined || Number.isNaN(Number(micros))) {
    return "—";
  }
  const amount = Number(micros) / 1_000_000;
  const code = currency && currency.trim() ? currency.trim() : "EUR";
  return `${amount.toFixed(6)} ${code}`;
}

export function formatAuditTokens(
  input: number | null | undefined,
  output: number | null | undefined,
): string {
  if (input == null && output == null) return "—";
  const inTok = input ?? 0;
  const outTok = output ?? 0;
  return `${inTok} / ${outTok}`;
}

export function formatAuditLatency(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  return `${ms} ms`;
}

function formatWhen(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("es-ES", {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(date);
}

function statusClass(status: string): string {
  if (status === "failed" || status === "denied") return "status danger";
  if (status === "succeeded") return "status active";
  if (status === "running") return "status warning";
  return "status";
}

export function AiAuditPanel() {
  const searchParams = useSearchParams();
  const initialDossier = searchParams.get("dossier_id") ?? "";
  const [items, setItems] = useState<AiAuditListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [denied, setDenied] = useState(false);
  const [status, setStatus] = useState("");
  const [agent, setAgent] = useState("");
  const [dossierId, setDossierId] = useState(initialDossier);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<AiAuditDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setDenied(false);
    try {
      const data = await api.aiAudit.list({
        status: status || undefined,
        agent: agent.trim() || undefined,
        dossier_id: dossierId.trim() || undefined,
      });
      setItems(data.items ?? []);
    } catch (reason) {
      if (reason instanceof ApiError && (reason.status === 403 || reason.status === 401)) {
        setDenied(true);
        setItems([]);
        setError(
          reason.status === 401
            ? "Debes iniciar sesión."
            : "No tienes permiso para consultar la auditoría de IA.",
        );
      } else {
        setError(
          reason instanceof ApiError
            ? reason.message
            : "No se pudo cargar la auditoría de IA.",
        );
        setItems([]);
      }
    } finally {
      setLoading(false);
    }
  }, [agent, dossierId, status]);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) void load();
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  const agentOptions = useMemo(() => {
    const set = new Set<string>();
    for (const item of items) {
      if (item.agent) set.add(item.agent);
    }
    if (agent.trim()) set.add(agent.trim());
    return Array.from(set).sort((a, b) => a.localeCompare(b, "es"));
  }, [agent, items]);

  const openDetail = useCallback(async (id: string) => {
    setSelectedId(id);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(true);
    try {
      const data = await api.aiAudit.get(id);
      setDetail(data);
    } catch (reason) {
      if (reason instanceof ApiError && (reason.status === 403 || reason.status === 401)) {
        setDenied(true);
        setDetailError("No tienes permiso para ver este detalle.");
      } else {
        setDetailError(
          reason instanceof ApiError
            ? reason.message
            : "No se pudo cargar el detalle de la ejecución.",
        );
      }
    } finally {
      setDetailLoading(false);
    }
  }, []);

  if (denied && !items.length && !loading) {
    return (
      <div className="admin-page" data-testid="ai-audit-denied">
        <PageHeader
          eyebrow="Administración"
          title="Auditoría de IA"
          description="Ejecuciones registradas con proveedor, modelo, tokens, coste y evidencias."
        />
        <div className="auth-state" role="alert">
          <h2>Acceso restringido</h2>
          <p>{error ?? "Tu cuenta no dispone del permiso audit.read."}</p>
          <Link href="/app">Volver a Inicio</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page" data-testid="ai-audit-panel">
      <PageHeader
        eyebrow="Administración"
        title="Auditoría de IA"
        description="Cada ejecución de agente: proveedor, modelo, estado, tokens, coste, latencia y evidencias usadas. Sin inventar datos ausentes."
        actions={
          <button
            type="button"
            className="vector-secondary"
            onClick={() => void load()}
            disabled={loading}
          >
            <RefreshCw size={15} />
            Actualizar
          </button>
        }
      />

      <section className="vector-panel" aria-label="Filtros de auditoría de IA">
        <div className="audit-toolbar" style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
          <label>
            <span className="sr-only">Estado</span>
            <select
              value={status}
              onChange={(event) => setStatus(event.target.value)}
              aria-label="Filtrar por estado"
              data-testid="ai-audit-filter-status"
            >
              {STATUS_OPTIONS.map((option) => (
                <option key={option.value || "all"} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="sr-only">Agente</span>
            <select
              value={agent}
              onChange={(event) => setAgent(event.target.value)}
              aria-label="Filtrar por agente"
              data-testid="ai-audit-filter-agent"
            >
              <option value="">Todos los agentes</option>
              {agentOptions.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label className="search-field" style={{ minWidth: 240, flex: 1 }}>
            <span className="sr-only">Expediente</span>
            <input
              value={dossierId}
              onChange={(event) => setDossierId(event.target.value)}
              placeholder="Filtrar por UUID de expediente…"
              aria-label="Filtrar por expediente"
              data-testid="ai-audit-filter-dossier"
            />
          </label>
        </div>
        <p style={{ margin: "8px 0 0", color: "var(--nav-muted, #556272)", fontSize: 13 }}>
          Por defecto se muestran primero las fallidas. Vacío o «—» = campo no informado por la API.
        </p>
      </section>

      {error && !denied ? (
        <div className="inline-error" role="alert">
          {error}
        </div>
      ) : null}

      <section className="full-bleed vector-panel" aria-label="Listado de ejecuciones IA">
        {loading ? (
          <p role="status">Cargando auditoría de IA…</p>
        ) : items.length === 0 ? (
          <p data-testid="ai-audit-empty">No hay ejecuciones de IA con los filtros actuales.</p>
        ) : (
          <div className="table-scroll table-wrap">
            <table className="admin-table dense-table" data-testid="ai-audit-table">
              <thead>
                <tr>
                  <th scope="col">Fecha</th>
                  <th scope="col">Agente</th>
                  <th scope="col">Proveedor</th>
                  <th scope="col">Modelo</th>
                  <th scope="col">Estado</th>
                  <th scope="col" className="numeric-col">
                    Tokens (in/out)
                  </th>
                  <th scope="col" className="numeric-col">
                    Coste
                  </th>
                  <th scope="col" className="numeric-col">
                    Latencia
                  </th>
                  <th scope="col">Expediente</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr
                    key={item.id}
                    data-testid={`ai-audit-row-${item.id}`}
                    data-selected={selectedId === item.id ? "true" : "false"}
                  >
                    <td>
                      <button
                        type="button"
                        className="text-button"
                        onClick={() => void openDetail(item.id)}
                        data-testid={`ai-audit-open-${item.id}`}
                      >
                        {formatWhen(item.created_at)}
                      </button>
                    </td>
                    <td>
                      <strong>{dash(item.agent)}</strong>
                      {item.action ? <small> · {item.action}</small> : null}
                    </td>
                    <td>{dash(item.provider)}</td>
                    <td>{dash(item.model)}</td>
                    <td>
                      <span className={statusClass(item.status)}>{dash(item.status)}</span>
                      {item.error_code ? <small> {item.error_code}</small> : null}
                    </td>
                    <td className="numeric-col">
                      {formatAuditTokens(item.input_tokens, item.output_tokens)}
                    </td>
                    <td className="numeric-col">
                      {formatAuditCost(item.cost_micros, item.currency)}
                    </td>
                    <td className="numeric-col">{formatAuditLatency(item.latency_ms)}</td>
                    <td>
                      {item.dossier_id ? (
                        <Link href={`/app/dossiers/${item.dossier_id}`}>
                          {item.dossier_id.slice(0, 8)}…
                        </Link>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {selectedId ? (
        <section
          className="vector-panel"
          aria-label="Detalle de ejecución IA"
          data-testid="ai-audit-detail"
        >
          <header className="admin-card-heading">
            <div>
              <h2>Detalle de ejecución</h2>
              <p>
                Evidencias usadas y trabajo de origen. Identificador{" "}
                <code>{selectedId}</code>
              </p>
            </div>
            <button
              type="button"
              className="vector-secondary"
              onClick={() => {
                setSelectedId(null);
                setDetail(null);
                setDetailError(null);
              }}
            >
              Cerrar
            </button>
          </header>
          {detailLoading ? (
            <p role="status">Cargando detalle…</p>
          ) : detailError ? (
            <div className="inline-error" role="alert">
              {detailError}
            </div>
          ) : detail ? (
            <div className="placeholder-contract is-metrics" data-testid="ai-audit-detail-body">
              <dl className="placeholder-contract is-metrics">
                <div>
                  <dt>Agente</dt>
                  <dd>{dash(detail.agent)}</dd>
                </div>
                <div>
                  <dt>Acción</dt>
                  <dd>{dash(detail.action)}</dd>
                </div>
                <div>
                  <dt>Estado</dt>
                  <dd>
                    <span className={statusClass(detail.status)}>{dash(detail.status)}</span>
                  </dd>
                </div>
                <div>
                  <dt>Proveedor / modelo</dt>
                  <dd>
                    {dash(detail.provider)} · {dash(detail.model)}
                  </dd>
                </div>
                <div>
                  <dt>Tokens in / out</dt>
                  <dd className="numeric-col">
                    {formatAuditTokens(
                      detail.usage?.input_tokens ?? detail.input_tokens,
                      detail.usage?.output_tokens ?? detail.output_tokens,
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Coste</dt>
                  <dd className="numeric-col">
                    {formatAuditCost(
                      detail.usage?.cost_micros ?? detail.cost_micros,
                      detail.usage?.currency ?? detail.currency,
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Latencia</dt>
                  <dd className="numeric-col">{formatAuditLatency(detail.latency_ms)}</dd>
                </div>
                <div>
                  <dt>Intentos</dt>
                  <dd className="numeric-col">{dash(detail.attempt_count)}</dd>
                </div>
                <div>
                  <dt>Trabajo (background job)</dt>
                  <dd>
                    {detail.background_job_id ? (
                      <code>{detail.background_job_id}</code>
                    ) : (
                      "—"
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Expediente</dt>
                  <dd>
                    {detail.dossier_id ? (
                      <Link href={`/app/dossiers/${detail.dossier_id}`}>{detail.dossier_id}</Link>
                    ) : (
                      "—"
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Clasificación</dt>
                  <dd>{dash(detail.data_classification)}</dd>
                </div>
                <div>
                  <dt>Revisión humana</dt>
                  <dd>{dash(detail.review_state ?? detail.human_review_state)}</dd>
                </div>
                <div>
                  <dt>Prompt</dt>
                  <dd>
                    {detail.prompt?.name
                      ? `${detail.prompt.name}@${dash(detail.prompt.version)}`
                      : "—"}
                  </dd>
                </div>
                <div>
                  <dt>Error</dt>
                  <dd>{dash(detail.error_code)}</dd>
                </div>
              </dl>
              <div style={{ marginTop: 16 }}>
                <h3>Evidencias usadas</h3>
                {(detail.source_ids ?? []).length === 0 ? (
                  <p data-testid="ai-audit-no-sources">—</p>
                ) : (
                  <ul data-testid="ai-audit-source-ids">
                    {(detail.source_ids ?? []).map((sourceId) => (
                      <li key={sourceId}>
                        <code>{sourceId}</code>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              {(detail.attempts ?? []).length > 0 ? (
                <div style={{ marginTop: 16 }}>
                  <h3>Intentos</h3>
                  <div className="table-scroll">
                    <table className="admin-table dense-table">
                      <thead>
                        <tr>
                          <th scope="col">#</th>
                          <th scope="col">Tipo</th>
                          <th scope="col">Estado</th>
                          <th scope="col" className="numeric-col">
                            Tokens
                          </th>
                          <th scope="col" className="numeric-col">
                            Coste
                          </th>
                          <th scope="col" className="numeric-col">
                            Latencia
                          </th>
                          <th scope="col">Error</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(detail.attempts ?? []).map((attempt) => (
                          <tr key={`${attempt.number}-${attempt.kind}`}>
                            <td className="numeric-col">{attempt.number}</td>
                            <td>{dash(attempt.kind)}</td>
                            <td>{dash(attempt.status)}</td>
                            <td className="numeric-col">
                              {formatAuditTokens(attempt.input_tokens, attempt.output_tokens)}
                            </td>
                            <td className="numeric-col">
                              {formatAuditCost(attempt.cost_micros, detail.currency)}
                            </td>
                            <td className="numeric-col">
                              {formatAuditLatency(attempt.latency_ms)}
                            </td>
                            <td>{dash(attempt.error_code)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
