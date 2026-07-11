"use client";

import { ApiError, api, type components } from "@oracle/api-client";
import { MailPlus, PauseCircle, PlayCircle, Plus, Search } from "lucide-react";
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { useRecentAuth } from "@/components/auth/recent-auth";

type Tenant = components["schemas"]["TenantResponse"];

export function PlatformTenants() {
  const recent = useRecentAuth();
  const [items, setItems] = useState<Tenant[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [plan, setPlan] = useState("");
  const [confirmStatus, setConfirmStatus] = useState<string | null>(null);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems((await api.platform.tenants()).items);
      setError(null);
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "No se pudieron cargar las organizaciones.",
      );
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);
  const visible = useMemo(
    () =>
      items.filter((item) =>
        `${item.name} ${item.slug}`
          .toLowerCase()
          .includes(filter.toLowerCase()),
      ),
    [items, filter],
  );
  async function create(event: FormEvent) {
    event.preventDefault();
    try {
      await recent.run(() =>
        api.platform.createTenant({
          name,
          slug: slug || undefined,
          plan: plan || undefined,
        }),
      );
      setCreating(false);
      setName("");
      setSlug("");
      setPlan("");
      await load();
      toast.success("Organización creada");
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "No se pudo crear la organización.",
      );
    }
  }
  async function status(item: Tenant) {
    const action = item.status === "active" ? "suspend" : "reactivate";
    try {
      await recent.run(() => api.platform.setTenantStatus(item.id, action));
      setConfirmStatus(null);
      await load();
      toast.success(
        action === "suspend"
          ? "Organización suspendida"
          : "Organización reactivada",
      );
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "No se pudo cambiar el estado.",
      );
    }
  }
  return (
    <div className="platform-page">
      <header className="admin-heading">
        <div>
          <p className="eyebrow">Plataforma</p>
          <h1>Organizaciones</h1>
          <p>
            Gestiona el ciclo de vida de los tenants sin abrir sus datos de
            negocio.
          </p>
        </div>
        <button className="platform-primary" onClick={() => setCreating(true)}>
          <Plus size={16} />
          Crear organización
        </button>
      </header>
      {error && (
        <div className="inline-error" role="alert">
          {error}
          <button onClick={() => setError(null)}>Cerrar</button>
        </div>
      )}
      {creating && (
        <section className="admin-form-card">
          <header>
            <h2>Nueva organización</h2>
            <button onClick={() => setCreating(false)} aria-label="Cerrar">
              ×
            </button>
          </header>
          <form onSubmit={create}>
            <label className="field">
              <span>Nombre</span>
              <input
                required
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label className="field">
              <span>Slug opcional</span>
              <input
                value={slug}
                onChange={(event) => setSlug(event.target.value)}
              />
            </label>
            <label className="field">
              <span>Plan</span>
              <input
                value={plan}
                onChange={(event) => setPlan(event.target.value)}
              />
            </label>
            <button className="platform-primary">Crear tenant</button>
          </form>
        </section>
      )}
      <section className="platform-toolbar">
        <label>
          <Search size={16} />
          <input
            placeholder="Buscar organización"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          />
        </label>
        <span>{visible.length} organizaciones</span>
      </section>
      <section className="admin-table-card">
        {loading ? (
          <p role="status">Cargando organizaciones…</p>
        ) : (
          <div className="table-scroll">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Organización</th>
                  <th>Estado</th>
                  <th>Plan</th>
                  <th>Acción</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <Link href={`/platform/tenants/${item.id}`}>
                        <strong>{item.name}</strong>
                        <small>{item.slug}</small>
                      </Link>
                    </td>
                    <td>
                      <span
                        className={`status ${item.status === "active" ? "active" : ""}`}
                      >
                        {item.status}
                      </span>
                    </td>
                    <td>{item.plan || "Sin plan"}</td>
                    <td>
                      {confirmStatus === item.id ? (
                        <div className="row-actions">
                          <button
                            className="confirm-delete"
                            onClick={() => void status(item)}
                          >
                            Confirmar
                          </button>
                          <button onClick={() => setConfirmStatus(null)}>
                            Cancelar
                          </button>
                        </div>
                      ) : (
                        <button
                          className="platform-icon-action"
                          onClick={() =>
                            item.status === "active"
                              ? setConfirmStatus(item.id)
                              : void status(item)
                          }
                        >
                          {item.status === "active" ? (
                            <>
                              <PauseCircle size={16} />
                              Suspender
                            </>
                          ) : (
                            <>
                              <PlayCircle size={16} />
                              Reactivar
                            </>
                          )}
                        </button>
                      )}
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

export function PlatformTenantDetail({ id }: { id: string }) {
  const recent = useRecentAuth();
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    void api.platform
      .tenant(id)
      .then(setTenant)
      .catch((reason) =>
        setError(
          reason instanceof ApiError
            ? reason.message
            : "No se pudo cargar la organización.",
        ),
      );
  }, [id]);
  async function invite(event: FormEvent) {
    event.preventDefault();
    try {
      await recent.run(() =>
        api.platform.inviteOwner(id, {
          email,
          name: name || undefined,
        }),
      );
      setEmail("");
      setName("");
      toast.success("Propietario invitado");
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "No se pudo invitar al propietario.",
      );
    }
  }
  if (error && !tenant)
    return (
      <div className="inline-error" role="alert">
        {error}
      </div>
    );
  if (!tenant) return <p role="status">Cargando detalle…</p>;
  return (
    <div className="platform-page">
      <Link className="back-link" href="/platform/tenants">
        ← Organizaciones
      </Link>
      <header className="admin-heading">
        <div>
          <p className="eyebrow">Datos de plataforma</p>
          <h1>{tenant.name}</h1>
          <p>
            ID {tenant.id} · slug {tenant.slug}
          </p>
        </div>
        <span
          className={`status ${tenant.status === "active" ? "active" : ""}`}
        >
          {tenant.status}
        </span>
      </header>
      <section className="platform-summary">
        <article>
          <span>Plan</span>
          <strong>{tenant.plan || "Sin plan asignado"}</strong>
        </article>
        <article>
          <span>Alcance</span>
          <strong>Metadatos de la organización</strong>
        </article>
        <article>
          <span>Datos de negocio</span>
          <strong>No accesibles por defecto</strong>
        </article>
      </section>
      <section className="admin-form-card">
        <header>
          <div>
            <h2>Invitar propietario</h2>
            <p>
              Crea una invitación de un solo uso; no se establece una contraseña
              fija.
            </p>
          </div>
          <MailPlus size={20} />
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
          <button className="platform-primary">Enviar invitación</button>
        </form>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </section>
    </div>
  );
}

export function PlatformUsers() {
  const [items, setItems] = useState<components["schemas"]["UserResponse"][]>(
    [],
  );
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    void api.platform
      .users()
      .then((data) => setItems(data.items))
      .catch((reason) =>
        setError(
          reason instanceof ApiError
            ? reason.message
            : "No se pudieron cargar los usuarios.",
        ),
      );
  }, []);
  return (
    <SimplePlatformTable
      title="Usuarios de plataforma"
      description="Directorio global sin datos de negocio."
      error={error}
      headers={["Usuario", "Estado", "Rol de plataforma"]}
      rows={items.map((item) => [
        <span key="user">
          <strong>{item.display_name}</strong>
          <small>{item.email}</small>
        </span>,
        item.status,
        item.platform_role || "—",
      ])}
    />
  );
}
export function PlatformAudit() {
  const [items, setItems] = useState<components["schemas"]["AuditResponse"][]>(
    [],
  );
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    void api.platform
      .audit()
      .then((data) => setItems(data.items))
      .catch((reason) =>
        setError(
          reason instanceof ApiError
            ? reason.message
            : "No se pudo cargar la auditoría.",
        ),
      );
  }, []);
  return (
    <SimplePlatformTable
      title="Auditoría global"
      description="Eventos administrativos de plataforma."
      error={error}
      headers={["Fecha", "Acción", "Resultado"]}
      rows={items.map((item) => [
        new Date(item.created_at).toLocaleString("es-ES"),
        <code key="action">{item.action}</code>,
        item.result,
      ])}
    />
  );
}

export function PlatformSystem() {
  const [system, setSystem] = useState<Awaited<ReturnType<typeof api.platform.system>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    void api.platform.system().then(setSystem).catch((reason) =>
      setError(reason instanceof ApiError ? reason.message : "No se pudo consultar la salud técnica."),
    );
  }, []);
  return (
    <div className="platform-page">
      <header className="admin-heading"><div><p className="eyebrow">Plataforma</p><h1>Salud técnica</h1><p>Probes autorizadas sin configuración sensible.</p></div></header>
      {error && <div className="inline-error" role="alert">{error}</div>}
      {!system ? <p role="status">Consultando dependencias…</p> : <section className="platform-summary"><article><span>Proceso</span><strong>{system.live.status}</strong></article><article><span>Dependencias</span><strong>{system.ready.status}</strong></article><article><span>Release</span><strong>{system.meta.release}</strong></article></section>}
    </div>
  );
}

export function PlatformOperationalOverview({ kind }: { kind: "jobs" | "integrations" }) {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    void api.platform.tenants().then((result) => setTenants(result.items)).catch((reason) =>
      setError(reason instanceof ApiError ? reason.message : "No se pudo cargar el alcance de plataforma."),
    );
  }, []);
  const active = tenants.filter((item) => item.status === "active").length;
  return (
    <div className="platform-page">
      <header className="admin-heading"><div><p className="eyebrow">Plataforma</p><h1>{kind === "jobs" ? "Trabajos y colas" : "Integraciones"}</h1><p>Vista global limitada a metadatos organizativos; nunca abre información estratégica.</p></div></header>
      {error && <div className="inline-error" role="alert">{error}</div>}
      <section className="platform-summary"><article><span>Organizaciones</span><strong>{tenants.length}</strong></article><article><span>Activas</span><strong>{active}</strong></article><article><span>Ámbito</span><strong>Metadatos globales</strong></article></section>
      <section className="admin-form-card"><header><div><h2>Resumen global no disponible</h2><p>{kind === "jobs" ? "Consulta cada organización para revisar sus procesos con el contexto y los permisos adecuados." : "Signal Avanza se administra dentro de cada organización para mantener el aislamiento de sus credenciales."}</p></div></header><Link className="platform-primary" href="/platform/tenants">Abrir organizaciones</Link></section>
    </div>
  );
}
function SimplePlatformTable({
  title,
  description,
  error,
  headers,
  rows,
}: {
  title: string;
  description: string;
  error: string | null;
  headers: string[];
  rows: React.ReactNode[][];
}) {
  return (
    <div className="platform-page">
      <header className="admin-heading">
        <div>
          <p className="eyebrow">Datos de plataforma</p>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
      </header>
      {error ? (
        <div className="inline-error" role="alert">
          {error}
        </div>
      ) : (
        <section className="admin-table-card">
          <div className="table-scroll">
            <table className="admin-table">
              <thead>
                <tr>
                  {headers.map((header) => (
                    <th key={header}>{header}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr key={index}>
                    {row.map((cell, cellIndex) => (
                      <td key={cellIndex}>{cell}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
