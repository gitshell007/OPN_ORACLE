"use client";

import {
  ApiError,
  api,
  type ActorAliasCandidate,
  type ActorAliasCandidatesMeta,
  type ActorMergePreview,
  type OracleActor,
} from "@oracle/api-client";
import { GitMerge, RefreshCw, ShieldAlert, ShieldCheck } from "lucide-react";
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
  preview: ActorMergePreview | null;
  previewOpen: boolean;
  confirmChecked: boolean;
};

const emptyState = (): CandidateState => ({
  targetId: "",
  sourceId: "",
  reason: "",
  busy: false,
  preview: null,
  previewOpen: false,
  confirmChecked: false,
});

function actorLabel(actor: ActorAliasCandidate["actors"][number]): string {
  const aliases = Array.isArray(actor.aliases)
    ? actor.aliases.map(String).filter(Boolean)
    : [];
  const nif = actor.tax_id ? ` · NIF ${actor.tax_id}` : "";
  if (aliases.length === 0) return `${actor.name}${nif}`;
  return `${actor.name}${nif} · alias: ${aliases.slice(0, 3).join(", ")}`;
}

function matchReasonLabel(item: ActorAliasCandidate): string {
  if (item.match_reason === "tax_id") return "Coincidencia fiscal (NIF/CIF)";
  if (item.match_reason === "tax_id_conflict") return "Bloqueo: NIF distintos";
  if (item.match_reason === "normalized_name") return "Coincidencia nominal (cautela)";
  return item.match_reason || "Candidato";
}

function taxProvenanceLine(actor: ActorAliasCandidate["actors"][number]): string {
  const nif = actor.tax_id || "sin NIF durable";
  const label =
    actor.tax_id_provenance?.origin_label ||
    (actor.has_durable_tax_id_column
      ? "columna fiscal durable (declarado; no verificación oficial)"
      : "sin procedencia fiscal");
  const scheme = actor.tax_id_scheme ? ` · ${actor.tax_id_scheme}` : "";
  const country = actor.tax_id_country ? ` · ${actor.tax_id_country}` : "";
  return `${nif}${scheme}${country} — ${label}`;
}

function defaultTargetId(item: ActorAliasCandidate): string {
  if (item.suggested_target_id) return item.suggested_target_id;
  // Fiscal rule: prefer the actor that already holds the durable NIF column.
  const withColumn = item.actors.find((actor) => actor.has_durable_tax_id_column && actor.tax_id);
  if (withColumn) return withColumn.id;
  return item.actors[0]?.id ?? "";
}

function targetOptionsLocked(item: ActorAliasCandidate, targetId: string): boolean {
  if (item.match_reason !== "tax_id") return false;
  const withColumn = item.actors.filter((actor) => actor.has_durable_tax_id_column && actor.tax_id);
  if (withColumn.length === 0) return false;
  // Only the holder of the durable NIF may be destination for tax matches.
  return !withColumn.some((actor) => actor.id === targetId);
}

export function ActorDuplicateMergePanel() {
  const [items, setItems] = useState<ActorAliasCandidate[]>([]);
  const [meta, setMeta] = useState<ActorAliasCandidatesMeta | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [forms, setForms] = useState<Record<string, CandidateState>>({});
  const [lastMerge, setLastMerge] = useState<{
    target: OracleActor;
    sourceId: string;
    reason: string;
    taxId?: string | null;
    at: string;
  } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.actors.aliasCandidates();
      const next = data.items ?? [];
      setItems(next);
      setMeta(data.meta ?? null);
      setForms((current) => {
        const updated: Record<string, CandidateState> = {};
        for (const item of next) {
          const previous = current[item.identity_key] ?? emptyState();
          const ids = item.actors.map((actor) => actor.id);
          const suggested = defaultTargetId(item);
          const targetId = ids.includes(previous.targetId)
            ? previous.targetId
            : suggested;
          // Enforce fiscal destination when match is tax_id.
          const enforcedTarget =
            item.match_reason === "tax_id" && suggested && ids.includes(suggested)
              ? suggested
              : targetId;
          const sourceId =
            ids.includes(previous.sourceId) && previous.sourceId !== enforcedTarget
              ? previous.sourceId
              : (ids.find((id) => id !== enforcedTarget) ?? "");
          updated[item.identity_key] = {
            ...previous,
            targetId: enforcedTarget,
            sourceId,
            busy: false,
            preview: null,
            previewOpen: false,
            confirmChecked: false,
          };
        }
        return updated;
      });
    } catch (reason) {
      setError(errorText(reason, "No se pudieron cargar los candidatos a fusión."));
      setItems([]);
      setMeta(null);
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

  async function openPreview(identityKey: string, item: ActorAliasCandidate) {
    const form = forms[identityKey] ?? emptyState();
    if (!form.targetId || !form.sourceId || form.targetId === form.sourceId) {
      setError("Elige un actor destino y un origen distintos.");
      return;
    }
    if (item.status === "blocked") {
      setError("Este par está bloqueado por NIF distintos; no se puede fusionar.");
      return;
    }
    if (targetOptionsLocked(item, form.targetId)) {
      setError(
        "Para coincidencia fiscal el destino debe ser el actor que ya posee el NIF durable.",
      );
      return;
    }
    updateForm(identityKey, { busy: true });
    setError(null);
    try {
      const preview = await api.actors.mergePreview(form.targetId, {
        source_actor_id: form.sourceId,
      });
      if (preview.blocked) {
        setError(preview.block_reason || "Fusión bloqueada por identidad fiscal.");
        updateForm(identityKey, { busy: false, preview: null, previewOpen: false });
        return;
      }
      updateForm(identityKey, {
        busy: false,
        preview,
        previewOpen: true,
        confirmChecked: false,
      });
    } catch (reason) {
      setError(errorText(reason, "No se pudo generar el preview de fusión."));
      updateForm(identityKey, { busy: false });
    }
  }

  async function confirmMerge(identityKey: string, item: ActorAliasCandidate, event: FormEvent) {
    event.preventDefault();
    const form = forms[identityKey] ?? emptyState();
    if (!form.previewOpen || !form.preview) {
      setError("Revisa el preview antes de confirmar la fusión.");
      return;
    }
    if (!form.confirmChecked) {
      setError("Marca la casilla de confirmación inequívoca antes de fusionar.");
      return;
    }
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
        confirm: true,
        expected_target_version: form.preview.confirmation_required.expected_target_version,
        expected_source_version: form.preview.confirmation_required.expected_source_version,
        match_reason: item.match_reason ?? null,
      });
      setLastMerge({
        target,
        sourceId: form.sourceId,
        reason: form.reason.trim(),
        taxId: target.tax_id ?? form.preview.target.tax_id,
        at: new Date().toISOString(),
      });
      toast.success("Fusión confirmada. El actor origen se ha unificado en el destino.");
      await load();
    } catch (reason) {
      const detail = errorText(reason, "No se pudo fusionar los actores.");
      const isCas =
        reason instanceof ApiError &&
        (String((reason.problem as { code?: string }).code || "").includes("version") ||
          /CAS|modificado por otro/i.test(detail));
      setError(
        isCas
          ? `${detail} Recarga los candidatos y vuelve a previsualizar antes de reintentar.`
          : detail,
      );
      updateForm(identityKey, { busy: false });
    }
  }

  const coverageText = meta
    ? `${meta.organizations_with_tax_id}/${meta.organizations_evaluated} con NIF durable (${meta.tax_id_coverage_pct}%)`
    : null;

  return (
    <div className="actor-duplicate-merge-page">
      <PageHeader
        eyebrow="Directorio de actores"
        title="Candidatos a fusión"
        description="El sistema propone primero por NIF/CIF durable y, solo como fallback, por denominación normalizada sin forma jurídica. Tú decides si fusionar. Nada se une de forma automática."
      />

      <section className="settings-section" aria-labelledby="merge-policy-title">
        <header>
          <h2 id="merge-policy-title">Cómo funciona y qué implica</h2>
        </header>
        <ul className="reporting-hint" style={{ margin: 0, paddingLeft: "1.25rem" }}>
          <li>
            <strong>La persona decide, el sistema propone.</strong> Coincidencia fiscal
            (NIF) tiene prioridad; la nominal exige más cautela y no infiere NIF.
          </li>
          <li>
            La fusión es <strong>trazable</strong>: auditoría <code>actor.merged</code> con
            quién, motivo, versiones CAS y motivo de coincidencia.
          </li>
          <li>
            <strong>No es reversible con un clic.</strong> El origen se elimina tras mover
            vínculos, alias e identificadores al destino.
          </li>
          <li>
            Dos NIF durables distintos <strong>bloquean</strong> la fusión (sin mutación).
          </li>
        </ul>
        {meta && (
          <p className="reporting-hint" style={{ marginTop: "0.75rem" }} role="status">
            Cobertura evaluada: <strong>{coverageText}</strong>. Criterios:{" "}
            {(meta.criteria_evaluated || []).join(", ") || "—"}.{" "}
            {meta.limitations}
          </p>
        )}
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
              {lastMerge.sourceId.slice(0, 8)}… · NIF{" "}
              {lastMerge.taxId || lastMerge.target.tax_id || "—"} ·{" "}
              {new Date(lastMerge.at).toLocaleString("es-ES")}
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
        <div className="global-inventory-state" role="status">
          <p>
            {meta?.empty_state_message ||
              "No hay candidatos bajo los criterios evaluados (NIF durable y denominación normalizada)."}
          </p>
          {coverageText && (
            <p className="reporting-hint">
              Cobertura NIF: {coverageText}. No se afirma que el directorio esté «limpio».
            </p>
          )}
        </div>
      ) : (
        <ul
          className="actor-duplicate-list"
          style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: "1rem" }}
        >
          {items.map((item) => {
            const form = forms[item.identity_key] ?? emptyState();
            const blocked = item.status === "blocked";
            const fiscalMatch = item.match_reason === "tax_id";
            const fiscalHolderIds = new Set(
              item.actors
                .filter((actor) => actor.has_durable_tax_id_column && actor.tax_id)
                .map((actor) => actor.id),
            );
            return (
              <li key={item.identity_key} className="settings-section">
                <header>
                  <h2>
                    {blocked ? (
                      <ShieldAlert size={18} aria-hidden="true" style={{ marginRight: 6 }} />
                    ) : (
                      <ShieldCheck size={18} aria-hidden="true" style={{ marginRight: 6 }} />
                    )}
                    {matchReasonLabel(item)}
                    {item.tax_id ? ` · ${item.tax_id}` : ""}
                  </h2>
                  <p>{item.reason}</p>
                  <p className="reporting-hint">
                    Clave «{item.identity_key}» · confianza {item.confidence || "—"} ·
                    prioridad {item.priority ?? "—"}
                  </p>
                </header>
                <ul style={{ margin: "0 0 1rem", paddingLeft: "1.25rem" }}>
                  {item.actors.map((actor) => (
                    <li key={actor.id}>
                      <strong>{actor.name}</strong>
                      <span className="reporting-hint">
                        {" "}
                        · id {actor.id.slice(0, 8)}… · v{actor.version}
                      </span>
                      <div className="reporting-hint">{taxProvenanceLine(actor)}</div>
                    </li>
                  ))}
                </ul>
                {blocked ? (
                  <p className="inline-error" role="status">
                    Fusión bloqueada. NIF en conflicto:{" "}
                    {(item.blocking_tax_ids || []).join(" vs ") || "distintos"}.
                  </p>
                ) : (
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
                      onSubmit={(event) => void confirmMerge(item.identity_key, item, event)}
                    >
                      <label className="field">
                        <span>Conservar (destino)</span>
                        <select
                          required
                          value={form.targetId}
                          onChange={(event) => {
                            const targetId = event.target.value;
                            if (
                              fiscalMatch &&
                              fiscalHolderIds.size > 0 &&
                              !fiscalHolderIds.has(targetId)
                            ) {
                              setError(
                                "En coincidencia fiscal el destino debe poseer el NIF durable.",
                              );
                              return;
                            }
                            const sourceId =
                              form.sourceId === targetId
                                ? item.actors.find((actor) => actor.id !== targetId)?.id ?? ""
                                : form.sourceId;
                            updateForm(item.identity_key, {
                              targetId,
                              sourceId,
                              preview: null,
                              previewOpen: false,
                              confirmChecked: false,
                            });
                          }}
                          disabled={form.busy || (fiscalMatch && fiscalHolderIds.size > 0)}
                        >
                          {item.actors
                            .filter(
                              (actor) =>
                                !fiscalMatch ||
                                fiscalHolderIds.size === 0 ||
                                fiscalHolderIds.has(actor.id),
                            )
                            .map((actor) => (
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
                            updateForm(item.identity_key, {
                              sourceId: event.target.value,
                              preview: null,
                              previewOpen: false,
                              confirmChecked: false,
                            })
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

                      {!form.previewOpen ? (
                        <div className="settings-actions">
                          <AsyncActionButton
                            className="vector-secondary"
                            type="button"
                            loading={form.busy}
                            disabled={
                              !form.targetId ||
                              !form.sourceId ||
                              form.targetId === form.sourceId
                            }
                            onClick={() => void openPreview(item.identity_key, item)}
                          >
                            Previsualizar fusión
                          </AsyncActionButton>
                        </div>
                      ) : (
                        form.preview && (
                          <div
                            className="settings-section"
                            style={{ marginTop: "0.75rem" }}
                            role="region"
                            aria-label="Preview de fusión"
                          >
                            <header>
                              <h3>Preview antes de mutar</h3>
                              <p className="reporting-hint">
                                Destino: <strong>{form.preview.target.name}</strong> (NIF{" "}
                                {form.preview.target.tax_id || "—"}) · Origen:{" "}
                                <strong>{form.preview.source.name}</strong> (NIF{" "}
                                {form.preview.source.tax_id || "—"})
                              </p>
                            </header>
                            <p className="reporting-hint">
                              Alias resultantes:{" "}
                              {form.preview.resulting_aliases.join(", ") || "—"}
                            </p>
                            <p className="reporting-hint">
                              {form.preview.reference_impact.summary}
                            </p>
                            <p className="reporting-hint">
                              Versiones CAS: destino v
                              {form.preview.confirmation_required.expected_target_version},
                              origen v
                              {form.preview.confirmation_required.expected_source_version}
                            </p>
                            <label className="field" style={{ display: "flex", gap: "0.5rem" }}>
                              <input
                                type="checkbox"
                                checked={form.confirmChecked}
                                onChange={(event) =>
                                  updateForm(item.identity_key, {
                                    confirmChecked: event.target.checked,
                                  })
                                }
                                disabled={form.busy}
                              />
                              <span>
                                Confirmo de forma inequívoca esta fusión (no es un reintento
                                accidental).
                              </span>
                            </label>
                            <p
                              className="inline-error"
                              role="note"
                              style={{ marginBottom: "0.75rem" }}
                            >
                              Esta acción no se puede deshacer con un solo clic. El origen
                              desaparece del directorio y sus vínculos pasan al destino.
                            </p>
                            <div className="settings-actions">
                              <AsyncActionButton
                                className="vector-secondary"
                                type="button"
                                disabled={form.busy}
                                onClick={() =>
                                  updateForm(item.identity_key, {
                                    previewOpen: false,
                                    preview: null,
                                    confirmChecked: false,
                                  })
                                }
                              >
                                Cancelar preview
                              </AsyncActionButton>
                              <AsyncActionButton
                                className="vector-primary"
                                type="submit"
                                loading={form.busy}
                                disabled={
                                  !form.confirmChecked ||
                                  !form.targetId ||
                                  !form.sourceId ||
                                  form.targetId === form.sourceId ||
                                  form.reason.trim().length < 3
                                }
                              >
                                <GitMerge size={15} aria-hidden="true" /> Confirmar fusión
                              </AsyncActionButton>
                            </div>
                          </div>
                        )
                      )}
                    </form>
                  </PermissionGate>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
