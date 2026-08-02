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

type MarketStep = (typeof MARKET_STEPS)[number][0];

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

  function resetForm() {
    setTitle("");
    setGoal("");
    setDescription("");
    setCreateStarterProfile(true);
    setCompetitors("");
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
  }

  function changeMarketCountries(next: string[]) {
    setMarketCountries(next);
    if (!languagesTouched) {
      setMarketLanguages(languagesForCountries(next).join(", "));
    }
  }

  const marketStepReady =
    step === "context"
      ? title.trim().length >= 2 && Boolean(goal.trim())
      : step === "scope"
        ? Boolean(ownOffer.trim()) && marketCountries.length > 0
        : step === "ecosystem"
          ? list(competitors).length > 0
          : Boolean(decisionToMake.trim());

  async function submit(event: FormEvent) {
    event.preventDefault();
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
            competitors: list(competitors).map((name) => ({ name, aliases: [] })),
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
          sessionStorage.setItem(
            `oracle:wizard-prefill:${dossier.id}:monitor`,
            JSON.stringify({
              name: `Radar de mercado: ${title.trim()}`.slice(0, 200),
              query: "",
              keywords: [...new Set([...list(keywords), ...list(segments), ...list(channels)])].slice(0, 50),
              entities: [...new Set([...list(competitors), ...list(partners), ...list(regulators)])].slice(0, 50),
              languages: list(marketLanguages).map((item) => item.toLowerCase()),
              geographies: marketCountries,
              source_types: ["news", "company_signal", "regulatory_signal", "official_publication"],
              cadence: "daily",
            }),
          );
        } catch {
          // sessionStorage puede no estar disponible; el prefill es opcional.
        }
      }
      onOpenChange(false);
      const createdMarket = isMarket;
      resetForm();
      toast.success("Expediente creado", {
        description: createdMarket
          ? "Se ha creado con su base de mercado editable. Revisa la vigilancia antes de activar el radar."
          : type === "competitive_intelligence" && activeOnCreate
            ? "Se ha creado activo con su base competitiva editable."
            : "Se ha creado como borrador en el espacio de trabajo principal.",
      });
      router.push(
        createdMarket
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
          <form onSubmit={submit}>
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
                  <p>Los nombres propios son los que permiten vigilar el mercado: sin al menos una empresa nombrada, el radar no podrá producir señales.</p>
                </header>
                <label className="field full">
                  <span>Competidores</span>
                  <input required value={competitors} onChange={(event) => setCompetitors(event.target.value)} placeholder="Una o varias razones sociales, separadas por comas" />
                  <small>Podrás resolver alias y variantes registrales después desde Actores.</small>
                </label>
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
                    <div><dt>Competidores</dt><dd>{list(competitors).join(", ")}</dd></div>
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
            {(!isMarket || step === "context") && starterField}
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
                    ? !marketStepReady
                    : !title.trim() || !goal.trim() || (type === "competitive_intelligence" && (!ownOffer.trim() || !competitors.trim()))
                }
                loading={busy}
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
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
