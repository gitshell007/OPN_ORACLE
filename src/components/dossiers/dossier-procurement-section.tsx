"use client";

import {
  api,
  type DossierProcurementItem,
  type OracleReport,
} from "@oracle/api-client";
import {
  BarChart3,
  ExternalLink,
  FileText,
  RefreshCw,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PermissionGate } from "@/components/auth/auth-boundary";
import { useAuth } from "@/components/auth/auth-provider";
import { AsyncActionButton } from "@/components/ui/async-action-button";
import {
  formatDate,
  formatMoney,
  problemMessage,
  snapshotNumber,
  snapshotText,
} from "@/components/procurement/procurement-helpers";
import { idempotencyKey } from "@/components/reporting/reporting-utils";
import { JobProgress } from "@/components/reporting/job-progress";

const COMPETITIVE_TEMPLATE = "competitive_procurement";

function snapshotAmount(item: DossierProcurementItem): number | null {
  const direct = snapshotNumber(item.snapshot, [
    "amount",
    "award_amount",
    "budget",
    "estimated_value",
  ]);
  if (direct !== null) return direct;
  const entries = item.snapshot.entries;
  if (!Array.isArray(entries)) return null;
  const total = entries.reduce((sum, entry) => {
    if (!entry || typeof entry !== "object") return sum;
    const value = (entry as Record<string, unknown>).award_amount;
    return typeof value === "number" && Number.isFinite(value) ? sum + value : sum;
  }, 0);
  return total > 0 ? total : null;
}

function snapshotTitle(item: DossierProcurementItem): string {
  return (
    snapshotText(item.snapshot, ["title", "object", "subject", "contract_title"]) ||
    `${item.kind === "tender" ? "Licitación" : "Adjudicación"} ${item.folder_id}`
  );
}

function snapshotBuyer(item: DossierProcurementItem): string {
  return (
    snapshotText(item.snapshot, ["buyer", "contracting_authority", "organ"]) ||
    "Órgano no publicado"
  );
}

function snapshotDeadline(item: DossierProcurementItem): string | null {
  return snapshotText(item.snapshot, ["deadline", "deadline_date", "award_date"]);
}

function snapshotIsUte(item: DossierProcurementItem): boolean {
  if (item.snapshot.is_ute === true) return true;
  const entries = item.snapshot.entries;
  return Array.isArray(entries) && entries.some(
    (entry) => entry && typeof entry === "object" && (entry as Record<string, unknown>).is_ute === true,
  );
}

function evidenceLabel(evidenceId: string): string {
  return `Evidencia ${evidenceId.slice(0, 8)}`;
}

function awardEntriesSummary(item: DossierProcurementItem): string | null {
  const entries = item.snapshot.entries;
  if (!Array.isArray(entries) || entries.length === 0) return null;
  const winners = new Set<string>();
  for (const entry of entries) {
    if (!entry || typeof entry !== "object") continue;
    const winner = (entry as Record<string, unknown>).winner;
    if (typeof winner === "string" && winner.trim()) winners.add(winner);
  }
  return `${entries.length} lote${entries.length === 1 ? "" : "s"}${
    winners.size ? ` · ${Array.from(winners).slice(0, 3).join(", ")}` : ""
  }`;
}

export function pinnedWinnerCandidates(
  items: DossierProcurementItem[],
): string[] {
  const winners = new Map<string, string>();
  for (const item of items) {
    if (item.kind !== "award") continue;
    const values: unknown[] = [item.snapshot.winner];
    if (Array.isArray(item.snapshot.entries)) {
      for (const entry of item.snapshot.entries) {
        if (entry && typeof entry === "object") {
          values.push((entry as Record<string, unknown>).winner);
        }
      }
    }
    for (const value of values) {
      if (typeof value !== "string" || !value.trim()) continue;
      winners.set(value.trim().toLocaleLowerCase("es"), value.trim());
    }
  }
  return Array.from(winners.values()).sort((left, right) =>
    left.localeCompare(right, "es"),
  );
}

export function DossierProcurementSection({ dossierId }: { dossierId: string }) {
  const auth = useAuth();
  const [items, setItems] = useState<DossierProcurementItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [generatingCompetitive, setGeneratingCompetitive] = useState(false);
  const [competitiveReport, setCompetitiveReport] =
    useState<OracleReport | null>(null);
  const [selectedCompany, setSelectedCompany] = useState("");
  const documentReportKey = useRef<string | null>(null);
  const competitiveReportKey = useRef<string | null>(null);
  const winnerCandidates = useMemo(() => pinnedWinnerCandidates(items), [items]);
  const effectiveCompany = winnerCandidates.includes(selectedCompany)
    ? selectedCompany
    : (winnerCandidates[0] ?? "");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.dossierProcurement.list(dossierId);
      setItems(response.data);
      try {
        const reportResponse = await api.reports.listDossier(dossierId, 1, 100);
        setCompetitiveReport(
          reportResponse.data.find(
            (report) => report.template_key === COMPETITIVE_TEMPLATE,
          ) ?? null,
        );
      } catch {
        setCompetitiveReport(null);
      }
    } catch (reason) {
      setError(
        problemMessage(
          reason,
          "No se pudieron cargar las referencias de contratación.",
        ),
      );
    } finally {
      setLoading(false);
    }
  }, [dossierId]);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) void load();
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  async function remove(itemId: string) {
    setRemovingId(itemId);
    setError(null);
    try {
      await api.dossierProcurement.remove(dossierId, itemId);
      setItems((current) => current.filter((item) => item.id !== itemId));
    } catch (reason) {
      setError(
        problemMessage(reason, "No se pudo desfijar la referencia."),
      );
    } finally {
      setRemovingId(null);
    }
  }

  async function generateDocumentReport() {
    if (!documentReportKey.current) {
      documentReportKey.current = idempotencyKey(`procurement-report-${dossierId}`);
    }
    setGenerating(true);
    setError(null);
    try {
      await api.dossierProcurement.createDocumentReport(
        dossierId,
        {},
        documentReportKey.current,
      );
    } catch (reason) {
      setError(problemMessage(reason, "No se pudo preparar el informe documental."));
    } finally {
      documentReportKey.current = null;
      setGenerating(false);
    }
  }

  async function generateCompetitiveReport() {
    if (!effectiveCompany) return;
    if (!competitiveReportKey.current) {
      competitiveReportKey.current = idempotencyKey(
        `competitive-procurement-${dossierId}`,
      );
    }
    setGeneratingCompetitive(true);
    setError(null);
    try {
      const result = await api.reports.generate(
        dossierId,
        {
          template_key: COMPETITIVE_TEMPLATE,
          options: {
            company_name: effectiveCompany,
            formats: ["html", "json"],
            classification: "internal",
            confidentiality_label: "Uso interno",
          },
        },
        competitiveReportKey.current,
      );
      setCompetitiveReport(result.report);
    } catch (reason) {
      setError(
        problemMessage(
          reason,
          "No se pudo solicitar la inteligencia competitiva.",
        ),
      );
    } finally {
      competitiveReportKey.current = null;
      setGeneratingCompetitive(false);
    }
  }

  return (
    <section className="vector-panel dossier-procurement-section" aria-busy={loading}>
      <header>
        <div>
          <span className="section-kicker">Contratación pública</span>
          <h2>Referencias fijadas al expediente</h2>
        </div>
        <div className="procurement-report-actions">
          <button
            className="vector-secondary"
            type="button"
            onClick={() => void load()}
            disabled={loading}
          >
            <RefreshCw size={15} />
            Actualizar
          </button>
          <PermissionGate permission="report.generate">
            <AsyncActionButton
              className="vector-secondary"
              type="button"
              onClick={() => void generateDocumentReport()}
              loading={loading || generating}
              loadingLabel={
                generating ? (
                  <>
                    <RefreshCw size={15} />
                    Preparando…
                  </>
                ) : (
                  "Cargando…"
                )
              }
              disabled={!items.some((item) => item.kind === "award")}
            >
              <FileText size={15} />
              Informe documental
            </AsyncActionButton>
            <AsyncActionButton
              className="vector-primary"
              type="button"
              onClick={() => void generateCompetitiveReport()}
              loading={loading || generatingCompetitive}
              loadingLabel={
                generatingCompetitive ? (
                  <>
                    <RefreshCw size={15} />
                    Encolando…
                  </>
                ) : (
                  "Cargando…"
                )
              }
              disabled={!effectiveCompany}
            >
              <BarChart3 size={15} />
              Inteligencia competitiva
            </AsyncActionButton>
          </PermissionGate>
        </div>
      </header>
      {winnerCandidates.length > 0 && (
        <div className="procurement-competitive-controls">
          <label>
            Adjudicatario a analizar
            <select
              value={effectiveCompany}
              onChange={(event) => setSelectedCompany(event.target.value)}
            >
              {winnerCandidates.map((winner) => (
                <option value={winner} key={winner}>
                  {winner}
                </option>
              ))}
            </select>
          </label>
          <p>
            Se consultará el histórico paginado de esta denominación en Signal;
            las referencias fijadas serán el foco y las citas del expediente.
          </p>
        </div>
      )}
      {competitiveReport?.job_id &&
        ["draft", "generating"].includes(competitiveReport.status) && (
          <div className="procurement-competitive-status" role="status">
            <strong>Informe competitivo en segundo plano</strong>
            <p>
              Está encolado. Puedes salir de esta pantalla y volver más tarde.
            </p>
            <JobProgress
              jobId={competitiveReport.job_id}
              label="Analizando el histórico de contratación"
              onTerminal={() => void load()}
              allowActions
            />
          </div>
        )}
      {competitiveReport &&
        ["ready", "reviewed", "published", "failed"].includes(
          competitiveReport.status,
        ) && (
          <div className="procurement-competitive-status">
            <strong>
              {competitiveReport.status === "failed"
                ? "El último informe necesita atención"
                : "La inteligencia competitiva está disponible"}
            </strong>
            <Link
              className="vector-secondary"
              href={`/app/dossiers/${dossierId}/reports?report=${competitiveReport.id}`}
            >
              Abrir en Informes
            </Link>
          </div>
        )}
      {error && (
        <div className="inline-error" role="alert">
          {error}
        </div>
      )}
      {loading ? (
        <div className="global-inventory-state" role="status">
          Cargando referencias de contratación…
        </div>
      ) : items.length ? (
        <div className="procurement-card-list">
          {items.map((item) => {
            const entries = awardEntriesSummary(item);
            const isUte = item.kind === "award" && snapshotIsUte(item);
            return (
              <article className="procurement-card" key={item.id}>
                <header>
                  <div>
                    <strong>{snapshotTitle(item)}</strong>
                    <small>{snapshotBuyer(item)}</small>
                  </div>
                  <div>
                    {isUte && <span className="status">UTE · En consorcio</span>}
                    <span className="status">
                      {item.kind === "tender" ? "Licitación" : "Adjudicación"}
                    </span>
                  </div>
                </header>
                {entries && <p>{entries}</p>}
                <dl>
                  <div>
                    <dt>Organismo licitador</dt>
                    <dd>{snapshotBuyer(item)}</dd>
                  </div>
                  <div>
                    <dt>Referencia</dt>
                    <dd>{item.folder_id}</dd>
                  </div>
                  <div>
                    <dt>{item.kind === "tender" ? "Plazo" : "Fecha"}</dt>
                    <dd>{formatDate(snapshotDeadline(item))}</dd>
                  </div>
                  <div>
                    <dt>Importe</dt>
                    <dd>{formatMoney(snapshotAmount(item))}</dd>
                  </div>
                  <div>
                    <dt>Evidencia</dt>
                    <dd title={item.evidence_id}>{evidenceLabel(item.evidence_id)}</dd>
                  </div>
                </dl>
                <footer>
                  {item.source_url && (
                    <a
                      className="vector-secondary"
                      href={item.source_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <ExternalLink size={14} />
                      Ver fuente oficial
                    </a>
                  )}
                  <PermissionGate permission="opportunity.write">
                    <AsyncActionButton
                      className="vector-danger"
                      type="button"
                      loading={removingId === item.id}
                      loadingLabel={
                        <>
                          <RefreshCw size={14} />
                          Desfijando…
                        </>
                      }
                      onClick={() => void remove(item.id)}
                    >
                      <Trash2 size={14} />
                      Desfijar
                    </AsyncActionButton>
                  </PermissionGate>
                </footer>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="global-inventory-state">
          <strong>No hay licitaciones o adjudicaciones fijadas</strong>
          <p>
            Puedes fijarlas desde{" "}
            {auth.can("opportunity.read") ? (
              <Link href="/app/procurement">Contratación pública</Link>
            ) : (
              "Contratación pública"
            )}{" "}
            o desde{" "}
            {auth.can("actor.read") ? (
              <Link href={`/app/dossiers/${dossierId}/actors`}>
                el panel de Actores
              </Link>
            ) : (
              "el panel de Actores"
            )}
            .
          </p>
        </div>
      )}
    </section>
  );
}
