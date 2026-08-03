"use client";

import { Save } from "lucide-react";
import Link from "next/link";
import { FormEvent } from "react";
import { AsyncActionButton } from "@/components/ui/async-action-button";
import {
  type CompetitiveProfileDraft,
  type MarketProfileDraft,
  type ProfileDraft,
  profileHasContent,
  profileKindFor,
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
}: {
  id: string;
  label: string;
  value: string;
  onChange(value: string): void;
  disabled?: boolean;
  multiline?: boolean;
  required?: boolean;
  hint?: string;
}) {
  return (
    <label className={`field${multiline ? " full" : ""}`}>
      <span id={`${id}-label`}>{label}</span>
      {multiline ? (
        <textarea
          id={id}
          aria-labelledby={`${id}-label`}
          value={value}
          required={required}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : (
        <input
          id={id}
          aria-labelledby={`${id}-label`}
          value={value}
          required={required}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
      {hint ? <small>{hint}</small> : null}
    </label>
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
}: {
  draft: MarketProfileDraft;
  onChange(next: MarketProfileDraft): void;
  disabled?: boolean;
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
    </>
  );
}

function CompetitiveFields({
  draft,
  onChange,
  disabled,
}: {
  draft: CompetitiveProfileDraft;
  onChange(next: CompetitiveProfileDraft): void;
  disabled?: boolean;
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

  if (kind === "empty") return null;

  if (kind === "other") {
    if (!hasContent) return null;
    return (
      <section className="settings-section" data-testid="dossier-profile-panel">
        <header>
          <h2>Perfil del expediente</h2>
          <p>
            Este tipo no tiene un perfil tipado en el producto. Hay datos en{" "}
            <code>profile_config</code> que la UI no modela aún.
          </p>
        </header>
        <pre className="reporting-hint" style={{ whiteSpace: "pre-wrap", margin: "0 18px 18px" }}>
          {JSON.stringify(profileConfig, null, 2)}
        </pre>
      </section>
    );
  }

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
          <p className="reporting-hint">
            Aún no hay oferta propia, competidores ni decisión capturados. Complétalos en
            configuración.
          </p>
          <div className="placeholder-actions">
            <Link className="vector-secondary" href={`/app/dossiers/${dossierId}/settings#dossier-profile`}>
              Editar perfil
            </Link>
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
        <dl className="competitive-review" style={{ border: "none", background: "transparent", padding: 0 }}>
          {draft.kind === "market" ? (
            <>
              <ReadOnlyRow label="Oferta propia" value={draft.own_offer} />
              <ReadOnlyRow label="Decisión a tomar" value={draft.decision_to_make} />
              <ReadOnlyRow label="Competidores" value={draft.competitors} />
              <ReadOnlyRow label="Barreras" value={draft.barriers} />
              <ReadOnlyRow label="Segmentos" value={draft.segments} />
              <ReadOnlyRow label="Canales" value={draft.channels} />
              <ReadOnlyRow label="Palabras clave" value={draft.keywords} />
            </>
          ) : (
            <>
              <ReadOnlyRow label="Oferta propia" value={draft.own_offer} />
              <ReadOnlyRow label="Objetivo de negocio" value={draft.business_objective} />
              <ReadOnlyRow label="Competidores" value={draft.competitors} />
              <ReadOnlyRow label="CPV" value={draft.cpv} />
              <ReadOnlyRow label="Palabras clave" value={draft.keywords} />
              <ReadOnlyRow label="Geografías" value={draft.geographies} />
              <ReadOnlyRow label="Compradores" value={draft.target_buyers} />
            </>
          )}
        </dl>
        <div className="placeholder-actions">
          <Link className="vector-secondary" href={`/app/dossiers/${dossierId}/settings#dossier-profile`}>
            Editar en configuración
          </Link>
        </div>
      </section>
    );
  }

  if (!draft) return null;

  return (
    <section
      className="settings-section"
      id="dossier-profile"
      data-testid="dossier-profile-panel"
    >
      <header>
        <h2>Perfil del expediente</h2>
        <p>
          {draft.kind === "market"
            ? "Oferta propia, ecosistema, barreras y decisión a tomar capturados en el alta. Edítalos aquí; se guardan en profile_config."
            : "Oferta propia, competidores, CPV y criterios del alta de inteligencia competitiva. Edítalos aquí; se guardan en profile_config."}
        </p>
      </header>
      <form className="dossier-settings-form competitive-intake-fields" onSubmit={onSave}>
        {draft.kind === "market" ? (
          <MarketFields
            draft={draft}
            disabled={disabled || busy}
            onChange={(next) => onDraftChange(next)}
          />
        ) : (
          <CompetitiveFields
            draft={draft}
            disabled={disabled || busy}
            onChange={(next) => onDraftChange(next)}
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
