"use client";

import {
  ApiError,
  api,
  type PlatformBackup,
  type PlatformBackupList,
} from "@oracle/api-client";
import {
  AlertTriangle,
  ArchiveRestore,
  DatabaseBackup,
  HardDrive,
  RefreshCw,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { useRecentAuth } from "@/components/auth/recent-auth";

const EMPTY: PlatformBackupList = {
  items: [],
  operations: [],
  retention_days: 30,
  storage_path: "No disponible",
};

function formatBytes(value: number | null): string {
  if (value === null) return "Pendiente";
  if (value === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const unit = Math.min(Math.floor(Math.log(value) / Math.log(1024)), 4);
  return `${(value / 1024 ** unit).toLocaleString("es-ES", { maximumFractionDigits: 1 })} ${units[unit]}`;
}

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString("es-ES") : "—";
}

function statusLabel(status: PlatformBackup["status"]): string {
  return {
    available: "Disponible",
    expired: "Caducada",
    missing: "No localizada",
  }[status];
}

function operationLabel(value: PlatformBackupList["operations"][number]): string {
  const kind = {
    manual_backup: "Copia manual",
    scheduled_backup: "Copia programada",
    restore: "Recuperación",
  }[value.operation_type];
  const status = {
    queued: "Pendiente del operador",
    awaiting_approval: "Pendiente de aprobación root",
    running: "En curso",
    succeeded: "Completada",
    failed: "Fallida",
    cancelled: "Cancelada",
  }[value.status];
  return `${kind} · ${status}`;
}

export function PlatformBackups() {
  const recent = useRecentAuth();
  const [data, setData] = useState<PlatformBackupList>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [restore, setRestore] = useState<PlatformBackup | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [restoring, setRestoring] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api.platform.backups());
      setError(null);
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "No se pudieron cargar las copias de seguridad.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  async function createBackup() {
    setCreating(true);
    try {
      await recent.run(() => api.platform.createBackup());
      toast.success("Copia de seguridad solicitada");
      await load();
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "No se pudo solicitar la copia de seguridad.",
      );
    } finally {
      setCreating(false);
    }
  }

  function openRestore(item: PlatformBackup) {
    setRestore(item);
    setConfirmation("");
  }

  function closeRestore() {
    if (restoring) return;
    setRestore(null);
    setConfirmation("");
  }

  async function submitRestore(event: FormEvent) {
    event.preventDefault();
    if (!restore) return;
    const required = `RECUPERAR ${restore.backup_name}`;
    if (confirmation !== required) return;
    setRestoring(true);
    try {
      await recent.run(() =>
        api.platform.restoreBackup(restore.id, confirmation),
      );
      toast.success("Recuperación solicitada", {
        description:
          "Queda pendiente de aprobación por un operador root durante una ventana de mantenimiento.",
      });
      setRestore(null);
      setConfirmation("");
      await load();
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "No se pudo solicitar la recuperación.",
      );
    } finally {
      setRestoring(false);
    }
  }

  return (
    <div className="platform-page">
      <header className="admin-heading">
        <div>
          <p className="eyebrow">Continuidad de plataforma</p>
          <h1>Copias de seguridad</h1>
          <p>
            Una copia diaria, conservación durante {data.retention_days} días y
            recuperación auditada para superadministradores.
          </p>
        </div>
        <button
          className="platform-primary"
          disabled={creating}
          onClick={() => void createBackup()}
        >
          {creating ? <RefreshCw className="spin" size={16} /> : <DatabaseBackup size={16} />}
          {creating ? "Solicitando…" : "Crear copia ahora"}
        </button>
      </header>

      {error && (
        <div className="inline-error" role="alert">
          {error}
          <button onClick={() => setError(null)}>Cerrar</button>
        </div>
      )}

      <section className="platform-summary" aria-label="Política de copias">
        <article>
          <span>Programación</span>
          <strong>Diaria</strong>
        </article>
        <article>
          <span>Retención</span>
          <strong>{data.retention_days} días</strong>
        </article>
        <article>
          <span>Carpeta del servidor</span>
          <strong className="backup-path" title={data.storage_path}>
            <HardDrive size={15} /> {data.storage_path}
          </strong>
        </article>
      </section>

      <section className="admin-table-card">
        {loading ? (
          <p role="status">Cargando copias de seguridad…</p>
        ) : data.items.length === 0 ? (
          <div className="empty-admin">
            <DatabaseBackup size={30} />
            <strong>No hay copias disponibles</strong>
            <span>La primera copia aparecerá al finalizar su creación.</span>
          </div>
        ) : (
          <div className="table-scroll">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Creación</th>
                  <th>Origen</th>
                  <th>Estado</th>
                  <th>Tamaño</th>
                  <th>Caducidad</th>
                  <th>Acción</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <strong>{formatDate(item.backup_created_at)}</strong>
                      <small title={item.backup_name}>{item.backup_name}</small>
                    </td>
                    <td>{item.origin === "scheduled" ? "Programada" : item.origin === "manual" ? "Manual" : "Importada"}</td>
                    <td>
                      <span className={`status backup-${item.status}`}>
                        {statusLabel(item.status)}
                      </span>
                    </td>
                    <td>{formatBytes(item.size_bytes)}</td>
                    <td>{formatDate(item.expires_at)}</td>
                    <td>
                      <button
                        className="platform-icon-action"
                        disabled={item.status !== "available"}
                        onClick={() => openRestore(item)}
                      >
                        <ArchiveRestore size={16} />
                        Recuperar
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {data.operations.length > 0 && (
        <section className="admin-table-card" aria-labelledby="backup-operations-title">
          <h2 id="backup-operations-title" className="backup-section-title">
            Operaciones recientes
          </h2>
          <div className="table-scroll">
            <table className="admin-table">
              <thead><tr><th>Solicitud</th><th>Estado</th><th>Finalización</th><th>Incidencia</th></tr></thead>
              <tbody>
                {data.operations.map((operation) => (
                  <tr key={operation.operation_id}>
                    <td>{formatDate(operation.created_at)}</td>
                    <td>{operationLabel(operation)}</td>
                    <td>{formatDate(operation.finished_at)}</td>
                    <td>{operation.error_code ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {restore && (
        <div className="backup-dialog-backdrop" role="presentation">
          <section
            aria-describedby="restore-description"
            aria-labelledby="restore-title"
            aria-modal="true"
            className="backup-dialog"
            role="dialog"
          >
            <header>
              <span className="backup-warning-icon"><AlertTriangle size={22} /></span>
              <div>
                <h2 id="restore-title">Recuperar esta copia</h2>
                <p id="restore-description">
                  Esta solicitud no restaura datos automáticamente. Un operador
                  root deberá aprobarla y ejecutarla durante una ventana de
                  mantenimiento; la recuperación reemplazará los datos actuales
                  y puede interrumpir temporalmente el servicio. La acción quedará
                  auditada.
                </p>
              </div>
            </header>
            <dl className="backup-restore-details">
              <div><dt>Copia</dt><dd>{restore.backup_name}</dd></div>
              <div><dt>Creada</dt><dd>{formatDate(restore.backup_created_at)}</dd></div>
              <div><dt>Checksum</dt><dd><code>{restore.sha256}</code></dd></div>
            </dl>
            <form onSubmit={submitRestore}>
              <label className="field">
                <span>
                  Escribe <strong>RECUPERAR {restore.backup_name}</strong> para confirmar
                </span>
                <input
                  autoComplete="off"
                  autoFocus
                  value={confirmation}
                  onChange={(event) => setConfirmation(event.target.value)}
                />
              </label>
              <div className="backup-dialog-actions">
                <button type="button" onClick={closeRestore} disabled={restoring}>
                  Cancelar
                </button>
                <button
                  className="backup-danger"
                  disabled={confirmation !== `RECUPERAR ${restore.backup_name}` || restoring}
                  type="submit"
                >
                  {restoring ? "Solicitando…" : "Solicitar recuperación"}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}
