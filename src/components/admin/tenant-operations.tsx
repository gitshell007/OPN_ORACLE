"use client";

import { ApiError, api, type BackendDossier, type components } from "@oracle/api-client";
import { Building2, FolderKanban, RefreshCw, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { JobProgress } from "@/components/reporting/job-progress";
import { useAuth } from "@/components/auth/auth-provider";
import {
  productJobTypeLabel,
  productQueueLabel,
  productRoleLabel,
  productStatusLabel,
} from "@/lib/product-copy";

type Role = components["schemas"]["RoleResponse"];
type Job = components["schemas"]["JobResponse"];

function errorMessage(reason: unknown, fallback: string) {
  return reason instanceof ApiError ? reason.problem.detail : fallback;
}

export function TenantRoles() {
  const [items, setItems] = useState<Role[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void api.tenantAdmin
      .roles()
      .then((result) => setItems(result.items))
      .catch((reason) =>
        setError(errorMessage(reason, "No se pudieron cargar los roles.")),
      )
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  return (
    <div className="settings-page">
      <section className="page-heading">
        <div>
          <div className="eyebrow">Administración de la organización</div>
          <h1>Roles y permisos</h1>
          <p>Roles autoritativos disponibles para asignar a los miembros.</p>
        </div>
      </section>
      {error && <div className="inline-error" role="alert">{error}</div>}
      <section className="admin-role-grid" aria-busy={loading}>
        {loading ? (
          <p role="status">Cargando roles…</p>
        ) : items.length ? (
          items.map((role) => (
            <article className="vector-panel" key={role.id}>
              <ShieldCheck size={20} aria-hidden="true" />
              <div>
                <h2>{role.name}</h2>
                <code>{role.key}</code>
                <p>{role.description || "Rol administrado por la política RBAC de Oracle."}</p>
              </div>
            </article>
          ))
        ) : (
          <p>No hay roles asignables en esta organización.</p>
        )}
      </section>
    </div>
  );
}

export function TenantJobs() {
  const [items, setItems] = useState<Job[]>([]);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api.jobs.list(1, 50, status || undefined);
      setItems(result.data);
      setError(null);
    } catch (reason) {
      setError(errorMessage(reason, "No se pudieron cargar los procesos."));
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  return (
    <div className="settings-page">
      <section className="page-heading">
        <div>
          <div className="eyebrow">Administración de la organización</div>
          <h1>Trabajos en segundo plano</h1>
          <p>Progreso, reintentos y fallos saneados de los procesos autorizados.</p>
        </div>
        <button className="vector-secondary" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={15} /> Actualizar
        </button>
      </section>
      <div className="dossier-toolbar">
        <label className="field compact-field">
          <span>Estado</span>
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">Todos</option>
            <option value="queued">En cola</option>
            <option value="running">En curso</option>
            <option value="retrying">Reintentando</option>
            <option value="succeeded">Completados</option>
            <option value="failed">Fallidos</option>
            <option value="cancelled">Cancelados</option>
          </select>
        </label>
      </div>
      {error && <div className="inline-error" role="alert">{error}</div>}
      <section className="admin-table-card" aria-busy={loading}>
        {loading ? <p role="status">Cargando procesos…</p> : (
          <div className="table-scroll">
            <table className="admin-table">
              <thead><tr><th>Proceso</th><th>Estado</th><th>Progreso</th><th>Intentos</th></tr></thead>
              <tbody>
                {items.map((job) => (
                  <tr key={job.id}>
                    <td><strong>{productJobTypeLabel(job.job_type)}</strong><small>{productQueueLabel(job.queue)} · {job.id}</small></td>
                    <td><span className={`status ${job.status}`}>{productStatusLabel(job.status)}</span></td>
                    <td><JobProgress jobId={job.id} label={productStatusLabel(job.stage)} allowActions onTerminal={() => void load()} /></td>
                    <td>{job.attempts ?? 0} / {job.max_attempts ?? 1}</td>
                  </tr>
                ))}
                {!items.length && <tr><td colSpan={4}>No hay procesos para este filtro.</td></tr>}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

export function TenantOrganization() {
  const auth = useAuth();
  const membership = auth.identity?.memberships.find(
    (item) => item.tenant_id === auth.identity?.active_tenant_id,
  );
  return (
    <div className="settings-page">
      <section className="page-heading"><div><div className="eyebrow">Administración de la organización</div><h1>Organización</h1><p>Contexto autorizado de la organización activa y sus capacidades.</p></div></section>
      <section className="organization-overview">
        <article className="vector-panel"><Building2 size={23} /><div><span>Organización activa</span><h2>{membership?.tenant_name || "Sin organización activa"}</h2><p>{membership?.tenant_slug || "—"}</p></div></article>
        <article className="vector-panel"><ShieldCheck size={23} /><div><span>Estado de acceso</span><h2>{productStatusLabel(membership?.membership_status)}</h2><p>{auth.identity?.roles.map(productRoleLabel).join(", ") || "Sin rol asignado"}</p></div></article>
      </section>
      <section className="settings-section"><header><h2>Configuración organizativa</h2><p>La edición del nombre, idioma y zona horaria estará disponible en una próxima actualización. Mientras tanto, estos datos se mantienen protegidos frente a cambios accidentales.</p></header><Link className="vector-secondary" href="/app/admin/audit">Revisar auditoría</Link></section>
    </div>
  );
}

export function TenantWorkspaces() {
  const [dossiers, setDossiers] = useState<BackendDossier[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    void api.dossiers.list({ size: 100 }).then((result) => setDossiers(result.data)).catch((reason) => setError(errorMessage(reason, "No se pudieron cargar los espacios de trabajo."))).finally(() => setLoading(false));
  }, []);
  const groups = new Map<string, BackendDossier[]>();
  for (const dossier of dossiers) {
    const key = dossier.workspace_id || "workspace-principal";
    groups.set(key, [...(groups.get(key) ?? []), dossier]);
  }
  return (
    <div className="settings-page">
      <section className="page-heading"><div><div className="eyebrow">Administración de la organización</div><h1>Espacios de trabajo</h1><p>Espacios representados en los expedientes a los que tienes acceso.</p></div></section>
      {error && <div className="inline-error" role="alert">{error}</div>}
      <section className="admin-role-grid" aria-busy={loading}>
        {loading ? <p role="status">Cargando espacios de trabajo…</p> : [...groups].map(([id, items]) => <article className="vector-panel" key={id}><FolderKanban size={20} /><div><h2>{id === "workspace-principal" ? "Espacio principal" : `Espacio ${id.slice(0, 8)}`}</h2><p>{items.length} expediente{items.length === 1 ? "" : "s"} accesible{items.length === 1 ? "" : "s"}</p><Link href="/app/dossiers">Ver expedientes</Link></div></article>)}
        {!loading && groups.size === 0 && <p>No hay espacios de trabajo representados en tus expedientes accesibles.</p>}
      </section>
      <p className="reporting-hint">La creación y asignación de espacios de trabajo estará disponible en una próxima actualización.</p>
    </div>
  );
}
