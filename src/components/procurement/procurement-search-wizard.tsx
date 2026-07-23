"use client";

import * as Dialog from "@radix-ui/react-dialog";
import {
  ApiError,
  api,
  type ComparableProcurementProfile,
  type CreateProcurementSearchProfile,
  type ProcurementSearchProfile,
  type TenderSearchPlan,
  type TenderSearchPlanPreviewResponse,
  type TenderSearchWizardArtifact,
} from "@oracle/api-client";
import {
  Check,
  ChevronLeft,
  Eye,
  Plus,
  Save,
  Sparkles,
  X,
} from "lucide-react";
import {
  type FormEvent,
  type KeyboardEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { PermissionGate } from "@/components/auth/auth-boundary";
import { JobProgress } from "@/components/reporting/job-progress";
import { AsyncActionButton } from "@/components/ui/async-action-button";
import { ProcurementAutocomplete } from "./procurement-autocomplete";
import {
  addMissingMeasuredCandidates,
  applyChipsToTenderSearchPlan,
  createUserTenderSearchChip,
  findMissingMeasuredBuyers,
  findMissingMeasuredCandidates,
  mergeRegeneratedTenderSearchPlan,
  tenderSearchChipKey,
  tenderSearchPlanToChips,
  type TenderSearchChip,
  type TenderSearchChipCategory,
} from "./procurement-search-wizard-model";

const CATEGORY_COPY: Record<
  TenderSearchChipCategory,
  { label: string; placeholder: string }
> = {
  include_terms: {
    label: "Términos principales",
    placeholder: "Añadir término",
  },
  synonyms: { label: "Sinónimos", placeholder: "Añadir sinónimo" },
  exclude_terms: {
    label: "Términos excluidos",
    placeholder: "Añadir exclusión",
  },
  candidate_cpv: { label: "CPV candidatos", placeholder: "" },
  buyers: { label: "Compradores", placeholder: "Añadir comprador" },
  geographies: { label: "Geografías", placeholder: "Añadir geografía" },
};

const EDITABLE_CATEGORIES = [
  "include_terms",
  "synonyms",
  "exclude_terms",
  "buyers",
  "geographies",
] as const;

type Step = "describe" | "review";

interface ProcurementSearchWizardProps {
  onWatchSaved?: () => void | Promise<void>;
}

interface ComparableCacheValue {
  profile: ComparableProcurementProfile;
  savedAt: number;
}

function cacheKey(company: string) {
  return `oracle:procurement-comparable:${company.trim().toLocaleLowerCase("es")}`;
}

function readComparableCache(company: string): ComparableCacheValue | null {
  try {
    const raw = window.sessionStorage.getItem(cacheKey(company));
    if (!raw) return null;
    return JSON.parse(raw) as ComparableCacheValue;
  } catch {
    return null;
  }
}

function writeComparableCache(
  company: string,
  profile: ComparableProcurementProfile,
) {
  try {
    window.sessionStorage.setItem(
      cacheKey(company),
      JSON.stringify({ profile, savedAt: Date.now() }),
    );
  } catch {
    // La caché de sesión es una mejora; el perfil recibido sigue siendo utilizable.
  }
}

function numberOrNull(value: string): number | null {
  if (!value.trim()) return null;
  const number = Number(value.replace(",", "."));
  return Number.isFinite(number) ? number : null;
}

function qualitativeConfidence(confidence: number) {
  if (confidence >= 75) return "Alta";
  if (confidence >= 45) return "Media";
  return "Baja";
}

function problemMessage(reason: unknown, fallback: string) {
  return reason instanceof ApiError
    ? reason.problem.detail || fallback
    : fallback;
}

function structuredFieldErrors(reason: unknown): Record<string, string> {
  if (!(reason instanceof ApiError) || !reason.problem.errors) return {};
  const result: Record<string, string> = {};
  const visit = (value: unknown, path = "") => {
    if (typeof value === "string") {
      result[path || "general"] = value;
      return;
    }
    if (Array.isArray(value)) {
      value.forEach((item, index) => visit(item, path || String(index)));
      return;
    }
    if (value && typeof value === "object") {
      Object.entries(value).forEach(([key, item]) =>
        visit(item, path ? `${path}.${key}` : key),
      );
    }
  };
  visit(reason.problem.errors);
  return result;
}

function applyDescribeOverrides(
  plan: TenderSearchPlan,
  geography: string,
  minimum: string,
  maximum: string,
) {
  const next = { ...plan };
  const normalizedGeography = geography.trim();
  if (
    normalizedGeography &&
    !next.geographies.some(
      (item) =>
        item.toLocaleLowerCase("es") ===
        normalizedGeography.toLocaleLowerCase("es"),
    )
  ) {
    next.geographies = [...next.geographies, normalizedGeography];
  }
  if (minimum.trim()) next.min_amount = numberOrNull(minimum);
  if (maximum.trim()) next.max_amount = numberOrNull(maximum);
  return next;
}

function isWizardArtifact(value: unknown): value is TenderSearchWizardArtifact {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<TenderSearchWizardArtifact>;
  return typeof candidate.id === "string" && Boolean(candidate.output);
}

function acceptedPlan(
  plan: TenderSearchPlan,
): CreateProcurementSearchProfile["accepted_plan"] {
  return {
    ...plan,
    min_amount: plan.min_amount ?? null,
    max_amount: plan.max_amount ?? null,
  };
}

function PlanChip({
  chip,
  onConfirm,
  onRemove,
}: {
  chip: TenderSearchChip;
  onConfirm: () => void;
  onRemove: () => void;
}) {
  function removeWithKeyboard(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key !== "Backspace" && event.key !== "Delete") return;
    event.preventDefault();
    onRemove();
  }

  return (
    <span
      className={`procurement-wizard-chip origin-${chip.provenance}`}
      data-origin={chip.provenance}
    >
      <span>
        {chip.label && chip.category === "candidate_cpv"
          ? `${chip.value} · ${chip.label}`
          : chip.value}
      </span>
      <small>
        {chip.provenance === "measured"
          ? "Medido"
          : chip.provenance === "user"
            ? "Usuario"
            : chip.confirmed
              ? "IA · confirmado"
              : "IA"}
      </small>
      {chip.provenance === "ai" && !chip.confirmed && (
        <button
          type="button"
          aria-label={`Confirmar ${chip.value}`}
          onClick={onConfirm}
        >
          <Check size={12} />
        </button>
      )}
      <button
        type="button"
        aria-label={`Eliminar ${chip.value}`}
        onClick={onRemove}
        onKeyDown={removeWithKeyboard}
      >
        <X size={12} />
      </button>
    </span>
  );
}

export function ProcurementSearchWizard({
  onWatchSaved,
}: ProcurementSearchWizardProps) {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<Step>("describe");
  const [description, setDescription] = useState("");
  const [comparable, setComparable] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [suggesting, setSuggesting] = useState(false);
  const [comparableProfile, setComparableProfile] =
    useState<ComparableProcurementProfile | null>(null);
  const [comparableError, setComparableError] = useState<string | null>(null);
  const [comparableFromCache, setComparableFromCache] = useState(false);
  const [geography, setGeography] = useState("");
  const [minimum, setMinimum] = useState("");
  const [maximum, setMaximum] = useState("");
  const [latestArtifact, setLatestArtifact] =
    useState<TenderSearchWizardArtifact | null>(null);
  const [artifact, setArtifact] = useState<TenderSearchWizardArtifact | null>(
    null,
  );
  const [jobId, setJobId] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [latestLoading, setLatestLoading] = useState(false);
  const [plan, setPlan] = useState<TenderSearchPlan | null>(null);
  const [chips, setChips] = useState<TenderSearchChip[]>([]);
  const [tombstones, setTombstones] = useState<Set<string>>(new Set());
  const [newChipValues, setNewChipValues] = useState<
    Partial<Record<TenderSearchChipCategory, string>>
  >({});
  const [preview, setPreview] =
    useState<TenderSearchPlanPreviewResponse | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewCooldown, setPreviewCooldown] = useState(0);
  const [acceptedProfile, setAcceptedProfile] =
    useState<ProcurementSearchProfile | null>(null);
  const [accepting, setAccepting] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [acceptError, setAcceptError] = useState<string | null>(null);
  const [watchName, setWatchName] = useState("");
  const [savingWatch, setSavingWatch] = useState(false);
  const [watchSaved, setWatchSaved] = useState(false);
  const suggestionSequence = useRef(0);

  const effectivePlan = useMemo(
    () => (plan ? applyChipsToTenderSearchPlan(plan, chips) : null),
    [chips, plan],
  );
  const missingMeasured = useMemo(
    () =>
      effectivePlan
        ? findMissingMeasuredCandidates(
            effectivePlan,
            comparableProfile,
            tombstones,
          )
        : { terms: [], cpvs: [] },
    [comparableProfile, effectivePlan, tombstones],
  );
  const missingBuyers = useMemo(
    () =>
      effectivePlan
        ? findMissingMeasuredBuyers(
            effectivePlan,
            comparableProfile,
            tombstones,
          )
        : [],
    [comparableProfile, effectivePlan, tombstones],
  );
  const hasMissingBaseline =
    missingMeasured.terms.length > 0 || missingMeasured.cpvs.length > 0;

  async function loadLatest() {
    setLatestLoading(true);
    try {
      const response = await api.tenderSearchWizard.latest();
      if (isWizardArtifact(response.artifact)) {
        setLatestArtifact(response.artifact);
      }
    } catch {
      // La ausencia del último artefacto no bloquea una generación nueva.
    } finally {
      setLatestLoading(false);
    }
  }

  useEffect(() => {
    if (!open || comparable.trim().length < 3) return;
    const sequence = ++suggestionSequence.current;
    const timer = window.setTimeout(() => {
      void api.procurement
        .suggest({ q: comparable, kind: "winner", limit: 8 })
        .then((response) => {
          if (sequence === suggestionSequence.current)
            setSuggestions(response.suggestions);
        })
        .catch(() => {
          if (sequence === suggestionSequence.current) setSuggestions([]);
        })
        .finally(() => {
          if (sequence === suggestionSequence.current) setSuggesting(false);
        });
    }, 260);
    return () => window.clearTimeout(timer);
  }, [comparable, open]);

  useEffect(() => {
    if (previewCooldown <= 0) return;
    const timer = window.setInterval(
      () => setPreviewCooldown((seconds) => Math.max(0, seconds - 1)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [previewCooldown]);

  async function measureComparable(company: string) {
    const normalized = company.trim();
    if (!normalized) return;
    setComparable(normalized);
    setSuggestions([]);
    setComparableError(null);
    setComparableFromCache(false);
    try {
      const response = await api.procurement.comparableProfile(normalized);
      setComparableProfile(response);
      writeComparableCache(normalized, response);
    } catch (reason) {
      const cached = readComparableCache(normalized);
      if (reason instanceof ApiError && reason.status === 429 && cached) {
        setComparableProfile(cached.profile);
        setComparableFromCache(true);
        return;
      }
      setComparableProfile(null);
      setComparableError(
        reason instanceof ApiError && reason.status === 429
          ? "Límite de seis perfiles por hora alcanzado. No había una copia de sesión disponible."
          : problemMessage(
              reason,
              "No se pudo medir la empresa comparable. Puedes continuar sin ella.",
            ),
      );
    }
  }

  function installArtifact(
    nextArtifact: TenderSearchWizardArtifact,
    regenerating: boolean,
  ) {
    const overridden = applyDescribeOverrides(
      nextArtifact.output,
      geography,
      minimum,
      maximum,
    );
    const geographyKey = geography.trim()
      ? tenderSearchChipKey("geographies", geography)
      : null;
    const userKeys = geographyKey ? [geographyKey] : [];
    if (regenerating && plan) {
      const merged = mergeRegeneratedTenderSearchPlan(
        overridden,
        chips,
        comparableProfile,
        tombstones,
      );
      setPlan(merged.plan);
      setChips(merged.chips);
    } else {
      setPlan(overridden);
      setChips(
        tenderSearchPlanToChips(overridden, comparableProfile, { userKeys }),
      );
    }
    setArtifact(nextArtifact);
    setPreview(null);
    setAcceptedProfile(null);
    setWatchSaved(false);
    setStep("review");
  }

  async function generate(regenerating = false) {
    if (description.trim().length < 10) return;
    setGenerating(true);
    setAcceptError(null);
    try {
      const response = await api.tenderSearchWizard.run(
        {
          description: description.trim(),
          comparable: comparable.trim() || null,
        },
        crypto.randomUUID(),
      );
      if (isWizardArtifact(response.artifact)) {
        installArtifact(response.artifact, regenerating);
      } else {
        setJobId(response.job.id);
      }
    } catch (reason) {
      setAcceptError(
        problemMessage(reason, "No se pudo iniciar la generación del plan."),
      );
    } finally {
      setGenerating(false);
    }
  }

  async function finishJob() {
    setJobId(null);
    try {
      const response = await api.tenderSearchWizard.latest();
      if (isWizardArtifact(response.artifact)) {
        installArtifact(response.artifact, Boolean(plan));
      } else {
        setAcceptError(
          "El trabajo terminó, pero el plan todavía no está disponible.",
        );
      }
    } catch (reason) {
      setAcceptError(
        problemMessage(reason, "No se pudo recuperar el plan terminado."),
      );
    }
  }

  function useLatest() {
    if (!latestArtifact) return;
    if (!description.trim()) {
      setDescription("Continuación del último plan de búsqueda disponible");
    }
    installArtifact(latestArtifact, false);
  }

  function removeChip(chip: TenderSearchChip) {
    setChips((current) => current.filter(({ key }) => key !== chip.key));
    setTombstones((current) => new Set([...current, chip.key]));
    setPreview(null);
    setAcceptedProfile(null);
  }

  function confirmChip(chip: TenderSearchChip) {
    setChips((current) =>
      current.map((item) =>
        item.key === chip.key ? { ...item, confirmed: true } : item,
      ),
    );
  }

  function addChip(category: TenderSearchChipCategory) {
    const value = newChipValues[category]?.trim();
    if (!value) return;
    const chip = createUserTenderSearchChip(category, value);
    setChips((current) =>
      current.some(({ key }) => key === chip.key)
        ? current
        : [...current, chip],
    );
    setTombstones((current) => {
      const next = new Set(current);
      next.delete(chip.key);
      return next;
    });
    setNewChipValues((current) => ({ ...current, [category]: "" }));
    setPreview(null);
    setAcceptedProfile(null);
  }

  function addMeasuredBaseline() {
    if (!effectivePlan) return;
    const merged = addMissingMeasuredCandidates(
      effectivePlan,
      comparableProfile,
      tombstones,
    );
    setPlan(merged.plan);
    setChips(merged.chips);
    setPreview(null);
    setAcceptedProfile(null);
  }

  function addMeasuredBuyer(chip: TenderSearchChip) {
    setChips((current) => [...current, chip]);
    setPreview(null);
    setAcceptedProfile(null);
  }

  async function requestPreview() {
    if (!effectivePlan || effectivePlan.scope === "historical") return;
    setPreviewing(true);
    setPreviewError(null);
    try {
      setPreview(await api.procurement.previewSearchPlan(effectivePlan));
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 429) {
        setPreviewCooldown(reason.retryAfter && reason.retryAfter > 0 ? reason.retryAfter : 60);
        setPreviewError(
          "Límite de previsualización alcanzado. No se reintentará automáticamente.",
        );
      } else {
        setPreviewError(
          problemMessage(reason, "No se pudo obtener la previsualización."),
        );
      }
    } finally {
      setPreviewing(false);
    }
  }

  async function acceptPlan() {
    if (!effectivePlan || !artifact || hasMissingBaseline) return;
    setAccepting(true);
    setAcceptError(null);
    setFieldErrors({});
    try {
      const response = acceptedProfile
        ? await api.procurementSearchProfiles.accept(acceptedProfile.id, {
            expected_version: acceptedProfile.version,
            accepted_plan: acceptedPlan(effectivePlan),
            ai_artifact_id: artifact.id,
          })
        : await api.procurementSearchProfiles.create({
            original_description: description.trim(),
            comparables: comparable.trim() ? [comparable.trim()] : [],
            accepted_plan: acceptedPlan(effectivePlan),
            ai_artifact_id: artifact.id,
          });
      setAcceptedProfile(response);
      setWatchName(
        (current) =>
          current || effectivePlan.intent_summary.slice(0, 120).trim(),
      );
    } catch (reason) {
      const errors = structuredFieldErrors(reason);
      setFieldErrors(errors);
      if (!Object.keys(errors).length) {
        setAcceptError(
          problemMessage(reason, "No se pudo aceptar esta versión del plan."),
        );
      }
    } finally {
      setAccepting(false);
    }
  }

  async function saveWatch(event: FormEvent) {
    event.preventDefault();
    if (
      !acceptedProfile ||
      effectivePlan?.scope !== "active" ||
      !watchName.trim()
    )
      return;
    setSavingWatch(true);
    setAcceptError(null);
    try {
      const response = await api.procurementSearchProfiles.saveSearch(
        acceptedProfile.id,
        {
          expected_version: acceptedProfile.version,
          name: watchName.trim(),
        },
      );
      setAcceptedProfile(response.profile);
      setWatchSaved(true);
      await onWatchSaved?.();
    } catch (reason) {
      setAcceptError(
        problemMessage(reason, "No se pudo guardar la vigilancia."),
      );
    } finally {
      setSavingWatch(false);
    }
  }

  const comparableWindow = comparableProfile?.award_date_window;
  const comparableAge = comparableProfile
    ? comparableFromCache
      ? "copia conservada en esta sesión"
      : comparableProfile.cache_hit
        ? `caché del servidor · ${comparableProfile.cached_seconds}s`
        : "medición recién calculada"
    : null;

  return (
    <PermissionGate permission="ai.execute">
      <Dialog.Root
        open={open}
        onOpenChange={(nextOpen) => {
          setOpen(nextOpen);
          if (nextOpen) void loadLatest();
        }}
      >
        <Dialog.Trigger asChild>
          <button className="vector-ai" type="button">
            <Sparkles size={15} />
            Buscar con Oracle
          </button>
        </Dialog.Trigger>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="dialog-content procurement-wizard-dialog">
            <header className="procurement-wizard-header">
              <div>
                <span className="section-kicker">
                  Plan de búsqueda · paso {step === "describe" ? "1" : "2"} de 2
                </span>
                <Dialog.Title>
                  {step === "describe"
                    ? "Describe qué quieres encontrar"
                    : "Revisa el plan antes de usarlo"}
                </Dialog.Title>
                <Dialog.Description>
                  La IA propone candidatos; ninguna búsqueda, aceptación o
                  vigilancia se ejecuta sin tu acción explícita.
                </Dialog.Description>
              </div>
              <Dialog.Close className="icon-button bordered" aria-label="Cerrar">
                <X size={18} />
              </Dialog.Close>
            </header>

            <div className="procurement-wizard-body">
              {step === "describe" ? (
                <div className="procurement-wizard-describe">
                  <label htmlFor="procurement-wizard-description">
                    <span>Qué vende tu empresa y qué contratos te interesan</span>
                    <textarea
                      id="procurement-wizard-description"
                      aria-describedby="procurement-wizard-description-help"
                      value={description}
                      onChange={(event) => setDescription(event.target.value)}
                      placeholder="Ej. Equipamiento y mantenimiento para emergencias, protección contra incendios y vehículos especiales…"
                      rows={5}
                    />
                  </label>
                  <small id="procurement-wizard-description-help">
                    Mínimo 10 caracteres. Será el único texto enviado al modelo.
                  </small>

                  <section className="procurement-wizard-comparable">
                    <ProcurementAutocomplete
                      label="Empresa comparable (opcional)"
                      value={comparable}
                      suggestions={suggestions}
                      loading={suggesting}
                      describedBy="procurement-comparable-help"
                      onChange={(value) => {
                        setComparable(value);
                        setComparableProfile(null);
                        setComparableError(null);
                        setSuggestions([]);
                        setSuggesting(value.trim().length >= 3);
                      }}
                      onSelect={(value) => void measureComparable(value)}
                      onConfirmFreeText={(value) =>
                        void measureComparable(value)
                      }
                    />
                    <small id="procurement-comparable-help">
                      Pulsa Intro o elige una sugerencia para medir sus
                      adjudicaciones. Esta medición es determinista y no usa IA.
                    </small>
                    {comparableProfile && (
                      <article className="procurement-comparable-card">
                        <header>
                          <div>
                            <strong>
                              {comparableProfile.company_normalized_by_signal}
                            </strong>
                            <small>{comparableAge}</small>
                          </div>
                          <span>
                            {comparableProfile.corpus.aggregated_contracts} adjudicaciones
                          </span>
                        </header>
                        <p>
                          Ventana observada:{" "}
                          {comparableWindow?.raw_observed_start || "inicio no publicado"}{" "}
                          — {comparableWindow?.raw_observed_end || "fin no publicado"}.
                          El contrato todavía no expone la fecha exacta de medición.
                        </p>
                        <dl>
                          <div>
                            <dt>CPV frecuentes</dt>
                            <dd>{comparableProfile.frequent_cpvs.items.length}</dd>
                          </div>
                          <div>
                            <dt>Términos frecuentes</dt>
                            <dd>{comparableProfile.title_terms.items.length}</dd>
                          </div>
                          <div>
                            <dt>Llamadas IA</dt>
                            <dd>{comparableProfile.measurement_contract.llm_calls}</dd>
                          </div>
                        </dl>
                      </article>
                    )}
                    {comparableError && (
                      <p className="form-error" role="alert">
                        {comparableError}
                      </p>
                    )}
                  </section>

                  <div className="procurement-wizard-optional-grid">
                    <label htmlFor="procurement-wizard-geography">
                      <span>Geografía preferida (opcional)</span>
                      <input
                        id="procurement-wizard-geography"
                        value={geography}
                        onChange={(event) => setGeography(event.target.value)}
                        placeholder="Ej. Andalucía"
                      />
                    </label>
                    <label htmlFor="procurement-wizard-minimum">
                      <span>Importe mínimo (opcional)</span>
                      <input
                        id="procurement-wizard-minimum"
                        inputMode="decimal"
                        value={minimum}
                        onChange={(event) => setMinimum(event.target.value)}
                      />
                    </label>
                    <label htmlFor="procurement-wizard-maximum">
                      <span>Importe máximo (opcional)</span>
                      <input
                        id="procurement-wizard-maximum"
                        inputMode="decimal"
                        value={maximum}
                        onChange={(event) => setMaximum(event.target.value)}
                      />
                    </label>
                  </div>

                  {latestArtifact && !artifact && (
                    <div className="procurement-wizard-latest">
                      <div>
                        <strong>Hay un plan anterior disponible</strong>
                        <small>
                          Oracle no lo abre ni ejecuta automáticamente.
                        </small>
                      </div>
                      <button
                        className="vector-secondary"
                        type="button"
                        onClick={useLatest}
                      >
                        Continuar ese plan
                      </button>
                    </div>
                  )}
                  {latestLoading && (
                    <p role="status">Comprobando si existe un plan anterior…</p>
                  )}
                  {jobId && (
                    <JobProgress
                      jobId={jobId}
                      label="Oracle está proponiendo el plan"
                      onTerminal={(job) => {
                        if (job.status === "succeeded") void finishJob();
                      }}
                    />
                  )}
                  {acceptError && (
                    <p className="form-error" role="alert">
                      {acceptError}
                    </p>
                  )}
                </div>
              ) : (
                effectivePlan && (
                  <div className="procurement-wizard-review">
                    <section className="procurement-wizard-intent">
                      <label htmlFor="procurement-wizard-intent">
                        Intención de búsqueda
                      </label>
                      <textarea
                        id="procurement-wizard-intent"
                        rows={3}
                        value={effectivePlan.intent_summary}
                        onChange={(event) => {
                          setPlan((current) =>
                            current
                              ? {
                                  ...current,
                                  intent_summary: event.target.value,
                                }
                              : current,
                          );
                          setAcceptedProfile(null);
                        }}
                      />
                      <div>
                        <span className="procurement-confidence">
                          Confianza {qualitativeConfidence(effectivePlan.confidence)}
                        </span>
                        <small>
                          {effectivePlan.discarded_count} candidatos descartados
                        </small>
                      </div>
                    </section>

                    {hasMissingBaseline && (
                      <section
                        className="procurement-wizard-measured-gap"
                        aria-label="Candidatos medidos omitidos"
                      >
                        <div>
                          <strong>
                            La propuesta omite candidatos medidos de la comparable
                          </strong>
                          <p>
                            {missingMeasured.terms.length} términos y{" "}
                            {missingMeasured.cpvs.length} CPV del top 20. Incorpóralos
                            con un clic; después podrás eliminarlos expresamente.
                          </p>
                        </div>
                        <button
                          className="vector-secondary"
                          type="button"
                          onClick={addMeasuredBaseline}
                        >
                          <Plus size={14} />
                          Incorporar base medida
                        </button>
                      </section>
                    )}

                    <div className="procurement-wizard-groups">
                      {Object.entries(CATEGORY_COPY).map(([rawCategory, copy]) => {
                        const category =
                          rawCategory as TenderSearchChipCategory;
                        const categoryChips = chips.filter(
                          (chip) => chip.category === category,
                        );
                        const editable = EDITABLE_CATEGORIES.includes(
                          category as (typeof EDITABLE_CATEGORIES)[number],
                        );
                        return (
                          <section className="procurement-wizard-chip-group" key={category}>
                            <header>
                              <h3>{copy.label}</h3>
                              <small>{categoryChips.length}</small>
                            </header>
                            <div className="procurement-wizard-chip-list">
                              {categoryChips.map((chip) => (
                                <PlanChip
                                  chip={chip}
                                  key={chip.key}
                                  onConfirm={() => confirmChip(chip)}
                                  onRemove={() => removeChip(chip)}
                                />
                              ))}
                              {!categoryChips.length && (
                                <span className="procurement-muted">Sin candidatos</span>
                              )}
                            </div>
                            {editable && (
                              <form
                                className="procurement-wizard-chip-add"
                                onSubmit={(event) => {
                                  event.preventDefault();
                                  addChip(category);
                                }}
                              >
                                <input
                                  aria-label={copy.placeholder}
                                  value={newChipValues[category] ?? ""}
                                  placeholder={copy.placeholder}
                                  onChange={(event) =>
                                    setNewChipValues((current) => ({
                                      ...current,
                                      [category]: event.target.value,
                                    }))
                                  }
                                />
                                <button
                                  type="submit"
                                  className="icon-button bordered"
                                  aria-label={`${copy.placeholder} al plan`}
                                >
                                  <Plus size={14} />
                                </button>
                              </form>
                            )}
                            {category === "candidate_cpv" && (
                              <small>
                                Puedes eliminar o recuperar CPV medidos. Añadir
                                códigos arbitrarios requiere el autocompletado de
                                la taxonomía CPV, aún no expuesto por el contrato.
                              </small>
                            )}
                          </section>
                        );
                      })}
                    </div>

                    {missingBuyers.length > 0 && (
                      <section className="procurement-wizard-buyers">
                        <strong>Compradores frecuentes medidos</strong>
                        <p>
                          No se añaden automáticamente porque estrecharían la búsqueda.
                        </p>
                        <div>
                          {missingBuyers.map((chip) => (
                            <button
                              type="button"
                              className="vector-secondary compact"
                              key={chip.key}
                              onClick={() => addMeasuredBuyer(chip)}
                            >
                              <Plus size={12} /> {chip.value}
                            </button>
                          ))}
                        </div>
                      </section>
                    )}

                    <section className="procurement-wizard-scope">
                      <fieldset>
                        <legend>Ámbito temporal</legend>
                        <label>
                          <input
                            type="radio"
                            name="wizard-scope"
                            checked={effectivePlan.scope === "active"}
                            onChange={() =>
                              setPlan((current) =>
                                current ? { ...current, scope: "active" } : current,
                              )
                            }
                          />
                          Solo activas
                        </label>
                        <label>
                          <input
                            type="radio"
                            name="wizard-scope"
                            checked={effectivePlan.scope === "all"}
                            onChange={() =>
                              setPlan((current) =>
                                current ? { ...current, scope: "all" } : current,
                              )
                            }
                          />
                          Todo el índice disponible
                        </label>
                        <label aria-disabled="true">
                          <input
                            type="radio"
                            name="wizard-scope"
                            checked={effectivePlan.scope === "historical"}
                          disabled
                          />
                          Solo histórico (no disponible)
                        </label>
                      </fieldset>
                      <p>
                        “Todo” no promete un archivo histórico completo. El histórico
                        fiable sigue siendo adjudicación-céntrico.
                      </p>
                    </section>

                    {(effectivePlan.assumptions.length > 0 ||
                      effectivePlan.questions.length > 0) && (
                      <section className="procurement-wizard-context">
                        {effectivePlan.assumptions.length > 0 && (
                          <div>
                            <h3>Supuestos de la propuesta</h3>
                            <ul>
                              {effectivePlan.assumptions.map((item) => (
                                <li key={item}>{item}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {effectivePlan.questions.length > 0 && (
                          <div>
                            <h3>Preguntas abiertas</h3>
                            <ul>
                              {effectivePlan.questions.map((item) => (
                                <li key={item}>{item}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </section>
                    )}

                    <section className="procurement-wizard-preview">
                      <header>
                        <div>
                          <h3>Previsualización por sonda</h3>
                          <p>
                            Máximo cuatro términos y cuatro CPV. Los resultados se
                            solapan: los totales no se suman.
                          </p>
                        </div>
                        <AsyncActionButton
                          className="vector-secondary"
                          loading={previewing}
                          disabled={
                            previewCooldown > 0 ||
                            effectivePlan.scope === "historical"
                          }
                          onClick={() => void requestPreview()}
                        >
                          <Eye size={14} />
                          {previewCooldown > 0
                            ? `Disponible en ${previewCooldown}s`
                            : "Previsualizar ahora"}
                        </AsyncActionButton>
                      </header>
                      {effectivePlan.scope === "historical" && (
                        <p className="form-error" role="alert">
                          El histórico exclusivo no es ejecutable con el contrato
                          actual. Elige activas o todo el índice.
                        </p>
                      )}
                      {previewError && (
                        <p className="form-error" role="status">
                          {previewError}
                        </p>
                      )}
                      {preview && (
                        <>
                          <div className="procurement-preview-grid">
                            {preview.preview.probes.map((probe) => (
                              <article key={`${probe.chip.kind}:${probe.chip.value}`}>
                                <span>{probe.chip.kind === "cpv" ? "CPV" : "Término"}</span>
                                <strong>
                                  {probe.chip.label
                                    ? `${probe.chip.value} · ${probe.chip.label}`
                                    : probe.chip.value}
                                </strong>
                                <b>{probe.total} coincidencias</b>
                              </article>
                            ))}
                          </div>
                          {preview.preview.unprobed_chips.length > 0 && (
                            <div className="procurement-preview-unprobed">
                              <strong>No sondeados por el límite</strong>
                              <span>
                                {preview.preview.unprobed_chips
                                  .map((chip) => chip.value)
                                  .join(", ")}
                              </span>
                            </div>
                          )}
                        </>
                      )}
                    </section>

                    {Object.keys(fieldErrors).length > 0 && (
                      <div className="procurement-wizard-field-errors" role="alert">
                        <strong>Revisa los campos indicados por el servidor</strong>
                        <ul>
                          {Object.entries(fieldErrors).map(([field, message]) => (
                            <li key={field}>
                              <b>{field}:</b> {message}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {acceptError && (
                      <p className="form-error" role="alert">
                        {acceptError}
                      </p>
                    )}

                    {acceptedProfile && (
                      <section className="procurement-wizard-accepted">
                        <div>
                          <Check size={16} />
                          <div>
                            <strong>Plan aceptado · v{acceptedProfile.version}</strong>
                            <small>
                              La vigilancia sigue sin guardarse hasta la siguiente
                              acción.
                            </small>
                          </div>
                        </div>
                        {effectivePlan.scope === "active" ? (
                          <form onSubmit={saveWatch}>
                            <label>
                              <span>Nombre de la vigilancia</span>
                              <input
                                value={watchName}
                                maxLength={120}
                                onChange={(event) => setWatchName(event.target.value)}
                              />
                            </label>
                            <AsyncActionButton
                              className="vector-primary"
                              type="submit"
                              loading={savingWatch}
                              disabled={watchSaved || watchName.trim().length < 2}
                            >
                              <Save size={14} />
                              {watchSaved ? "Vigilancia guardada" : "Guardar vigilancia"}
                            </AsyncActionButton>
                          </form>
                        ) : (
                          <p>
                            Una vigilancia solo puede guardarse para licitaciones
                            activas con Signal v1.
                          </p>
                        )}
                      </section>
                    )}
                  </div>
                )
              )}
            </div>

            <footer className="procurement-wizard-footer">
              {step === "describe" ? (
                <>
                  <Dialog.Close className="vector-secondary" type="button">
                    Cancelar
                  </Dialog.Close>
                  <AsyncActionButton
                    className="vector-ai"
                    loading={generating}
                    disabled={description.trim().length < 10 || Boolean(jobId)}
                    onClick={() => void generate(false)}
                  >
                    <Sparkles size={15} />
                    Generar propuesta
                  </AsyncActionButton>
                </>
              ) : (
                <>
                  <button
                    className="vector-secondary"
                    type="button"
                    onClick={() => setStep("describe")}
                  >
                    <ChevronLeft size={14} />
                    Volver
                  </button>
                  <div>
                    <AsyncActionButton
                      className="vector-ai"
                      loading={generating}
                      disabled={Boolean(jobId)}
                      onClick={() => void generate(true)}
                    >
                      <Sparkles size={14} />
                      Regenerar propuesta
                    </AsyncActionButton>
                    <AsyncActionButton
                      className="vector-primary"
                      loading={accepting}
                      disabled={
                        !artifact ||
                        hasMissingBaseline ||
                        effectivePlan?.scope === "historical"
                      }
                      onClick={() => void acceptPlan()}
                    >
                      <Check size={14} />
                      {acceptedProfile
                        ? `Aceptar como v${acceptedProfile.version + 1}`
                        : "Aceptar plan"}
                    </AsyncActionButton>
                  </div>
                </>
              )}
            </footer>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </PermissionGate>
  );
}
