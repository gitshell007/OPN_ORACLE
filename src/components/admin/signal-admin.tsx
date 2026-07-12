"use client";

import {
  ApiError,
  api,
  type SignalConnection,
  type SignalMonitor,
} from "@oracle/api-client";
import {
  Activity,
  KeyRound,
  Link2,
  Pause,
  Play,
  RefreshCw,
  RotateCw,
  ShieldCheck,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { AdminNav } from "@/components/admin/tenant-admin";
import { useRecentAuth } from "@/components/auth/recent-auth";
import { productStatusLabel } from "@/lib/product-copy";

type HealthState = "configured" | "healthy" | "degraded" | "error";

function message(reason: unknown, fallback: string) {
  return reason instanceof ApiError ? reason.message : fallback;
}

function healthState(connection: SignalConnection): HealthState {
  if (connection.status === "error" || connection.circuit_state === "open")
    return "error";
  if (connection.last_error || connection.circuit_state === "half_open")
    return "degraded";
  if (connection.last_success_at && connection.circuit_state === "closed")
    return "healthy";
  return "configured";
}

const healthLabels: Record<HealthState, string> = {
  configured: "Configurada",
  healthy: "Saludable",
  degraded: "Degradada",
  error: "Error",
};

function when(value: string | null) {
  return value
    ? new Intl.DateTimeFormat("es-ES", {
        dateStyle: "short",
        timeStyle: "short",
      }).format(new Date(value))
    : "Sin actividad registrada";
}

export function SignalAdmin() {
  const recent = useRecentAuth();
  const [connections, setConnections] = useState<SignalConnection[]>([]);
  const [monitors, setMonitors] = useState<SignalMonitor[]>([]);
  const [dossierId, setDossierId] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rotation, setRotation] = useState<{
    connectionId: string;
    kind: "api_token" | "webhook_secret";
    secret: string;
  } | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [create, setCreate] = useState({
    name: "Principal",
    adapter_mode: "mock" as "mock" | "http",
    base_url: "",
    api_token: "",
    webhook_secret: "",
  });
  const [monitorDraft, setMonitorDraft] = useState({
    connection_id: "",
    name: "Monitor Signal",
    query: "",
    cadence: "daily",
  });
  const [jobs, setJobs] = useState<
    Record<
      string,
      { id: string; status: string; version: number; monitorId: string }
    >
  >({});

  const loadConnections = useCallback(async () => {
    const data = await api.signalAvanza.connections();
    setConnections(data.items);
  }, []);

  useEffect(() => {
    const kickoff = window.setTimeout(() => {
      void loadConnections()
        .catch((reason) =>
          setError(message(reason, "No se pudo cargar Signal Avanza.")),
        )
        .finally(() => setLoading(false));
    }, 0);
    return () => window.clearTimeout(kickoff);
  }, [loadConnections]);

  useEffect(() => {
    const active = Object.values(jobs).filter((job) =>
      ["queued", "running", "retrying"].includes(job.status),
    );
    if (!active.length) return;
    const timer = window.setInterval(() => {
      active.forEach((tracked) => {
        void api.jobs.get(tracked.id).then((job) =>
          setJobs((current) => ({
            ...current,
            [tracked.id]: {
              id: job.id,
              status: job.status,
              version: job.version,
              monitorId: tracked.monitorId,
            },
          })),
        );
      });
    }, 2500);
    return () => window.clearInterval(timer);
  }, [jobs]);

  async function loadMonitors(event?: FormEvent) {
    event?.preventDefault();
    if (!dossierId.trim()) return;
    setBusy("load-monitors");
    setError(null);
    try {
      const data = await api.signalAvanza.monitors(dossierId.trim());
      setMonitors(data.data);
    } catch (reason) {
      setError(message(reason, "No se pudieron cargar los monitores."));
    } finally {
      setBusy(null);
    }
  }

  async function createConnection(event: FormEvent) {
    event.preventDefault();
    setBusy("create");
    setError(null);
    try {
      await recent.run(() =>
        api.signalAvanza.create({
          ...create,
          base_url: create.base_url || undefined,
          api_token: create.api_token || undefined,
          webhook_secret: create.webhook_secret || undefined,
        }),
      );
      setCreate((current) => ({
        ...current,
        api_token: "",
        webhook_secret: "",
      }));
      setCreateOpen(false);
      await loadConnections();
      toast.success("Conexión Signal Avanza configurada");
    } catch (reason) {
      setError(message(reason, "No se pudo configurar la conexión."));
    } finally {
      setBusy(null);
    }
  }

  async function rotate(event: FormEvent) {
    event.preventDefault();
    if (!rotation) return;
    setBusy("rotate");
    setError(null);
    try {
      await recent.run(() =>
        api.signalAvanza.rotate(rotation.connectionId, {
          kind: rotation.kind,
          secret: rotation.secret,
        }),
      );
      setRotation(null);
      toast.success("Credencial rotada", {
        description: "El secreto anterior ya no se muestra ni se recupera.",
      });
    } catch (reason) {
      setError(message(reason, "No se pudo rotar la credencial."));
    } finally {
      setBusy(null);
    }
  }

  async function testConnection(connection: SignalConnection) {
    setBusy(`test-${connection.id}`);
    setError(null);
    try {
      await api.signalAvanza.test(connection.id);
      await loadConnections();
      toast.success("Prueba de conexión encolada", {
        description: "Actualiza el diagnóstico para consultar el resultado.",
      });
    } catch (reason) {
      setError(message(reason, "La prueba de conexión no se pudo completar."));
    } finally {
      setBusy(null);
    }
  }

  async function createMonitor(event: FormEvent) {
    event.preventDefault();
    if (!dossierId.trim()) return;
    setBusy("create-monitor");
    try {
      await api.signalAvanza.createMonitor(dossierId.trim(), monitorDraft);
      setMonitorDraft((current) => ({ ...current, query: "" }));
      await loadMonitors();
      toast.success("Monitor creado");
    } catch (reason) {
      setError(message(reason, "No se pudo crear el monitor."));
    } finally {
      setBusy(null);
    }
  }

  async function monitorAction(
    monitor: SignalMonitor,
    action: "pause" | "resume" | "sync",
  ) {
    setBusy(`${action}-${monitor.id}`);
    setError(null);
    try {
      const result = await api.signalAvanza.action(monitor.id, action);
      if (result.job_id) {
        setJobs((current) => ({
          ...current,
          [result.job_id!]: {
            id: result.job_id!,
            status: result.status ?? "queued",
            version: 1,
            monitorId: monitor.id,
          },
        }));
      }
      await loadMonitors();
      toast.success(
        action === "sync"
          ? "Sincronización encolada"
          : "Estado solicitado",
      );
    } catch (reason) {
      setError(message(reason, "No se pudo completar la acción del monitor."));
    } finally {
      setBusy(null);
    }
  }

  async function reconcileConnection(connection: SignalConnection) {
    setBusy(`reconcile-${connection.id}`);
    setError(null);
    try {
      const result = await api.signalAvanza.reconcile(connection.id);
      toast.success("Reconciliación solicitada", {
        description: `${result.requeued} entregas pendientes reencoladas.`,
      });
    } catch (reason) {
      setError(message(reason, "No se pudo reconciliar la conexión."));
    } finally {
      setBusy(null);
    }
  }

  async function retryJob(jobId: string) {
    const tracked = jobs[jobId];
    if (!tracked) return;
    try {
      const job = await api.jobs.retry(jobId, tracked.version);
      setJobs((current) => ({
        ...current,
        [job.id]: {
          id: job.id,
          status: job.status,
          version: job.version,
          monitorId: tracked.monitorId,
        },
      }));
    } catch (reason) {
      setError(message(reason, "El proceso no admite reintento."));
    }
  }

  return (
    <div className="admin-page signal-admin">
      <header className="admin-heading">
        <div>
          <p className="eyebrow">Administración de organización</p>
          <h1>Signal Avanza</h1>
          <p>
            Gestiona la conexión, credenciales rotables y sincronización de
            monitores sin exponer secretos en el navegador.
          </p>
        </div>
        <button className="vector-primary" onClick={() => setCreateOpen(true)}>
          <Link2 size={16} /> Nueva conexión
        </button>
      </header>
      <AdminNav active="signal" />

      {error && (
        <div className="inline-error" role="alert">
          <span>{error}</span>
          <button onClick={() => setError(null)}>Cerrar</button>
        </div>
      )}

      {createOpen && (
        <section className="admin-form-card signal-form-card">
          <header>
            <div>
              <h2>Configurar conexión</h2>
              <p>Los secretos se envían una vez y nunca vuelven en la API.</p>
            </div>
            <button onClick={() => setCreateOpen(false)} aria-label="Cerrar formulario">
              ×
            </button>
          </header>
          <form onSubmit={createConnection}>
            <label className="field">
              <span>Nombre</span>
              <input
                required
                autoFocus
                value={create.name}
                onChange={(event) => setCreate({ ...create, name: event.target.value })}
              />
            </label>
            <label className="field">
              <span>Modo</span>
              <select
                value={create.adapter_mode}
                onChange={(event) =>
                  setCreate({
                    ...create,
                    adapter_mode: event.target.value as "mock" | "http",
                  })
                }
              >
                <option value="mock">Simulación segura</option>
                <option value="http">Conexión remota confirmada</option>
              </select>
            </label>
            <label className="field">
              <span>Dirección base (URL)</span>
              <input
                type="url"
                value={create.base_url}
                onChange={(event) => setCreate({ ...create, base_url: event.target.value })}
              />
            </label>
            <label className="field">
              <span>Clave de acceso</span>
              <input
                type="password"
                autoComplete="new-password"
                value={create.api_token}
                onChange={(event) => setCreate({ ...create, api_token: event.target.value })}
              />
            </label>
            <label className="field">
              <span>Clave de recepción automática</span>
              <input
                type="password"
                autoComplete="new-password"
                value={create.webhook_secret}
                onChange={(event) =>
                  setCreate({ ...create, webhook_secret: event.target.value })
                }
              />
            </label>
            <button className="vector-primary" disabled={busy === "create"}>
              {busy === "create" ? "Guardando…" : "Guardar conexión"}
            </button>
          </form>
        </section>
      )}

      <section className="signal-section" aria-labelledby="connections-title">
        <header>
          <div>
            <h2 id="connections-title">Conexiones</h2>
            <p>Diagnóstico del adaptador y del circuito de entrega.</p>
          </div>
          <button className="vector-secondary" onClick={() => void loadConnections()}>
            <RefreshCw size={15} /> Actualizar
          </button>
        </header>
        {loading ? (
          <p role="status">Cargando conexiones…</p>
        ) : connections.length === 0 ? (
          <div className="signal-empty">
            <ShieldCheck size={25} />
            <strong>Signal Avanza no está configurado</strong>
            <p>Crea una conexión de simulación o una conexión remota cuando el contrato esté confirmado.</p>
          </div>
        ) : (
          <div className="connection-grid">
            {connections.map((connection) => {
              const state = healthState(connection);
              return (
                <article className="connection-card" key={connection.id}>
                  <div className="connection-title">
                    <span className={`health-dot ${state}`} aria-hidden="true" />
                    <div>
                      <strong>{connection.name}</strong>
                      <small>{connection.adapter_mode === "mock" ? "Simulación" : "Conexión remota"} · contrato {connection.api_version}</small>
                    </div>
                    <span className={`health-badge ${state}`} data-status={state}>
                      {healthLabels[state]}
                    </span>
                  </div>
                  <dl>
                    <div><dt>Última salud</dt><dd>{when(connection.last_health_at)}</dd></div>
                    <div><dt>Último éxito</dt><dd>{when(connection.last_success_at)}</dd></div>
                    <div><dt>Circuito</dt><dd>{productStatusLabel(connection.circuit_state)}</dd></div>
                  </dl>
                  {connection.last_error && (
                    <p className="connection-error" role="status">{connection.last_error}</p>
                  )}
                  <div className="signal-actions">
                    <button
                      className="vector-secondary"
                      disabled={busy === `test-${connection.id}`}
                      onClick={() => void testConnection(connection)}
                    >
                      <Activity size={15} /> Probar conexión
                    </button>
                    <button
                      className="vector-secondary"
                      onClick={() =>
                        setRotation({
                          connectionId: connection.id,
                          kind: "api_token",
                          secret: "",
                        })
                      }
                    >
                      <KeyRound size={15} /> Rotar credencial
                    </button>
                    {(state === "degraded" || state === "error") && (
                      <button
                        className="vector-secondary"
                        disabled={busy === `reconcile-${connection.id}`}
                        onClick={() => void reconcileConnection(connection)}
                      >
                        <RefreshCw size={15} /> Reconciliar
                      </button>
                    )}
                  </div>
                  {rotation?.connectionId === connection.id && (
                    <form className="rotation-form" onSubmit={rotate}>
                      <label className="field">
                        <span>Tipo de credencial</span>
                        <select
                          value={rotation.kind}
                          onChange={(event) =>
                            setRotation({
                              ...rotation,
                              kind: event.target.value as "api_token" | "webhook_secret",
                            })
                          }
                        >
                          <option value="api_token">Clave de acceso</option>
                          <option value="webhook_secret">Clave de recepción automática</option>
                        </select>
                      </label>
                      <label className="field">
                        <span>Nuevo secreto</span>
                        <input
                          type="password"
                          autoComplete="new-password"
                          autoFocus
                          minLength={16}
                          required
                          value={rotation.secret}
                          onChange={(event) =>
                            setRotation({ ...rotation, secret: event.target.value })
                          }
                        />
                      </label>
                      <div>
                        <button className="vector-primary" disabled={busy === "rotate"}>
                          Rotar
                        </button>
                        <button
                          type="button"
                          className="vector-secondary"
                          onClick={() => setRotation(null)}
                        >
                          Cancelar
                        </button>
                      </div>
                    </form>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </section>

      <section className="signal-section" aria-labelledby="monitors-title">
        <header>
          <div>
            <h2 id="monitors-title">Monitores</h2>
            <p>Consulta un expediente y sincroniza sus monitores remotos.</p>
          </div>
        </header>
        <form className="monitor-lookup" onSubmit={loadMonitors}>
          <label className="field">
            <span>Identificador del expediente</span>
            <input
              required
              value={dossierId}
              onChange={(event) => setDossierId(event.target.value)}
              placeholder="Identificador único del expediente"
            />
          </label>
          <button className="vector-secondary" disabled={busy === "load-monitors"}>
            Cargar vigilancias
          </button>
        </form>
        {dossierId && (
          <form className="monitor-create" onSubmit={createMonitor}>
            <label className="field">
              <span>Nombre de la vigilancia</span>
              <input
                required
                value={monitorDraft.name}
                onChange={(event) =>
                  setMonitorDraft({
                    ...monitorDraft,
                    name: event.target.value,
                  })
                }
              />
            </label>
            <label className="field">
              <span>Conexión</span>
              <select
                required
                value={monitorDraft.connection_id}
                onChange={(event) =>
                  setMonitorDraft({
                    ...monitorDraft,
                    connection_id: event.target.value,
                  })
                }
              >
                <option value="">Selecciona conexión</option>
                {connections.map((connection) => (
                  <option key={connection.id} value={connection.id}>
                    {connection.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Consulta</span>
              <input
                required
                value={monitorDraft.query}
                onChange={(event) =>
                  setMonitorDraft({ ...monitorDraft, query: event.target.value })
                }
              />
            </label>
            <label className="field">
              <span>Cadencia</span>
              <select
                value={monitorDraft.cadence}
                onChange={(event) =>
                  setMonitorDraft({ ...monitorDraft, cadence: event.target.value })
                }
              >
                <option value="hourly">Cada hora</option>
                <option value="daily">Diaria</option>
                <option value="weekly">Semanal</option>
              </select>
            </label>
            <button className="vector-primary" disabled={busy === "create-monitor"}>
              Crear vigilancia
            </button>
          </form>
        )}
        {monitors.length === 0 ? (
          <div className="signal-empty compact">
            <Activity size={22} />
            <strong>No hay vigilancias cargadas</strong>
            <p>Introduce un expediente para consultar sus vigilancias.</p>
          </div>
        ) : (
          <div className="table-scroll">
            <table className="admin-table monitor-table">
              <thead>
                <tr>
                  <th>Monitor</th><th>Estado</th><th>Última sincronización</th><th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {monitors.map((monitor) => {
                  const tracked = Object.values(jobs).find(
                    (job) =>
                      job.monitorId === monitor.id &&
                      ["queued", "running", "retrying", "failed"].includes(
                        job.status,
                      ),
                  );
                  return (
                    <tr key={monitor.id}>
                      <td>
                        <strong>{monitor.external_id ?? monitor.id}</strong>
                        <small>{monitor.provider}</small>
                        {monitor.last_error && <span className="monitor-error">{monitor.last_error}</span>}
                      </td>
                      <td>
                        <span className={`status ${monitor.status}`}>{productStatusLabel(monitor.status)}</span>
                        <small>Estado observado: {productStatusLabel(monitor.observed_status)}</small>
                      </td>
                      <td>
                        {when(monitor.last_synced_at)}
                        {tracked && <small role="status">Proceso: {productStatusLabel(tracked.status)}</small>}
                      </td>
                      <td>
                        <div className="row-actions signal-row-actions">
                          <button
                            aria-label={`Sincronizar ${monitor.external_id ?? monitor.id}`}
                            title="Sincronizar ahora"
                            onClick={() => void monitorAction(monitor, "sync")}
                          ><RotateCw size={15} /></button>
                          <button
                            aria-label={`${monitor.status === "paused" ? "Reanudar" : "Pausar"} ${monitor.external_id ?? monitor.id}`}
                            title={monitor.status === "paused" ? "Reanudar" : "Pausar"}
                            onClick={() =>
                              void monitorAction(
                                monitor,
                                monitor.status === "paused" ? "resume" : "pause",
                              )
                            }
                          >{monitor.status === "paused" ? <Play size={15} /> : <Pause size={15} />}</button>
                          {tracked?.status === "failed" && (
                            <button className="text-action" onClick={() => void retryJob(tracked.id)}>
                              Reintentar proceso
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
