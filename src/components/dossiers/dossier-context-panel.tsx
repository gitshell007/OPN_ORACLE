"use client";

import * as Dialog from "@radix-ui/react-dialog";
import {
  ApiError,
  api,
  type OracleEvidence,
  type OracleHypothesis,
  type OracleObjective,
} from "@oracle/api-client";
import { Plus, RefreshCw, X } from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { PermissionGate } from "@/components/auth/auth-boundary";

const HYPOTHESIS_STATUS: Record<string, string> = {
  open: "Activa",
  supported: "Validada",
  contradicted: "Contradicha",
  discarded: "Descartada",
};

function failure(reason: unknown, fallback: string) {
  return reason instanceof ApiError ? reason.problem.detail : fallback;
}

export function DossierContextPanel({ dossierId }: { dossierId: string }) {
  const [objectives, setObjectives] = useState<OracleObjective[]>([]);
  const [hypotheses, setHypotheses] = useState<OracleHypothesis[]>([]);
  const [evidence, setEvidence] = useState<OracleEvidence[]>([]);
  const [selected, setSelected] = useState<OracleHypothesis | null>(null);
  const [contextOpen, setContextOpen] = useState(false);
  const [statement, setStatement] = useState("");
  const [rationale, setRationale] = useState("");
  const [confidence, setConfidence] = useState(50);
  const [hypothesisStatus, setHypothesisStatus] = useState("open");
  const [evidenceId, setEvidenceId] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [objectiveResult, hypothesisResult, evidenceResult] = await Promise.all([
        api.objectives.list(dossierId, { page: 1, size: 25, sort: "position" }),
        api.hypotheses.list(dossierId, { page: 1, size: 25, sort: "position" }),
        api.dossierEvidence.list(dossierId),
      ]);
      setObjectives(objectiveResult.data);
      setHypotheses(hypothesisResult.data);
      setEvidence(evidenceResult.data);
    } catch (reason) {
      setError(failure(reason, "No se pudo cargar el contexto estratégico."));
    } finally {
      setLoading(false);
    }
  }, [dossierId]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  function edit(item?: OracleHypothesis) {
    setSelected(item ?? null);
    setContextOpen(true);
    setStatement(item?.statement ?? "");
    setRationale(item?.rationale ?? "");
    setConfidence(item?.confidence ?? 50);
    setHypothesisStatus(item?.status ?? "open");
    setEvidenceId("");
    setError(null);
  }

  async function saveHypothesis(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const input = { statement: statement.trim(), rationale: rationale.trim(), confidence, status: hypothesisStatus };
      if (selected) await api.hypotheses.update(selected.id, { ...input, version: selected.version }, selected.version ?? 1);
      else await api.hypotheses.create(dossierId, input);
      toast.success(selected ? "Hipótesis actualizada" : "Hipótesis creada");
      setContextOpen(false);
      setSelected(null);
      await load();
    } catch (reason) {
      setError(failure(reason, "No se pudo guardar la hipótesis."));
    } finally {
      setBusy(false);
    }
  }

  async function linkEvidence() {
    if (!selected || !evidenceId) return;
    setBusy(true);
    try {
      await api.hypotheses.linkEvidence(selected.id, evidenceId);
      toast.success("Evidencia vinculada");
      setEvidenceId("");
    } catch (reason) {
      setError(failure(reason, "No se pudo vincular la evidencia."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="dossier-context-panel" aria-labelledby="dossier-context-title">
      <header><div><span className="section-kicker">Marco de trabajo</span><h2 id="dossier-context-title">Objetivos e hipótesis</h2></div><button className="icon-button bordered" type="button" aria-label="Actualizar contexto" onClick={() => void load()}><RefreshCw size={15} /></button></header>
      {loading ? <p role="status">Cargando objetivos e hipótesis…</p> : error ? <p className="form-error" role="alert">{error}</p> : <div className="dossier-context-grid">
        <section><h3>Objetivos</h3>{objectives.length ? <ul>{objectives.map((item) => <li key={item.id}><strong>{item.title}</strong><span>{item.status === "achieved" ? "Alcanzado" : item.status === "in_progress" ? "En curso" : "Abierto"}</span><p>{item.description || "Sin descripción adicional."}</p></li>)}</ul> : <p>No hay objetivos registrados todavía.</p>}</section>
        <section><header><h3>Hipótesis</h3><PermissionGate permission="dossier.write"><button className="icon-button bordered" type="button" aria-label="Nueva hipótesis" onClick={() => edit()}><Plus size={15} /></button></PermissionGate></header>{hypotheses.length ? <ul>{hypotheses.map((item) => <li key={item.id}><button className="context-item-button" type="button" aria-label={`Editar hipótesis: ${item.statement}`} onClick={() => edit(item)}><strong>{item.statement}</strong><span>{HYPOTHESIS_STATUS[item.status ?? "open"] ?? "Activa"} · {item.confidence ?? 0} %</span></button><p>{item.rationale || "Sin razonamiento documentado."}</p></li>)}</ul> : <p>No hay hipótesis registradas todavía.</p>}</section>
      </div>}
      <Dialog.Root open={contextOpen} onOpenChange={(open) => { if (!open) setContextOpen(false); }}>
        <Dialog.Portal><Dialog.Overlay className="dialog-overlay" /><Dialog.Content className="dialog-content work-dialog"><div className="dialog-header"><div><span className="section-kicker">Hipótesis del expediente</span><Dialog.Title>{selected ? "Editar hipótesis" : "Nueva hipótesis"}</Dialog.Title></div><Dialog.Close className="icon-button" aria-label="Cerrar"><X /></Dialog.Close></div><form onSubmit={saveHypothesis}><label>Hipótesis<textarea required minLength={3} value={statement} onChange={(event) => setStatement(event.target.value)} /></label><label>Razonamiento<textarea value={rationale} onChange={(event) => setRationale(event.target.value)} /></label><label>Estado<select value={hypothesisStatus} onChange={(event) => setHypothesisStatus(event.target.value)}>{Object.entries(HYPOTHESIS_STATUS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>Confianza inicial<input type="number" min="0" max="100" value={confidence} onChange={(event) => setConfidence(Number(event.target.value))} /></label>{selected && <label>Vincular evidencia<select value={evidenceId} onChange={(event) => setEvidenceId(event.target.value)}><option value="">Seleccionar evidencia…</option>{evidence.map((item) => <option key={item.id} value={item.id}>{item.extract || item.id}</option>)}</select><button className="vector-secondary" type="button" disabled={!evidenceId || busy} onClick={() => void linkEvidence()}>Vincular</button></label>}{error && <p className="form-error" role="alert">{error}</p>}<div className="dialog-actions"><Dialog.Close className="vector-secondary" type="button">Cancelar</Dialog.Close><button className="vector-primary" disabled={busy || statement.trim().length < 3}>{busy ? "Guardando…" : "Guardar"}</button></div></form></Dialog.Content></Dialog.Portal>
      </Dialog.Root>
    </section>
  );
}
