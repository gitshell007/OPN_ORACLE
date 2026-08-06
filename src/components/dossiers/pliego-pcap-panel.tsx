"use client";

/**
 * G-11 · CTA prioritario «Subir PCAP» y estado honesto de adquisición.
 *
 * Independiente de fit/verdict/artifact. Visible aunque documents=[] o falle HTTP/WAF.
 */

import {
  api,
  ApiError,
  type PliegoAcquisitionResponse,
  type PliegoAcquisitionStatus,
} from "@oracle/api-client";
import { AlertTriangle, FileUp, RefreshCw, Upload } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { PermissionGate } from "@/components/auth/auth-boundary";
import { AsyncActionButton } from "@/components/ui/async-action-button";
import { JobProgress } from "@/components/reporting/job-progress";

const STATUS_LABEL: Record<PliegoAcquisitionStatus, string> = {
  descargado: "Descargado (oficial)",
  subido: "Subido manualmente",
  extracto_parcial: "Extracto parcial",
  no_disponible: "No disponible",
};

function statusClass(status: string): string {
  switch (status) {
    case "subido":
      return "pliego-status pliego-status-ok";
    case "descargado":
      return "pliego-status pliego-status-ok";
    case "extracto_parcial":
      return "pliego-status pliego-status-warn";
    default:
      return "pliego-status pliego-status-bad";
  }
}

function errorMessage(reason: unknown, fallback: string): string {
  if (reason instanceof ApiError) {
    if (reason.problem.code === "documents_disabled") {
      return "El módulo documental está deshabilitado en este entorno.";
    }
    if (reason.problem.code === "document_rejected" || reason.problem.code === "parse_failed") {
      return reason.problem.detail || "Formato o tamaño de archivo no válido.";
    }
    return reason.problem.detail || fallback;
  }
  return fallback;
}

export function PliegoPcapPanel({
  dossierId,
  opportunityId,
}: {
  dossierId: string;
  opportunityId?: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [acquisition, setAcquisition] = useState<PliegoAcquisitionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [processedMessage, setProcessedMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await api.dossierProcurement.pliegoAcquisition(
        dossierId,
        opportunityId,
      );
      setAcquisition(payload);
    } catch (reason) {
      setAcquisition(null);
      setError(
        errorMessage(
          reason,
          "No se pudo cargar el estado de adquisición del pliego.",
        ),
      );
    } finally {
      setLoading(false);
    }
  }, [dossierId, opportunityId]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  async function onFile(file: File | null | undefined) {
    if (!file) return;
    setBusy(true);
    setError(null);
    setProcessedMessage(null);
    try {
      const result = await api.dossierProcurement.uploadPliegoPcap(dossierId, file, {
        opportunityId,
      });
      setActiveJobId(result.job_id);
      setProcessedMessage(result.message);
      if (result.pliego_acquisition) {
        setAcquisition(result.pliego_acquisition);
      }
      toast.success("PCAP recibido", {
        description: "Oracle lo trocea y prepara el esqueleto en segundo plano.",
      });
      await load();
    } catch (reason) {
      setError(
        errorMessage(
          reason,
          "No se pudo subir el PCAP. Revise formato (PDF/texto), tamaño y permisos.",
        ),
      );
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  const overall = acquisition?.overall_status ?? "no_disponible";
  const showWafHint =
    overall === "no_disponible" ||
    overall === "extracto_parcial" ||
    (acquisition?.pins_without_documents ?? 0) > 0 ||
    (acquisition?.signal_document_refs === 0 && (acquisition?.acquisitions.length ?? 0) > 0);

  return (
    <section
      className="pliego-pcap-panel vector-panel"
      aria-label="Adquisición de pliego PCAP"
      data-testid="pliego-pcap-panel"
    >
      <header className="pliego-pcap-header">
        <div>
          <span className="section-kicker">G-11 · Pliego / PCAP</span>
          <h3>Camino comercial fiable</h3>
          <p>
            {acquisition?.cta.hint ??
              "La descarga automática es best-effort (WAF/HTTP pueden bloquearla). Suba el PCAP: Oracle lo trocea, puntúa y prepara el esqueleto."}
          </p>
        </div>
        <PermissionGate permission="documents.manage">
          <div className="pliego-pcap-actions">
            <input
              ref={input}
              type="file"
              accept=".pdf,.txt,.doc,.docx,application/pdf,text/plain"
              hidden
              data-testid="pliego-pcap-input"
              onChange={(event) => void onFile(event.target.files?.[0])}
            />
            <AsyncActionButton
              className="vector-primary"
              type="button"
              data-testid="pliego-pcap-cta"
              loading={busy}
              loadingLabel={
                <>
                  <RefreshCw size={15} />
                  Subiendo…
                </>
              }
              onClick={() => input.current?.click()}
              disabled={loading}
            >
              <Upload size={15} />
              Subir PCAP
            </AsyncActionButton>
          </div>
        </PermissionGate>
      </header>

      {loading && (
        <p className="muted" role="status">
          Cargando estado de adquisición…
        </p>
      )}

      {!loading && acquisition && (
        <div className="pliego-pcap-status" data-testid="pliego-pcap-status">
          <p className={statusClass(overall)}>
            <strong>{STATUS_LABEL[overall] ?? overall}</strong>
            {acquisition.overall_reason ? (
              <span> — {acquisition.overall_reason}</span>
            ) : null}
          </p>
          {showWafHint && (
            <p className="pliego-pcap-waf-hint" role="note" data-testid="pliego-pcap-waf-hint">
              <AlertTriangle size={14} />
              Si la descarga automática falló (403/WAF, 429, timeout) o Signal no entregó
              documentos, use «Subir PCAP». No es un error silencioso: el estado es
              «no disponible» o «extracto parcial», no «0 documentos» normales.
            </p>
          )}
          {overall === "extracto_parcial" && (
            <p className="pliego-pcap-partial" data-testid="pliego-pcap-partial">
              Se reutilizó un extracto del expediente. No es el PCAP completo; la subida
              manual tiene prioridad si aporta el PDF real.
            </p>
          )}
          {acquisition.preferred_document && (
            <p className="pliego-pcap-preferred">
              <FileUp size={14} /> Preferido:{" "}
              <strong>{acquisition.preferred_document.filename}</strong> (
              {acquisition.preferred_document.status})
            </p>
          )}
          {acquisition.acquisitions.length > 0 && (
            <ul className="pliego-pcap-list" data-testid="pliego-pcap-list">
              {acquisition.acquisitions.slice(0, 8).map((item) => (
                <li key={item.key ?? `${item.status}-${item.source_uri ?? item.file_name}`}>
                  <span className={statusClass(String(item.status))}>
                    {STATUS_LABEL[item.status as PliegoAcquisitionStatus] ?? item.status}
                  </span>
                  {item.file_name ? ` · ${item.file_name}` : null}
                  {item.reason ? <small> — {item.reason}</small> : null}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {error && (
        <p className="form-error" role="alert" data-testid="pliego-pcap-error">
          {error}
        </p>
      )}
      {processedMessage && (
        <p className="pliego-pcap-ok" role="status" data-testid="pliego-pcap-ok">
          {processedMessage}
        </p>
      )}
      {activeJobId && (
        <JobProgress
          jobId={activeJobId}
          label="Procesando PCAP (troceo y evidencia)"
          onTerminal={() => {
            setActiveJobId(null);
            void load();
          }}
          allowActions
        />
      )}
    </section>
  );
}
