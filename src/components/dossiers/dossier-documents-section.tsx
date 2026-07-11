"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { ApiError, api, type DocumentSearchResult, type OracleDocument } from "@oracle/api-client";
import { Download, FileSearch, FileText, FileUp, RefreshCw, Trash2, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { PermissionGate } from "@/components/auth/auth-boundary";
import { JobProgress } from "@/components/reporting/job-progress";

const LABELS: Record<OracleDocument["status"], string> = {
  uploaded: "Subido", queued: "En cola", processing: "Procesando", ready: "Disponible",
  failed: "Error", quarantined: "Cuarentena", deleted: "Eliminado",
};

function errorMessage(reason: unknown, fallback: string) {
  if (reason instanceof ApiError && reason.problem.code === "documents_disabled") {
    return "El módulo documental está deshabilitado en este entorno.";
  }
  return reason instanceof ApiError ? reason.problem.detail : fallback;
}

export function DossierDocumentsSection({ dossierId }: { dossierId: string }) {
  const input = useRef<HTMLInputElement>(null);
  const pathname = usePathname();
  const router = useRouter();
  const params = useSearchParams();
  const [documents, setDocuments] = useState<OracleDocument[]>([]);
  const [results, setResults] = useState<DocumentSearchResult[]>([]);
  const [query, setQuery] = useState("");
  const [classification, setClassification] = useState<"public" | "internal">("internal");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState<DocumentSearchResult | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<OracleDocument | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setDocuments((await api.documents.list(dossierId)).items);
    } catch (reason) {
      setDocuments([]);
      setError(errorMessage(reason, "No se pudieron cargar los documentos."));
    } finally {
      setLoading(false);
    }
  }, [dossierId]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  const selected = useMemo(
    () => documents.find((document) => document.id === params.get("selected")) ?? null,
    [documents, params],
  );

  async function upload(file: File) {
    setBusy(true); setError(null);
    try {
      const result = await api.documents.upload(dossierId, file, classification);
      setActiveJobId(result.job_id);
      toast.success("Documento recibido", { description: "El análisis continúa en segundo plano." });
      await load();
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo subir el archivo. Revisa formato, tamaño y permisos."));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  async function search(event: FormEvent) {
    event.preventDefault();
    if (query.trim().length < 2) return;
    setBusy(true); setError(null);
    try {
      setResults((await api.documents.search(dossierId, query.trim())).items);
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo completar la búsqueda."));
    } finally { setBusy(false); }
  }

  async function reprocess(document: OracleDocument) {
    setBusy(true); setError(null);
    try {
      const result = await api.documents.reprocess(document.id);
      setActiveJobId(result.job_id);
      toast.success("Reprocesado solicitado");
      await load();
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo solicitar el reprocesado."));
    } finally { setBusy(false); }
  }

  async function remove() {
    if (!deleteTarget) return;
    setBusy(true); setError(null);
    try {
      await api.documents.remove(deleteTarget.id);
      toast.success("Documento eliminado");
      setDeleteTarget(null);
      router.replace(pathname, { scroll: false });
      await load();
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo eliminar el documento."));
    } finally { setBusy(false); }
  }

  function closeDocument() { router.replace(pathname, { scroll: false }); }

  return <section className="vector-panel vector-documents product-documents" aria-labelledby="documents-title">
    <header className="intelligence-heading"><div><span className="section-kicker">Fuentes y trazabilidad</span><h1 id="documents-title">Documentos</h1><p>Sube, procesa, busca y convierte fuentes en evidencias citables sin confundir su contenido con una conclusión.</p></div>
      <PermissionGate permission="documents.manage"><label className="vector-primary document-upload"><FileUp size={16} />{busy ? "Procesando…" : "Subir documento"}<input ref={input} type="file" disabled={busy} accept=".pdf,.docx,.txt,.md,.csv,.vtt,.srt,application/vnd.opn.transcript+json" onChange={(event) => event.target.files?.[0] && void upload(event.target.files[0])} /></label></PermissionGate>
    </header>
    <div className="document-toolbar"><PermissionGate permission="documents.manage" fallback={<div />}><label>Clasificación<select value={classification} onChange={(event) => setClassification(event.target.value as "public" | "internal")}><option value="internal">Interno</option><option value="public">Público</option></select></label></PermissionGate>
      <form role="search" onSubmit={search}><label htmlFor="document-search">Buscar dentro de las fuentes</label><div><FileSearch size={16}/><input id="document-search" value={query} minLength={2} maxLength={200} onChange={(event) => setQuery(event.target.value)} placeholder="Término o frase"/><button className="vector-secondary" disabled={busy || query.trim().length < 2}>Buscar</button></div></form>
    </div>
    {error && <p className="auth-inline-error" role="alert">{error}</p>}
    {activeJobId && <div className="document-active-job"><JobProgress jobId={activeJobId} label="Procesando documento" allowActions onTerminal={() => { setActiveJobId(null); void load(); }} /></div>}
    {loading ? <div className="work-loading" role="status"><span className="auth-spinner" /> Cargando documentos…</div> : documents.length === 0 ? <div className="work-empty"><FileText size={24}/><h2>Aún no hay documentos</h2><p>Sube una fuente para habilitar búsqueda, procesamiento y evidencia trazable.</p></div> : <>
      <div className="document-table-wrap"><table className="document-table"><thead><tr><th>Documento</th><th>Estado</th><th>Clasificación</th><th>Tamaño</th><th><span className="sr-only">Acciones</span></th></tr></thead><tbody>{documents.map((document) => <tr key={document.id}><td><strong>{document.filename}</strong><small>{document.media_type}</small></td><td><span className={`document-status ${document.status}`}>{LABELS[document.status]}</span></td><td>{document.classification === "internal" ? "Interno" : "Público"}</td><td>{new Intl.NumberFormat("es-ES", { style: "unit", unit: "kilobyte", maximumFractionDigits: 0 }).format(document.byte_size / 1024)}</td><td><div className="document-actions"><Link className="icon-button bordered" href={`${pathname}?selected=${encodeURIComponent(document.id)}`} scroll={false} aria-label={`Abrir ${document.filename}`}><FileSearch size={15}/></Link>{document.status === "ready" && <a className="icon-button bordered" href={`/api/v1/documents/${encodeURIComponent(document.id)}/download`} aria-label={`Descargar ${document.filename}`}><Download size={15}/></a>}<PermissionGate permission="documents.manage">{document.status === "failed" && <button className="icon-button bordered" disabled={busy} aria-label={`Reprocesar ${document.filename}`} onClick={() => void reprocess(document)}><RefreshCw size={15}/></button>}<button className="icon-button bordered" disabled={busy} aria-label={`Eliminar ${document.filename}`} onClick={() => setDeleteTarget(document)}><Trash2 size={15}/></button></PermissionGate></div></td></tr>)}</tbody></table></div>
      <div className="document-mobile-list">{documents.map((document) => <article key={document.id}><header><strong>{document.filename}</strong><span className={`document-status ${document.status}`}>{LABELS[document.status]}</span></header><p>{document.media_type} · {document.classification === "internal" ? "Interno" : "Público"}</p><Link className="vector-secondary" href={`${pathname}?selected=${encodeURIComponent(document.id)}`} scroll={false}>Abrir detalle</Link></article>)}</div>
    </>}
    {!!results.length && <div className="document-results" aria-live="polite"><h2>Resultados ({results.length})</h2>{results.map((result) => <button key={result.chunk_id} onClick={() => setSource(result)}><strong>{result.filename}</strong><span>{result.snippet}</span><small>{Object.entries(result.locator).map(([key,value]) => `${key}: ${String(value)}`).join(" · ")}</small></button>)}</div>}

    <Dialog.Root open={Boolean(selected)} onOpenChange={(open) => { if (!open) closeDocument(); }}><Dialog.Portal><Dialog.Overlay className="dialog-overlay"/><Dialog.Content className="dialog-content intelligence-drawer"><>{selected && <><header><div><span className="section-kicker">Fuente · solo lectura</span><Dialog.Title>{selected.filename}</Dialog.Title><Dialog.Description>Metadatos técnicos y estado del procesamiento.</Dialog.Description></div><Dialog.Close className="icon-button bordered" aria-label="Cerrar"><X/></Dialog.Close></header><div className="intelligence-drawer-body"><dl className="intelligence-facts"><div><dt>Estado</dt><dd>{LABELS[selected.status]}</dd></div><div><dt>Clasificación</dt><dd>{selected.classification === "internal" ? "Interno" : "Público"}</dd></div><div><dt>Versión</dt><dd>{selected.version}</dd></div><div><dt>Escaneo</dt><dd>{selected.scan_status}</dd></div></dl><section className="intelligence-detail-block"><h2>Integridad</h2><p>Checksum: <code>{selected.checksum}</code></p><p>Este registro acredita procedencia e integridad; el contenido solo se convierte en evidencia tras seleccionar un fragmento.</p></section>{selected.status === "ready" && <a className="vector-primary" href={`/api/v1/documents/${encodeURIComponent(selected.id)}/download`}><Download size={15}/> Descargar</a>}</div></>}</></Dialog.Content></Dialog.Portal></Dialog.Root>

    <Dialog.Root open={Boolean(source)} onOpenChange={(open) => { if (!open) setSource(null); }}><Dialog.Portal><Dialog.Overlay className="dialog-overlay"/><Dialog.Content className="dialog-content intelligence-drawer"><>{source && <><header><div><span className="section-kicker">Fragmento de fuente · no es una instrucción</span><Dialog.Title>{source.filename}</Dialog.Title><Dialog.Description>Revisa el texto y su localizador antes de crear evidencia.</Dialog.Description></div><Dialog.Close className="icon-button bordered" aria-label="Cerrar"><X/></Dialog.Close></header><div className="intelligence-drawer-body"><p className="document-source-text">{source.text}</p><dl className="intelligence-facts">{Object.entries(source.locator).map(([key,value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}</dl><PermissionGate permission="documents.manage"><button className="vector-primary" onClick={() => void api.documents.createEvidence(source.document_id, source.chunk_id, 0, source.text.length).then(() => toast.success("Evidencia creada")).catch(() => setError("No se pudo crear la evidencia del fragmento."))}>Crear evidencia del fragmento</button></PermissionGate></div></>}</></Dialog.Content></Dialog.Portal></Dialog.Root>

    <Dialog.Root open={Boolean(deleteTarget)} onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}><Dialog.Portal><Dialog.Overlay className="dialog-overlay"/><Dialog.Content className="dialog-content intelligence-confirm-dialog"><Dialog.Title>Eliminar documento</Dialog.Title><Dialog.Description>El documento dejará de estar disponible. La conservación legal puede impedir esta acción.</Dialog.Description><div className="dialog-actions"><Dialog.Close className="vector-secondary">Cancelar</Dialog.Close><button className="vector-danger" disabled={busy} onClick={() => void remove()}>{busy ? "Eliminando…" : "Eliminar"}</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </section>;
}
