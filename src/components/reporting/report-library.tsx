"use client";

import * as Dialog from "@radix-ui/react-dialog";
import {
  ApiError,
  api,
  type BackendDossier,
  type OracleReport,
} from "@oracle/api-client";
import type { components } from "@oracle/api-client";
import {
  CalendarDays,
  ChevronRight,
  FileChartColumn,
  FilePlus2,
  Filter,
  RefreshCw,
  Search,
  ShieldCheck,
  X,
} from "lucide-react";
import { useParams, useSearchParams } from "next/navigation";
import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";
import { PermissionGate } from "@/components/auth/auth-boundary";
import { HydratedActionButton } from "@/components/ui/async-action-button";
import { ExportMenu } from "./exports";
import { JobProgress } from "./job-progress";
import { ReportDrawer } from "./report-viewer";
import {
  formatDateTime,
  idempotencyKey,
  reportStatusLabel,
} from "./reporting-utils";

type ReportTemplate = components["schemas"]["ReportTemplate"];

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function fieldLabel(key: string): string {
  return (
    {
      meeting_id: "ID de la reunión",
      opportunity_id: "ID de la oportunidad",
      risk_id: "ID del riesgo",
      actor_ids: "IDs de actores",
      owner_user_ids: "IDs de responsables",
      period_start: "Inicio del periodo",
      period_end: "Fin del periodo",
      deadline: "Fecha límite",
      audience: "Audiencia",
      horizon: "Horizonte",
      relationship_scope: "Ámbito de relaciones",
    }[key] ?? key.replaceAll("_", " ")
  );
}

function normalizeOption(
  type: string,
  value: string,
): components["schemas"]["JsonValue"] {
  if (type.includes("[]"))
    return value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  return value.trim();
}

function ReportGenerateWizard({
  open,
  onOpenChange,
  templates,
  dossiers,
  dossierId,
  pdfEnabled,
  initialTemplateKey,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  templates: ReportTemplate[];
  dossiers: BackendDossier[];
  dossierId?: string;
  pdfEnabled: boolean;
  initialTemplateKey?: string;
  onCreated: (report: OracleReport) => void;
}) {
  const [selectedDossier, setSelectedDossier] = useState(dossierId ?? "");
  const [templateKey, setTemplateKey] = useState(initialTemplateKey ?? "");
  const [classification, setClassification] = useState<"public" | "internal">("internal");
  const [confidentialityLabel, setConfidentialityLabel] = useState("Uso interno");
  const [formats, setFormats] = useState<string[]>(["html", "json"]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selected = templates.find((item) => item.key === templateKey) ?? templates[0];
  const contract = record(selected?.input_contract);
  const properties = record(contract?.properties) ?? {};
  const required = Array.isArray(contract?.required)
    ? contract.required.filter((item): item is string => typeof item === "string")
    : [];

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const targetDossier = dossierId || selectedDossier;
    if (!targetDossier || !selected) {
      setError("Selecciona un expediente y una plantilla.");
      return;
    }
    const options: components["schemas"]["JsonObject"] = {
      formats,
      classification,
      confidentiality_label: confidentialityLabel.trim(),
    };
    for (const [key, rawType] of Object.entries(properties)) {
      const value = values[key]?.trim();
      if (value) options[key] = normalizeOption(String(rawType), value);
    }
    for (const key of required.filter((item) => item !== "dossier_id")) {
      if (!options[key]) {
        setError(`${fieldLabel(key)} es obligatorio para esta plantilla.`);
        return;
      }
    }
    if (!formats.length) {
      setError("Selecciona al menos un formato.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await api.reports.generate(
        targetDossier,
        { template_key: selected.key, options },
        idempotencyKey(`report-${targetDossier}-${selected.key}`),
      );
      onCreated(result.report);
      onOpenChange(false);
      toast.success("Informe en preparación", {
        description: "Puedes seguir el progreso sin mantener esta ventana abierta.",
      });
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.problem.detail
          : "No se pudo solicitar el informe.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="report-dialog-overlay" />
        <Dialog.Content className="report-wizard">
          <header>
            <div>
              <span className="section-kicker">Generación asíncrona</span>
              <Dialog.Title>Crear informe</Dialog.Title>
              <Dialog.Description>
                Oracle congelará un snapshot de contexto y evidencias antes de
                iniciar el análisis.
              </Dialog.Description>
            </div>
            <Dialog.Close className="icon-button bordered" aria-label="Cerrar">
              <X size={17} />
            </Dialog.Close>
          </header>
          <form onSubmit={submit}>
            {!dossierId && (
              <label>
                Expediente
                <select
                  required
                  value={selectedDossier}
                  onChange={(event) => setSelectedDossier(event.target.value)}
                >
                  <option value="">Selecciona un expediente</option>
                  {dossiers.map((dossier) => (
                    <option key={dossier.id} value={dossier.id}>
                      {dossier.title}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label>
              Plantilla
              <select
                required
                value={selected?.key ?? ""}
                onChange={(event) => {
                  setTemplateKey(event.target.value);
                  setValues({});
                }}
              >
                {templates.map((template) => (
                  <option key={template.key} value={template.key}>
                    {template.label}
                  </option>
                ))}
              </select>
            </label>
            {selected && (
              <div className="report-template-summary" role="note">
                <ShieldCheck size={17} />
                <div>
                  <strong>{selected.evidence_policy}</strong>
                  <span>
                    {selected.sections.length} secciones · contrato {selected.output_schema}
                  </span>
                </div>
              </div>
            )}
            <div className="report-wizard-grid">
              {Object.entries(properties).map(([key, rawType]) => {
                const type = String(rawType);
                const dateField = type.startsWith("date");
                return (
                  <label key={key}>
                    {fieldLabel(key)}
                    {type.includes("[]") && <small>Separa varios IDs con comas.</small>}
                    <input
                      type={dateField ? "date" : "text"}
                      required={required.includes(key)}
                      value={values[key] ?? ""}
                      onChange={(event) =>
                        setValues((current) => ({ ...current, [key]: event.target.value }))
                      }
                    />
                  </label>
                );
              })}
              <label>
                Clasificación
                <select
                  value={classification}
                  onChange={(event) => {
                    const next = event.target.value as "public" | "internal";
                    setClassification(next);
                    setConfidentialityLabel(
                      next === "public" ? "Público" : "Uso interno",
                    );
                  }}
                >
                  <option value="internal">Interno</option>
                  <option value="public">Público</option>
                </select>
              </label>
              <label>
                Etiqueta de confidencialidad
                <input
                  required
                  maxLength={120}
                  value={confidentialityLabel}
                  onChange={(event) => setConfidentialityLabel(event.target.value)}
                />
              </label>
            </div>
            <fieldset className="report-format-options">
              <legend>Formatos</legend>
              {(selected?.formats ?? []).map((format) => {
                const disabled = format === "pdf" && !pdfEnabled;
                return (
                  <label key={format} title={disabled ? "PDF no está habilitado en este entorno" : undefined}>
                    <input
                      type="checkbox"
                      disabled={disabled}
                      checked={formats.includes(format) && !disabled}
                      onChange={(event) =>
                        setFormats((current) =>
                          event.target.checked
                            ? [...current, format]
                            : current.filter((item) => item !== format),
                        )
                      }
                    />
                    {format.toUpperCase()}
                    {disabled && <small>No disponible</small>}
                  </label>
                );
              })}
            </fieldset>
            {error && <p className="auth-inline-error" role="alert">{error}</p>}
            <footer>
              <Dialog.Close className="vector-secondary" type="button">Cancelar</Dialog.Close>
              <button className="vector-primary" disabled={busy || !templates.length}>
                <FilePlus2 size={16} /> {busy ? "Solicitando…" : "Generar informe"}
              </button>
            </footer>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function ReportLibrary({
  dossierId,
  routeBase = "/app",
}: {
  dossierId?: string;
  routeBase?: "/app" | "/concept-a";
}) {
  const searchParams = useSearchParams();
  const initialReportId = searchParams.get("report");
  const requestedTemplate = searchParams.get("template") ?? undefined;
  const requestedNew = searchParams.get("new") === "1";
  const openedFromQuery = useRef(false);
  const [reports, setReports] = useState<OracleReport[]>([]);
  const [templates, setTemplates] = useState<ReportTemplate[]>([]);
  const [dossiers, setDossiers] = useState<BackendDossier[]>([]);
  const [pdfEnabled, setPdfEnabled] = useState(false);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [template, setTemplate] = useState("");
  const [selectedReportId, setSelectedReportId] = useState<string | null>(initialReportId);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [reportResult, templateResult, dossierResult] = await Promise.all([
        dossierId
          ? api.reports.listDossier(dossierId, 1, 100)
          : api.reports.list(1, 100),
        api.reports.templates(),
        dossierId
          ? Promise.resolve({ data: [] as BackendDossier[] })
          : api.dossiers.list(),
      ]);
      setReports(reportResult.data);
      setTemplates(templateResult.items);
      setPdfEnabled(templateResult.capabilities.pdf);
      setDossiers(dossierResult.data);
    } catch (reason) {
      setError(
        reason instanceof ApiError && reason.status === 403
          ? "No tienes permiso para consultar informes en este ámbito."
          : "No se pudo cargar la biblioteca de informes.",
      );
    } finally {
      setLoading(false);
    }
  }, [dossierId]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  useEffect(() => {
    if (!requestedNew || openedFromQuery.current || !templates.length) return;
    openedFromQuery.current = true;
    setWizardOpen(true);
  }, [requestedNew, templates.length]);

  const dossierName = useMemo(
    () => new Map(dossiers.map((item) => [item.id, item.title])),
    [dossiers],
  );
  const templateName = useMemo(
    () => new Map(templates.map((item) => [item.key, item.label])),
    [templates],
  );
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("es");
    return reports.filter(
      (report) =>
        (!needle || report.title.toLocaleLowerCase("es").includes(needle)) &&
        (!status || report.status === status) &&
        (!template || report.template_key === template),
    );
  }, [query, reports, status, template]);

  const addReport = (report: OracleReport) => {
    setReports((current) => [report, ...current.filter((item) => item.id !== report.id)]);
    setSelectedReportId(report.id);
  };

  return (
    <div className="reporting-page report-library">
      <header className="page-heading">
        <div>
          <span className="section-kicker">
            {dossierId ? "Expediente · resultados trazables" : "Cartera · resultados trazables"}
          </span>
          <h1>{dossierId ? "Informes del expediente" : "Biblioteca de informes"}</h1>
          <p>
            Versiones auditables con hechos, inferencias, recomendaciones,
            citas y artefactos inmutables.
          </p>
        </div>
        <div className="report-library-actions">
          <PermissionGate permission="export.create">
            <ExportMenu dataset="reports" dossierId={dossierId} routeBase={routeBase} />
          </PermissionGate>
          <PermissionGate permission="report.generate">
            <HydratedActionButton className="vector-primary" onClick={() => setWizardOpen(true)}>
              <FilePlus2 size={16} /> Generar informe
            </HydratedActionButton>
          </PermissionGate>
        </div>
      </header>

      <section className="vector-panel report-library-panel" aria-labelledby="report-library-title">
        <header>
          <div>
            <span className="section-kicker">{reports.length} versiones accesibles</span>
            <h2 id="report-library-title">Informes</h2>
          </div>
          <button className="icon-button bordered" aria-label="Actualizar informes" onClick={() => void load()}>
            <RefreshCw size={16} />
          </button>
        </header>
        <div className="report-filters">
          <label className="search-field">
            <Search size={16} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Buscar por título…"
              aria-label="Buscar informes"
            />
          </label>
          <label>
            <span className="sr-only">Estado</span>
            <select value={status} onChange={(event) => setStatus(event.target.value)}>
              <option value="">Todos los estados</option>
              {Object.entries(reportStatusLabel).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>
          <label>
            <span className="sr-only">Plantilla</span>
            <select value={template} onChange={(event) => setTemplate(event.target.value)}>
              <option value="">Todas las plantillas</option>
              {templates.map((item) => (
                <option key={item.key} value={item.key}>{item.label}</option>
              ))}
            </select>
          </label>
          {(query || status || template) && (
            <button
              className="text-button"
              onClick={() => {
                setQuery("");
                setStatus("");
                setTemplate("");
              }}
            >
              <Filter size={14} /> Limpiar filtros
            </button>
          )}
        </div>

        {error && (
          <div className="reporting-error" role="alert">
            <strong>No se pudo abrir la biblioteca</strong>
            <p>{error}</p>
            <button className="vector-secondary" onClick={() => void load()}>Reintentar</button>
          </div>
        )}
        {loading ? (
          <div className="reporting-loading" role="status">
            <span className="auth-spinner" /> Cargando informes…
          </div>
        ) : !error && !filtered.length ? (
          <div className="reporting-empty">
            <FileChartColumn size={30} />
            <strong>{reports.length ? "No hay resultados con estos filtros" : "Aún no hay informes"}</strong>
            <p>
              {reports.length
                ? "Amplía los criterios para volver a ver la biblioteca."
                : "Genera el primero; el trabajo continuará en segundo plano."}
            </p>
            {!reports.length && (
              <PermissionGate permission="report.generate">
                <HydratedActionButton className="vector-primary" onClick={() => setWizardOpen(true)}>
                  Generar primer informe
                </HydratedActionButton>
              </PermissionGate>
            )}
          </div>
        ) : !error ? (
          <div className="report-table-wrap">
            <table className="report-table">
              <thead>
                <tr>
                  <th>Informe</th>
                  {!dossierId && <th>Expediente</th>}
                  <th>Estado</th>
                  <th>Versión</th>
                  <th>Actualizado</th>
                  <th><span className="sr-only">Abrir</span></th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((report) => (
                  <tr key={report.id}>
                    <td>
                      <button className="report-title-button" onClick={() => setSelectedReportId(report.id)}>
                        <strong>{report.title}</strong>
                        <small>{templateName.get(report.template_key) ?? report.template_key}</small>
                      </button>
                    </td>
                    {!dossierId && <td>{dossierName.get(report.dossier_id) ?? "Expediente accesible"}</td>}
                    <td>
                      <span className={`report-status ${report.status}`}>
                        {reportStatusLabel[report.status]}
                      </span>
                      {report.job_id && ["draft", "generating"].includes(report.status) && (
                        <JobProgress jobId={report.job_id} label="Generando informe" onTerminal={() => void load()} allowActions />
                      )}
                    </td>
                    <td>g{report.generation_version} · r{report.version}</td>
                    <td>
                      <CalendarDays size={14} /> {formatDateTime(report.updated_at ?? report.created_at)}
                    </td>
                    <td>
                      <button
                        className="icon-button bordered"
                        aria-label={`Abrir ${report.title}`}
                        onClick={() => setSelectedReportId(report.id)}
                      >
                        <ChevronRight size={16} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      {wizardOpen && (
        <ReportGenerateWizard
          open
          onOpenChange={setWizardOpen}
          templates={templates}
          dossiers={dossiers}
          dossierId={dossierId}
          pdfEnabled={pdfEnabled}
          initialTemplateKey={requestedTemplate}
          onCreated={addReport}
        />
      )}
      <ReportDrawer
        reportId={selectedReportId}
        routeBase={routeBase}
        open={Boolean(selectedReportId)}
        onOpenChange={(open) => !open && setSelectedReportId(null)}
      />
    </div>
  );
}

export function SyntheticReports() {
  return (
    <section className="vector-panel synthetic-documents" aria-labelledby="synthetic-reports-title">
      <span className="section-kicker">Datos sintéticos</span>
      <h2 id="synthetic-reports-title">Informes no disponibles en esta ficha comparativa</h2>
      <p>
        Esta ficha procede del escaparate visual. Abre un expediente operativo
        con UUID desde el Command Center para generar, revisar y publicar
        informes persistentes con evidencias reales del entorno.
      </p>
    </section>
  );
}

export function DossierReportsRoute({
  routeBase = "/app",
}: {
  routeBase?: "/app" | "/concept-a";
}) {
  const { id } = useParams<{ id: string }>();
  return <ReportLibrary dossierId={id} routeBase={routeBase} />;
}
