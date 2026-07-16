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
  sourceLabel: string;
  sourceTitle: string | null;
  sourceType: string;
  publishedAt: string | null;
  sourceUrl: string | null;
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

function textField(value: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const candidate = value[key];
    if (typeof candidate === "string" && candidate.trim()) return candidate.trim();
  }
  return null;
}

function sourceUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const parsed = new URL(value);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.toString() : null;
  } catch {
    return null;
  }
}

function sourceName(value: string | null): string {
  const url = sourceUrl(value);
  if (!url) return value?.trim() || "Fuente del informe";
  return new URL(url).hostname.replace(/^www\./, "") || "Fuente del informe";
}

function sourceType(value: string | null, classification: string): string {
  const normalized = value?.trim().toLowerCase();
  if (["signal", "news", "press", "company_signal", "market_signal"].includes(normalized ?? "")) {
    return "Señal de prensa no verificada";
  }
  if (normalized === "document") return "Documento";
  if (normalized === "procurement" || normalized === "tender") return "Licitación o adjudicación";
  if (normalized === "official_publication" || normalized === "regulatory_signal") {
    return "Publicación oficial";
  }
  return classification === "public" ? "Fuente pública" : "Documento interno";
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
  const revision = object(report.revision);
  const content = object(revision?.content);
  const sourceIndex = Array.isArray(content?.source_index) ? content.source_index : [];
  const sourceOrder = new Map(
    sourceIndex.flatMap((raw, index) => {
      const item = object(raw);
      return item && typeof item.evidence_id === "string" ? [[item.evidence_id, index] as const] : [];
    }),
  );
  const parsed = (report.evidence ?? []).flatMap((raw) => {
    const item = object(raw);
    if (!item || typeof item.id !== "string") return [];
    const locator = object(item.locator) ?? {};
    const rawLabel = typeof item.source_label === "string" ? item.source_label : null;
    const locatorUrl = textField(locator, ["source_url", "canonical_source_url", "url", "link"]);
    const link = sourceUrl(locatorUrl) ?? sourceUrl(rawLabel);
    const classification = typeof item.classification === "string" ? item.classification : "internal";
    return [
      {
        id: item.id,
        extract: typeof item.extract === "string" ? item.extract : "",
        sourceLabel: sourceName(rawLabel ?? locatorUrl),
        sourceTitle: textField(locator, ["title", "headline", "document_title", "name"]),
        sourceType: sourceType(textField(locator, ["source_kind", "source_type", "type", "kind"]), classification),
        publishedAt: textField(locator, ["published_at", "publication_date", "date"]),
        sourceUrl: link,
      },
    ];
  });
  return sourceOrder.size
    ? parsed.filter((item) => sourceOrder.has(item.id)).sort((left, right) => sourceOrder.get(left.id)! - sourceOrder.get(right.id)!)
    : parsed;
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
