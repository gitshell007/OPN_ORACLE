"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { ApiError, api } from "@oracle/api-client";
import { AlertTriangle, CheckCircle2, FilePlus2, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { toast } from "sonner";
import { AsyncActionButton } from "@/components/ui/async-action-button";
import { EuCountryMultiSelect } from "@/components/ui/eu-country-multiselect";
import { starterProfileFor } from "@/lib/dossier-starter-profiles";
import { PRIORITY_COUNTRY_CODES, euCountryName, languagesForCountries } from "@/lib/eu-countries";

const DOSSIER_TYPES = [
  ["project", "Proyecto"],
  ["market", "Mercado"],
  ["strategic_account", "Cuenta estratégica"],
  ["tender_or_grant", "Licitación o convocatoria"],
  ["partnership", "Alianza"],
  ["regulatory_affair", "Asunto regulatorio"],
  ["competitive_intelligence", "Inteligencia competitiva"],
  ["custom", "Otro"],
] as const;

const MARKET_STEPS = [
  ["context", "Contexto", "Nombra el mercado y la meta que persigues."],
  ["scope", "Alcance de mercado", "Delimita oferta propia, sector y geografía."],
  ["ecosystem", "Ecosistema", "Nombra competidores, clientes, canales y reguladores."],
  ["decision", "Decisión y revisión", "Concreta la decisión a tomar y revisa la base."],
] as const;

/** Intención honesta sobre competidores: viaja al perfil y al agente de descubrimiento. */
export type CompetitorsKnowledge = "known" | "unknown" | "not_seeking";

/** G-19 target actor types for market_actor_discovery (not competitor discovery). */
export type DiscoveryActorType =
  | "company"
  | "research_group"
  | "technology_center"
  | "regulator"
  | "potential_customer";

export const DISCOVERY_ACTOR_TYPE_LABELS: Record<DiscoveryActorType, string> = {
  company: "Empresa",
  research_group: "Grupo de investigación",
  technology_center: "Centro tecnológico",
  regulator: "Regulador",
  potential_customer: "Cliente potencial",
};

export const DISCOVERY_INTENT_MIN = 10;
export const DISCOVERY_INTENT_MAX = 2000;

type MarketStep = (typeof MARKET_STEPS)[number][0];

const COMPETITORS_KNOWLEDGE_LABELS: Record<CompetitorsKnowledge, string> = {
  known: "Conozco competidores",
  unknown: "Aún no lo sé",
  not_seeking: "No busco competidores",
};

export function normalizeDiscoveryIntent(value: string): string {
  return value.trim().replace(/\s+/g, " ");
}

export function marketStepBlockers(input: {
  step: MarketStep;
  title: string;
  goal: string;
  ownOffer: string;
  marketCountries: string[];
  competitors: string;
  competitorsKnowledge: CompetitorsKnowledge | "";
  decisionToMake: string;
  discoveryIntent?: string;
  discoveryActorType?: DiscoveryActorType | "";
}): string[] {
  const list = (value: string) => value.split(",").map((item) => item.trim()).filter(Boolean);
  if (input.step === "context") {
    const blockers: string[] = [];
    if (input.title.trim().length < 2) blockers.push("Nombre del expediente (mínimo 2 caracteres)");
    if (!input.goal.trim()) blockers.push("Objetivo estratégico");
    return blockers;
  }
  if (input.step === "scope") {
    const blockers: string[] = [];
    if (!input.ownOffer.trim()) blockers.push("Oferta o capacidades propias");
    if (input.marketCountries.length === 0) blockers.push("Al menos un país objetivo");
    return blockers;
  }
  if (input.step === "ecosystem") {
    const intent = normalizeDiscoveryIntent(input.discoveryIntent ?? "");
    const actorType = input.discoveryActorType ?? "";
    const hasActorDiscovery =
      intent.length >= DISCOVERY_INTENT_MIN &&
      intent.length <= DISCOVERY_INTENT_MAX &&
      Boolean(actorType);
    const intentPartial = Boolean(intent) || Boolean(actorType);
    if (intentPartial && !hasActorDiscovery) {
      const blockers: string[] = [];
      if (intent.length > 0 && intent.length < DISCOVERY_INTENT_MIN) {
        blockers.push(`Intención de búsqueda (mínimo ${DISCOVERY_INTENT_MIN} caracteres)`);
      }
      if (intent.length > DISCOVERY_INTENT_MAX) {
        blockers.push(`Intención de búsqueda (máximo ${DISCOVERY_INTENT_MAX} caracteres)`);
      }
      if (!intent) blockers.push("¿A quién quieres encontrar y para qué?");
      if (!actorType) blockers.push("Tipo de actor a encontrar");
      return blockers;
    }
    // Non-competitor actor path (e.g. research_group): no competitor names required.
    if (hasActorDiscovery && actorType !== "company") {
      return [];
    }
    if (!input.competitorsKnowledge) {
      if (hasActorDiscovery) {
        return [];
      }
      return [
        "Indica si conoces competidores, aún no lo sabes o no los buscas",
      ];
    }
    if (input.competitorsKnowledge === "known" && list(input.competitors).length === 0) {
      return [
        "Añade al menos un competidor, o elige «Aún no lo sé» / «No busco competidores»",
      ];
    }
    return [];
  }
  if (!input.decisionToMake.trim()) {
    return ["Decisión concreta a tomar"];
  }
  return [];
}

export function CreateProductDossierDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange(open: boolean): void;
}) {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [type, setType] = useState("project");
  const [goal, setGoal] = useState("");
  const [description, setDescription] = useState("");
  const [createStarterProfile, setCreateStarterProfile] = useState(true);
  const [competitors, setCompetitors] = useState("");
  const [competitorsKnowledge, setCompetitorsKnowledge] = useState<CompetitorsKnowledge | "">("");
  const [discoveryIntent, setDiscoveryIntent] = useState("");
  const [discoveryActorType, setDiscoveryActorType] = useState<DiscoveryActorType | "">("");
  const [discoveryKnownNames, setDiscoveryKnownNames] = useState("");
  const [ownOffer, setOwnOffer] = useState("");
  const [segments, setSegments] = useState("");
  const [geographies, setGeographies] = useState("");
  const [buyers, setBuyers] = useState("");
  const [horizon, setHorizon] = useState("");
  const [keywords, setKeywords] = useState("");
  const [cpv, setCpv] = useState("");
  const [sources, setSources] = useState("PLACSP, fuentes oficiales, noticias");
  const [participation, setParticipation] = useState("");
  const [exclusion, setExclusion] = useState("");
  const [indicators, setIndicators] = useState("");
  const [activeOnCreate, setActiveOnCreate] = useState(true);
  const [reviewing, setReviewing] = useState(false);
  const [readiness, setReadiness] = useState<Awaited<ReturnType<typeof api.dossiers.competitiveReadiness>> | null>(null);
  const [step, setStep] = useState<MarketStep>("context");
  const [sectors, setSectors] = useState("");
  const [channels, setChannels] = useState("");
  const [partners, setPartners] = useState("");
  const [regulators, setRegulators] = useState("");
  const [barriers, setBarriers] = useState("");
  const [decisionToMake, setDecisionToMake] = useState("");
  const [marketCountries, setMarketCountries] = useState<string[]>([...PRIORITY_COUNTRY_CODES]);
  const [marketLanguages, setMarketLanguages] = useState(
    languagesForCountries(PRIORITY_COUNTRY_CODES).join(", "),
  );
  const [languagesTouched, setLanguagesTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selectedProfile = starterProfileFor(type);
  const isMarket = type === "market";
  const stepIndex = MARKET_STEPS.findIndex(([value]) => value === step);

  const list = (value: string) => value.split(",").map((item) => item.trim()).filter(Boolean);

  const marketBlockers = isMarket
    ? marketStepBlockers({
        step,
        title,
        goal,
        ownOffer,
        marketCountries,
        competitors,
        competitorsKnowledge,
        decisionToMake,
        discoveryIntent,
        discoveryActorType,
      })
    : [];
  const marketStepReady = marketBlockers.length === 0;

  function resetForm() {
    setTitle("");
    setGoal("");
    setDescription("");
    setCreateStarterProfile(true);
    setCompetitors("");
    setCompetitorsKnowledge("");
    setDiscoveryIntent("");
    setDiscoveryActorType("");
    setDiscoveryKnownNames("");
    setOwnOffer("");
    setSegments("");
    setGeographies("");
    setBuyers("");
    setHorizon("");
    setKeywords("");
    setCpv("");
    setSources("PLACSP, fuentes oficiales, noticias");
    setParticipation("");
    setExclusion("");
    setIndicators("");
    setActiveOnCreate(true);
    setReviewing(false);
    setReadiness(null);
    setStep("context");
    setSectors("");
    setChannels("");
    setPartners("");
    setRegulators("");
    setBarriers("");
    setDecisionToMake("");
    setMarketCountries([...PRIORITY_COUNTRY_CODES]);
    setMarketLanguages(languagesForCountries(PRIORITY_COUNTRY_CODES).join(", "));
    setLanguagesTouched(false);
    setError(null);
  }

  function changeType(value: string) {
    setType(value);
    setReviewing(false);
    setReadiness(null);
    setStep("context");
    setCompetitorsKnowledge("");
    setDiscoveryIntent("");
    setDiscoveryActorType("");
    setDiscoveryKnownNames("");
  }

  function changeMarketCountries(next: string[]) {
    setMarketCountries(next);
    if (!languagesTouched) {
      setMarketLanguages(languagesForCountries(next).join(", "));
    }
  }

  function setCompetitorsText(value: string) {
    setCompetitors(value);
    if (value.trim()) {
      setCompetitorsKnowledge("known");
    }
  }

  function chooseCompetitorsKnowledge(value: CompetitorsKnowledge) {
    setCompetitorsKnowledge(value);
    if (value !== "known") {
      setCompetitors("");
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (isMarket && !marketStepReady) {
      setError(
        marketBlockers.length === 1
          ? `Falta: ${marketBlockers[0]}.`
          : `Completa lo pendiente: ${marketBlockers.join("; ")}.`,
      );
      return;
    }
    if (
      type === "competitive_intelligence" &&
      (!title.trim() || !goal.trim() || !ownOffer.trim() || !competitors.trim())
    ) {
      setError("Completa nombre, objetivo, oferta propia y al menos un competidor.");
      return;
    }
    if (!isMarket && type !== "competitive_intelligence" && (!title.trim() || !goal.trim())) {
      setError("Completa el nombre y el objetivo estratégico.");
      return;
    }
    if (type === "competitive_intelligence" && !reviewing) {
      setBusy(true);
      setError(null);
      try {
        setReadiness(await api.dossiers.competitiveReadiness());
        setReviewing(true);
      } catch (reason) {
        setError(reason instanceof ApiError ? reason.problem.detail : "No se pudieron comprobar IA y Signal.");
      } finally {
        setBusy(false);
      }
      return;
    }
    if (isMarket && step !== "decision") {
      if (step === "ecosystem") {
        setBusy(true);
        setError(null);
        try {
          setReadiness(await api.dossiers.competitiveReadiness());
          setStep("decision");
        } catch (reason) {
          setError(reason instanceof ApiError ? reason.problem.detail : "No se pudieron comprobar IA y Signal.");
        } finally {
          setBusy(false);
        }
      } else {
        setError(null);
        setStep(step === "context" ? "scope" : "ecosystem");
      }
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const intentNormalized = normalizeDiscoveryIntent(discoveryIntent);
      const hasActorDiscovery =
        intentNormalized.length >= DISCOVERY_INTENT_MIN &&
        intentNormalized.length <= DISCOVERY_INTENT_MAX &&
        Boolean(discoveryActorType);
      const knowledge: CompetitorsKnowledge =
        competitorsKnowledge === "known" || list(competitors).length > 0
          ? "known"
          : competitorsKnowledge === "not_seeking"
            ? "not_seeking"
            : competitorsKnowledge === "unknown"
              ? "unknown"
              : hasActorDiscovery
                ? "not_seeking"
                : "unknown";
      const competitorNames =
        knowledge === "known" ? list(competitors).map((name) => ({ name, aliases: [] as string[] })) : [];
      const dossier = await api.dossiers.create({
        title: title.trim(),
        type,
        strategic_goal: goal.trim(),
        description: description.trim(),
        create_starter_profile: createStarterProfile,
        accept_creation_intent: true,
        initial_status:
          (type === "competitive_intelligence" || isMarket) && activeOnCreate ? "active" : "draft",
        ...(type === "competitive_intelligence" ? { profile_config: {
          own_offer: ownOffer.trim(),
          competitors: list(competitors).map((name) => ({ name, aliases: [] })),
          segments: list(segments),
          geographies: list(geographies),
          target_buyers: list(buyers),
          horizon: horizon.trim(),
          business_objective: goal.trim(),
          keywords: list(keywords),
          cpv: list(cpv),
          sources: list(sources),
          participation_criteria: participation.trim(),
          exclusion_criteria: exclusion.trim(),
          success_indicators: list(indicators),
        }} : {}),
        ...(isMarket ? {
          geography: marketCountries,
          sectors: list(sectors),
          languages: list(marketLanguages).map((item) => item.toLowerCase()),
          profile_config: {
            own_offer: ownOffer.trim(),
            decision_to_make: decisionToMake.trim(),
            horizon: horizon.trim(),
            segments: list(segments),
            channels: list(channels),
            target_buyers: list(buyers),
            competitors: competitorNames,
            competitors_knowledge: knowledge,
            // G-19: free-text intent stored separately (never title+goal concat).
            ...(hasActorDiscovery
              ? {
                  discovery_intent: intentNormalized,
                  discovery_actor_type: discoveryActorType,
                  discovery_known_names: list(discoveryKnownNames),
                }
              : {}),
            partners: list(partners),
            regulators: list(regulators),
            barriers: list(barriers),
            success_indicators: list(indicators),
            keywords: list(keywords),
          },
        } : {}),
      });
      if (isMarket) {
        try {
          // Prefill efímero de UX: no es memoria durable ni sustituye profile_config.
          // Si sessionStorage no está disponible, el expediente ya está creado con el perfil.
          const entityNames =
            knowledge === "known"
              ? [...new Set([...list(competitors), ...list(partners), ...list(regulators)])]
              : [...new Set([...list(partners), ...list(regulators)])];
          sessionStorage.setItem(
            `oracle:wizard-prefill:${dossier.id}:monitor`,
            JSON.stringify({
              name: `Radar de mercado: ${title.trim()}`.slice(0, 200),
              query: "",
              keywords: [...new Set([...list(keywords), ...list(segments), ...list(channels)])].slice(0, 50),
              entities: entityNames.slice(0, 50),
              languages: list(marketLanguages).map((item) => item.toLowerCase()),
              geographies: marketCountries,
              source_types: ["news", "company_signal", "regulatory_signal", "official_publication"],
              cadence: "daily",
              competitors_knowledge: knowledge,
            }),
          );
        } catch {
          // sessionStorage puede no estar disponible; el prefill es opcional.
        }
      }
      // G-19: after market dossier exists, enqueue actor discovery from server-owned profile.
      // Client sends only dossier_id + deterministic Idempotency-Key for this creation.
      let discoveryEnqueueFailed = false;
      if (isMarket && hasActorDiscovery) {
        try {
          await api.marketActorDiscovery.run(
            { dossier_id: dossier.id },
            `g19-actor-run:${dossier.id}:intake`.slice(0, 200),
          );
        } catch {
          discoveryEnqueueFailed = true;
        }
      }
      onOpenChange(false);
      const createdMarket = isMarket;
      const goActors = Boolean(createdMarket && hasActorDiscovery);
      resetForm();
      if (discoveryEnqueueFailed) {
        // Dossier already exists — never present "could not create" or re-submit create.
        toast.message("Expediente creado; descubrimiento pendiente", {
          description:
            "El expediente de mercado ya está guardado. Puedes reintentar el descubrimiento de actores en la sección Actores.",
        });
      } else {
        toast.success("Expediente creado", {
          description: goActors
            ? "Se ha encolado el descubrimiento de actores. Revisa el resultado en Actores."
            : createdMarket
              ? "Se ha creado con su base de mercado editable. Revisa la vigilancia antes de activar el radar."
              : type === "competitive_intelligence" && activeOnCreate
                ? "Se ha creado activo con su base competitiva editable."
                : "Se ha creado como borrador en el espacio de trabajo principal.",
        });
      }
      router.push(
        goActors
          ? `/app/dossiers/${dossier.id}/actors`
          : createdMarket
            ? `/app/dossiers/${dossier.id}/settings?wizard_prefill=monitor`
            : `/app/dossiers/${dossier.id}`,
      );
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.problem.detail
          : "No se pudo crear el expediente.",
      );
    } finally {
      setBusy(false);
    }
  }

  const commonFields = (
    <>
      <label className="field">
        <span id="dossier-title-label">Nombre</span>
        <input
          aria-labelledby="dossier-title-label"
          required
          minLength={2}
          maxLength={240}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          autoFocus
        />
      </label>
      <label className="field">
        <span id="dossier-type-label">Tipo</span>
        <select
          aria-labelledby="dossier-type-label"
          aria-describedby="dossier-type-help dossier-type-options"
          value={type}
          onChange={(event) => changeType(event.target.value)}
        >
          {DOSSIER_TYPES.map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
        <small id="dossier-type-help">{selectedProfile.description}</small>
      </label>
      <section className="dossier-type-help" id="dossier-type-options" aria-label="Ayuda para elegir tipo de expediente">
        <strong>¿Cuándo elegir este tipo?</strong>
        <p>{selectedProfile.bestFor}</p>
        <details>
          <summary>Comparar todos los tipos</summary>
          <div className="dossier-type-help-grid">
            {DOSSIER_TYPES.map(([value, label]) => {
              const profile = starterProfileFor(value);
              return (
                <button
                  className={value === type ? "selected" : ""}
                  key={value}
                  type="button"
                  aria-pressed={value === type}
                  onClick={() => changeType(value)}
                >
                  <strong>{label}</strong>
                  <span>{profile.description}</span>
                  <small>{profile.bestFor}</small>
                </button>
              );
            })}
          </div>
        </details>
      </section>
      <label className="field">
        <span id="dossier-goal-label">Objetivo estratégico</span>
        <textarea
          aria-labelledby="dossier-goal-label"
          required
          maxLength={5000}
          value={goal}
          onChange={(event) => setGoal(event.target.value)}
        />
      </label>
      <label className="field">
        <span id="dossier-description-label">Descripción (opcional)</span>
        <textarea
          aria-labelledby="dossier-description-label"
          maxLength={10000}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
      </label>
    </>
  );

  const starterField = (
    <label className="field full">
      <span>Base de trabajo</span>
      <span className="checkbox-row">
        <input
          type="checkbox"
          aria-label="Crear una base inicial editable"
          checked={createStarterProfile}
          onChange={(event) =>
            setCreateStarterProfile(event.target.checked)
          }
        />
        <span>Crear una base inicial editable</span>
      </span>
      <small>
        {createStarterProfile
          ? `${selectedProfile.focus} No activará fuentes ni monitores externos.`
          : "El expediente se creará vacío; podrás añadir estos elementos desde su configuración."}
      </small>
    </label>
  );

  const marketPendingSummary =
    isMarket && marketBlockers.length > 0 ? (
      <div
        className="step-pending-requirements"
        role="status"
        aria-live="polite"
        data-testid="market-step-pending"
      >
        <strong>Para continuar falta:</strong>
        <ul>
          {marketBlockers.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </div>
    ) : null;

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content create-product-dialog">
          <Dialog.Title>Nuevo expediente</Dialog.Title>
          <Dialog.Description>
            {isMarket
              ? "Delimita el mercado paso a paso: la base y la vigilancia se prepararán con lo que definas aquí."
              : "Define el contexto mínimo. Podrás completar objetivos, miembros y fuentes desde la configuración del expediente."}
          </Dialog.Description>
          <Dialog.Close className="dialog-close" aria-label="Cerrar">
            <X size={18} />
          </Dialog.Close>
          <form onSubmit={submit} noValidate={isMarket}>
            {isMarket && (
              <header className="market-wizard-progress" aria-live="polite">
                <span className="eyebrow">Paso {stepIndex + 1} de {MARKET_STEPS.length}</span>
                <strong>{MARKET_STEPS[stepIndex][1]}</strong>
                <p>{MARKET_STEPS[stepIndex][2]}</p>
              </header>
            )}
            {(!isMarket || step === "context") && commonFields}
            {isMarket && step === "scope" && (
              <section className="competitive-intake-fields" aria-labelledby="market-scope-title">
                <header>
                  <h2 id="market-scope-title">Alcance de mercado</h2>
                  <p>Estos datos delimitan el análisis y alimentan la vigilancia y la IA del expediente.</p>
                </header>
                <label className="field full">
                  <span>Oferta o capacidades propias</span>
                  <input required value={ownOffer} onChange={(event) => setOwnOffer(event.target.value)} placeholder="Ej. Integración de sistemas de baterías y O&M" />
                </label>
                <label className="field"><span>Sector</span><input value={sectors} onChange={(event) => setSectors(event.target.value)} placeholder="Ej. almacenamiento energético" /></label>
                <label className="field"><span>Segmentos</span><input value={segments} onChange={(event) => setSegments(event.target.value)} placeholder="Separados por comas" /></label>
                <EuCountryMultiSelect
                  label="Países objetivo"
                  value={marketCountries}
                  onChange={changeMarketCountries}
                  hint="Ámbito global: España y Alemania van preseleccionados; puedes añadir cualquier país ISO-2 (p. ej. US, MX, JP)."
                />
                <label className="field">
                  <span>Idiomas de la vigilancia</span>
                  <input
                    value={marketLanguages}
                    onChange={(event) => { setMarketLanguages(event.target.value); setLanguagesTouched(true); }}
                    placeholder="es, de"
                  />
                  <small>Sugeridos según los países seleccionados; edítalos si necesitas otros.</small>
                </label>
                <label className="field"><span>Horizonte temporal</span><input value={horizon} onChange={(event) => setHorizon(event.target.value)} placeholder="Ej. decidir antes de diciembre" /></label>
              </section>
            )}
            {isMarket && step === "ecosystem" && (
              <section className="competitive-intake-fields" aria-labelledby="market-ecosystem-title">
                <header>
                  <h2 id="market-ecosystem-title">Ecosistema del mercado</h2>
                  <p>
                    Si conoces competidores, nómbralos para excluirlos del descubrimiento.
                    Si aún no lo sabes o no buscas competidores, dilo con honestidad: no hace
                    falta inventar nombres.
                  </p>
                </header>
                <fieldset className="field full competitors-knowledge" data-testid="competitors-knowledge">
                  <legend>Competidores</legend>
                  <div className="competitors-knowledge-options" role="radiogroup" aria-label="Conocimiento de competidores">
                    {(Object.keys(COMPETITORS_KNOWLEDGE_LABELS) as CompetitorsKnowledge[]).map((value) => (
                      <label key={value} className="checkbox-row">
                        <input
                          type="radio"
                          name="competitors_knowledge"
                          value={value}
                          checked={competitorsKnowledge === value}
                          onChange={() => chooseCompetitorsKnowledge(value)}
                        />
                        <span>{COMPETITORS_KNOWLEDGE_LABELS[value]}</span>
                      </label>
                    ))}
                  </div>
                  {competitorsKnowledge === "known" && (
                    <>
                      <input
                        value={competitors}
                        onChange={(event) => setCompetitorsText(event.target.value)}
                        placeholder="Una o varias razones sociales, separadas por comas"
                        aria-label="Nombres de competidores"
                      />
                      <small>
                        Estos nombres se envían al agente de descubrimiento como lista de exclusión
                        (no los volverá a proponer). Podrás resolver alias después desde Actores.
                      </small>
                    </>
                  )}
                  {competitorsKnowledge === "unknown" && (
                    <small data-testid="competitors-unknown-hint">
                      Se registrará la intención «aún no lo sé». El agente de descubrimiento
                      buscará candidatos sin lista de exclusión inventada.
                    </small>
                  )}
                  {competitorsKnowledge === "not_seeking" && (
                    <small data-testid="competitors-not-seeking-hint">
                      Se registrará la intención «no busco competidores». El agente no tratará
                      una lista vacía como si hubieras declarado rivales.
                    </small>
                  )}
                </fieldset>
                <fieldset className="field full" data-testid="discovery-intent-fieldset">
                  <legend>¿A quién quieres encontrar y para qué?</legend>
                  <p className="muted">
                    Intención libre para el agente de actores (no competidores). Se guarda tal cual,
                    sin mezclarla con el título ni la meta del expediente.
                  </p>
                  <label className="field full">
                    <span id="discovery-intent-label">Intención de búsqueda</span>
                    <textarea
                      aria-labelledby="discovery-intent-label"
                      data-testid="discovery-intent"
                      maxLength={DISCOVERY_INTENT_MAX}
                      value={discoveryIntent}
                      onChange={(event) => setDiscoveryIntent(event.target.value)}
                      placeholder="Ej. quiero contactar con grupos de investigación en Francia que trabajen en grafeno"
                    />
                    <small>
                      Entre {DISCOVERY_INTENT_MIN} y {DISCOVERY_INTENT_MAX} caracteres si la usas.
                      Espacios en blanco solos no valen.
                    </small>
                  </label>
                  <label className="field">
                    <span id="discovery-actor-type-label">Tipo de actor</span>
                    <select
                      aria-labelledby="discovery-actor-type-label"
                      data-testid="discovery-actor-type"
                      value={discoveryActorType}
                      onChange={(event) =>
                        setDiscoveryActorType(event.target.value as DiscoveryActorType | "")
                      }
                    >
                      <option value="">— Sin búsqueda de actores —</option>
                      {(Object.keys(DISCOVERY_ACTOR_TYPE_LABELS) as DiscoveryActorType[]).map(
                        (value) => (
                          <option key={value} value={value}>
                            {DISCOVERY_ACTOR_TYPE_LABELS[value]}
                          </option>
                        ),
                      )}
                    </select>
                  </label>
                  <label className="field full">
                    <span>Ya conocidos para este objetivo (opcional)</span>
                    <input
                      data-testid="discovery-known-names"
                      value={discoveryKnownNames}
                      onChange={(event) => setDiscoveryKnownNames(event.target.value)}
                      placeholder="Solo nombres a excluir para este objetivo, separados por comas"
                    />
                    <small>
                      No se rellenan automáticamente partners, reguladores ni competidores del perfil.
                    </small>
                  </label>
                </fieldset>
                <label className="field"><span>Clientes o compradores objetivo</span><input value={buyers} onChange={(event) => setBuyers(event.target.value)} placeholder="Ej. operadores de red, utilities" /></label>
                <label className="field"><span>Canales de entrada</span><input value={channels} onChange={(event) => setChannels(event.target.value)} placeholder="Ej. licitación pública, partner local" /></label>
                <label className="field"><span>Posibles partners</span><input value={partners} onChange={(event) => setPartners(event.target.value)} placeholder="Separados por comas" /></label>
                <label className="field"><span>Reguladores</span><input value={regulators} onChange={(event) => setRegulators(event.target.value)} placeholder="Ej. CNMC, Bundesnetzagentur" /></label>
                <label className="field"><span>Barreras de entrada</span><input value={barriers} onChange={(event) => setBarriers(event.target.value)} placeholder="Separadas por comas" /><small>Se registrarán como riesgos abiertos pendientes de evidencia.</small></label>
                <label className="field full"><span>Palabras clave</span><input value={keywords} onChange={(event) => setKeywords(event.target.value)} placeholder="Términos separados por comas" /></label>
              </section>
            )}
            {isMarket && step === "decision" && (
              <>
                <section className="competitive-intake-fields" aria-labelledby="market-decision-title">
                  <header>
                    <h2 id="market-decision-title">Decisión a tomar</h2>
                    <p>Oracle prioriza señales y análisis en función de esta decisión, no solo del tema.</p>
                  </header>
                  <label className="field full">
                    <span>Decisión concreta</span>
                    <textarea required maxLength={2000} value={decisionToMake} onChange={(event) => setDecisionToMake(event.target.value)} placeholder="Ej. decidir si entramos en el mercado y mediante qué canal" />
                  </label>
                  <label className="field full"><span>Criterios de éxito</span><input value={indicators} onChange={(event) => setIndicators(event.target.value)} placeholder="Separados por comas" /></label>
                  <label className="checkbox-row full">
                    <input type="checkbox" checked={activeOnCreate} onChange={(event) => setActiveOnCreate(event.target.checked)} />
                    <span><strong>Crear activo</strong><small>{activeOnCreate ? "La vigilancia y los análisis podrán ponerse en marcha cuando sus dependencias estén disponibles." : "En borrador no se ejecutarán la vigilancia ni los análisis programados hasta activarlo."}</small></span>
                  </label>
                </section>
                <section className="competitive-review" aria-labelledby="market-review-title">
                  <h2 id="market-review-title">Revisión antes de crear</h2>
                  <dl>
                    <div><dt>Oferta propia</dt><dd>{ownOffer}</dd></div>
                    <div><dt>Países</dt><dd>{marketCountries.map(euCountryName).join(", ")}</dd></div>
                    <div>
                      <dt>Competidores</dt>
                      <dd>
                        {competitorsKnowledge === "known"
                          ? list(competitors).join(", ") || "—"
                          : competitorsKnowledge
                            ? COMPETITORS_KNOWLEDGE_LABELS[competitorsKnowledge]
                            : "—"}
                      </dd>
                    </div>
                    <div>
                      <dt>Actores a encontrar</dt>
                      <dd>
                        {discoveryActorType
                          ? `${DISCOVERY_ACTOR_TYPE_LABELS[discoveryActorType]}: ${normalizeDiscoveryIntent(discoveryIntent) || "—"}`
                          : "—"}
                      </dd>
                    </div>
                    <div><dt>Estado inicial</dt><dd>{activeOnCreate ? "Activo" : "Borrador"}</dd></div>
                    <div className="full"><dt>Base generada</dt><dd>Objetivo, hipótesis, actores con roles, decisión propuesta, riesgos desde barreras, vigilancia preparada y tres tareas.</dd></div>
                  </dl>
                  <h3>Dependencias</h3>
                  {readiness?.checks.map((check) => (
                    <article key={check.key} className={check.ready ? "ready" : "pending"}>
                      {check.ready ? <CheckCircle2 aria-hidden="true" /> : <AlertTriangle aria-hidden="true" />}
                      <div><strong>{check.label}</strong><p>{check.detail}</p>{!check.ready && <Link href={check.action_href}>Resolver en Administración</Link>}</div>
                    </article>
                  ))}
                  {!readiness?.ready && <p className="inline-warning">Puedes crear el expediente, pero la IA o la vigilancia no funcionarán hasta resolver estos puntos.</p>}
                </section>
              </>
            )}
            {type === "competitive_intelligence" && (
              <section className="competitive-intake-fields" aria-labelledby="competitive-intake-title">
                <header>
                  <h2 id="competitive-intake-title">Alcance competitivo</h2>
                  <p>Define el radar inicial. Los datos manuales no recibirán una confianza inventada: quedarán pendientes de evidencia.</p>
                </header>
                <label className="field full">
                  <span>Empresa o producto propio</span>
                  <input required value={ownOffer} onChange={(event) => setOwnOffer(event.target.value)} placeholder="Ej. Vehículos industriales y servicio posventa" />
                </label>
                <label className="field full">
                  <span>Competidores</span>
                  <input required value={competitors} onChange={(event) => setCompetitors(event.target.value)} placeholder="Una o varias razones sociales, separadas por comas" />
                  <small>Podrás resolver alias y variantes registrales después desde Actores.</small>
                </label>
                <label className="field"><span>Segmentos</span><input value={segments} onChange={(event) => setSegments(event.target.value)} placeholder="Separados por comas" /></label>
                <label className="field"><span>Países y regiones</span><input value={geographies} onChange={(event) => setGeographies(event.target.value)} placeholder="Separados por comas" /></label>
                <label className="field"><span>Compradores objetivo</span><input value={buyers} onChange={(event) => setBuyers(event.target.value)} placeholder="Organismos o grupos compradores" /></label>
                <label className="field"><span>Horizonte temporal</span><input value={horizon} onChange={(event) => setHorizon(event.target.value)} placeholder="Ej. próximos 24 meses" /></label>
                <label className="field"><span>Palabras clave</span><input value={keywords} onChange={(event) => setKeywords(event.target.value)} placeholder="Términos separados por comas" /></label>
                <label className="field"><span>Códigos CPV</span><input value={cpv} onChange={(event) => setCpv(event.target.value)} placeholder="Ej. 34144210" /></label>
                <label className="field full"><span>Fuentes</span><input value={sources} onChange={(event) => setSources(event.target.value)} /></label>
                <label className="field"><span>Criterios para participar</span><textarea value={participation} onChange={(event) => setParticipation(event.target.value)} /></label>
                <label className="field"><span>Criterios para no participar</span><textarea value={exclusion} onChange={(event) => setExclusion(event.target.value)} /></label>
                <label className="field full"><span>Indicadores de éxito</span><input value={indicators} onChange={(event) => setIndicators(event.target.value)} placeholder="Separados por comas" /></label>
                <label className="checkbox-row full">
                  <input type="checkbox" checked={activeOnCreate} onChange={(event) => setActiveOnCreate(event.target.checked)} />
                  <span><strong>Crear activo</strong><small>{activeOnCreate ? "La vigilancia y los análisis podrán ponerse en marcha cuando sus dependencias estén disponibles." : "En borrador no se ejecutarán la vigilancia ni los análisis programados hasta activarlo."}</small></span>
                </label>
              </section>
            )}
            {/* Base inicial: en pantallas de un solo paso va aquí; en wizards multi-paso
                solo al final, para no rellenar cuatro pantallas y crear un expediente vacío. */}
            {!isMarket && type !== "competitive_intelligence" && starterField}
            {isMarket && step === "decision" && starterField}
            {type === "competitive_intelligence" && reviewing && starterField}
            {marketPendingSummary}
            {error && <p className="form-error" role="alert">{error}</p>}
            {type === "competitive_intelligence" && reviewing && (
              <section className="competitive-review" aria-labelledby="competitive-review-title">
                <h2 id="competitive-review-title">Revisión antes de crear</h2>
                <dl>
                  <div><dt>Oferta propia</dt><dd>{ownOffer}</dd></div>
                  <div><dt>Competidores</dt><dd>{list(competitors).join(", ")}</dd></div>
                  <div><dt>Estado inicial</dt><dd>{activeOnCreate ? "Activo" : "Borrador"}</dd></div>
                  <div><dt>Base generada</dt><dd>Objetivo, hipótesis, actores, vigilancia y tres tareas específicas</dd></div>
                </dl>
                <h3>Dependencias</h3>
                {readiness?.checks.map((check) => (
                  <article key={check.key} className={check.ready ? "ready" : "pending"}>
                    {check.ready ? <CheckCircle2 aria-hidden="true" /> : <AlertTriangle aria-hidden="true" />}
                    <div><strong>{check.label}</strong><p>{check.detail}</p>{!check.ready && <Link href={check.action_href}>Resolver en Administración</Link>}</div>
                  </article>
                ))}
                {!readiness?.ready && <p className="inline-warning">Puedes crear el expediente, pero la IA o la vigilancia no funcionarán hasta resolver estos puntos.</p>}
              </section>
            )}
            <div className="dialog-actions">
              {reviewing && <button className="vector-secondary" type="button" onClick={() => setReviewing(false)}>Volver a editar</button>}
              {isMarket && step !== "context" && (
                <button
                  className="vector-secondary"
                  type="button"
                  onClick={() => { setError(null); setStep(MARKET_STEPS[stepIndex - 1][0]); }}
                >
                  Atrás
                </button>
              )}
              <Dialog.Close className="vector-secondary" type="button">
                Cancelar
              </Dialog.Close>
              <AsyncActionButton
                className="vector-primary"
                type="submit"
                disabled={
                  isMarket
                    ? false
                    : !title.trim() || !goal.trim() || (type === "competitive_intelligence" && (!ownOffer.trim() || !competitors.trim()))
                }
                loading={busy}
                aria-describedby={isMarket && !marketStepReady ? "market-step-pending-desc" : undefined}
              >
                <FilePlus2 size={16} />
                {busy
                  ? "Procesando…"
                  : isMarket && step !== "decision"
                    ? "Continuar"
                    : type === "competitive_intelligence" && !reviewing
                      ? "Revisar expediente"
                      : "Crear expediente"}
              </AsyncActionButton>
            </div>
            {isMarket && !marketStepReady && (
              <p id="market-step-pending-desc" className="sr-only">
                Hay requisitos pendientes en este paso.
              </p>
            )}
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
