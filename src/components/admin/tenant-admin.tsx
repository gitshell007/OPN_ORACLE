"use client";

import { ApiError, api, type components } from "@oracle/api-client";
import { Ban, MailPlus, RefreshCw, Trash2, UserCog } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { useRecentAuth } from "@/components/auth/recent-auth";

type Member = components["schemas"]["MemberResponse"];
type Role = components["schemas"]["RoleResponse"];

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
        <button className="vector-primary" onClick={() => setInviteOpen(true)}>
          <MailPlus size={16} />
          Invitar miembro
        </button>
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
                        {member.status}
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
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    void api.tenantAdmin
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
    <div className="admin-page">
      <header className="admin-heading">
        <div>
          <p className="eyebrow">Administración de organización</p>
          <h1>Auditoría</h1>
          <p>Eventos de seguridad y administración de la organización activa.</p>
        </div>
      </header>
      <AdminNav active="audit" />
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
                  <th>Fecha</th>
                  <th>Acción</th>
                  <th>Resultado</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td>{new Date(item.created_at).toLocaleString("es-ES")}</td>
                    <td>
                      <code>{item.action}</code>
                    </td>
                    <td>{item.result}</td>
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
