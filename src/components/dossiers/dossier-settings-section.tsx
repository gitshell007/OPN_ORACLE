"use client";

import { ApiError, api, type BackendDossier, type SignalMonitor } from "@oracle/api-client";
import { Archive, PauseCircle, PlayCircle, RefreshCw, Save } from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { PermissionGate } from "@/components/auth/auth-boundary";
import { productStatusLabel } from "@/lib/product-copy";

const errorText = (reason: unknown, fallback: string) =>
  reason instanceof ApiError ? reason.problem.detail : fallback;

export function DossierSettingsSection({ dossierId }: { dossierId: string }) {
  const [dossier, setDossier] = useState<BackendDossier | null>(null);
  const [monitors, setMonitors] = useState<SignalMonitor[]>([]);
  const [form, setForm] = useState({ title: "", goal: "", description: "", status: "active" });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [monitorsUnavailable, setMonitorsUnavailable] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const resource = await api.dossiers.get(dossierId);
      const monitorResult = await api.signalAvanza
        .monitors(dossierId)
        .then((value) => ({ value, available: true }))
        .catch(() => ({ value: { data: [] as SignalMonitor[] }, available: false }));
      setDossier(resource);
      setForm({
        title: resource.title,
        goal: resource.strategic_goal || "",
        description: resource.description || "",
        status: resource.status,
      });
      setMonitors(monitorResult.value.data);
      setMonitorsUnavailable(!monitorResult.available);
      setError(null);
    } catch (reason) {
      setError(errorText(reason, "No se pudo cargar la configuración."));
    } finally {
      setLoading(false);
    }
  }, [dossierId]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!dossier?.version) return;
    setBusy(true);
    try {
      const updated = await api.dossiers.update(
        dossierId,
        {
          title: form.title.trim(),
          strategic_goal: form.goal.trim(),
          description: form.description.trim(),
          ...(form.status !== dossier.status
            ? { status: form.status as "draft" | "active" | "paused" }
            : {}),
          version: dossier.version,
        },
        dossier.version,
      );
      setDossier(updated);
      setError(null);
      toast.success("Expediente actualizado");
    } catch (reason) {
      setError(errorText(reason, "No se pudieron guardar los cambios."));
    } finally {
      setBusy(false);
    }
  }

  async function actOnMonitor(item: SignalMonitor, action: "pause" | "resume" | "sync") {
    setBusy(true);
    try {
      await api.signalAvanza.action(item.id, action);
      toast.success(action === "sync" ? "Sincronización encolada" : "Monitor actualizado");
      await load();
    } catch (reason) {
      setError(errorText(reason, "No se pudo actualizar el monitor."));
    } finally {
      setBusy(false);
    }
  }

  async function archive() {
    if (!dossier?.version || confirmation !== dossier.title) return;
    setBusy(true);
    try {
      const updated = await api.dossiers.archive(dossierId, dossier.version);
      setDossier(updated);
      setForm((current) => ({ ...current, status: updated.status }));
      setConfirmation("");
      toast.success("Expediente archivado");
    } catch (reason) {
      setError(errorText(reason, "No se pudo archivar el expediente."));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <p className="global-inventory-state" role="status">Cargando configuración…</p>;
  if (!dossier) return <div className="inline-error" role="alert">{error || "Expediente no disponible."}<button onClick={() => void load()}>Reintentar</button></div>;
  const archived = dossier.status === "archived";
  const statusOptions: Record<string, Array<[string, string]>> = {
    draft: [["draft", "Borrador"], ["active", "Activo"]],
    active: [["active", "Activo"], ["paused", "Pausado"]],
    paused: [["paused", "Pausado"], ["active", "Activo"]],
    archived: [["archived", "Archivado"]],
  };
  return (
    <div className="dossier-settings-product">
      <section className="page-heading"><div><div className="eyebrow">Gobierno del expediente</div><h1>Configuración</h1><p>Objetivo, estado, vigilancia y archivo con control de versión.</p></div></section>
      {error && <div className="inline-error" role="alert">{error}<button onClick={() => setError(null)}>Cerrar</button></div>}
      <PermissionGate permission="dossier.write" fallback={<p className="reporting-hint">Configuración en modo lectura por permisos.</p>}>
        <form className="settings-section dossier-settings-form" onSubmit={save}>
          <header><h2>Identidad y objetivo</h2><p>Los tipos siguen siendo transversales y no codifican sectores.</p></header>
          <label className="field"><span>Título</span><input required minLength={2} maxLength={300} value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} disabled={archived} /></label>
          <label className="field full"><span>Objetivo estratégico</span><textarea value={form.goal} onChange={(event) => setForm({ ...form, goal: event.target.value })} disabled={archived} /></label>
          <label className="field full"><span>Descripción</span><textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} disabled={archived} /></label>
          <label className="field"><span>Estado</span><select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })} disabled={archived}>{(statusOptions[dossier.status] ?? [[dossier.status, dossier.status]]).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
          <button className="vector-primary" disabled={busy || archived}><Save size={15} /> Guardar cambios</button>
        </form>
      </PermissionGate>
      <section className="settings-section"><header><h2>Monitores de Signal Avanza</h2><p>Estado deseado y observado permanecen separados.</p></header>{monitorsUnavailable ? <p className="reporting-hint">Los monitores no están disponibles con tus permisos actuales; la configuración general sigue accesible.</p> : monitors.length ? <div className="monitor-settings-list">{monitors.map((item) => <article key={item.id}><div><strong>{item.provider}</strong><span className={`status ${item.status}`}>{productStatusLabel(item.status)}</span><p>{item.last_error || `Última sincronización: ${item.last_synced_at ? new Date(item.last_synced_at).toLocaleString("es-ES") : "pendiente"}`}</p></div><PermissionGate permission="signal.review"><div>{item.status === "paused" ? <button disabled={busy} onClick={() => void actOnMonitor(item, "resume")}><PlayCircle size={14} /> Reanudar</button> : <button disabled={busy} onClick={() => void actOnMonitor(item, "pause")}><PauseCircle size={14} /> Pausar</button>}<button disabled={busy} onClick={() => void actOnMonitor(item, "sync")}><RefreshCw size={14} /> Sincronizar</button></div></PermissionGate></article>)}</div> : <p className="reporting-hint">No hay monitores configurados para este expediente.</p>}<button className="vector-secondary" onClick={() => void load()}><RefreshCw size={14} /> Actualizar</button></section>
      {!archived && <PermissionGate permission="dossier.archive"><section className="settings-section destructive-zone"><header><h2>Archivar expediente</h2><p>Quedará en modo lectura y conservará toda su trazabilidad.</p></header><label className="field"><span>Escribe «{dossier.title}» para confirmar</span><input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label><button className="vector-danger" disabled={busy || confirmation !== dossier.title} onClick={() => void archive()}><Archive size={15} /> Archivar</button></section></PermissionGate>}
    </div>
  );
}
