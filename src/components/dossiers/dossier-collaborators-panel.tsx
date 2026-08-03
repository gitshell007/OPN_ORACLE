"use client";

import {
  ApiError,
  api,
  type AssignableUser,
  type DossierCollaborator,
  type DossierCollaboratorRole,
} from "@oracle/api-client";
import { UserPlus, X } from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { PermissionGate } from "@/components/auth/auth-boundary";
import { AsyncActionButton } from "@/components/ui/async-action-button";

const errorText = (reason: unknown, fallback: string) =>
  reason instanceof ApiError ? reason.problem.detail : fallback;

const ROLE_OPTIONS: Array<{ value: DossierCollaboratorRole; label: string; hint: string }> = [
  { value: "viewer", label: "Solo lectura", hint: "Puede ver el expediente, no editar." },
  { value: "collaborator", label: "Colaborador", hint: "Puede aportar en el trabajo del expediente." },
  { value: "editor", label: "Editor", hint: "Puede editar el contenido del expediente." },
  { value: "owner", label: "Propietario compartido", hint: "Gestión amplia del expediente (no cambia el dueño del registro)." },
];

function roleLabel(role: string): string {
  return ROLE_OPTIONS.find((item) => item.value === role)?.label ?? role;
}

export function DossierCollaboratorsPanel({
  dossierId,
  disabled = false,
}: {
  dossierId: string;
  disabled?: boolean;
}) {
  const [collaborators, setCollaborators] = useState<DossierCollaborator[]>([]);
  const [assignable, setAssignable] = useState<AssignableUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [userId, setUserId] = useState("");
  const [role, setRole] = useState<DossierCollaboratorRole>("collaborator");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [collabResult, usersResult] = await Promise.all([
        api.dossiers.listCollaborators(dossierId),
        api.assignableUsers.list().catch(() => ({ items: [] as AssignableUser[] })),
      ]);
      setCollaborators(collabResult.data ?? []);
      setAssignable(usersResult.items ?? []);
    } catch (reason) {
      setError(errorText(reason, "No se pudo cargar el acceso del expediente."));
      setCollaborators([]);
    } finally {
      setLoading(false);
    }
  }, [dossierId]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  const nameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const user of assignable) {
      map.set(user.id, user.display_name || user.id);
    }
    return map;
  }, [assignable]);

  const availableToInvite = useMemo(() => {
    const already = new Set(collaborators.map((item) => item.user_id));
    return assignable.filter((user) => !already.has(user.id));
  }, [assignable, collaborators]);

  async function invite(event: FormEvent) {
    event.preventDefault();
    if (!userId || disabled) return;
    setBusy(true);
    setError(null);
    try {
      await api.dossiers.setCollaborator(dossierId, userId, { role });
      toast.success("Acceso concedido al compañero de la organización.");
      setUserId("");
      await load();
    } catch (reason) {
      setError(
        errorText(
          reason,
          "No se pudo invitar. Solo se puede compartir con miembros activos de tu organización.",
        ),
      );
    } finally {
      setBusy(false);
    }
  }

  async function changeRole(collaborator: DossierCollaborator, nextRole: DossierCollaboratorRole) {
    if (disabled) return;
    setBusy(true);
    setError(null);
    try {
      await api.dossiers.setCollaborator(dossierId, collaborator.user_id, { role: nextRole });
      toast.success("Nivel de acceso actualizado.");
      await load();
    } catch (reason) {
      setError(errorText(reason, "No se pudo cambiar el rol."));
    } finally {
      setBusy(false);
    }
  }

  async function remove(collaborator: DossierCollaborator) {
    if (disabled) return;
    setBusy(true);
    setError(null);
    try {
      await api.dossiers.removeCollaborator(dossierId, collaborator.user_id);
      toast.success("Acceso retirado.");
      await load();
    } catch (reason) {
      setError(errorText(reason, "No se pudo retirar el acceso."));
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <section className="settings-section" aria-labelledby="dossier-share-title">
        <header>
          <h2 id="dossier-share-title">Compartir expediente</h2>
          <p>Quién de tu organización puede ver o trabajar este expediente.</p>
        </header>
        <p className="global-inventory-state" role="status">
          Cargando accesos…
        </p>
      </section>
    );
  }

  return (
    <section className="settings-section" aria-labelledby="dossier-share-title">
      <header>
        <h2 id="dossier-share-title">Compartir expediente</h2>
        <p>
          Invita solo a compañeros de tu organización. No es posible compartir con
          usuarios de otra organización: el aislamiento por tenant lo impide.
        </p>
      </header>

      {error && (
        <div className="inline-error" role="alert">
          {error}
          <button type="button" onClick={() => setError(null)}>
            Cerrar
          </button>
        </div>
      )}

      {collaborators.length === 0 ? (
        <p className="reporting-hint" role="status">
          Aún no hay colaboradores explícitos. El propietario y los administradores
          del tenant ya tienen acceso.
        </p>
      ) : (
        <ul className="dossier-collaborator-list" style={{ listStyle: "none", padding: 0, margin: "0 0 1rem" }}>
          {collaborators.map((item) => (
            <li
              key={`${item.user_id}-${item.role}`}
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: "0.75rem",
                alignItems: "center",
                marginBottom: "0.75rem",
              }}
            >
              <strong>{nameById.get(item.user_id) ?? item.user_id.slice(0, 8)}</strong>
              <PermissionGate
                permission="dossier.write"
                fallback={<span className="reporting-hint">{roleLabel(item.role)}</span>}
              >
                <select
                  aria-label={`Rol de ${nameById.get(item.user_id) ?? item.user_id}`}
                  value={item.role}
                  disabled={disabled || busy}
                  onChange={(event) =>
                    void changeRole(item, event.target.value as DossierCollaboratorRole)
                  }
                >
                  {ROLE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <AsyncActionButton
                  type="button"
                  className="vector-secondary"
                  disabled={disabled}
                  loading={busy}
                  onClick={() => void remove(item)}
                  aria-label={`Quitar acceso a ${nameById.get(item.user_id) ?? item.user_id}`}
                >
                  <X size={14} aria-hidden="true" /> Quitar
                </AsyncActionButton>
              </PermissionGate>
            </li>
          ))}
        </ul>
      )}

      <PermissionGate
        permission="dossier.write"
        fallback={
          <p className="reporting-hint">
            Solo quien puede editar el expediente puede invitar o cambiar accesos.
          </p>
        }
      >
        <form className="dossier-settings-form" onSubmit={(event) => void invite(event)}>
          <label className="field">
            <span>Compañero de la organización</span>
            <select
              required
              value={userId}
              onChange={(event) => setUserId(event.target.value)}
              disabled={disabled || busy || availableToInvite.length === 0}
            >
              <option value="">
                {availableToInvite.length === 0
                  ? "No hay más miembros disponibles"
                  : "Selecciona un miembro"}
              </option>
              {availableToInvite.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.display_name || user.id}
                </option>
              ))}
            </select>
            <small>La lista solo incluye miembros activos de tu organización (tenant).</small>
          </label>
          <label className="field">
            <span>Nivel de acceso</span>
            <select
              value={role}
              onChange={(event) => setRole(event.target.value as DossierCollaboratorRole)}
              disabled={disabled || busy}
            >
              {ROLE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label} — {option.hint}
                </option>
              ))}
            </select>
          </label>
          <div className="settings-actions">
            <AsyncActionButton
              className="vector-primary"
              type="submit"
              loading={busy}
              disabled={disabled || !userId}
            >
              <UserPlus size={15} aria-hidden="true" /> Invitar
            </AsyncActionButton>
          </div>
        </form>
      </PermissionGate>
    </section>
  );
}
