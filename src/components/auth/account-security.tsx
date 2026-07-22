"use client";

import { ApiError, api, type components } from "@oracle/api-client";
import { KeyRound, Laptop, LogOut, ShieldCheck, Trash2 } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { AsyncActionButton } from "@/components/ui/async-action-button";
import { useAuth } from "./auth-provider";
import { useRecentAuth } from "./recent-auth";

type Session = components["schemas"]["SessionResponse"];

export function SettingsHeader({
  active,
}: {
  active: "profile" | "security" | "sessions" | "preferences" | "notifications";
}) {
  const canonical = usePathname().startsWith("/app/account");
  const base = canonical ? "/app/account" : "/concept-a/settings";
  return (
    <nav className="account-tabs" aria-label="Ajustes de cuenta">
      <Link
        aria-current={active === "profile" ? "page" : undefined}
        href={`${base}/profile`}
      >
        Perfil
      </Link>
      <Link
        aria-current={active === "security" ? "page" : undefined}
        href={`${base}/security`}
      >
        Seguridad
      </Link>
      <Link
        aria-current={active === "sessions" ? "page" : undefined}
        href={`${base}/sessions`}
      >
        Sesiones activas
      </Link>
      <Link
        aria-current={active === "preferences" ? "page" : undefined}
        href={canonical ? `${base}/preferences` : base}
      >
        Preferencias
      </Link>
      {canonical && (
        <Link
          aria-current={active === "notifications" ? "page" : undefined}
          href={`${base}/notifications`}
        >
          Notificaciones
        </Link>
      )}
    </nav>
  );
}

export function ProfileSettings() {
  const identity = useAuth().identity!;
  const tenant = identity.memberships.find(
    (item) => item.tenant_id === identity.active_tenant_id,
  );
  return (
    <div className="settings-page">
      <section className="page-heading">
        <div>
          <div className="eyebrow">Cuenta</div>
          <h1>Perfil</h1>
          <p>Identidad corporativa validada por el servidor.</p>
        </div>
      </section>
      <SettingsHeader active="profile" />
      <section className="settings-section">
        <header>
          <h2>Información personal</h2>
          <p>
            La edición de perfil estará disponible en una próxima actualización.
          </p>
        </header>
        <div className="settings-grid">
          <label className="field">
            <span>Nombre</span>
            <input value={identity.user.display_name} disabled />
          </label>
          <label className="field">
            <span>Correo</span>
            <input value={identity.user.email} disabled />
          </label>
          <label className="field">
            <span>Organización activa</span>
            <input
              value={tenant?.tenant_name ?? "Contexto de plataforma"}
              disabled
            />
          </label>
          <label className="field">
            <span>Roles</span>
            <input value={identity.roles.join(", ") || "Plataforma"} disabled />
          </label>
        </div>
      </section>
    </div>
  );
}

export function SecuritySettings() {
  const recent = useRecentAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (next !== confirm) {
      setError("Las contraseñas no coinciden.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await recent.run(() => api.auth.changePassword(current, next));
      setCurrent("");
      setNext("");
      setConfirm("");
      toast.success("Contraseña actualizada", {
        description:
          "Las demás sesiones se han revocado según la política de seguridad.",
      });
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "No se pudo cambiar la contraseña.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="settings-page">
      <section className="page-heading">
        <div>
          <div className="eyebrow">Cuenta</div>
          <h1>Seguridad</h1>
          <p>Actualiza las credenciales sin almacenarlas en el navegador.</p>
        </div>
        <ShieldCheck size={30} />
      </section>
      <SettingsHeader active="security" />
      <section className="settings-section">
        <header>
          <h2>Cambiar contraseña</h2>
          <p>Usa una frase larga, única y no reutilizada.</p>
        </header>
        <form className="security-form" onSubmit={submit}>
          <label className="field">
            <span>Contraseña actual</span>
            <input
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(event) => setCurrent(event.target.value)}
              required
            />
          </label>
          <label className="field">
            <span>Nueva contraseña</span>
            <input
              type="password"
              autoComplete="new-password"
              value={next}
              onChange={(event) => setNext(event.target.value)}
              required
            />
          </label>
          <label className="field">
            <span>Repite la nueva contraseña</span>
            <input
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
              required
            />
          </label>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <AsyncActionButton className="vector-primary" type="submit" loading={busy}>
            <KeyRound size={16} />
            {busy ? "Actualizando…" : "Cambiar contraseña"}
          </AsyncActionButton>
        </form>
      </section>
    </div>
  );
}

export function SessionsSettings() {
  const auth = useAuth();
  const recent = useRecentAuth();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmOthers, setConfirmOthers] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSessions((await api.auth.sessions()).items);
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "No se pudieron cargar las sesiones.",
      );
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);
  async function revoke(item: Session) {
    await recent.run(() => api.auth.revokeSession(item.id));
    if (item.current) {
      await auth.refresh();
      return;
    }
    await load();
    toast.success("Sesión revocada");
  }
  async function revokeOthers() {
    await recent.run(() => api.auth.revokeOthers());
    setConfirmOthers(false);
    await load();
    toast.success("Las demás sesiones se han cerrado");
  }
  return (
    <div className="settings-page">
      <section className="page-heading">
        <div>
          <div className="eyebrow">Cuenta</div>
          <h1>Sesiones activas</h1>
          <p>Revisa dónde está abierta tu cuenta y revoca accesos.</p>
        </div>
      </section>
      <SettingsHeader active="sessions" />
      <section className="settings-section">
        <header>
          <h2>Dispositivos conectados</h2>
          <p>Las fechas proceden del registro seguro de sesiones.</p>
        </header>
        {loading ? (
          <p role="status">Cargando sesiones…</p>
        ) : error ? (
          <div className="inline-error" role="alert">
            {error}
            <button onClick={() => void load()}>Reintentar</button>
          </div>
        ) : (
          <div className="session-list">
            {sessions.map((item) => (
              <article key={item.id}>
                <span className="session-icon">
                  <Laptop size={19} />
                </span>
                <div>
                  <strong>
                    {item.current ? "Este dispositivo" : "Sesión de Oracle"}
                  </strong>
                  <small>
                    Iniciada{" "}
                    {new Intl.DateTimeFormat("es-ES", {
                      dateStyle: "medium",
                      timeStyle: "short",
                    }).format(new Date(item.created_at))}
                  </small>
                  <small>
                    Caduca{" "}
                    {new Intl.DateTimeFormat("es-ES", {
                      dateStyle: "medium",
                      timeStyle: "short",
                    }).format(new Date(item.expires_at))}
                  </small>
                </div>
                {item.current && <span className="status active">Actual</span>}
                <AsyncActionButton
                  className="vector-secondary danger-outline"
                  onClick={() => void revoke(item)}
                  aria-label={`Revocar ${item.current ? "sesión actual" : "sesión"}`}
                >
                  <Trash2 size={15} />
                  Revocar
                </AsyncActionButton>
              </article>
            ))}
          </div>
        )}
        <div className="session-actions">
          {confirmOthers ? (
            <>
              <span>¿Cerrar todas las demás sesiones?</span>
              <AsyncActionButton
                className="vector-danger"
                onClick={() => void revokeOthers()}
              >
                Confirmar
              </AsyncActionButton>
              <button
                className="vector-secondary"
                onClick={() => setConfirmOthers(false)}
              >
                Cancelar
              </button>
            </>
          ) : (
            <button
              className="vector-secondary"
              onClick={() => setConfirmOthers(true)}
            >
              <LogOut size={15} />
              Cerrar las demás sesiones
            </button>
          )}
        </div>
      </section>
    </div>
  );
}
