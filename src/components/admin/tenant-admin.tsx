"use client";

import { ApiError, api, type components } from "@oracle/api-client";
import { Activity, AlertTriangle, Ban, MailPlus, RefreshCw, Trash2, UserCog } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { useRecentAuth } from "@/components/auth/recent-auth";
import { HydratedActionButton } from "@/components/ui/async-action-button";
import {
  productAuditActionLabel,
  productJobTypeLabel,
  productQueueLabel,
  productStatusLabel,
} from "@/lib/product-copy";

type Member = components["schemas"]["MemberResponse"];
type Role = components["schemas"]["RoleResponse"];
type Job = components["schemas"]["JobResponse"];

function formatAdminDate(value?: string | null): string {
  if (!value) return "Sin fecha";
  return new Intl.DateTimeFormat("es-ES", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

export function AdminNav({
  active,
}: {
  active: "members" | "audit" | "signal";
}) {
  if (usePathname().startsWith("/app/admin")) return null;
  return (
    <nav className="account-tabs" aria-label="Administración de organización">
      <Link
        aria-current={active === "members" ? "page" : undefined}
        href="/concept-a/admin/members"
      >
        Miembros y roles
      </Link>
      <Link
        aria-current={active === "audit" ? "page" : undefined}
        href="/concept-a/admin/audit"
      >
        Auditoría
      </Link>
      <Link
        aria-current={active === "signal" ? "page" : undefined}
        href="/concept-a/admin/integrations"
      >
        Signal Avanza
      </Link>
    </nav>
  );
}

export function MembersAdmin() {
  const recent = useRecentAuth();
  const [members, setMembers] = useState<Member[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("viewer");
  const [busy, setBusy] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [memberData, roleData] = await Promise.all([
        api.tenantAdmin.members(),
        api.tenantAdmin.roles(),
      ]);
      setMembers(memberData.items);
      setRoles(roleData.items);
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "No se pudo cargar la administración.",
      );
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);
  async function invite(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await recent.run(() =>
        api.tenantAdmin.invite({ email, name: name || undefined, role }),
      );
      setInviteOpen(false);
      setEmail("");
      setName("");
      await load();
      toast.success("Invitación emitida", {
        description: "El enlace se ha enviado mediante el canal configurado.",
      });
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "No se pudo invitar al miembro.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function mutate(action: () => Promise<unknown>, success: string) {
    try {
      await recent.run(action);
      setConfirmRemove(null);
      await load();
      toast.success(success);
    } catch (reason) {
      const message =
        reason instanceof ApiError
          ? reason.message
          : "No se pudo completar la acción.";
      setError(message);
      toast.error(message);
    }
  }
  return (
    <div className="admin-page">
      <header className="admin-heading">
        <div>
          <p className="eyebrow">Administración de organización</p>
          <h1>Miembros y roles</h1>
          <p>
            Gestiona el acceso a la organización activa. Cada cambio de permisos
            se valida y queda registrado de forma segura.
          </p>
        </div>
        <HydratedActionButton className="vector-primary" onClick={() => setInviteOpen(true)}>
          <MailPlus size={16} />
          Invitar miembro
        </HydratedActionButton>
      </header>
      <AdminNav active="members" />
      {error && (
        <div className="inline-error" role="alert">
          {error}
          <button onClick={() => setError(null)}>Cerrar</button>
        </div>
      )}
      {inviteOpen && (
        <section className="admin-form-card">
          <header>
            <h2>Nueva invitación</h2>
            <button
              onClick={() => setInviteOpen(false)}
              aria-label="Cerrar formulario"
            >
              ×
            </button>
          </header>
          <form onSubmit={invite}>
            <label className="field">
              <span>Correo</span>
              <input
                type="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </label>
            <label className="field">
              <span>Nombre</span>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label className="field">
              <span>Rol inicial</span>
              <select
                value={role}
                onChange={(event) => setRole(event.target.value)}
              >
                {roles.map((item) => (
                  <option key={item.id} value={item.key}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <button className="vector-primary" disabled={busy}>
              {busy ? "Enviando…" : "Enviar invitación"}
            </button>
          </form>
        </section>
      )}
      <section className="admin-table-card">
        {loading ? (
          <p role="status">Cargando miembros…</p>
        ) : members.length === 0 ? (
          <div className="empty-admin">
            <UserCog size={26} />
            <strong>No hay miembros visibles</strong>
            <p>Invita a la primera persona para colaborar.</p>
          </div>
        ) : (
          <div className="table-scroll">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Miembro</th>
                  <th>Estado</th>
                  <th>Asignar rol</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {members.map((member) => (
                  <tr key={member.id}>
                    <td>
                      <strong>
                        {member.display_name || "Invitación pendiente"}
                      </strong>
                      <small>{member.email}</small>
                    </td>
                    <td>
                      <span
                        className={`status ${member.status === "active" ? "active" : ""}`}
                      >
                        {productStatusLabel(member.status)}
                      </span>
                    </td>
                    <td>
                      <select
                        aria-label={`Rol de ${member.email}`}
                        value={member.roles[0] ?? "viewer"}
                        onChange={(event) =>
                          void mutate(
                            () =>
                              api.tenantAdmin.setRoles(member.id, [
                                event.target.value,
                              ]),
                            "Roles actualizados",
                          )
                        }
                      >
                        {roles.map((item) => (
                          <option key={item.id} value={item.key}>
                            {item.name}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <div className="row-actions">
                        {member.status === "invited" && (
                          <button
                            title="Reenviar invitación"
                            aria-label={`Reenviar invitación a ${member.email}`}
                            onClick={() =>
                              void mutate(
                                () => api.tenantAdmin.resend(member.id),
                                "Invitación reenviada",
                              )
                            }
                          >
                            <RefreshCw size={15} />
                          </button>
                        )}
                        {member.status === "active" && (
                          <button
                            title="Suspender"
                            aria-label={`Suspender a ${member.email}`}
                            onClick={() =>
                              void mutate(
                                () =>
                                  api.tenantAdmin.setStatus(
                                    member.id,
                                    "suspended",
                                  ),
                                "Miembro suspendido",
                              )
                            }
                          >
                            <Ban size={15} />
                          </button>
                        )}
                        {member.status === "suspended" && (
                          <button
                            title="Reactivar"
                            aria-label={`Reactivar a ${member.email}`}
                            onClick={() =>
                              void mutate(
                                () =>
                                  api.tenantAdmin.setStatus(
                                    member.id,
                                    "active",
                                  ),
                                "Miembro reactivado",
                              )
                            }
                          >
                            <RefreshCw size={15} />
                          </button>
                        )}
                        {confirmRemove === member.id ? (
                          <>
                            <button
                              className="confirm-delete"
                              onClick={() =>
                                void mutate(
                                  () => api.tenantAdmin.remove(member.id),
                                  "Miembro retirado",
                                )
                              }
                            >
                              Confirmar
                            </button>
                            <button onClick={() => setConfirmRemove(null)}>
                              Cancelar
                            </button>
                          </>
                        ) : (
                          <button
                            title="Retirar"
                            aria-label={`Retirar a ${member.email}`}
                            onClick={() => setConfirmRemove(member.id)}
                          >
                            <Trash2 size={15} />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

export function TenantAudit() {
  const [items, setItems] = useState<components["schemas"]["AuditResponse"][]>(
    [],
  );
  const [jobs, setJobs] = useState<Job[]>([]);
  const [activeView, setActiveView] = useState<"audit" | "processes">(() => {
    if (typeof window === "undefined") return "audit";
    return new URLSearchParams(window.location.search).get("view") === "processes"
      ? "processes"
      : "audit";
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [processError, setProcessError] = useState<string | null>(null);
  const failedJobs = jobs.filter((job) => job.status === "failed").length;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setProcessError(null);
    try {
      const [auditResult, jobsResult] = await Promise.allSettled([
        api.tenantAdmin.audit(),
        api.jobs.list(1, 50),
      ]);
      if (auditResult.status === "fulfilled") setItems(auditResult.value.items);
      else throw auditResult.reason;
      if (jobsResult.status === "fulfilled") setJobs(jobsResult.value.data);
      else {
        setJobs([]);
        setProcessError(
          jobsResult.reason instanceof ApiError
            ? jobsResult.reason.problem.detail
            : "No se pudieron cargar los procesos.",
        );
      }
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "No se pudo cargar la auditoría.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) void load();
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  return (
    <div className="admin-page">
      <header className="admin-heading">
        <div>
          <p className="eyebrow">Administración de organización</p>
          <h1>Auditoría</h1>
          <p>Registro temporal de eventos y procesos en segundo plano de la organización activa.</p>
        </div>
        <button className="vector-secondary" type="button" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={15} />
          Actualizar
        </button>
      </header>
      <AdminNav active="audit" />
      <div className="audit-view-tabs" role="tablist" aria-label="Vistas de auditoría">
        <button
          type="button"
          role="tab"
          aria-selected={activeView === "audit"}
          className={activeView === "audit" ? "active" : ""}
          onClick={() => setActiveView("audit")}
        >
          Registro de auditoría
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeView === "processes"}
          className={activeView === "processes" ? "active" : ""}
          onClick={() => setActiveView("processes")}
        >
          Procesos
          {failedJobs > 0 && <span>{failedJobs} fallidos</span>}
        </button>
      </div>
      {error ? (
        <div className="inline-error" role="alert">
          {error}
        </div>
      ) : loading ? (
        <section className="admin-table-card">
          <p role="status">Cargando auditoría…</p>
        </section>
      ) : activeView === "audit" ? (
        <section className="admin-table-card" aria-labelledby="tenant-audit-events-title">
          <header className="admin-card-heading">
            <div>
              <h2 id="tenant-audit-events-title">Registro de auditoría</h2>
              <p>Quién hizo qué, cuándo y con qué resultado.</p>
            </div>
          </header>
          <div className="table-scroll">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th>Acción</th>
                  <th>Resultado</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td>{formatAdminDate(item.created_at)}</td>
                    <td>
                      {productAuditActionLabel(item.action)}
                    </td>
                    <td>{productStatusLabel(item.result)}</td>
                  </tr>
                ))}
                {!items.length && <tr><td colSpan={3}>No hay eventos de auditoría recientes.</td></tr>}
              </tbody>
            </table>
          </div>
        </section>
      ) : (
        <section className="admin-table-card" aria-labelledby="tenant-processes-title">
          <header className="admin-card-heading">
            <div>
              <h2 id="tenant-processes-title">Procesos</h2>
              <p>Trabajos en segundo plano con fecha de creación, última actualización, progreso y estado.</p>
            </div>
            {failedJobs > 0 && <span className="status critical"><AlertTriangle size={14} /> {failedJobs} fallidos</span>}
          </header>
          {processError && <div className="inline-warning" role="status">{processError}</div>}
          <div className="table-scroll">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th>Proceso</th>
                  <th>Estado</th>
                  <th>Progreso</th>
                  <th>Actualización</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.id} className={job.status === "failed" ? "job-row-failed" : undefined}>
                    <td>{formatAdminDate(job.created_at)}</td>
                    <td>
                      <strong>{productJobTypeLabel(job.job_type)}</strong>
                      <small>{productQueueLabel(job.queue)} · {job.id}</small>
                    </td>
                    <td><span className={`status ${job.status}`}>{productStatusLabel(job.status)}</span></td>
                    <td><Activity size={14} aria-hidden="true" /> {job.progress}%</td>
                    <td>{formatAdminDate(job.updated_at)}</td>
                  </tr>
                ))}
                {!jobs.length && <tr><td colSpan={5}>No hay procesos recientes.</td></tr>}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}

export function TenantAIAdmin() {
  const [policy, setPolicy] = useState<components["schemas"]["AIPolicyResponse"] | null>(null);
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try { setPolicy(await api.tenantAdmin.aiPolicy()); }
    catch (reason) { setError(reason instanceof ApiError ? reason.problem.detail : "No se pudo cargar la política IA."); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { queueMicrotask(() => void load()); }, [load]);
  async function testConnection() {
    setTesting(true);
    setError(null);
    try {
      const result = await api.tenantAdmin.testAI();
      toast.success("Configuración IA comprobada", { description: `${result.status}${result.model ? ` · ${result.model}` : ""}. Esta comprobación no ejecuta una inferencia.` });
      await load();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.problem.detail : "No se pudo comprobar la configuración IA.");
    } finally { setTesting(false); }
  }
  return <div className="admin-page">
    <header className="admin-heading"><div><p className="eyebrow">Administración de organización</p><h1>Inteligencia artificial</h1><p>Política efectiva, límites y último resultado, sin exponer credenciales.</p></div><button className="vector-primary" disabled={testing || !policy?.enabled || policy.kill_switch} onClick={() => void testConnection()}>{testing ? "Comprobando…" : "Comprobar configuración"}</button></header>
    {error && <div className="inline-error" role="alert">{error}<button onClick={() => void load()}>Reintentar</button></div>}
    {loading ? <p role="status">Cargando política IA…</p> : policy && <section className="admin-table-card ai-policy-grid">
      <article><strong>Estado</strong><p>{policy.enabled && !policy.kill_switch ? "Activa" : "Desactivada"}</p>{(!policy.enabled || policy.kill_switch) && <small>Solicita a un administrador que revise el kill switch y la política del tenant.</small>}</article>
      <article><strong>Proveedor de acceso</strong><p>{policy.provider}</p><small>{policy.routing_authority === "signal" ? "Signal decide proveedor y modelo por task_key." : "Oracle usa la política local configurada."}</small></article>
      <article><strong>Modelos permitidos</strong><p>{policy.allowed_models?.length ? policy.allowed_models.join(", ") : "Gobernados por Signal"}</p></article>
      <article><strong>Límites</strong><p>{String(policy.limits.daily_calls ?? 0)} llamadas/día · {String(policy.limits.max_concurrency ?? 0)} simultáneas</p></article>
      <article><strong>Presupuesto</strong><p>{Number(policy.limits.monthly_hard_budget_micros ?? 0) > 0 ? `${Number(policy.limits.monthly_hard_budget_micros) / 1_000_000} €` : "Sin techo económico configurado en Oracle"}</p></article>
      <article><strong>Último resultado</strong><p>{policy.last_run ? `${String(policy.last_run.status)} · ${String(policy.last_run.provider ?? "proveedor no informado")}` : "Todavía no hay ejecuciones"}</p></article>
      <article><strong>Último error</strong><p>{policy.last_error ? `${String(policy.last_error.error_code ?? "error no clasificado")} · ${String(policy.last_error.provider ?? "proveedor no informado")}` : "No hay errores registrados"}</p></article>
    </section>}
  </div>;
}
