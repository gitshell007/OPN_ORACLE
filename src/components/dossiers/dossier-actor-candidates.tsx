"use client";

import * as Dialog from "@radix-ui/react-dialog";
import {
  ApiError,
  api,
  type OracleActorCandidate,
} from "@oracle/api-client";
import { ExternalLink, Import, RefreshCw, RotateCcw, ScanSearch, Trash2, X } from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { PermissionGate } from "@/components/auth/auth-boundary";
import { AsyncActionButton } from "@/components/ui/async-action-button";

const TYPE_LABELS: Record<string, string> = {
  person: "Persona",
  organization: "Empresa u organización",
  institution: "Organismo o institución",
  program: "Programa o iniciativa",
  other: "Otro",
};

function errorMessage(reason: unknown, fallback: string) {
  return reason instanceof ApiError ? reason.problem.detail : fallback;
}

function labelsFrom(value: string) {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

export function DossierActorCandidates({
  dossierId,
  onImported,
}: {
  dossierId: string;
  onImported(): void;
}) {
  const [items, setItems] = useState<OracleActorCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<OracleActorCandidate | null>(null);
  const [actorType, setActorType] = useState("organization");
  const [labels, setLabels] = useState("");
  const [roles, setRoles] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [showDismissed, setShowDismissed] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.actors.candidates(dossierId, showDismissed);
      setItems(response.data);
    } catch (reason) {
      setItems([]);
      setError(errorMessage(reason, "No se pudieron detectar candidatos en las fuentes."));
    } finally {
      setLoading(false);
    }
  }, [dossierId, showDismissed]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  function review(candidate: OracleActorCandidate) {
    setSelected(candidate);
    setActorType(candidate.suggested_actor_type);
    setLabels((candidate.labels.length ? candidate.labels : candidate.suggested_labels).join(", "));
    setRoles("");
    setFormError(null);
  }

  async function importCandidate(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    setBusy(true);
    setFormError(null);
    try {
      await api.actors.importCandidate(dossierId, selected.id, {
        actor_type: actorType as "person" | "organization" | "institution" | "program" | "other",
        tags: labelsFrom(labels),
        roles: labelsFrom(roles),
      });
      toast.success("Actor incorporado", {
        description: `${selected.name} ya forma parte del expediente.`,
      });
      setSelected(null);
      await load();
      onImported();
    } catch (reason) {
      setFormError(errorMessage(reason, "No se pudo incorporar el candidato."));
    } finally {
      setBusy(false);
    }
  }

  async function reviewStatus(candidate: OracleActorCandidate, status: "candidate" | "dismissed") {
    setBusy(true);
    setError(null);
    try {
      await api.actors.reviewCandidate(dossierId, candidate.id, { status });
      toast.success(status === "dismissed" ? "Candidato descartado" : "Candidato restaurado", {
        description: candidate.name,
      });
      await load();
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo actualizar la revisión del candidato."));
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return <div className="work-loading" role="status"><span className="auth-spinner" /> Analizando entidades de las fuentes…</div>;
  }

  return (
    <div className="actor-candidates">
      <div className="actor-candidates-toolbar">
        <div><p>Entidades detectadas en señales vinculadas. Revisa su tipo y etiquetas antes de incorporarlas.</p><label className="candidate-dismissed-toggle"><input type="checkbox" checked={showDismissed} onChange={(event) => setShowDismissed(event.target.checked)} /> Mostrar descartados</label></div>
        <button className="icon-button bordered" type="button" aria-label="Recargar candidatos" onClick={() => void load()}><RefreshCw size={15} /></button>
      </div>
      {error && <p className="auth-inline-error" role="alert">{error}</p>}
      {!error && items.length === 0 ? (
        <div className="work-empty">
          <ScanSearch size={24} />
          <h2>No hay candidatos detectados</h2>
          <p>Las empresas, personas y organismos mencionados en las señales vinculadas aparecerán aquí con su procedencia.</p>
        </div>
      ) : (
        <>
          <div className="work-table-wrap">
            <table className="work-table actor-candidates-table">
              <thead><tr><th>Candidato</th><th>Tipo sugerido</th><th>Etiquetas</th><th>Fuentes</th><th><span className="sr-only">Acciones</span></th></tr></thead>
              <tbody>{items.map((candidate) => (
                <tr key={candidate.id}>
                  <td><strong>{candidate.name}</strong><small>{candidate.status === "linked" ? "Ya vinculado" : candidate.status === "existing" ? "Ya existe en la organización" : candidate.status === "dismissed" ? "Descartado" : "Pendiente de revisión"}</small></td>
                  <td>{TYPE_LABELS[candidate.suggested_actor_type] ?? candidate.suggested_actor_type}</td>
                  <td><div className="actor-labels">{candidate.suggested_labels.length ? candidate.suggested_labels.map((label) => <span key={label}>{label}</span>) : <small>Sin sugerencias</small>}</div></td>
                  <td><strong>{candidate.source_count}</strong><small>{candidate.sources[0]?.source_name}</small></td>
                  <td><PermissionGate permission="actor.write"><div className="candidate-actions">{candidate.status === "dismissed" ? <AsyncActionButton className="icon-button bordered" type="button" title="Restaurar candidato" aria-label={`Restaurar ${candidate.name}`} loading={busy} onClick={() => void reviewStatus(candidate, "candidate")}><RotateCcw size={14} /></AsyncActionButton> : <><button className="vector-secondary compact" disabled={candidate.status === "linked" || busy} onClick={() => review(candidate)}><Import size={13} /> {candidate.status === "existing" ? "Vincular" : "Revisar"}</button>{candidate.status !== "linked" && <AsyncActionButton className="icon-button bordered danger" type="button" title="Descartar candidato" aria-label={`Descartar ${candidate.name}`} loading={busy} onClick={() => void reviewStatus(candidate, "dismissed")}><Trash2 size={14} /></AsyncActionButton>}</>}</div></PermissionGate></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <div className="work-mobile-list">{items.map((candidate) => (
            <article key={candidate.id}>
              <header><span className={`intelligence-status status-${candidate.status}`}>{candidate.status === "linked" ? "Vinculado" : "Candidato"}</span><small>{candidate.source_count} fuentes</small></header>
              <h2>{candidate.name}</h2>
              <p>{TYPE_LABELS[candidate.suggested_actor_type] ?? candidate.suggested_actor_type}</p>
              <PermissionGate permission="actor.write">{candidate.status === "dismissed" ? <AsyncActionButton className="vector-secondary" loading={busy} onClick={() => void reviewStatus(candidate, "candidate")}><RotateCcw size={14} /> Restaurar</AsyncActionButton> : <div className="candidate-actions"><button className="vector-secondary" disabled={candidate.status === "linked" || busy} onClick={() => review(candidate)}>Revisar candidato</button>{candidate.status !== "linked" && <AsyncActionButton className="icon-button bordered danger" type="button" aria-label={`Descartar ${candidate.name}`} loading={busy} onClick={() => void reviewStatus(candidate, "dismissed")}><Trash2 size={14} /></AsyncActionButton>}</div>}</PermissionGate>
            </article>
          ))}</div>
        </>
      )}

      <Dialog.Root open={Boolean(selected)} onOpenChange={(open) => !open && setSelected(null)}>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="dialog-content work-dialog actor-candidate-dialog">
            {selected && <>
              <div className="dialog-header"><div><span className="section-kicker">Importación desde fuentes</span><Dialog.Title>{selected.name}</Dialog.Title><Dialog.Description>Confirma cómo debe incorporarse al mapa de actores. La procedencia de las señales quedará registrada.</Dialog.Description></div><Dialog.Close className="icon-button" aria-label="Cerrar"><X /></Dialog.Close></div>
              <form onSubmit={importCandidate}>
                <label>Tipo de actor<select value={actorType} onChange={(event) => setActorType(event.target.value)}>{Object.entries(TYPE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
                <label>Etiquetas (separadas por comas)<input value={labels} onChange={(event) => setLabels(event.target.value)} placeholder="fabricante, socio industrial" /></label>
                <label>Roles en este expediente (separados por comas)<input value={roles} onChange={(event) => setRoles(event.target.value)} placeholder="competidor, aliado potencial" /></label>
                <section className="candidate-sources" aria-label="Fuentes del candidato"><h3>Procedencia</h3><ul>{selected.sources.map((source) => <li key={source.dossier_signal_id}><div><strong>{source.title}</strong><small>{source.source_name}</small></div>{source.source_url && <a href={source.source_url} target="_blank" rel="noreferrer" aria-label={`Abrir fuente de ${source.title}`}><ExternalLink size={13} /></a>}</li>)}</ul></section>
                {formError && <p className="form-error" role="alert">{formError}</p>}
                <div className="dialog-actions"><Dialog.Close className="vector-secondary" type="button">Cancelar</Dialog.Close><AsyncActionButton className="vector-primary" type="submit" loading={busy}>{busy ? "Incorporando…" : "Incorporar actor"}</AsyncActionButton></div>
              </form>
            </>}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}
