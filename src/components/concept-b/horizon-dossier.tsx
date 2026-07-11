"use client";

import {
  ArrowLeft,
  ArrowUpRight,
  CalendarDays,
  CheckCircle2,
  CircleAlert,
  Clock3,
  FileCheck2,
  Loader2,
  Sparkles,
  UsersRound,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { useOracle } from "@/components/shared/oracle-provider";
import { formatDate, riskLabel } from "@/lib/oracle/format";

export function HorizonDossier() {
  const { id } = useParams<{ id: string }>();
  const { dossiers, signals, loading } = useOracle();
  const dossier = dossiers.find((d) => d.id === id);
  const linked = signals.filter((s) => s.dossierId === id);
  const [view, setView] = useState<"canvas" | "actors" | "trace">("canvas");
  if (loading)
    return (
      <div className="b-loading">
        <Loader2 className="spin" />
        <p>Preparando el espacio de decisión…</p>
      </div>
    );
  if (!dossier)
    return (
      <div className="b-not-found">
        <p className="b-eyebrow">Expediente no encontrado</p>
        <h1>Este espacio no está disponible.</h1>
        <Link href="/concept-b/portfolio">
          <ArrowLeft size={16} /> Volver al canvas
        </Link>
      </div>
    );
  return (
    <>
      <div className="b-dossier-top">
        <Link href="/concept-b/portfolio">
          <ArrowLeft size={16} /> Canvas de prioridades
        </Link>
        <span className="synthetic-badge">
          <Sparkles size={13} /> Datos sintéticos
        </span>
      </div>
      <header className="b-dossier-hero">
        <div>
          <div className="b-dossier-meta">
            <span>{dossier.typeLabel}</span>
            <span>
              {dossier.status === "active" ? "En movimiento" : "En pausa"}
            </span>
            <span>Actualizado {formatDate(dossier.updatedAt, true)}</span>
          </div>
          <h1>{dossier.title}</h1>
          <p>{dossier.objective}</p>
          <div className="b-tag-row">
            {[...dossier.geography, ...dossier.sectors].map((x) => (
              <span key={x}>{x}</span>
            ))}
          </div>
        </div>
        <aside>
          <p>Siguiente punto de decisión</p>
          <strong>{dossier.nextMilestone}</strong>
          <span>
            <CalendarDays size={15} />
            {formatDate(dossier.nextMilestoneDate)}
          </span>
          <div className="b-hero-score">
            <small>Potencial</small>
            <b>{dossier.opportunityScore}</b>
          </div>
        </aside>
      </header>
      <div
        className="b-dossier-tabs"
        role="tablist"
        aria-label="Vistas del expediente"
      >
        {(
          [
            ["canvas", "Canvas de decisión"],
            ["actors", "Actores"],
            ["trace", "Trazabilidad"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            role="tab"
            aria-selected={view === key}
            onClick={() => setView(key)}
          >
            {label}
          </button>
        ))}
      </div>
      {view === "canvas" && (
        <div className="b-decision-grid">
          <section className="b-canvas-zone b-situation">
            <header>
              <span>01</span>
              <div>
                <p>Situación</p>
                <h2>Qué está ocurriendo</h2>
              </div>
            </header>
            <p className="b-summary">{dossier.livingSummary}</p>
            <div className="b-trace-note">
              <FileCheck2 size={18} />
              <p>
                <strong>Lectura trazable</strong>
                <br />
                Construida con {linked.length} señales vinculadas. Las
                inferencias deben contrastarse antes de decidir.
              </p>
            </div>
          </section>
          <section className="b-canvas-zone b-options">
            <header>
              <span>02</span>
              <div>
                <p>Opciones</p>
                <h2>Cómo podemos avanzar</h2>
              </div>
            </header>
            {dossier.opportunities.length ? (
              dossier.opportunities.map((o) => (
                <article key={o.id}>
                  <div>
                    <span>
                      {o.status === "qualified" ? "Cualificada" : "Candidata"}
                    </span>
                    <strong>{o.score}</strong>
                  </div>
                  <h3>{o.title}</h3>
                  <p>{o.action}</p>
                  <small>
                    {o.deadline
                      ? `Ventana hasta ${formatDate(o.deadline)}`
                      : "Sin fecha límite"}
                  </small>
                </article>
              ))
            ) : (
              <div className="b-inline-empty">
                Todavía no hay opciones consolidadas.
              </div>
            )}
          </section>
          <section className="b-canvas-zone b-guards">
            <header>
              <span>03</span>
              <div>
                <p>Protecciones</p>
                <h2>Qué puede frenar el avance</h2>
              </div>
            </header>
            {dossier.risks.length ? (
              dossier.risks.map((r) => (
                <article key={r.id}>
                  <div>
                    <CircleAlert size={17} />
                    <span className={`b-risk ${r.level}`}>
                      {riskLabel[r.level]} · {r.score}
                    </span>
                  </div>
                  <h3>{r.title}</h3>
                  <p>{r.mitigation}</p>
                </article>
              ))
            ) : (
              <div className="b-inline-empty">Sin riesgos abiertos.</div>
            )}
          </section>
          <section className="b-canvas-zone b-next">
            <header>
              <span>04</span>
              <div>
                <p>Secuencia</p>
                <h2>Siguientes movimientos</h2>
              </div>
            </header>
            <div className="b-timeline">
              {dossier.timeline.slice(0, 4).map((item) => (
                <article key={item.id}>
                  <span>
                    <Clock3 size={15} />
                  </span>
                  <div>
                    <small>
                      {formatDate(item.date)} · {item.type}
                    </small>
                    <h3>{item.title}</h3>
                    <p>{item.detail}</p>
                  </div>
                </article>
              ))}
            </div>
          </section>
          <aside className="b-signal-rail">
            <p className="b-eyebrow">Evidencia vinculada</p>
            <h2>{linked.length} señales</h2>
            {linked.slice(0, 5).map((s) => (
              <article key={s.id}>
                <span>{s.confidence}% confianza</span>
                <strong>{s.title}</strong>
                <small>{s.sourceName}</small>
              </article>
            ))}
          </aside>
        </div>
      )}
      {view === "actors" && (
        <section className="b-actors-view">
          <header>
            <p className="b-eyebrow">Nexus</p>
            <h2>Actores que cambian el escenario</h2>
            <p>
              Prepara conversaciones desde influencia, alineamiento y contexto.
            </p>
          </header>
          <div className="b-actor-grid">
            {dossier.actors.map((a) => (
              <article key={a.id}>
                <span className="b-avatar">
                  {a.name
                    .split(" ")
                    .map((x) => x[0])
                    .join("")
                    .slice(0, 2)}
                </span>
                <div>
                  <h3>{a.name}</h3>
                  <p>
                    {a.role} · {a.kind}
                  </p>
                  <dl>
                    <div>
                      <dt>Influencia</dt>
                      <dd>{a.influence}</dd>
                    </div>
                    <div>
                      <dt>Alineamiento</dt>
                      <dd>{a.alignment}</dd>
                    </div>
                  </dl>
                </div>
                <button
                  onClick={() =>
                    toast.success("Briefing preparado", {
                      description: `Reunión sintética con ${a.name}.`,
                    })
                  }
                >
                  <UsersRound size={16} /> Preparar reunión
                </button>
              </article>
            ))}
          </div>
        </section>
      )}
      {view === "trace" && (
        <section className="b-history-view">
          <header>
            <p className="b-eyebrow">Registro verificable</p>
            <h2>Actividad y decisiones</h2>
          </header>
          <div className="b-timeline">
            {dossier.timeline.map((item) => (
              <article key={item.id}>
                <span>
                  <CheckCircle2 size={15} />
                </span>
                <div>
                  <small>
                    {formatDate(item.date)} · {item.type}
                  </small>
                  <h3>{item.title}</h3>
                  <p>{item.detail}</p>
                </div>
                <button
                  onClick={() =>
                    toast.info("Evidencias sintéticas", {
                      description: `Fuentes asociadas a «${item.title}».`,
                    })
                  }
                >
                  Ver fuentes <ArrowUpRight size={14} />
                </button>
              </article>
            ))}
          </div>
        </section>
      )}
    </>
  );
}
