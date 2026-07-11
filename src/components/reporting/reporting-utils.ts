import type {
  OracleNotification,
  OracleReport,
} from "@oracle/api-client";

export type ReportStatus = OracleReport["status"];
export type NotificationSeverity = OracleNotification["severity"];

export interface ReportParagraphView {
  text: string;
  kind: "fact" | "inference" | "recommendation" | "decision";
  confidence: number;
  evidence_ids: string[];
}

export interface ReportSectionView {
  heading: string;
  paragraphs: ReportParagraphView[];
}

export interface ReportContentView {
  title: string;
  executive_summary: string;
  confidence: number;
  sections: ReportSectionView[];
  open_questions: string[];
  warnings: string[];
}

export interface ReportEvidenceView {
  id: string;
  extract: string;
  locator: string;
  sourceLabel: string;
  classification: string;
}

export const reportStatusLabel: Record<ReportStatus, string> = {
  draft: "Borrador",
  generating: "Generando",
  ready: "Listo para revisar",
  reviewed: "Revisado",
  published: "Publicado",
  failed: "Fallido",
  superseded: "Sustituido",
};

export const notificationSeverityLabel: Record<
  NotificationSeverity,
  string
> = {
  info: "Información",
  success: "Correcto",
  warning: "Atención",
  critical: "Crítica",
};

export function formatDateTime(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("es-ES", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function formatBytes(value?: number | null): string {
  if (value == null) return "—";
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${Math.round(value / 1024)} KB`;
  return `${(value / 1024 ** 2).toFixed(1)} MB`;
}

export function idempotencyKey(prefix: string): string {
  const suffix =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}`;
  return `${prefix}-${suffix}`;
}

function object(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function strings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function paragraph(value: unknown): ReportParagraphView | null {
  const item = object(value);
  if (!item || typeof item.text !== "string") return null;
  const allowedKinds = ["fact", "inference", "recommendation", "decision"];
  const kind = allowedKinds.includes(String(item.kind))
    ? (item.kind as ReportParagraphView["kind"])
    : "inference";
  const confidence = Number(item.confidence);
  return {
    text: item.text,
    kind,
    confidence: Number.isFinite(confidence)
      ? Math.min(100, Math.max(0, confidence))
      : 0,
    evidence_ids: strings(item.evidence_ids),
  };
}

export function reportContent(report: OracleReport): ReportContentView | null {
  const revision = object(report.revision);
  const content = object(revision?.content);
  if (!content) return null;
  const sections = Array.isArray(content.sections)
    ? content.sections.flatMap((raw) => {
        const section = object(raw);
        if (!section || typeof section.heading !== "string") return [];
        return [
          {
            heading: section.heading,
            paragraphs: Array.isArray(section.paragraphs)
              ? section.paragraphs.flatMap((item) => {
                  const parsed = paragraph(item);
                  return parsed ? [parsed] : [];
                })
              : [],
          },
        ];
      })
    : [];
  const confidence = Number(content.confidence);
  return {
    title: typeof content.title === "string" ? content.title : report.title,
    executive_summary:
      typeof content.executive_summary === "string"
        ? content.executive_summary
        : "",
    confidence: Number.isFinite(confidence)
      ? Math.min(100, Math.max(0, confidence))
      : 0,
    sections,
    open_questions: strings(content.open_questions),
    warnings: strings(content.warnings),
  };
}

export function reportRevisionId(report: OracleReport): string | null {
  const revision = object(report.revision);
  return typeof revision?.id === "string" ? revision.id : null;
}

export function reportEvidence(report: OracleReport): ReportEvidenceView[] {
  return (report.evidence ?? []).flatMap((raw) => {
    const item = object(raw);
    if (!item || typeof item.id !== "string") return [];
    const rawLocator = item.locator;
    const locator =
      typeof rawLocator === "string"
        ? rawLocator
        : rawLocator
          ? JSON.stringify(rawLocator)
          : "Localización no indicada";
    return [
      {
        id: item.id,
        extract: typeof item.extract === "string" ? item.extract : "",
        locator,
        sourceLabel:
          typeof item.source_label === "string"
            ? item.source_label
            : "Evidencia del snapshot",
        classification:
          typeof item.classification === "string"
            ? item.classification
            : "internal",
      },
    ];
  });
}

export function safeProductLink(value?: string | null): string | null {
  if (!value || !value.startsWith("/")) return null;
  if (value.startsWith("//") || value.includes("\\")) return null;
  try {
    const decoded = decodeURIComponent(value.split("?", 1)[0]);
    if (decoded.split("/").some((part) => part === "." || part === ".."))
      return null;
  } catch {
    return null;
  }
  return ["/app/", "/concept-a/", "/platform/"].some((prefix) =>
    value.startsWith(prefix),
  )
    ? value
    : null;
}

export function triggerDownload(url: string): void {
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.rel = "noopener";
  anchor.style.display = "none";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
}
