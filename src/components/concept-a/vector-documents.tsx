"use client";

import { ApiError, api, type DocumentSearchResult, type OracleDocument } from "@oracle/api-client";
import { Download, FileSearch, FileUp, RefreshCw, Trash2 } from "lucide-react";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

const statusLabel: Record<OracleDocument["status"], string> = {
  uploaded: "Subido",
  queued: "En cola",
  processing: "Procesando",
  ready: "Disponible",
  failed: "Error",
  quarantined: "Cuarentena",
  deleted: "Eliminado",
};

function sourceLocation(locator: Record<string, unknown>): string {
  const labels: Array<[string, string]> = [
    ["page", "Página"],
    ["paragraph", "Párrafo"],
    ["segment", "Fragmento"],
    ["line", "Línea"],
  ];
  const parts = labels.flatMap(([key, label]) => {
    const value = locator[key];
    return typeof value === "string" || typeof value === "number" ? [`${label} ${value}`] : [];
  });
  return parts.length ? parts.join(" · ") : "Ubicación del fragmento no indicada";
}

export function DossierDocuments({ dossierId }: { dossierId: string }) {
  const backendId = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(dossierId);
  if (backendId) return <VectorDocuments dossierId={dossierId} />;
  return <section className="vector-panel synthetic-documents" aria-labelledby="synthetic-documents-title">
    <span className="section-kicker">Datos sintéticos</span>
    <h2 id="synthetic-documents-title">Documentos no disponibles en esta ficha comparativa</h2>
    <p>Esta ficha pertenece al escaparate visual y no representa un expediente persistente. Abre un expediente de la sección «Expedientes operativos» del Command Center para subir, buscar y citar documentos reales.</p>
  </section>;
}

export function VectorDocuments({ dossierId }: { dossierId: string }) {
  const input = useRef<HTMLInputElement>(null);
  const [documents, setDocuments] = useState<OracleDocument[]>([]);
  const [results, setResults] = useState<DocumentSearchResult[]>([]);
  const [query, setQuery] = useState("");
  const [classification, setClassification] = useState<"public" | "internal">("internal");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<DocumentSearchResult | null>(null);

  const load = useCallback(async () => {
    const data = await api.documents.list(dossierId);
    setDocuments(data.items);
  }, [dossierId]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => {
      void load().catch((reason) => setError(
        reason instanceof ApiError && reason.problem.code === "documents_disabled"
          ? "El módulo documental está deshabilitado para este entorno. Contacta con administración para configurar storage y antivirus."
          : "No se pudieron cargar los documentos. Reinténtalo o comprueba tus permisos.",
      ));
    }, 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    try {
      await api.documents.upload(dossierId, file, classification);
      toast.success("Documento recibido", { description: "El análisis continúa en segundo plano." });
      await load();
    } catch {
      setError("El archivo no se pudo subir. Revisa formato, tamaño y permisos.");
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  async function search(event: FormEvent) {
    event.preventDefault();
    if (query.trim().length < 2) return;
    setBusy(true);
    setError(null);
    try {
      setResults((await api.documents.search(dossierId, query.trim())).items);
    } catch {
      setError("No se pudo completar la búsqueda.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="vector-panel vector-documents" aria-labelledby="documents-title">
      <header>
        <div><span className="section-kicker">Fuentes y trazabilidad</span><h2 id="documents-title">Documentos</h2></div>
        <label className="vector-primary document-upload">
          <FileUp size={16} />{busy ? "Procesando…" : "Subir documento"}
          <input ref={input} type="file" disabled={busy} accept=".pdf,.docx,.txt,.md,.csv,.vtt,.srt,application/vnd.opn.transcript+json" onChange={(event) => event.target.files?.[0] && void upload(event.target.files[0])} />
        </label>
      </header>
      <div className="document-toolbar">
        <label>Clasificación<select value={classification} onChange={(event) => setClassification(event.target.value as "public" | "internal")}><option value="internal">Interno</option><option value="public">Público</option></select></label>
        <form role="search" onSubmit={search}><label htmlFor="document-search">Buscar en el expediente</label><div><FileSearch size={16}/><input id="document-search" value={query} minLength={2} maxLength={200} onChange={(event) => setQuery(event.target.value)} placeholder="Término o frase"/><button className="vector-secondary" disabled={busy || query.trim().length < 2}>Buscar</button></div></form>
      </div>
      {error && <p className="auth-inline-error" role="alert">{error}</p>}
      <div className="document-table-wrap"><table className="document-table"><thead><tr><th>Documento</th><th>Estado</th><th>Clasificación</th><th>Tamaño</th><th><span className="sr-only">Acciones</span></th></tr></thead><tbody>
        {documents.map((document) => <tr key={document.id}><td><strong>{document.filename}</strong><small>{document.media_type}</small></td><td><span className={`document-status ${document.status}`}>{statusLabel[document.status]}</span></td><td>{document.classification === "internal" ? "Interno" : "Público"}</td><td>{new Intl.NumberFormat("es-ES", { style: "unit", unit: "kilobyte", maximumFractionDigits: 0 }).format(document.byte_size / 1024)}</td><td><div className="document-actions">{document.status === "ready" && <a className="icon-button bordered" href={`/api/v1/documents/${document.id}/download`} aria-label={`Descargar ${document.filename}`}><Download size={15}/></a>}{document.status === "failed" && <button className="icon-button bordered" aria-label={`Reprocesar ${document.filename}`} onClick={() => void api.documents.reprocess(document.id).then(load)}><RefreshCw size={15}/></button>}<button className="icon-button bordered" aria-label={`Eliminar ${document.filename}`} onClick={() => void api.documents.remove(document.id).then(load)}><Trash2 size={15}/></button></div></td></tr>)}
        {!documents.length && <tr><td colSpan={5} className="document-empty">Aún no hay documentos. Sube una fuente para generar fragmentos trazables.</td></tr>}
      </tbody></table></div>
      {!!results.length && <div className="document-results" aria-live="polite"><h3>Resultados ({results.length})</h3>{results.map((result) => <button key={result.chunk_id} onClick={() => setSelected(result)}><strong>{result.filename}</strong><span>{result.snippet}</span><small>{sourceLocation(result.locator)}</small></button>)}</div>}
      {selected && <div className="evidence-drawer" role="dialog" aria-modal="true" aria-labelledby="evidence-source-title"><button className="evidence-backdrop" aria-label="Cerrar fuente" onClick={() => setSelected(null)}/><aside><header><div><span className="section-kicker">Fuente no confiable · solo lectura</span><h3 id="evidence-source-title">{selected.filename}</h3></div><button className="icon-button bordered" aria-label="Cerrar" onClick={() => setSelected(null)}>×</button></header><p>{selected.text}</p><dl><div><dt>Ubicación</dt><dd>{sourceLocation(selected.locator)}</dd></div></dl><button className="vector-primary" onClick={() => void api.documents.createEvidence(selected.document_id, selected.chunk_id, 0, selected.text.length).then(() => toast.success("Evidencia creada")).catch(() => toast.error("Selecciona un rango válido en la fuente."))}>Crear evidencia del fragmento</button></aside></div>}
    </section>
  );
}
