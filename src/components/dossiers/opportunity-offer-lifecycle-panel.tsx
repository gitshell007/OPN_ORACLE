"use client";

/**
 * G-10 · seguimiento comercial de la oferta (separado del estado CRM).
 *
 * Visible siempre que haya una oportunidad seleccionada; no depende de
 * artifacts IA, fit ni verdict.
 */

import {
  ApiError,
  api,
  type OpportunityOfferLifecyclePatchInput,
  type OpportunityOfferLifecycleResource,
  type OpportunityOfferLifecycleStatus,
} from "@oracle/api-client";
import { AlertTriangle, RefreshCw, Save } from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { PermissionGate } from "@/components/auth/auth-boundary";
import { AsyncActionButton } from "@/components/ui/async-action-button";

const STATUS_OPTIONS: { value: OpportunityOfferLifecycleStatus; label: string }[] = [
  { value: "preparando", label: "Preparando" },
  { value: "presentada", label: "Presentada" },
  { value: "en_evaluacion", label: "En evaluación" },
  { value: "adjudicada", label: "Adjudicada" },
  { value: "perdida", label: "Perdida" },
  { value: "excluida", label: "Excluida" },
];

type SaveState = "idle" | "dirty" | "saving" | "saved" | "conflict" | "error";

export interface OpportunityOfferLifecyclePanelProps {
  dossierId: string;
  opportunityId: string;
  /** CRM status of the opportunity — shown as separate, never editable here. */
  crmStatus?: string;
  crmStatusLabel?: string;
}

function errorMessage(reason: unknown, fallback: string): string {
  return reason instanceof ApiError ? reason.problem.detail : fallback;
}

function fieldErrors(reason: unknown): Record<string, string[]> {
  if (!(reason instanceof ApiError)) return {};
  const errors = (reason.problem as { errors?: Record<string, string[]> }).errors;
  return errors && typeof errors === "object" ? errors : {};
}

function saveLabel(state: SaveState): string {
  switch (state) {
    case "dirty":
      return "Sin guardar";
    case "saving":
      return "Guardando…";
    case "saved":
      return "Guardado";
    case "conflict":
      return "Conflicto de versión (409)";
    case "error":
      return "Error al guardar";
    default:
      return "Listo";
  }
}

interface FormState {
  status: OpportunityOfferLifecycleStatus;
  importe_ofertado: string;
  baja_porcentaje: string;
  lotesText: string;
  garantia_provisional: string;
  fecha_mesa: string;
  motivo_exclusion: string;
}

function fromResource(row: OpportunityOfferLifecycleResource): FormState {
  return {
    status: row.status,
    importe_ofertado: row.importe_ofertado ?? "",
    baja_porcentaje: row.baja_porcentaje ?? "",
    lotesText: (row.lotes ?? []).join(", "),
    garantia_provisional: row.garantia_provisional ?? "",
    fecha_mesa: row.fecha_mesa ?? "",
    motivo_exclusion: row.motivo_exclusion ?? "",
  };
}

function emptyForm(): FormState {
  return {
    status: "preparando",
    importe_ofertado: "",
    baja_porcentaje: "",
    lotesText: "",
    garantia_provisional: "",
    fecha_mesa: "",
    motivo_exclusion: "",
  };
}

function versionLabel(row: OpportunityOfferLifecycleResource): string {
  if (!row.materialized || row.version === 0) {
    return "Sin materializar (v0)";
  }
  return `v${row.version}`;
}

function parseLotes(text: string): string[] {
  return text
    .split(/[,\n]/)
    .map((part) => part.trim())
    .filter(Boolean);
}

export function OpportunityOfferLifecyclePanel({
  dossierId,
  opportunityId,
  crmStatus,
  crmStatusLabel,
}: OpportunityOfferLifecyclePanelProps) {
  const [server, setServer] = useState<OpportunityOfferLifecycleResource | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [baseline, setBaseline] = useState<FormState>(emptyForm);
  const [loading, setLoading] = useState(true);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string[]>>({});

  const dirty = useMemo(
    () => JSON.stringify(form) !== JSON.stringify(baseline),
    [form, baseline],
  );
  const displayedSaveState: SaveState =
    dirty && saveState !== "saving" && saveState !== "conflict" ? "dirty" : saveState;

  useEffect(() => {
    if (!dirty) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  const applyServer = useCallback((row: OpportunityOfferLifecycleResource) => {
    const next = fromResource(row);
    setServer(row);
    setForm(next);
    setBaseline(next);
    setSaveState("idle");
    setError(null);
    setErrors({});
  }, []);

  const fetchLifecycle = useCallback(
    () => api.opportunities.getOfferLifecycle(dossierId, opportunityId),
    [dossierId, opportunityId],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchLifecycle();
      // Virtual (materialized=false, version=0) and durable rows share the same form shape.
      applyServer(response.lifecycle);
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo cargar el seguimiento de la oferta."));
      setServer(null);
    } finally {
      setLoading(false);
    }
  }, [applyServer, fetchLifecycle]);

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      setLoading(true);
      setError(null);
    });
    void fetchLifecycle()
      .then((response) => {
        if (active) applyServer(response.lifecycle);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(errorMessage(reason, "No se pudo cargar el seguimiento de la oferta."));
        setServer(null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [applyServer, fetchLifecycle]);

  function updateField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
    setErrors((prev) => {
      if (!(key in prev) && key !== "motivo_exclusion") return prev;
      const next = { ...prev };
      delete next[key as string];
      if (key === "lotesText") delete next.lotes;
      return next;
    });
  }

  async function onSave(event?: FormEvent) {
    event?.preventDefault();
    if (!server) return;
    setSaveState("saving");
    setError(null);
    setErrors({});

    const payload: OpportunityOfferLifecyclePatchInput = {
      version: server.version,
      status: form.status,
      importe_ofertado: form.importe_ofertado.trim() === "" ? null : form.importe_ofertado.trim(),
      baja_porcentaje: form.baja_porcentaje.trim() === "" ? null : form.baja_porcentaje.trim(),
      lotes: parseLotes(form.lotesText),
      garantia_provisional:
        form.garantia_provisional.trim() === "" ? null : form.garantia_provisional.trim(),
      fecha_mesa: form.fecha_mesa.trim() === "" ? null : form.fecha_mesa.trim(),
    };
    if (form.status === "excluida") {
      payload.motivo_exclusion = form.motivo_exclusion.trim();
    } else {
      // Explicitly omit residual motivo; server rejects non-empty outside excluida.
      payload.motivo_exclusion = null;
    }

    // Client-side guard for visible validation.
    if (form.status === "excluida" && !form.motivo_exclusion.trim()) {
      setErrors({ motivo_exclusion: ["Obligatorio en estado excluida."] });
      setSaveState("error");
      setError("Indica el motivo de exclusión.");
      return;
    }

    try {
      const response = await api.opportunities.patchOfferLifecycle(
        dossierId,
        opportunityId,
        payload,
        server.etag,
      );
      applyServer(response.lifecycle);
      setSaveState("saved");
      toast.success("Seguimiento de oferta guardado");
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        setSaveState("conflict");
        setError(
          "Otro usuario ha modificado el seguimiento. Recarga para ver la versión actual y vuelve a aplicar tus cambios.",
        );
        return;
      }
      setSaveState("error");
      setErrors(fieldErrors(reason));
      setError(errorMessage(reason, "No se pudo guardar el seguimiento de la oferta."));
    }
  }

  async function reloadAfterConflict() {
    await load();
    toast.message("Seguimiento recargado. Revisa y vuelve a guardar si hace falta.");
  }

  return (
    <section
      className="intelligence-detail-block opportunity-offer-lifecycle"
      data-testid="opportunity-offer-lifecycle-panel"
      aria-labelledby="offer-lifecycle-heading"
    >
      <header className="offer-lifecycle-header">
        <div>
          <h2 id="offer-lifecycle-heading">Ciclo de vida de la oferta</h2>
          <p className="muted">
            Seguimiento comercial de la licitación. Independiente del estado CRM de la
            oportunidad
            {crmStatus
              ? ` (CRM actual: ${crmStatusLabel ?? crmStatus}).`
              : "."}
          </p>
        </div>
        <span
          className={`offer-lifecycle-save-status status-${displayedSaveState}`}
          data-testid="offer-lifecycle-save-status"
          role="status"
        >
          {saveLabel(displayedSaveState)}
        </span>
      </header>

      {loading && (
        <p role="status" data-testid="offer-lifecycle-loading">
          Cargando seguimiento…
        </p>
      )}

      {!loading && error && !server && (
        <p className="form-error" role="alert" data-testid="offer-lifecycle-load-error">
          {error}
        </p>
      )}

      {!loading && server && (
        <PermissionGate permission="opportunity.write" fallback={
          <dl className="detail-grid" data-testid="offer-lifecycle-readonly">
            <div>
              <dt>Estado de la oferta</dt>
              <dd data-testid="offer-lifecycle-status-label">{server.status_label}</dd>
            </div>
            <div>
              <dt>Importe ofertado</dt>
              <dd>{server.importe_ofertado ?? "—"}</dd>
            </div>
            <div>
              <dt>Baja (%)</dt>
              <dd>{server.baja_porcentaje ?? "—"}</dd>
            </div>
            <div>
              <dt>Lotes</dt>
              <dd>{server.lotes.length ? server.lotes.join(", ") : "—"}</dd>
            </div>
            <div>
              <dt>Garantía provisional</dt>
              <dd>{server.garantia_provisional ?? "—"}</dd>
            </div>
            <div>
              <dt>Fecha de mesa</dt>
              <dd>{server.fecha_mesa ?? "—"}</dd>
            </div>
            {server.status === "excluida" && (
              <div>
                <dt>Motivo de exclusión</dt>
                <dd>{server.motivo_exclusion}</dd>
              </div>
            )}
          </dl>
        }>
          <form
            className="offer-lifecycle-form"
            data-testid="offer-lifecycle-form"
            onSubmit={(event) => void onSave(event)}
          >
            <label className="field" htmlFor="offer-lifecycle-status">
              Estado de la oferta
              <select
                id="offer-lifecycle-status"
                data-testid="offer-lifecycle-status"
                value={form.status}
                onChange={(event) =>
                  updateField("status", event.target.value as OpportunityOfferLifecycleStatus)
                }
              >
                {STATUS_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            {errors.status && (
              <p className="form-error" role="alert">
                {errors.status.join(" ")}
              </p>
            )}

            <div className="offer-lifecycle-grid">
              <label className="field" htmlFor="offer-lifecycle-importe">
                Importe ofertado (€)
                <input
                  id="offer-lifecycle-importe"
                  data-testid="offer-lifecycle-importe"
                  inputMode="decimal"
                  value={form.importe_ofertado}
                  onChange={(event) => updateField("importe_ofertado", event.target.value)}
                  placeholder="p. ej. 125000.50"
                />
              </label>
              <label className="field" htmlFor="offer-lifecycle-baja">
                Baja aplicada (%)
                <input
                  id="offer-lifecycle-baja"
                  data-testid="offer-lifecycle-baja"
                  inputMode="decimal"
                  value={form.baja_porcentaje}
                  onChange={(event) => updateField("baja_porcentaje", event.target.value)}
                  placeholder="0–100"
                />
              </label>
              <label className="field" htmlFor="offer-lifecycle-garantia">
                Garantía provisional (€)
                <input
                  id="offer-lifecycle-garantia"
                  data-testid="offer-lifecycle-garantia"
                  inputMode="decimal"
                  value={form.garantia_provisional}
                  onChange={(event) => updateField("garantia_provisional", event.target.value)}
                />
              </label>
              <label className="field" htmlFor="offer-lifecycle-fecha-mesa">
                Fecha de mesa
                <input
                  id="offer-lifecycle-fecha-mesa"
                  data-testid="offer-lifecycle-fecha-mesa"
                  type="date"
                  value={form.fecha_mesa}
                  onChange={(event) => updateField("fecha_mesa", event.target.value)}
                />
              </label>
            </div>
            {(errors.importe_ofertado || errors.baja_porcentaje || errors.garantia_provisional || errors.fecha_mesa) && (
              <p className="form-error" role="alert" data-testid="offer-lifecycle-field-errors">
                {[
                  ...(errors.importe_ofertado ?? []),
                  ...(errors.baja_porcentaje ?? []),
                  ...(errors.garantia_provisional ?? []),
                  ...(errors.fecha_mesa ?? []),
                ].join(" ")}
              </p>
            )}

            <label className="field" htmlFor="offer-lifecycle-lotes">
              Lotes a los que se concurre
              <input
                id="offer-lifecycle-lotes"
                data-testid="offer-lifecycle-lotes"
                value={form.lotesText}
                onChange={(event) => updateField("lotesText", event.target.value)}
                placeholder="Lote 1, Lote 3"
              />
            </label>
            {errors.lotes && (
              <p className="form-error" role="alert">
                {errors.lotes.join(" ")}
              </p>
            )}

            {form.status === "excluida" && (
              <label className="field" htmlFor="offer-lifecycle-motivo">
                Motivo de exclusión
                <textarea
                  id="offer-lifecycle-motivo"
                  data-testid="offer-lifecycle-motivo"
                  aria-required="true"
                  value={form.motivo_exclusion}
                  onChange={(event) => updateField("motivo_exclusion", event.target.value)}
                  rows={3}
                  placeholder="Explica por qué la oferta quedó excluida"
                />
              </label>
            )}
            {errors.motivo_exclusion && (
              <p className="form-error" role="alert" data-testid="offer-lifecycle-motivo-error">
                {errors.motivo_exclusion.join(" ")}
              </p>
            )}

            {error && (
              <p className="form-error" role="alert" data-testid="offer-lifecycle-error">
                {error}
              </p>
            )}

            {saveState === "conflict" && (
              <div className="offer-lifecycle-conflict" data-testid="offer-lifecycle-conflict" role="alert">
                <AlertTriangle size={16} aria-hidden="true" />
                <p>Conflicto 409: la versión en servidor ha cambiado.</p>
                <AsyncActionButton
                  type="button"
                  className="vector-secondary"
                  data-testid="offer-lifecycle-reload"
                  onClick={() => void reloadAfterConflict()}
                >
                  <RefreshCw size={14} /> Recargar versión actual
                </AsyncActionButton>
              </div>
            )}

            <div className="offer-lifecycle-actions">
              <AsyncActionButton
                type="submit"
                className="vector-primary"
                data-testid="offer-lifecycle-save"
                loading={saveState === "saving"}
                disabled={!dirty || saveState === "saving"}
              >
                <Save size={14} />{" "}
                {server.materialized ? "Guardar seguimiento" : "Guardar por primera vez"}
              </AsyncActionButton>
              <span className="muted" data-testid="offer-lifecycle-version">
                {versionLabel(server)}
              </span>
              {!server.materialized && (
                <span
                  className="muted"
                  data-testid="offer-lifecycle-virtual-hint"
                >
                  Aún no hay fila persistida; el primer guardado materializa el seguimiento.
                </span>
              )}
            </div>
          </form>
        </PermissionGate>
      )}
    </section>
  );
}
