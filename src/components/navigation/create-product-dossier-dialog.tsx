"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { ApiError, api } from "@oracle/api-client";
import { AlertTriangle, CheckCircle2, FilePlus2, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { toast } from "sonner";
import { AsyncActionButton } from "@/components/ui/async-action-button";
import { starterProfileFor } from "@/lib/dossier-starter-profiles";

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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selectedProfile = starterProfileFor(type);

  const list = (value: string) => value.split(",").map((item) => item.trim()).filter(Boolean);

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
    setBusy(true);
    setError(null);
    try {
      const dossier = await api.dossiers.create({
        title: title.trim(),
        type,
        strategic_goal: goal.trim(),
        description: description.trim(),
        create_starter_profile: createStarterProfile,
        initial_status: type === "competitive_intelligence" && activeOnCreate ? "active" : "draft",
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
      });
      onOpenChange(false);
      setTitle("");
      setGoal("");
      setDescription("");
      setCreateStarterProfile(true);
      setReviewing(false);
      setReadiness(null);
      toast.success("Expediente creado", {
        description: type === "competitive_intelligence" && activeOnCreate
          ? "Se ha creado activo con su base competitiva editable."
          : "Se ha creado como borrador en el espacio de trabajo principal.",
      });
      router.push(`/app/dossiers/${dossier.id}`);
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

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content create-product-dialog">
          <Dialog.Title>Nuevo expediente</Dialog.Title>
          <Dialog.Description>
            Define el contexto mínimo. Podrás completar objetivos, miembros y
            fuentes desde la configuración del expediente.
          </Dialog.Description>
          <Dialog.Close className="dialog-close" aria-label="Cerrar">
            <X size={18} />
          </Dialog.Close>
          <form onSubmit={submit}>
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
                onChange={(event) => { setType(event.target.value); setReviewing(false); setReadiness(null); }}
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
                        onClick={() => { setType(value); setReviewing(false); setReadiness(null); }}
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
              <Dialog.Close className="vector-secondary" type="button">
                Cancelar
              </Dialog.Close>
              <AsyncActionButton className="vector-primary" type="submit" disabled={!title.trim() || !goal.trim() || (type === "competitive_intelligence" && (!ownOffer.trim() || !competitors.trim()))} loading={busy}>
                <FilePlus2 size={16} />
                {busy ? "Procesando…" : type === "competitive_intelligence" && !reviewing ? "Revisar expediente" : "Crear expediente"}
              </AsyncActionButton>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
