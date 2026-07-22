"use client";

import * as Popover from "@radix-ui/react-popover";
import {
  ApiError,
  api,
  type NotificationPreference,
  type OracleNotification,
} from "@oracle/api-client";
import {
  Bell,
  BellRing,
  CheckCheck,
  ChevronRight,
  Inbox,
  Settings2,
  Trash2,
  X,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { AsyncActionButton } from "@/components/ui/async-action-button";
import {
  formatDateTime,
  notificationSeverityLabel,
  safeProductLink,
} from "./reporting-utils";

const typeLabel: Record<string, string> = {
  "*": "Todas las notificaciones",
  "report.ready": "Informes disponibles",
  "export.ready": "Exportaciones disponibles",
  "security.password_changed": "Cambio de contraseña",
  "security.session_revoked": "Sesión revocada",
  "security.suspicious_login": "Acceso sospechoso",
};

const preferenceTypes = Object.keys(typeLabel);
const lockedTypes = new Set([
  "security.password_changed",
  "security.session_revoked",
  "security.suspicious_login",
]);

function NotificationItem({
  item,
  compact = false,
  onOpen,
  onRead,
  onDismiss,
}: {
  item: OracleNotification;
  compact?: boolean;
  onOpen: () => void;
  onRead?: () => void;
  onDismiss?: () => void;
}) {
  return (
    <article
      className={`notification-item severity-${item.severity} ${item.read_at ? "is-read" : "is-unread"}`}
    >
      <button className="notification-open" onClick={onOpen}>
        <span className="notification-severity" aria-label={notificationSeverityLabel[item.severity]} />
        <span>
          <strong>{item.title}</strong>
          {!compact && <p>{item.body}</p>}
          <small>{formatDateTime(item.created_at)}</small>
        </span>
        <ChevronRight size={15} />
      </button>
      {!compact && (
        <footer>
          {!item.read_at && onRead && <AsyncActionButton className="" onClick={onRead}>Marcar como leída</AsyncActionButton>}
          {onDismiss && (
            <AsyncActionButton className="danger-text" onClick={onDismiss}>
              <Trash2 size={13} /> Descartar
            </AsyncActionButton>
          )}
        </footer>
      )}
    </article>
  );
}

export function NotificationBell({
  routeBase = "/app",
}: {
  routeBase?: "/app" | "/concept-a";
}) {
  const router = useRouter();
  const [items, setItems] = useState<OracleNotification[]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [available, setAvailable] = useState(true);

  const load = useCallback(async () => {
    try {
      const result = await api.notifications.list(1, 6);
      setItems(result.data);
      setUnread(result.meta.unread_count);
      setAvailable(true);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 403) setAvailable(false);
    }
  }, []);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    const interval = window.setInterval(() => void load(), 30000);
    const tenantChanged = () => void load();
    window.addEventListener("oracle:tenant-changed", tenantChanged);
    return () => {
      window.clearTimeout(kickoff);
      window.clearInterval(interval);
      window.removeEventListener("oracle:tenant-changed", tenantChanged);
    };
  }, [load]);

  if (!available) return null;

  const openItem = async (item: OracleNotification) => {
    if (!item.read_at) {
      try {
        const updated = await api.notifications.read(item.id);
        setItems((current) => current.map((row) => (row.id === item.id ? updated : row)));
        setUnread((value) => Math.max(0, value - 1));
      } catch {
        toast.error("No se pudo marcar la notificación como leída");
      }
    }
    setOpen(false);
    const link = safeProductLink(item.link);
    if (link) router.push(link);
    else router.push(`${routeBase}/notifications`);
  };

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger
        className="icon-button"
        aria-label={`Notificaciones${unread ? `, ${unread} sin leer` : ""}`}
      >
        <Bell size={18} />
        {unread > 0 && <b>{Math.min(unread, 99)}</b>}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content className="notification-popover" align="end" sideOffset={9}>
          <header>
            <div>
              <strong>Notificaciones</strong>
              <small>{unread ? `${unread} sin leer` : "Todo al día"}</small>
            </div>
            <Popover.Close className="icon-button" aria-label="Cerrar notificaciones">
              <X size={16} />
            </Popover.Close>
          </header>
          <div className="notification-popover-list">
            {items.length ? (
              items.map((item) => (
                <NotificationItem key={item.id} item={item} compact onOpen={() => void openItem(item)} />
              ))
            ) : (
              <div className="notification-popover-empty">
                <Inbox size={22} />
                <span>No hay notificaciones activas.</span>
              </div>
            )}
          </div>
          <footer>
            <Popover.Close asChild>
              <Link href={`${routeBase}/notifications`}>Abrir centro</Link>
            </Popover.Close>
            <Popover.Close asChild>
              <Link href={`${routeBase}/account/notifications`}>
                <Settings2 size={14} /> Preferencias
              </Link>
            </Popover.Close>
          </footer>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

export function NotificationCenter({
  routeBase = "/app",
}: {
  routeBase?: "/app" | "/concept-a";
}) {
  const router = useRouter();
  const [items, setItems] = useState<OracleNotification[]>([]);
  const [unread, setUnread] = useState(0);
  const [filter, setFilter] = useState<"all" | "unread">("all");
  const [severity, setSeverity] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const result = await api.notifications.list(1, 100);
      setItems(result.data);
      setUnread(result.meta.unread_count);
    } catch {
      setError("No se pudieron cargar las notificaciones.");
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
      items.filter(
        (item) =>
          (filter === "all" || !item.read_at) &&
          (!severity || item.severity === severity),
      ),
    [filter, items, severity],
  );

  const markRead = async (item: OracleNotification) => {
    try {
      const updated = await api.notifications.read(item.id);
      setItems((current) => current.map((row) => (row.id === item.id ? updated : row)));
      if (!item.read_at) setUnread((value) => Math.max(0, value - 1));
    } catch {
      toast.error("No se pudo actualizar la notificación");
    }
  };

  const openItem = async (item: OracleNotification) => {
    if (!item.read_at) await markRead(item);
    const link = safeProductLink(item.link);
    if (link) router.push(link);
  };

  const dismiss = async (item: OracleNotification) => {
    try {
      await api.notifications.dismiss(item.id);
      setItems((current) => current.filter((row) => row.id !== item.id));
      if (!item.read_at) setUnread((value) => Math.max(0, value - 1));
    } catch {
      toast.error("No se pudo descartar la notificación");
    }
  };

  const readAll = async () => {
    try {
      await api.notifications.readAll();
      const now = new Date().toISOString();
      setItems((current) => current.map((item) => ({ ...item, read_at: item.read_at || now })));
      setUnread(0);
      toast.success("Todas las notificaciones están leídas");
    } catch {
      toast.error("No se pudieron marcar todas como leídas");
    }
  };

  return (
    <div className="reporting-page notification-center">
      <header className="page-heading">
        <div>
          <span className="section-kicker">Bandeja personal · {unread} sin leer</span>
          <h1>Centro de notificaciones</h1>
          <p>Eventos persistentes y accionables; los toasts no sustituyen esta bandeja.</p>
        </div>
        <div className="report-library-actions">
          <Link className="vector-secondary" href={`${routeBase}/account/notifications`}>
            <Settings2 size={16} /> Preferencias
          </Link>
          <AsyncActionButton className="vector-primary" disabled={!unread} onClick={() => void readAll()}>
            <CheckCheck size={16} /> Marcar todas como leídas
          </AsyncActionButton>
        </div>
      </header>

      <section className="vector-panel notification-center-panel">
        <header>
          <div className="segmented" aria-label="Filtro de lectura">
            <button aria-pressed={filter === "all"} onClick={() => setFilter("all")}>Todas</button>
            <button aria-pressed={filter === "unread"} onClick={() => setFilter("unread")}>Sin leer ({unread})</button>
          </div>
          <label>
            <span className="sr-only">Filtrar por severidad</span>
            <select value={severity} onChange={(event) => setSeverity(event.target.value)}>
              <option value="">Toda severidad</option>
              {Object.entries(notificationSeverityLabel).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>
        </header>
        {error && (
          <div className="reporting-error" role="alert">
            <strong>Bandeja no disponible</strong><p>{error}</p>
            <button className="vector-secondary" onClick={() => void load()}>Reintentar</button>
          </div>
        )}
        {loading ? (
          <div className="reporting-loading" role="status">Cargando notificaciones…</div>
        ) : !error && !visible.length ? (
          <div className="reporting-empty">
            <BellRing size={28} />
            <strong>{items.length ? "No hay notificaciones con este filtro" : "No hay notificaciones activas"}</strong>
            <p>{items.length ? "Cambia la vista o la severidad." : "Las alertas relevantes aparecerán aquí."}</p>
          </div>
        ) : !error ? (
          <div className="notification-center-list">
            {visible.map((item) => (
              <NotificationItem
                key={item.id}
                item={item}
                onOpen={() => void openItem(item)}
                onRead={() => void markRead(item)}
                onDismiss={() => void dismiss(item)}
              />
            ))}
          </div>
        ) : null}
      </section>
    </div>
  );
}

interface PreferenceForm {
  inApp: boolean;
  email: boolean;
  cadence: "instant" | "daily" | "weekly" | "off";
  timezone: string;
  localTime: string;
  weekday: number;
  quietStart: string;
  quietEnd: string;
  minimumSeverity: string;
}

const defaultForm: PreferenceForm = {
  inApp: true,
  email: false,
  cadence: "instant",
  timezone: "Europe/Madrid",
  localTime: "08:00",
  weekday: 1,
  quietStart: "",
  quietEnd: "",
  minimumSeverity: "info",
};

function formFor(row?: NotificationPreference): PreferenceForm {
  if (!row) return defaultForm;
  return {
    inApp: row.channels.in_app,
    email: row.channels.email,
    cadence: row.digest_cadence,
    timezone: row.timezone,
    localTime: row.local_time || "08:00",
    weekday: row.weekday ?? 1,
    quietStart: row.quiet_hours_start || "",
    quietEnd: row.quiet_hours_end || "",
    minimumSeverity: row.minimum_severity || "info",
  };
}

export function NotificationPreferences() {
  const [rows, setRows] = useState<NotificationPreference[]>([]);
  const [type, setType] = useState("*");
  const [form, setForm] = useState<PreferenceForm>(defaultForm);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const result = await api.notifications.preferences();
      setRows(result.items);
      const current = result.items.find((item) => item.notification_type === type);
      setForm(formFor(current));
    } catch {
      setError("No se pudieron cargar las preferencias.");
    } finally {
      setLoading(false);
    }
  }, [type]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  const current = rows.find((item) => item.notification_type === type);
  const locked = Boolean(current?.security_locked || lockedTypes.has(type));

  const selectType = (next: string) => {
    setType(next);
    setForm(formFor(rows.find((item) => item.notification_type === next)));
    setError(null);
  };

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (Boolean(form.quietStart) !== Boolean(form.quietEnd)) {
      setError("Define tanto el inicio como el fin de las horas silenciosas.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const saved = await api.notifications.updatePreference({
        notification_type: type,
        channels: locked
          ? { in_app: true, email: true }
          : { in_app: form.inApp, email: form.email },
        digest_cadence: locked ? "instant" : form.cadence,
        timezone: form.timezone,
        local_time: form.localTime,
        weekday: form.cadence === "weekly" ? form.weekday : null,
        quiet_hours_start: form.quietStart || null,
        quiet_hours_end: form.quietEnd || null,
        minimum_severity: form.minimumSeverity,
        ...(current ? { version: current.version } : {}),
      });
      setRows((items) => [saved, ...items.filter((item) => item.notification_type !== type)]);
      setForm(formFor(saved));
      toast.success("Preferencias guardadas");
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.problem.detail
          : "No se pudieron guardar las preferencias.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="reporting-page notification-preferences">
      <header className="page-heading">
        <div>
          <span className="section-kicker">Cuenta · canales y digests</span>
          <h1>Preferencias de notificación</h1>
          <p>Controla frecuencia, canal, severidad mínima y horas silenciosas.</p>
        </div>
      </header>
      {loading ? (
        <div className="reporting-loading" role="status">Cargando preferencias…</div>
      ) : (
        <form className="vector-panel notification-preference-form" onSubmit={save}>
          <header>
            <div>
              <span className="section-kicker">Regla personal</span>
              <h2>{typeLabel[type] ?? type}</h2>
            </div>
            <AsyncActionButton className="vector-primary" type="submit" loading={busy}>
              {busy ? "Guardando…" : "Guardar preferencias"}
            </AsyncActionButton>
          </header>
          <div className="preference-layout">
            <nav aria-label="Tipos de notificación">
              {preferenceTypes.map((item) => (
                <button key={item} type="button" className={type === item ? "active" : ""} onClick={() => selectType(item)}>
                  {typeLabel[item]}
                  {lockedTypes.has(item) && <small>Obligatoria</small>}
                </button>
              ))}
            </nav>
            <div className="preference-fields">
              {locked && (
                <div className="preference-locked" role="note">
                  <BellRing size={17} />
                  Las alertas de seguridad se envían al instante por aplicación y correo.
                </div>
              )}
              <fieldset>
                <legend>Canales</legend>
                <label><input type="checkbox" disabled={locked} checked={locked || form.inApp} onChange={(event) => setForm((value) => ({ ...value, inApp: event.target.checked }))}/> Aplicación</label>
                <label><input type="checkbox" disabled={locked} checked={locked || form.email} onChange={(event) => setForm((value) => ({ ...value, email: event.target.checked }))}/> Correo electrónico</label>
              </fieldset>
              <div className="preference-grid">
                <label>
                  Frecuencia
                  <select disabled={locked} value={locked ? "instant" : form.cadence} onChange={(event) => setForm((value) => ({ ...value, cadence: event.target.value as PreferenceForm["cadence"] }))}>
                    <option value="instant">Al instante</option><option value="daily">Digest diario</option><option value="weekly">Digest semanal</option><option value="off">Desactivada</option>
                  </select>
                </label>
                <label>
                  Zona horaria
                  <select value={form.timezone} onChange={(event) => setForm((value) => ({ ...value, timezone: event.target.value }))}>
                    <option value="Europe/Madrid">Europe/Madrid</option><option value="Europe/Lisbon">Europe/Lisbon</option><option value="UTC">UTC</option><option value="America/New_York">America/New_York</option>
                  </select>
                </label>
                <label>
                  Hora del digest
                  <input type="time" required value={form.localTime} onChange={(event) => setForm((value) => ({ ...value, localTime: event.target.value }))}/>
                </label>
                {form.cadence === "weekly" && (
                  <label>
                    Día de la semana
                    <select value={form.weekday} onChange={(event) => setForm((value) => ({ ...value, weekday: Number(event.target.value) }))}>
                      <option value={0}>Lunes</option><option value={1}>Martes</option><option value={2}>Miércoles</option><option value={3}>Jueves</option><option value={4}>Viernes</option><option value={5}>Sábado</option><option value={6}>Domingo</option>
                    </select>
                  </label>
                )}
                <label>
                  Severidad mínima
                  <select disabled={locked} value={form.minimumSeverity} onChange={(event) => setForm((value) => ({ ...value, minimumSeverity: event.target.value }))}>
                    {Object.entries(notificationSeverityLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </label>
                <label>Inicio de horas silenciosas<input type="time" value={form.quietStart} onChange={(event) => setForm((value) => ({ ...value, quietStart: event.target.value }))}/></label>
                <label>Fin de horas silenciosas<input type="time" value={form.quietEnd} onChange={(event) => setForm((value) => ({ ...value, quietEnd: event.target.value }))}/></label>
              </div>
              <p className="reporting-hint">Las horas silenciosas posponen notificaciones no críticas; no eliminan eventos de la bandeja.</p>
              {error && <p className="auth-inline-error" role="alert">{error}</p>}
            </div>
          </div>
        </form>
      )}
    </div>
  );
}
