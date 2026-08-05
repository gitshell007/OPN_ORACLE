"use client";

import {
  ApiError,
  api,
  type BackendDossier,
  type CreateSignalMonitorInput,
  type SignalConnection,
  type SignalMonitor,
  type SignalMonitorSourceType,
  type DossierMemoryProfile,
} from "@oracle/api-client";
import { Archive, CirclePlus, PauseCircle, PlayCircle, RefreshCw, Save } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { PermissionGate } from "@/components/auth/auth-boundary";
import { DossierCollaboratorsPanel } from "@/components/dossiers/dossier-collaborators-panel";
import { DossierProfilePanel } from "@/components/dossiers/dossier-profile-panel";
import { AsyncActionButton } from "@/components/ui/async-action-button";
import { EuCountryMultiSelect } from "@/components/ui/eu-country-multiselect";
import { PageHeader } from "@/components/ui/page-header";
import {
  draftFromProfileConfig,
  profileConfigFromDraft,
  type ProfileDraft,
} from "@/lib/dossier-profile";
import { productStatusLabel } from "@/lib/product-copy";

const errorText = (reason: unknown, fallback: string) =>
  reason instanceof ApiError ? reason.problem.detail : fallback;

const safeSourceTypes: Array<{ value: SignalMonitorSourceType; label: string; hint: string }> = [
  { value: "news", label: "Noticias", hint: "Medios y publicaciones especializadas" },
  { value: "company_signal", label: "Actividad corporativa", hint: "Webs y comunicados de organizaciones" },
  { value: "official_publication", label: "Publicaciones oficiales", hint: "Boletines y diarios oficiales" },
  { value: "regulatory_signal", label: "Regulación", hint: "Normativa, consultas y reguladores" },
  { value: "social_signal", label: "Redes y foros", hint: "Conversación pública y menciones sociales" },
];

type MonitorDraft = {
  connection_id: string;
  name: string;
  query: string;
  keywords: string;
  entities: string;
  cadence: CreateSignalMonitorInput["cadence"];
  source_types: SignalMonitorSourceType[];
  languages: string;
  geographies: string;
  retention_days: number;
};

const initialMonitorDraft = (): MonitorDraft => ({
  connection_id: "",
  name: "",
  query: "",
  keywords: "",
  entities: "",
  cadence: "daily",
  source_types: ["news", "company_signal", "official_publication"],
  languages: "es",
  geographies: "ES",
  retention_days: 90,
});

function commaSeparated(value: string) {
  return [...new Set(value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean))].slice(0, 30);
}

export function DossierSettingsSection({ dossierId }: { dossierId: string }) {
  const searchParams = useSearchParams();
  const [dossier, setDossier] = useState<BackendDossier | null>(null);
  const [monitors, setMonitors] = useState<SignalMonitor[]>([]);
  const [connections, setConnections] = useState<SignalConnection[]>([]);
  const [form, setForm] = useState({ title: "", goal: "", description: "", status: "active" });
  const [monitorForm, setMonitorForm] = useState<MonitorDraft>(initialMonitorDraft);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [monitorsUnavailable, setMonitorsUnavailable] = useState(false);
  const [memoryProfile, setMemoryProfile] = useState<DossierMemoryProfile | null>(null);
  const [memoryBusy, setMemoryBusy] = useState(false);
  const [memoryError, setMemoryError] = useState<string | null>(null);
  const [profileDraft, setProfileDraft] = useState<ProfileDraft | null>(null);
  const [profileBusy, setProfileBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const resource = await api.dossiers.get(dossierId);
      const monitorResult = await api.signalAvanza
        .monitors(dossierId)
        .then((value) => ({ value, available: true }))
        .catch(() => ({ value: { data: [] as SignalMonitor[] }, available: false }));
      const connectionResult = await api.signalAvanza
        .connections()
        .then((value) => ({ value, available: true }))
        .catch(() => ({ value: { items: [] as SignalConnection[] }, available: false }));
      const activeConnections = connectionResult.value.items.filter(
        (connection) => connection.status === "active",
      );
      setDossier(resource);
      setForm({
        title: resource.title,
        goal: resource.strategic_goal || "",
        description: resource.description || "",
        status: resource.status,
      });
      setProfileDraft(
        draftFromProfileConfig(resource.dossier_type, resource.profile_config ?? null),
      );
      setMonitors(monitorResult.value.data);
      setMonitorsUnavailable(!monitorResult.available);
      setConnections(activeConnections);
      try {
        const mem = await api.dossierMemory.getEffective(dossierId);
        setMemoryProfile(mem);
        setMemoryError(null);
      } catch (reason) {
        setMemoryError(errorText(reason, "No se pudo cargar la memoria del expediente."));
      }
      setMonitorForm((current) =>
        current.connection_id && activeConnections.some((item) => item.id === current.connection_id)
          ? current
          : { ...current, connection_id: activeConnections[0]?.id ?? "" },
      );
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

  useEffect(() => {
    if (loading || searchParams?.get("wizard_prefill") !== "monitor") return;
    const key = `oracle:wizard-prefill:${dossierId}:monitor`;
    const raw = sessionStorage.getItem(key);
    if (!raw) return;
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      try {
        const value = JSON.parse(raw) as Record<string, unknown>;
        setMonitorForm((current) => ({
          ...current,
          name: typeof value.name === "string" ? value.name : current.name,
          query: typeof value.query === "string" ? value.query : current.query,
          keywords: Array.isArray(value.keywords)
            ? value.keywords.map(String).join(", ")
            : current.keywords,
          entities: Array.isArray(value.entities)
            ? value.entities.map(String).join(", ")
            : current.entities,
          source_types: Array.isArray(value.source_types)
            ? value.source_types
                .map(String)
                .filter((item): item is SignalMonitorSourceType =>
                  safeSourceTypes.some((source) => source.value === item),
                )
            : current.source_types,
          languages: Array.isArray(value.languages)
            ? value.languages.map(String).join(", ")
            : current.languages,
          geographies: Array.isArray(value.geographies)
            ? value.geographies.map(String).join(", ")
            : current.geographies,
          cadence:
            value.cadence === "hourly" || value.cadence === "weekly"
              ? value.cadence
              : value.cadence === "daily"
                ? "daily"
                : current.cadence,
        }));
        sessionStorage.removeItem(key);
      } catch {
        sessionStorage.removeItem(key);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [dossierId, loading, searchParams]);

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
      setProfileDraft(
        draftFromProfileConfig(updated.dossier_type, updated.profile_config ?? null),
      );
      setError(null);
      toast.success("Expediente actualizado");
    } catch (reason) {
      setError(errorText(reason, "No se pudieron guardar los cambios."));
    } finally {
      setBusy(false);
    }
  }

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    if (!dossier?.version || !profileDraft) return;
    setProfileBusy(true);
    try {
      const updated = await api.dossiers.update(
        dossierId,
        {
          profile_config: profileConfigFromDraft(profileDraft) as NonNullable<
            Parameters<typeof api.dossiers.update>[1]["profile_config"]
          >,
          version: dossier.version,
        },
        dossier.version,
      );
      setDossier(updated);
      setProfileDraft(
        draftFromProfileConfig(updated.dossier_type, updated.profile_config ?? null),
      );
      setError(null);
      toast.success("Perfil del expediente actualizado");
    } catch (reason) {
      setError(errorText(reason, "No se pudo guardar el perfil del expediente."));
    } finally {
      setProfileBusy(false);
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

  async function createMonitor(event: FormEvent) {
    event.preventDefault();
    const keywords = commaSeparated(monitorForm.keywords);
    const entities = commaSeparated(monitorForm.entities);
    if (!monitorForm.connection_id || !monitorForm.name.trim()) return;
    if (!monitorForm.query.trim() && keywords.length === 0 && entities.length === 0) {
      setError("Define al menos una consulta, palabras clave o entidades a vigilar.");
      return;
    }
    if (monitorForm.source_types.length === 0) {
      setError("Selecciona al menos un tipo de fuente.");
      return;
    }
    setBusy(true);
    try {
      await api.signalAvanza.createMonitor(dossierId, {
        connection_id: monitorForm.connection_id,
        name: monitorForm.name.trim(),
        query: monitorForm.query.trim(),
        keywords,
        entities: entities.map((name) => ({ type: "company", name })),
        cadence: monitorForm.cadence,
        source_types: monitorForm.source_types,
        languages: commaSeparated(monitorForm.languages).map((item) => item.toLowerCase()),
        geographies: commaSeparated(monitorForm.geographies).map((item) => item.toUpperCase()),
        retention_days: monitorForm.retention_days,
      });
      setMonitorForm((current) => ({
        ...initialMonitorDraft(),
        connection_id: current.connection_id,
      }));
      setError(null);
      toast.success("Monitor creado y preparado para la primera sincronización");
      await load();
    } catch (reason) {
      setError(errorText(reason, "No se pudo crear el monitor."));
    } finally {
      setBusy(false);
    }
  }

  function toggleSourceType(sourceType: SignalMonitorSourceType) {
    setMonitorForm((current) => ({
      ...current,
      source_types: current.source_types.includes(sourceType)
        ? current.source_types.filter((item) => item !== sourceType)
        : [...current.source_types, sourceType],
    }));
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

  async function saveMemoryProfile() {
    if (!memoryProfile?.etag) return;
    setMemoryBusy(true);
    try {
      const updated = await api.dossierMemory.putProfile(
        dossierId,
        {
          mode: memoryProfile.mode,
          sources: memoryProfile.sources,
          kinds: memoryProfile.kinds,
          classifications_allowed: memoryProfile.classifications_allowed,
          token_budget: memoryProfile.token_budget,
          limit: memoryProfile.limit,
        },
        memoryProfile.etag,
      );
      setMemoryProfile(updated);
      setMemoryError(null);
      toast.success("Memoria del expediente actualizada");
    } catch (reason) {
      setMemoryError(errorText(reason, "No se pudo guardar la memoria del expediente."));
    } finally {
      setMemoryBusy(false);
    }
  }

  async function testMemoryConnection() {
    setMemoryBusy(true);
    try {
      const result = await api.dossierMemory.testConnection(dossierId);
      if (result.ok) {
        toast.success(
          result.synthetic
            ? "Prueba sintética (mock) correcta"
            : "Conexión de memoria correcta",
        );
      } else {
        toast.error(result.message || `Prueba fallida: ${result.status}`);
      }
      const mem = await api.dossierMemory.getEffective(dossierId);
      setMemoryProfile(mem);
      setMemoryError(null);
    } catch (reason) {
      setMemoryError(errorText(reason, "No se pudo probar la conexión de memoria."));
    } finally {
      setMemoryBusy(false);
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
    <div className="dossier-settings-product dossier-section-page">
      <PageHeader
        eyebrow="Gestión del expediente"
        title="Configuración"
        description="Define el objetivo, el estado, lo que quieres vigilar y cuándo archivarlo."
      />
      {error && <div className="inline-error" role="alert">{error}<button onClick={() => setError(null)}>Cerrar</button></div>}
      <PermissionGate permission="dossier.write" fallback={<p className="reporting-hint">Configuración en modo lectura por permisos.</p>}>
        <form className="settings-section dossier-settings-form" onSubmit={save}>
          <header><h2>Datos principales</h2><p>Identifican el expediente y en qué punto de avance está.</p></header>
          <label className="field"><span>Título</span><input required minLength={2} maxLength={300} value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} disabled={archived} /></label>
          <label className="field"><span>Estado</span><select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })} disabled={archived}>{(statusOptions[dossier.status] ?? [[dossier.status, dossier.status]]).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
          <label className="field full"><span>Objetivo estratégico</span><textarea value={form.goal} onChange={(event) => setForm({ ...form, goal: event.target.value })} disabled={archived} /></label>
          <label className="field full"><span>Descripción</span><textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} disabled={archived} /></label>
          <div className="settings-actions"><AsyncActionButton className="vector-primary" type="submit" disabled={archived} loading={busy}><Save size={15} /> Guardar cambios</AsyncActionButton></div>
        </form>
      </PermissionGate>
      <PermissionGate
        permission="dossier.write"
        fallback={
          <DossierProfilePanel
            dossierId={dossierId}
            dossierType={dossier.dossier_type}
            profileConfig={dossier.profile_config}
            draft={profileDraft}
            onDraftChange={setProfileDraft}
            onSave={(event) => event.preventDefault()}
            readOnly
          />
        }
      >
        <DossierProfilePanel
          dossierId={dossierId}
          dossierType={dossier.dossier_type}
          profileConfig={dossier.profile_config}
          draft={profileDraft}
          onDraftChange={setProfileDraft}
          onSave={(event) => void saveProfile(event)}
          busy={profileBusy}
          disabled={archived}
        />
      </PermissionGate>
      <DossierCollaboratorsPanel dossierId={dossierId} disabled={archived} />
      <section className="settings-section"><header><h2>Vigilancia de fuentes</h2><p>Define qué quieres seguir y comprueba si la conexión está funcionando.</p></header>
        {!archived && <PermissionGate permission="signal.review">
          <form className="dossier-monitor-create" onSubmit={createMonitor}>
            <div className="dossier-monitor-create-heading"><CirclePlus size={17} aria-hidden="true" /><div><h3>Nueva vigilancia</h3><p>Define qué vigilar y enviaremos la configuración a Signal Avanza.</p></div></div>
            <label className="field"><span>Conexión activa</span><select required value={monitorForm.connection_id} onChange={(event) => setMonitorForm({ ...monitorForm, connection_id: event.target.value })} disabled={busy || connections.length === 0}><option value="">Selecciona una conexión</option>{connections.map((connection) => <option key={connection.id} value={connection.id}>{connection.name}</option>)}</select></label>
            <label className="field"><span>Nombre de la vigilancia</span><input required maxLength={200} value={monitorForm.name} onChange={(event) => setMonitorForm({ ...monitorForm, name: event.target.value })} placeholder="Ej. Competencia y regulación" disabled={busy || connections.length === 0} /></label>
            <label className="field full"><span>Consulta principal (opcional)</span><input value={monitorForm.query} onChange={(event) => setMonitorForm({ ...monitorForm, query: event.target.value })} placeholder="Ej. almacenamiento energético España" disabled={busy || connections.length === 0} /><small>Puedes dejarla vacía si defines palabras clave o entidades: la vigilancia se construye a partir de ellas.</small></label>
            <label className="field"><span>Palabras clave</span><textarea value={monitorForm.keywords} onChange={(event) => setMonitorForm({ ...monitorForm, keywords: event.target.value })} placeholder="baterías, subvenciones, almacenamiento" disabled={busy || connections.length === 0} /><small>Separadas por comas o líneas.</small></label>
            <label className="field"><span>Competidores y entidades</span><textarea value={monitorForm.entities} onChange={(event) => setMonitorForm({ ...monitorForm, entities: event.target.value })} placeholder="Empresa A, Organismo B" disabled={busy || connections.length === 0} /><small>Se guardarán como organizaciones vigiladas.</small></label>
            <label className="field"><span>Cadencia</span><select value={monitorForm.cadence} onChange={(event) => setMonitorForm({ ...monitorForm, cadence: event.target.value as MonitorDraft["cadence"] })} disabled={busy || connections.length === 0}><option value="hourly">Cada hora</option><option value="daily">Diaria</option><option value="weekly">Semanal</option></select></label>
            <label className="field"><span>Conservación</span><select value={monitorForm.retention_days} onChange={(event) => setMonitorForm({ ...monitorForm, retention_days: Number(event.target.value) })} disabled={busy || connections.length === 0}><option value={30}>30 días</option><option value={90}>90 días</option><option value={180}>180 días</option><option value={365}>365 días</option></select></label>
            <label className="field"><span>Idiomas</span><input value={monitorForm.languages} onChange={(event) => setMonitorForm({ ...monitorForm, languages: event.target.value })} placeholder="es, en" disabled={busy || connections.length === 0} /><small>Códigos ISO separados por comas.</small></label>
            <EuCountryMultiSelect
              label="Ámbitos geográficos (UE)"
              value={commaSeparated(monitorForm.geographies).map((item) => item.toUpperCase())}
              onChange={(next) => setMonitorForm({ ...monitorForm, geographies: next.join(", ") })}
              disabled={busy || connections.length === 0}
              hint="España y Alemania son los mercados prioritarios ahora mismo."
            />
            <fieldset className="monitor-source-types full" disabled={busy || connections.length === 0}><legend>Fuentes a vigilar</legend><p>Solo se muestran fuentes compatibles y verificadas con Signal Avanza.</p><div>{safeSourceTypes.map((source) => <label key={source.value}><input type="checkbox" checked={monitorForm.source_types.includes(source.value)} onChange={() => toggleSourceType(source.value)} /><span><strong>{source.label}</strong><small>{source.hint}</small></span></label>)}</div></fieldset>
            {connections.length === 0 && <p className="monitor-create-notice full" role="status">No hay una conexión activa disponible. Pide a la administración de tu organización que active Signal Avanza.</p>}
            <div className="settings-actions"><AsyncActionButton className="vector-primary" type="submit" disabled={connections.length === 0} loading={busy}><CirclePlus size={15} /> Crear vigilancia</AsyncActionButton></div>
          </form>
        </PermissionGate>}
        {monitorsUnavailable ? <p className="reporting-hint">No puedes consultar las vigilancias con tus permisos actuales; el resto de la configuración sigue disponible.</p> : monitors.length ? <div className="monitor-settings-list">{monitors.map((item) => <article key={item.id}><div><strong>{item.name || "Vigilancia sin nombre"}</strong><span className={`status ${item.status}`}>{productStatusLabel(item.status)}</span><p>{item.last_error || `Conexión: ${connections.find((connection) => connection.id === item.connection_id)?.name || item.provider} · Última sincronización: ${item.last_synced_at ? new Date(item.last_synced_at).toLocaleString("es-ES") : "pendiente"}`}</p></div><PermissionGate permission="signal.review"><div>{item.status === "paused" ? <AsyncActionButton className="" loading={busy} onClick={() => void actOnMonitor(item, "resume")}><PlayCircle size={14} /> Reanudar</AsyncActionButton> : <AsyncActionButton className="" loading={busy} onClick={() => void actOnMonitor(item, "pause")}><PauseCircle size={14} /> Pausar</AsyncActionButton>}<AsyncActionButton className="" loading={busy} onClick={() => void actOnMonitor(item, "sync")}><RefreshCw size={14} /> Sincronizar</AsyncActionButton></div></PermissionGate></article>)}</div> : <p className="reporting-hint">Todavía no hay vigilancias configuradas para este expediente.</p>}<button className="vector-secondary" onClick={() => void load()}><RefreshCw size={14} /> Actualizar</button></section>
      <section className="settings-section" data-testid="dossier-memory-settings">
        <header>
          <h2>Memoria del expediente</h2>
          <p>Controla si Signal aporta contexto de memoria a este expediente. No se muestran secretos, proveedores ni modelos.</p>
        </header>
        {memoryError && (
          <div className="inline-error" role="alert">
            {memoryError}
            <button type="button" onClick={() => setMemoryError(null)}>
              Cerrar
            </button>
          </div>
        )}
        {!memoryProfile ? (
          <p className="reporting-hint" role="status">
            Configuración de memoria no disponible.
          </p>
        ) : (
          <PermissionGate
            permission="dossier.write"
            fallback={
              <p className="reporting-hint">
                Memoria en modo lectura. Estado:{" "}
                {memoryProfile.mode === "disabled"
                  ? "Desactivada"
                  : memoryProfile.mode === "shadow"
                    ? "Solo observar"
                    : "Usar para responder"}
                {memoryProfile.last_test_status
                  ? ` · Última prueba: ${memoryProfile.last_test_status}`
                  : ""}
                {memoryProfile.publisher_reliable === false ? " · Degradado" : ""}
              </p>
            }
          >
            <form
              className="dossier-memory-form"
              onSubmit={(event) => {
                event.preventDefault();
                void saveMemoryProfile();
              }}
            >
              <label className="field">
                <span>Modo</span>
                <select
                  value={memoryProfile.mode}
                  disabled={memoryBusy || archived}
                  onChange={(event) =>
                    setMemoryProfile({
                      ...memoryProfile,
                      mode: event.target.value as DossierMemoryProfile["mode"],
                    })
                  }
                >
                  <option value="disabled">Desactivada</option>
                  <option value="shadow">Solo observar</option>
                  <option value="augment">Usar para responder</option>
                </select>
              </label>
              <p className="reporting-hint" role="status">
                Versión {memoryProfile.version}
                {memoryProfile.persisted === false ? " · defaults no persistidos" : ""}
                {memoryProfile.last_test_status
                  ? ` · Última prueba: ${memoryProfile.last_test_status}`
                  : " · Sin prueba reciente"}
                {memoryProfile.last_error ? ` · Error: ${memoryProfile.last_error}` : ""}
                {memoryProfile.publisher_reliable === false || memoryProfile.actions_reliable === false
                  ? " · Banner: servicio degradado"
                  : ""}
              </p>
              {memoryProfile.last_coverage && (
                <pre className="reporting-hint" style={{ whiteSpace: "pre-wrap" }}>
                  Cobertura: {JSON.stringify(memoryProfile.last_coverage)}
                </pre>
              )}
              <label className="field">
                <span>Límite de resultados</span>
                <input
                  type="number"
                  min={1}
                  max={100}
                  value={memoryProfile.limit}
                  disabled={memoryBusy || archived}
                  onChange={(event) =>
                    setMemoryProfile({
                      ...memoryProfile,
                      limit: Number(event.target.value) || 1,
                    })
                  }
                />
              </label>
              <label className="field">
                <span>Presupuesto de tokens</span>
                <input
                  type="number"
                  min={0}
                  max={128000}
                  value={memoryProfile.token_budget}
                  disabled={memoryBusy || archived}
                  onChange={(event) =>
                    setMemoryProfile({
                      ...memoryProfile,
                      token_budget: Number(event.target.value) || 0,
                    })
                  }
                />
              </label>
              <label className="field full">
                <span>Fuentes (coma)</span>
                <input
                  value={(memoryProfile.sources || []).join(", ")}
                  disabled={memoryBusy || archived}
                  onChange={(event) =>
                    setMemoryProfile({
                      ...memoryProfile,
                      sources: event.target.value
                        .split(",")
                        .map((s) => s.trim())
                        .filter(Boolean),
                    })
                  }
                />
              </label>
              <label className="field full">
                <span>Kinds (coma)</span>
                <input
                  value={(memoryProfile.kinds || []).join(", ")}
                  disabled={memoryBusy || archived}
                  onChange={(event) =>
                    setMemoryProfile({
                      ...memoryProfile,
                      kinds: event.target.value
                        .split(",")
                        .map((s) => s.trim())
                        .filter(Boolean),
                    })
                  }
                />
              </label>
              <label className="field full">
                <span>Clasificaciones permitidas (coma)</span>
                <input
                  value={(memoryProfile.classifications_allowed || []).join(", ")}
                  disabled={memoryBusy || archived}
                  onChange={(event) =>
                    setMemoryProfile({
                      ...memoryProfile,
                      classifications_allowed: event.target.value
                        .split(",")
                        .map((s) => s.trim())
                        .filter(Boolean),
                    })
                  }
                />
              </label>
              <div className="settings-actions">
                <AsyncActionButton
                  className="vector-primary"
                  type="submit"
                  disabled={archived}
                  loading={memoryBusy}
                >
                  <Save size={15} /> Guardar memoria
                </AsyncActionButton>
                <AsyncActionButton
                  className="vector-secondary"
                  type="button"
                  disabled={archived || memoryProfile.mode === "disabled"}
                  loading={memoryBusy}
                  onClick={() => void testMemoryConnection()}
                >
                  <RefreshCw size={14} /> Probar conexión
                </AsyncActionButton>
              </div>
            </form>
          </PermissionGate>
        )}
      </section>
      {!archived && <PermissionGate permission="dossier.archive"><section className="settings-section destructive-zone"><header><h2>Archivar expediente</h2><p>Quedará en modo lectura y conservará toda su trazabilidad.</p></header><label className="field"><span>Escribe «{dossier.title}» para confirmar</span><input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label><AsyncActionButton className="vector-danger" disabled={confirmation !== dossier.title} loading={busy} onClick={() => void archive()}><Archive size={15} /> Archivar</AsyncActionButton></section></PermissionGate>}
    </div>
  );
}
