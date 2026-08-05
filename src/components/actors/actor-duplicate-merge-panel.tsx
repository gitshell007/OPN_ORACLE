"use client";

import {
  ApiError,
  api,
  type ActorAliasCandidate,
  type OracleActor,
} from "@oracle/api-client";
import { GitMerge, RefreshCw } from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { PermissionGate } from "@/components/auth/auth-boundary";
import { AsyncActionButton } from "@/components/ui/async-action-button";
import { PageHeader } from "@/components/ui/page-header";

const errorText = (reason: unknown, fallback: string) =>
  reason instanceof ApiError ? reason.problem.detail : fallback;

type CandidateState = {
  targetId: string;
  sourceId: string;
  reason: string;
  busy: boolean;
};

const emptyState = (): CandidateState => ({
  targetId: "",
  sourceId: "",
  reason: "",
  busy: false,
});

function actorLabel(actor: ActorAliasCandidate["actors"][number]): string {
  const aliases = Array.isArray(actor.aliases)
    ? actor.aliases.map(String).filter(Boolean)
    : [];
  if (aliases.length === 0) return actor.name;
  return `${actor.name} · alias: ${aliases.slice(0, 3).join(", ")}`;
}

export function ActorDuplicateMergePanel() {
  const [items, setItems] = useState<ActorAliasCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [forms, setForms] = useState<Record<string, CandidateState>>({});
  const [lastMerge, setLastMerge] = useState<{
    target: OracleActor;
    sourceId: string;
    reason: string;
    at: string;
  } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.actors.aliasCandidates();
      const next = data.items ?? [];
      setItems(next);
      setForms((current) => {
        const updated: Record<string, CandidateState> = {};
        for (const item of next) {
          const previous = current[item.identity_key] ?? emptyState();
          const ids = item.actors.map((actor) => actor.id);
          const targetId = ids.includes(previous.targetId)
            ? previous.targetId
            : (ids[0] ?? "");
          const sourceId = ids.includes(previous.sourceId) && previous.sourceId !== targetId
            ? previous.sourceId
            : (ids.find((id) => id !== targetId) ?? "");
          updated[item.identity_key] = {
            ...previous,
            targetId,
            sourceId,
            busy: false,
          };
        }
        return updated;
      });
    } catch (reason) {
      setError(errorText(reason, "No se pudieron cargar los candidatos a fusión."));
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  function updateForm(identityKey: string, patch: Partial<CandidateState>) {
    setForms((current) => ({
      ...current,
      [identityKey]: { ...(current[identityKey] ?? emptyState()), ...patch },
    }));
  }

  async function confirmMerge(identityKey: string, event: FormEvent) {
    event.preventDefault();
    const form = forms[identityKey] ?? emptyState();
    if (!form.targetId || !form.sourceId || form.targetId === form.sourceId) {
      setError("Elige un actor destino y un origen distintos.");
      return;
    }
    if (form.reason.trim().length < 3) {
      setError("Indica un motivo de la fusión (mínimo 3 caracteres).");
      return;
    }
    updateForm(identityKey, { busy: true });
    setError(null);
    try {
      const target = await api.actors.merge(form.targetId, {
        source_actor_id: form.sourceId,
        reason: form.reason.trim(),
      });
      setLastMerge({
        target,
        sourceId: form.sourceId,
        reason: form.reason.trim(),
        at: new Date().toISOString(),
      });
      toast.success("Fusión confirmada. El actor origen se ha unificado en el destino.");
      await load();
    } catch (reason) {
      setError(errorText(reason, "No se pudo fusionar los actores."));
      updateForm(identityKey, { busy: false });
    }
  }

  return (
    <div className="actor-duplicate-merge-page">
      <PageHeader
        eyebrow="Directorio de actores"
        title="Candidatos a fusión"
        description="El sistema propone organizaciones con la misma denominación normalizada (sin forma jurídica). Tú decides si fusionar. Nada se une de forma automática."
      />

      <section className="settings-section" aria-labelledby="merge-policy-title">
        <header>
          <h2 id="merge-policy-title">Cómo funciona y qué implica</h2>
        </header>
        <ul className="reporting-hint" style={{ margin: 0, paddingLeft: "1.25rem" }}>
          <li>
            <strong>La persona decide, el sistema propone.</strong> Esta lista solo
            muestra coincidencias; no fusiona sola.
          </li>
          <li>
            La fusión es <strong>trazable</strong>: queda en auditoría como{" "}
            <code>actor.merged</code> con quién la hizo, el motivo y el actor origen.
          </li>
          <li>
            <strong>No es reversible con un clic.</strong> El actor origen se elimina
            tras mover vínculos, alias e identificadores al destino. Si te equivocas,
            hay que reconstruir el actor a mano.
          </li>
        </ul>
      </section>

      {error && (
        <div className="inline-error" role="alert">
          {error}
          <button type="button" onClick={() => setError(null)}>
            Cerrar
          </button>
        </div>
      )}

      {lastMerge && (
        <div className="settings-section" role="status">
          <header>
            <h2>Última fusión en esta sesión</h2>
            <p>
              Destino <strong>{lastMerge.target.canonical_name}</strong> (
              {lastMerge.target.id.slice(0, 8)}…) · origen{" "}
              {lastMerge.sourceId.slice(0, 8)}… · {new Date(lastMerge.at).toLocaleString("es-ES")}
            </p>
          </header>
          <p className="reporting-hint">Motivo: {lastMerge.reason}</p>
        </div>
      )}

      <div className="settings-actions" style={{ marginBottom: "1rem" }}>
        <AsyncActionButton
          type="button"
          className="vector-secondary"
          loading={loading}
          onClick={() => void load()}
        >
          <RefreshCw size={15} aria-hidden="true" /> Actualizar candidatos
        </AsyncActionButton>
      </div>

      {loading && items.length === 0 ? (
        <p className="global-inventory-state" role="status">
          Buscando posibles duplicados…
        </p>
      ) : items.length === 0 ? (
        <p className="global-inventory-state" role="status">
          No hay candidatos de organización con la misma clave de identidad. El
          directorio está limpio en este criterio.
        </p>
      ) : (
        <ul className="actor-duplicate-list" style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: "1rem" }}>
          {items.map((item) => {
            const form = forms[item.identity_key] ?? emptyState();
            return (
              <li key={item.identity_key} className="settings-section">
                <header>
                  <h2>Clave «{item.identity_key}»</h2>
                  <p>{item.reason}</p>
                </header>
                <ul style={{ margin: "0 0 1rem", paddingLeft: "1.25rem" }}>
                  {item.actors.map((actor) => (
                    <li key={actor.id}>
                      <strong>{actor.name}</strong>
                      <span className="reporting-hint"> · id {actor.id.slice(0, 8)}…</span>
                    </li>
                  ))}
                </ul>
                <PermissionGate
                  permission="actor.write"
                  fallback={
                    <p className="reporting-hint">
                      Solo lectura: necesitas permiso de escritura de actores para
                      confirmar una fusión.
                    </p>
                  }
                >
                  <form
                    className="dossier-settings-form"
                    onSubmit={(event) => void confirmMerge(item.identity_key, event)}
                  >
                    <label className="field">
                      <span>Conservar (destino)</span>
                      <select
                        required
                        value={form.targetId}
                        onChange={(event) => {
                          const targetId = event.target.value;
                          const sourceId =
                            form.sourceId === targetId
                              ? item.actors.find((actor) => actor.id !== targetId)?.id ?? ""
                              : form.sourceId;
                          updateForm(item.identity_key, { targetId, sourceId });
                        }}
                        disabled={form.busy}
                      >
                        {item.actors.map((actor) => (
                          <option key={actor.id} value={actor.id}>
                            {actorLabel(actor)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="field">
                      <span>Fusionar y archivar (origen)</span>
                      <select
                        required
                        value={form.sourceId}
                        onChange={(event) =>
                          updateForm(item.identity_key, { sourceId: event.target.value })
                        }
                        disabled={form.busy}
                      >
                        {item.actors
                          .filter((actor) => actor.id !== form.targetId)
                          .map((actor) => (
                            <option key={actor.id} value={actor.id}>
                              {actorLabel(actor)}
                            </option>
                          ))}
                      </select>
                    </label>
                    <label className="field full">
                      <span>Motivo (obligatorio, queda en auditoría)</span>
                      <textarea
                        required
                        minLength={3}
                        maxLength={1000}
                        value={form.reason}
                        onChange={(event) =>
                          updateForm(item.identity_key, { reason: event.target.value })
                        }
                        disabled={form.busy}
                        placeholder="Ej. Misma empresa con distinta forma jurídica en el alta."
                      />
                    </label>
                    <p className="inline-error" role="note" style={{ marginBottom: "0.75rem" }}>
                      Esta acción no se puede deshacer con un solo clic. El origen
                      desaparece del directorio y sus vínculos pasan al destino.
                    </p>
                    <div className="settings-actions">
                      <AsyncActionButton
                        className="vector-primary"
                        type="submit"
                        loading={form.busy}
                        disabled={
                          !form.targetId ||
                          !form.sourceId ||
                          form.targetId === form.sourceId ||
                          form.reason.trim().length < 3
                        }
                      >
                        <GitMerge size={15} aria-hidden="true" /> Confirmar fusión
                      </AsyncActionButton>
                    </div>
                  </form>
                </PermissionGate>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
