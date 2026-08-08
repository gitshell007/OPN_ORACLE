"use client";

import { Save } from "lucide-react";
import Link from "next/link";
import { FormEvent, useState } from "react";
import { AsyncActionButton } from "@/components/ui/async-action-button";
import {
  type CompetitiveProfileDraft,
  type CustomProfileDraft,
  type DeclaredSolvencyDraft,
  type MarketProfileDraft,
  type ProfileDraft,
  type SolvencyFieldErrors,
  PAST_SERVICES_MAX_LEN,
  SOLVENCY_DECLARED_HINT,
  hasSolvencyFieldErrors,
  profileHasContent,
  profileKindFor,
  validateSolvencyDraft,
} from "@/lib/dossier-profile";

type Props = {
  dossierId: string;
  dossierType: string;
  profileConfig?: Record<string, unknown> | null;
  draft: ProfileDraft | null;
  onDraftChange(next: ProfileDraft): void;
  onSave(event: FormEvent): void;
  busy?: boolean;
  disabled?: boolean;
  /** When true, render read-only summary with link to settings. */
  readOnly?: boolean;
};

function Field({
  id,
  label,
  value,
  onChange,
  disabled,
  multiline,
  required,
  hint,
  inputMode,
  error,
}: {
  id: string;
  label: string;
  value: string;
  onChange(value: string): void;
  disabled?: boolean;
  multiline?: boolean;
  required?: boolean;
  hint?: string;
  inputMode?: "decimal" | "text";
  error?: string;
}) {
  const errorId = `${id}-error`;
  const describedBy = [hint ? `${id}-hint` : null, error ? errorId : null]
    .filter(Boolean)
    .join(" ") || undefined;
  return (
    <label className={`field${multiline ? " full" : ""}`}>
      <span id={`${id}-label`}>{label}</span>
      {multiline ? (
        <textarea
          id={id}
          aria-labelledby={`${id}-label`}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          value={value}
          required={required}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : (
        <input
          id={id}
          aria-labelledby={`${id}-label`}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          value={value}
          required={required}
          disabled={disabled}
          inputMode={inputMode}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
      {hint ? (
        <small id={`${id}-hint`}>{hint}</small>
      ) : null}
      {error ? (
        <small id={errorId} role="alert" data-testid={`${id}-error`} className="field-error">
          {error}
        </small>
      ) : null}
    </label>
  );
}

function SolvencyFields({
  draft,
  onChange,
  disabled,
  errors,
}: {
  draft: DeclaredSolvencyDraft;
  onChange(patch: Partial<DeclaredSolvencyDraft>): void;
  disabled?: boolean;
  errors?: SolvencyFieldErrors;
}) {
  return (
    <>
      <Field
        id="profile-annual-turnover"
        label="Volumen anual de negocio declarado (EUR)"
        value={draft.annual_turnover}
        inputMode="decimal"
        disabled={disabled}
        hint={SOLVENCY_DECLARED_HINT}
        error={errors?.annual_turnover}
        onChange={(value) => onChange({ annual_turnover: value })}
      />
      <Field
        id="profile-past-services"
        label="Servicios similares de los últimos 3 años"
        value={draft.past_services}
        multiline
        disabled={disabled}
        hint={`${SOLVENCY_DECLARED_HINT} Máximo ${PAST_SERVICES_MAX_LEN} caracteres.`}
        error={errors?.past_services}
        onChange={(value) => onChange({ past_services: value })}
      />
    </>
  );
}

function ReadOnlyRow({ label, value }: { label: string; value: string }) {
  if (!value.trim()) return null;
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function MarketFields({
  draft,
  onChange,
  disabled,
  solvencyErrors,
}: {
  draft: MarketProfileDraft;
  onChange(next: MarketProfileDraft): void;
  disabled?: boolean;
  solvencyErrors?: SolvencyFieldErrors;
}) {
  const set = <K extends keyof MarketProfileDraft>(key: K, value: MarketProfileDraft[K]) =>
    onChange({ ...draft, [key]: value });
  return (
    <>
      <Field
        id="profile-own-offer"
        label="Oferta propia"
        value={draft.own_offer}
        required
        multiline
        disabled={disabled}
        onChange={(value) => set("own_offer", value)}
      />
      <Field
        id="profile-decision"
        label="Decisión a tomar"
        value={draft.decision_to_make}
        required
        multiline
        disabled={disabled}
        onChange={(value) => set("decision_to_make", value)}
      />
      <Field
        id="profile-horizon"
        label="Horizonte"
        value={draft.horizon}
        disabled={disabled}
        onChange={(value) => set("horizon", value)}
      />
      <Field
        id="profile-segments"
        label="Segmentos"
        value={draft.segments}
        hint="Separados por comas."
        disabled={disabled}
        onChange={(value) => set("segments", value)}
      />
      <Field
        id="profile-channels"
        label="Canales"
        value={draft.channels}
        hint="Separados por comas."
        disabled={disabled}
        onChange={(value) => set("channels", value)}
      />
      <Field
        id="profile-buyers"
        label="Compradores objetivo"
        value={draft.target_buyers}
        hint="Separados por comas."
        disabled={disabled}
        onChange={(value) => set("target_buyers", value)}
      />
      <Field
        id="profile-competitors"
        label="Competidores"
        value={draft.competitors}
        hint="Nombres separados por comas."
        multiline
        disabled={disabled}
        onChange={(value) => set("competitors", value)}
      />
      <Field
        id="profile-partners"
        label="Partners"
        value={draft.partners}
        hint="Separados por comas."
        disabled={disabled}
        onChange={(value) => set("partners", value)}
      />
      <Field
        id="profile-regulators"
        label="Reguladores"
        value={draft.regulators}
        hint="Separados por comas."
        disabled={disabled}
        onChange={(value) => set("regulators", value)}
      />
      <Field
        id="profile-barriers"
        label="Barreras"
        value={draft.barriers}
        hint="Separadas por comas."
        multiline
        disabled={disabled}
        onChange={(value) => set("barriers", value)}
      />
      <Field
        id="profile-keywords"
        label="Palabras clave"
        value={draft.keywords}
        hint="Separadas por comas."
        disabled={disabled}
        onChange={(value) => set("keywords", value)}
      />
      <Field
        id="profile-indicators"
        label="Indicadores de éxito"
        value={draft.success_indicators}
        hint="Separados por comas."
        disabled={disabled}
        onChange={(value) => set("success_indicators", value)}
      />
      <SolvencyFields
        draft={draft}
        disabled={disabled}
        errors={solvencyErrors}
        onChange={(patch) => onChange({ ...draft, ...patch })}
      />
    </>
  );
}

function CompetitiveFields({
  draft,
  onChange,
  disabled,
  solvencyErrors,
}: {
  draft: CompetitiveProfileDraft;
  onChange(next: CompetitiveProfileDraft): void;
  disabled?: boolean;
  solvencyErrors?: SolvencyFieldErrors;
}) {
  const set = <K extends keyof CompetitiveProfileDraft>(
    key: K,
    value: CompetitiveProfileDraft[K],
  ) => onChange({ ...draft, [key]: value });
  return (
    <>
      <Field
        id="profile-own-offer"
        label="Oferta propia"
        value={draft.own_offer}
        required
        multiline
        disabled={disabled}
        onChange={(value) => set("own_offer", value)}
      />
      <Field
        id="profile-business-objective"
        label="Objetivo de negocio"
        value={draft.business_objective}
        required
        multiline
        disabled={disabled}
        onChange={(value) => set("business_objective", value)}
      />
      <Field
        id="profile-competitors"
        label="Competidores"
        value={draft.competitors}
        required
        multiline
        hint="Al menos uno. Nombres separados por comas."
        disabled={disabled}
        onChange={(value) => set("competitors", value)}
      />
      <Field
        id="profile-cpv"
        label="Códigos CPV"
        value={draft.cpv}
        hint="Separados por comas. Alimentan la vigilancia de licitaciones al crear el expediente."
        disabled={disabled}
        onChange={(value) => set("cpv", value)}
      />
      <Field
        id="profile-keywords"
        label="Palabras clave"
        value={draft.keywords}
        hint="Separadas por comas."
        disabled={disabled}
        onChange={(value) => set("keywords", value)}
      />
      <Field
        id="profile-geographies"
        label="Geografías"
        value={draft.geographies}
        hint="Separadas por comas."
        disabled={disabled}
        onChange={(value) => set("geographies", value)}
      />
      <Field
        id="profile-segments"
        label="Segmentos"
        value={draft.segments}
        hint="Separados por comas."
        disabled={disabled}
        onChange={(value) => set("segments", value)}
      />
      <Field
        id="profile-buyers"
        label="Compradores objetivo"
        value={draft.target_buyers}
        hint="Separados por comas."
        disabled={disabled}
        onChange={(value) => set("target_buyers", value)}
      />
      <Field
        id="profile-horizon"
        label="Horizonte"
        value={draft.horizon}
        disabled={disabled}
        onChange={(value) => set("horizon", value)}
      />
      <Field
        id="profile-sources"
        label="Fuentes"
        value={draft.sources}
        hint="Separadas por comas."
        disabled={disabled}
        onChange={(value) => set("sources", value)}
      />
      <Field
        id="profile-participation"
        label="Criterios de participación"
        value={draft.participation_criteria}
        multiline
        disabled={disabled}
        onChange={(value) => set("participation_criteria", value)}
      />
      <Field
        id="profile-exclusion"
        label="Criterios de exclusión"
        value={draft.exclusion_criteria}
        multiline
        disabled={disabled}
        onChange={(value) => set("exclusion_criteria", value)}
      />
      <Field
        id="profile-indicators"
        label="Indicadores de éxito"
        value={draft.success_indicators}
        hint="Separados por comas."
        disabled={disabled}
        onChange={(value) => set("success_indicators", value)}
      />
      <SolvencyFields
        draft={draft}
        disabled={disabled}
        errors={solvencyErrors}
        onChange={(patch) => onChange({ ...draft, ...patch })}
      />
    </>
  );
}

function CustomFields({
  draft,
  onChange,
  disabled,
  solvencyErrors,
}: {
  draft: CustomProfileDraft;
  onChange(next: CustomProfileDraft): void;
  disabled?: boolean;
  solvencyErrors?: SolvencyFieldErrors;
}) {
  const set = <K extends keyof CustomProfileDraft>(key: K, value: CustomProfileDraft[K]) =>
    onChange({ ...draft, [key]: value });
  return (
    <>
      <Field
        id="profile-own-offer"
        label="Oferta propia"
        value={draft.own_offer}
        required
        multiline
        disabled={disabled}
        onChange={(value) => set("own_offer", value)}
      />
      <Field
        id="profile-decision"
        label="Decisión a tomar"
        value={draft.decision_to_make}
        multiline
        disabled={disabled}
        onChange={(value) => set("decision_to_make", value)}
      />
      <Field
        id="profile-competitors"
        label="Competidores"
        value={draft.competitors}
        required
        multiline
        hint="Nombres separados por comas."
        disabled={disabled}
        onChange={(value) => set("competitors", value)}
      />
      <Field
        id="profile-cpv"
        label="Códigos CPV"
        value={draft.cpv}
        hint="Separados por comas (p. ej. familias software/servicios IT)."
        disabled={disabled}
        onChange={(value) => set("cpv", value)}
      />
      <Field
        id="profile-barriers"
        label="Barreras"
        value={draft.barriers}
        hint="Separadas por comas."
        multiline
        disabled={disabled}
        onChange={(value) => set("barriers", value)}
      />
      <Field
        id="profile-business-objective"
        label="Objetivo de negocio"
        value={draft.business_objective}
        multiline
        disabled={disabled}
        onChange={(value) => set("business_objective", value)}
      />
      <Field
        id="profile-keywords"
        label="Palabras clave"
        value={draft.keywords}
        hint="Separadas por comas."
        disabled={disabled}
        onChange={(value) => set("keywords", value)}
      />
      <Field
        id="profile-geographies"
        label="Geografías"
        value={draft.geographies}
        hint="Separadas por comas."
        disabled={disabled}
        onChange={(value) => set("geographies", value)}
      />
      <Field
        id="profile-buyers"
        label="Compradores objetivo"
        value={draft.target_buyers}
        hint="Separados por comas."
        disabled={disabled}
        onChange={(value) => set("target_buyers", value)}
      />
      <Field
        id="profile-segments"
        label="Segmentos"
        value={draft.segments}
        hint="Separados por comas."
        disabled={disabled}
        onChange={(value) => set("segments", value)}
      />
      <Field
        id="profile-sources"
        label="Fuentes"
        value={draft.sources}
        hint="Separadas por comas."
        disabled={disabled}
        onChange={(value) => set("sources", value)}
      />
      <Field
        id="profile-indicators"
        label="Indicadores de éxito"
        value={draft.success_indicators}
        hint="Separados por comas."
        disabled={disabled}
        onChange={(value) => set("success_indicators", value)}
      />
      <SolvencyFields
        draft={draft}
        disabled={disabled}
        errors={solvencyErrors}
        onChange={(patch) => onChange({ ...draft, ...patch })}
      />
    </>
  );
}

function readOnlySolvencyRows(draft: DeclaredSolvencyDraft) {
  return (
    <>
      <ReadOnlyRow
        label="Volumen anual de negocio declarado (EUR)"
        value={draft.annual_turnover}
      />
      <ReadOnlyRow
        label="Servicios similares de los últimos 3 años"
        value={draft.past_services}
      />
    </>
  );
}

function readOnlyRows(draft: ProfileDraft) {
  if (draft.kind === "market") {
    return (
      <>
        <ReadOnlyRow label="Oferta propia" value={draft.own_offer} />
        <ReadOnlyRow label="Decisión a tomar" value={draft.decision_to_make} />
        <ReadOnlyRow label="Competidores" value={draft.competitors} />
        <ReadOnlyRow label="Barreras" value={draft.barriers} />
        <ReadOnlyRow label="Segmentos" value={draft.segments} />
        <ReadOnlyRow label="Canales" value={draft.channels} />
        <ReadOnlyRow label="Palabras clave" value={draft.keywords} />
        {readOnlySolvencyRows(draft)}
      </>
    );
  }
  if (draft.kind === "competitive_intelligence") {
    return (
      <>
        <ReadOnlyRow label="Oferta propia" value={draft.own_offer} />
        <ReadOnlyRow label="Objetivo de negocio" value={draft.business_objective} />
        <ReadOnlyRow label="Competidores" value={draft.competitors} />
        <ReadOnlyRow label="CPV" value={draft.cpv} />
        <ReadOnlyRow label="Palabras clave" value={draft.keywords} />
        <ReadOnlyRow label="Geografías" value={draft.geographies} />
        <ReadOnlyRow label="Compradores" value={draft.target_buyers} />
        {readOnlySolvencyRows(draft)}
      </>
    );
  }
  return (
    <>
      <ReadOnlyRow label="Oferta propia" value={draft.own_offer} />
      <ReadOnlyRow label="Decisión a tomar" value={draft.decision_to_make} />
      <ReadOnlyRow label="Competidores" value={draft.competitors} />
      <ReadOnlyRow label="CPV" value={draft.cpv} />
      <ReadOnlyRow label="Barreras" value={draft.barriers} />
      <ReadOnlyRow label="Objetivo de negocio" value={draft.business_objective} />
      <ReadOnlyRow label="Palabras clave" value={draft.keywords} />
      <ReadOnlyRow label="Geografías" value={draft.geographies} />
      <ReadOnlyRow label="Compradores" value={draft.target_buyers} />
      {readOnlySolvencyRows(draft)}
    </>
  );
}

export function DossierProfilePanel({
  dossierId,
  dossierType,
  profileConfig,
  draft,
  onDraftChange,
  onSave,
  busy = false,
  disabled = false,
  readOnly = false,
}: Props) {
  const kind = profileKindFor(dossierType, profileConfig);
  const hasContent = profileHasContent(profileConfig);
  const [solvencyErrors, setSolvencyErrors] = useState<SolvencyFieldErrors>({});
  const visibleSolvencyErrors: SolvencyFieldErrors = { ...solvencyErrors };
  if (draft && !readOnly) {
    const currentErrors = validateSolvencyDraft(draft);
    if (!currentErrors.annual_turnover) delete visibleSolvencyErrors.annual_turnover;
    if (!currentErrors.past_services) delete visibleSolvencyErrors.past_services;
  }

  if (kind === "empty") return null;

  if (readOnly) {
    if (!draft || !hasContent) {
      return (
        <section className="vector-panel" data-testid="dossier-profile-summary">
          <header>
            <div>
              <span className="section-kicker">Perfil de intake</span>
              <h2>Perfil del expediente</h2>
            </div>
          </header>
          <div
            className="vector-panel-body vector-panel-body--stack"
            data-testid="dossier-profile-body"
          >
            <p className="reporting-hint">
              Aún no hay oferta propia, competidores ni decisión capturados. Complétalos en
              configuración.
            </p>
            <div className="placeholder-actions">
              <Link
                className="vector-secondary"
                href={`/app/dossiers/${dossierId}/settings#dossier-profile`}
              >
                Editar perfil
              </Link>
            </div>
          </div>
        </section>
      );
    }
    return (
      <section className="vector-panel" data-testid="dossier-profile-summary">
        <header>
          <div>
            <span className="section-kicker">Perfil de intake</span>
            <h2>Perfil del expediente</h2>
          </div>
        </header>
        <div
          className="vector-panel-body vector-panel-body--stack"
          data-testid="dossier-profile-body"
        >
          <dl
            className="competitive-review"
            style={{ border: "none", background: "transparent", padding: 0 }}
          >
            {readOnlyRows(draft)}
          </dl>
          <div className="placeholder-actions">
            <Link
              className="vector-secondary"
              href={`/app/dossiers/${dossierId}/settings#dossier-profile`}
            >
              Editar en configuración
            </Link>
          </div>
        </div>
      </section>
    );
  }

  if (!draft) return null;

  const blurb =
    draft.kind === "market"
      ? "Oferta propia, ecosistema, barreras y decisión a tomar capturados en el alta. Edítalos aquí; se guardan en profile_config."
      : draft.kind === "competitive_intelligence"
        ? "Oferta propia, competidores, CPV y criterios del alta de inteligencia competitiva. Edítalos aquí; se guardan en profile_config."
        : "Oferta propia, competidores, CPV, barreras y decisión del expediente. Edítalos aquí; se guardan en profile_config (custom.v1).";

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!draft) return;
    const errors = validateSolvencyDraft(draft);
    if (hasSolvencyFieldErrors(errors)) {
      setSolvencyErrors(errors);
      // Fail-closed: do not call parent onSave → no PATCH.
      return;
    }
    setSolvencyErrors({});
    onSave(event);
  }

  function handleDraftChange(next: ProfileDraft) {
    const nextErrors = validateSolvencyDraft(next);
    setSolvencyErrors((prev) => {
      if (!hasSolvencyFieldErrors(prev)) return prev;
      const cleared: SolvencyFieldErrors = { ...prev };
      if (!nextErrors.annual_turnover) delete cleared.annual_turnover;
      if (!nextErrors.past_services) delete cleared.past_services;
      return cleared;
    });
    onDraftChange(next);
  }

  return (
    <section
      className="settings-section"
      id="dossier-profile"
      data-testid="dossier-profile-panel"
    >
      <header>
        <h2>Perfil del expediente</h2>
        <p>{blurb}</p>
      </header>
      <form className="dossier-settings-form competitive-intake-fields" onSubmit={handleSubmit}>
        {draft.kind === "market" ? (
          <MarketFields
            draft={draft}
            disabled={disabled || busy}
            solvencyErrors={visibleSolvencyErrors}
            onChange={handleDraftChange}
          />
        ) : draft.kind === "competitive_intelligence" ? (
          <CompetitiveFields
            draft={draft}
            disabled={disabled || busy}
            solvencyErrors={visibleSolvencyErrors}
            onChange={handleDraftChange}
          />
        ) : (
          <CustomFields
            draft={draft}
            disabled={disabled || busy}
            solvencyErrors={visibleSolvencyErrors}
            onChange={handleDraftChange}
          />
        )}
        <div className="settings-actions full">
          <AsyncActionButton
            className="vector-primary"
            type="submit"
            disabled={disabled}
            loading={busy}
          >
            <Save size={15} /> Guardar perfil
          </AsyncActionButton>
        </div>
      </form>
    </section>
  );
}
