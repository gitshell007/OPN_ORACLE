"use client";

import * as Dialog from "@radix-ui/react-dialog";
import {
  ArrowRight,
  CheckCircle2,
  CircleAlert,
  Clock3,
  Filter,
  Loader2,
  Search,
  Sparkles,
  X,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { useOracle } from "@/components/shared/oracle-provider";
import { formatDate, riskLabel, signalTypeLabel } from "@/lib/oracle/format";
import type { RiskLevel, Signal, StrategicDossier } from "@/lib/oracle/types";

type Lane = "decide" | "advance" | "watch";
const laneMeta: Record<Lane, { title: string; note: string }> = {
  decide: {
    title: "Decidir ahora",
    note: "Ventanas o bloqueos con impacto inmediato",
  },
  advance: {
    title: "Impulsar",
    note: "Expedientes con margen claro de avance",
  },
  watch: { title: "Observar", note: "Seguimiento activo sin acción urgente" },
};

function laneFor(d: StrategicDossier): Lane {
  if (d.riskLevel === "critical" || d.riskLevel === "high" || d.newSignals > 1)
    return "decide";
  if (d.opportunityScore >= 70 && d.status === "active") return "advance";
  return "watch";
}

export function HorizonPortfolio() {
  const { dossiers, signals, loading } = useOracle();
  const [query, setQuery] = useState("");
  const [risk, setRisk] = useState<RiskLevel | "all">("all");
  const [selected, setSelected] = useState<string[]>([]);
  const [decisionSignal, setDecisionSignal] = useState<Signal | null>(null);
  const visible = useMemo(
    () =>
      dossiers.filter(
        (d) =>
          `${d.title} ${d.owner} ${d.sectors.join(" ")}`
            .toLocaleLowerCase("es")
            .includes(query.toLocaleLowerCase("es")) &&
          (risk === "all" || d.riskLevel === risk),
      ),
    [dossiers, query, risk],
  );
  const newSignals = signals
    .filter((s) => s.status === "new")
    .sort((a, b) => b.relevance - a.relevance);
  const toggle = (id: string) =>
    setSelected((v) =>
      v.includes(id) ? v.filter((x) => x !== id) : [...v, id],
    );

  return (
    <>
      <header className="b-canvas-head">
        <div>
          <p className="b-eyebrow">Espacio de decisión · 10 julio 2026</p>
          <h1>Convierte señales en movimiento.</h1>
          <p>
            Ordena el portfolio por la acción que exige, no por su categoría.
          </p>
        </div>
        <span className="synthetic-badge">
          <Sparkles size={13} /> Datos sintéticos
        </span>
      </header>
      {loading ? (
        <div className="b-loading">
          <Loader2 className="spin" />
          <p>Componiendo el canvas…</p>
        </div>
      ) : (
        <>
          <section className="b-pulse" aria-label="Pulso del portfolio">
            <div>
              <span>Decisiones abiertas</span>
              <strong>
                {visible.filter((d) => laneFor(d) === "decide").length}
              </strong>
              <small>requieren foco hoy</small>
            </div>
            <div>
              <span>Potencial medio</span>
              <strong>
                {Math.round(
                  visible.reduce((n, d) => n + d.opportunityScore, 0) /
                    Math.max(visible.length, 1),
                )}
              </strong>
              <small>sobre 100</small>
            </div>
            <div>
              <span>Señales nuevas</span>
              <strong>{newSignals.length}</strong>
              <small>pendientes de contraste</small>
            </div>
            <div className="b-pulse-callout">
              <CircleAlert size={18} />
              <p>
                <strong>Ventana activa</strong>
                <br />
                Revisa los carriles antes del siguiente hito.
              </p>
            </div>
          </section>

          <section className="b-canvas-tools" aria-label="Filtros del canvas">
            <label className="b-table-search">
              <Search size={17} />
              <span className="sr-only">Buscar expediente</span>
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Buscar expediente, responsable o sector"
              />
            </label>
            <label className="b-select-wrap">
              <Filter size={16} />
              <span className="sr-only">Filtrar por riesgo</span>
              <select
                value={risk}
                onChange={(e) => setRisk(e.target.value as RiskLevel | "all")}
              >
                <option value="all">Todos los riesgos</option>
                <option value="critical">Crítico</option>
                <option value="high">Alto</option>
                <option value="medium">Medio</option>
                <option value="low">Bajo</option>
              </select>
            </label>
            <span>{visible.length} expedientes visibles</span>
          </section>
          {selected.length > 0 && (
            <div className="b-bulk">
              <strong>{selected.length} elementos en foco</strong>
              <button
                onClick={() => {
                  toast.success("Foco de trabajo actualizado");
                  setSelected([]);
                }}
              >
                Crear lista de trabajo
              </button>
              <button onClick={() => setSelected([])}>Limpiar</button>
            </div>
          )}

          <section className="b-lanes" aria-label="Carriles de prioridad">
            {(Object.keys(laneMeta) as Lane[]).map((lane) => {
              const items = visible.filter((d) => laneFor(d) === lane);
              return (
                <section className={`b-lane ${lane}`} key={lane}>
                  <header>
                    <span>{items.length}</span>
                    <div>
                      <h2>{laneMeta[lane].title}</h2>
                      <p>{laneMeta[lane].note}</p>
                    </div>
                  </header>
                  <div className="b-lane-stack">
                    {items.map((d) => (
                      <DossierCard
                        key={d.id}
                        dossier={d}
                        selected={selected.includes(d.id)}
                        onSelect={() => toggle(d.id)}
                      />
                    ))}
                    {!items.length && (
                      <div className="b-lane-empty">
                        No hay expedientes en este carril con los filtros
                        actuales.
                      </div>
                    )}
                  </div>
                </section>
              );
            })}
          </section>

          <section id="signals" className="b-signal-queue">
            <header>
              <div>
                <p className="b-eyebrow">Bandeja de contraste</p>
                <h2>Señales que pueden mover el canvas</h2>
              </div>
              <span>{newSignals.length} nuevas</span>
            </header>
            <div>
              {newSignals.slice(0, 4).map((s) => (
                <button key={s.id} onClick={() => setDecisionSignal(s)}>
                  <span className="b-signal-icon">
                    {signalTypeLabel[s.sourceType].slice(0, 2)}
                  </span>
                  <span>
                    <small>
                      {signalTypeLabel[s.sourceType]} ·{" "}
                      {formatDate(s.publishedAt)}
                    </small>
                    <strong>{s.title}</strong>
                    <em>{s.whyItMatters}</em>
                  </span>
                  <span className="b-signal-score">
                    <strong>{s.relevance}</strong>
                    <small>relevancia</small>
                  </span>
                  <ArrowRight size={18} />
                </button>
              ))}
            </div>
          </section>
        </>
      )}
      <SignalDecisionDialog
        signal={decisionSignal}
        onClose={() => setDecisionSignal(null)}
      />
    </>
  );
}

function DossierCard({
  dossier: d,
  selected,
  onSelect,
}: {
  dossier: StrategicDossier;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <article className={`b-canvas-card ${selected ? "selected" : ""}`}>
      <div className="b-card-top">
        <label>
          <input type="checkbox" checked={selected} onChange={onSelect} />
          <span className="sr-only">Seleccionar {d.title}</span>
        </label>
        <span className={`b-risk ${d.riskLevel}`}>
          {riskLabel[d.riskLevel]} · {d.riskScore}
        </span>
      </div>
      <Link href={`/concept-b/dossiers/${d.id}`}>
        <small>
          {d.typeLabel} · {d.owner}
        </small>
        <h3>{d.title}</h3>
        <p>{d.livingSummary}</p>
      </Link>
      <div className="b-card-scores">
        <span>
          <small>Oportunidad</small>
          <strong>{d.opportunityScore}</strong>
        </span>
        <span>
          <small>Señales</small>
          <strong>{d.newSignals}</strong>
        </span>
      </div>
      <footer>
        <Clock3 size={14} />
        <span>{d.nextMilestone}</span>
        <time>{formatDate(d.nextMilestoneDate)}</time>
      </footer>
    </article>
  );
}

function SignalDecisionDialog({
  signal,
  onClose,
}: {
  signal: Signal | null;
  onClose: () => void;
}) {
  const { actOnSignal, dossiers } = useOracle();
  const [working, setWorking] = useState(false);
  const dossier = dossiers.find((d) => d.id === signal?.dossierId);
  const act = async (
    status: "reviewed" | "dismissed" | "promoted",
    promotedAs?: "opportunity" | "risk",
  ) => {
    if (!signal) return;
    setWorking(true);
    await actOnSignal({ signalId: signal.id, status, promotedAs });
    toast.success(
      status === "promoted"
        ? `Señal promovida a ${promotedAs === "risk" ? "riesgo" : "oportunidad"}`
        : status === "dismissed"
          ? "Señal descartada"
          : "Señal revisada",
      { description: dossier?.title },
    );
    setWorking(false);
    onClose();
  };
  return (
    <Dialog.Root open={!!signal} onOpenChange={(v) => !v && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content b-signal-dialog">
          <div className="b-dialog-label">Inspección contextual</div>
          <Dialog.Title>Decidir sobre esta señal</Dialog.Title>
          <Dialog.Description>
            {dossier?.title} · {signal && signalTypeLabel[signal.sourceType]}
          </Dialog.Description>
          <Dialog.Close className="dialog-close" aria-label="Cerrar">
            <X size={18} />
          </Dialog.Close>
          {signal && (
            <>
              <div className="b-dialog-score">
                <span>
                  <strong>{signal.relevance}</strong> relevancia
                </span>
                <span>
                  <strong>{signal.confidence}%</strong> confianza
                </span>
                <span>
                  <strong>{signal.credibility}%</strong> credibilidad
                </span>
              </div>
              <h3>{signal.title}</h3>
              <p>{signal.summary}</p>
              <aside>
                <strong>Impacto posible</strong>
                <p>{signal.whyItMatters}</p>
              </aside>
              <div className="b-evidence">
                <strong>Evidencias</strong>
                {signal.evidence.map((e) => (
                  <div key={e.id}>
                    <CheckCircle2 size={16} />
                    <p>
                      <b>{e.label}</b> · {e.source}
                      <br />
                      <span>{e.excerpt}</span>
                    </p>
                  </div>
                ))}
              </div>
              <div className="b-decision-actions">
                <button
                  disabled={working}
                  className="b-promote"
                  onClick={() => act("promoted", "opportunity")}
                >
                  Convertir en oportunidad
                </button>
                <button
                  disabled={working}
                  onClick={() => act("promoted", "risk")}
                >
                  Convertir en riesgo
                </button>
                <button disabled={working} onClick={() => act("reviewed")}>
                  Marcar revisada
                </button>
                <button
                  disabled={working}
                  className="b-dismiss"
                  onClick={() => act("dismissed")}
                >
                  Descartar
                </button>
              </div>
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
