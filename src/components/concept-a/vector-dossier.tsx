"use client";
import {
  ArrowLeft,
  CalendarPlus,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  FileText,
  Link2,
  MoreHorizontal,
  Pencil,
  Radio,
  Share2,
  ShieldCheck,
  Users,
} from "lucide-react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api, type BackendDossier } from "@oracle/api-client";
import { toast } from "sonner";
import { useOracle } from "@/components/shared/oracle-provider";
import { formatDate, riskLabel, signalTypeLabel } from "@/lib/oracle/format";
import type { RiskLevel, Signal } from "@/lib/oracle/types";
import { SignalDrawer } from "./signal-drawer";
import { DossierDocuments, VectorDocuments } from "./vector-documents";
import { ReportLibrary, SyntheticReports } from "@/components/reporting/report-library";
const tabs = [
  "Resumen",
  "Radar",
  "Oportunidades",
  "Riesgos",
  "Actores",
  "Decisiones",
  "Informes",
  "Documentos",
] as const;
export function VectorDossier() {
  const { id } = useParams<{ id: string }>();
  const pathname = usePathname();
  const routeBase: "/app" | "/concept-a" = pathname.startsWith("/app")
    ? "/app"
    : "/concept-a";
  const canonical = routeBase === "/app";
  const { dossiers, signals, loading } = useOracle();
  const [tab, setTab] = useState<(typeof tabs)[number]>("Resumen");
  const [signal, setSignal] = useState<Signal | null>(null);
  const dossier = useMemo(
    () => dossiers.find((d) => d.id === id),
    [dossiers, id],
  );
  const related = signals.filter((s) => s.dossierId === id);
  if (loading && !dossier)
    return (
      <div className="dossier-loading">
        <span />
        <span />
        <span />
      </div>
    );
  if (!dossier && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(id))
    return <BackendVectorDossier dossierId={id} routeBase={routeBase} />;
  if (!dossier)
    return (
      <div className="not-found">
        <strong>Expediente no encontrado</strong>
        <p>Puede que se haya restablecido el estado local de la demo.</p>
        <Link className="vector-primary" href={canonical ? "/app/dossiers" : "/concept-a/portfolio"}>
          Volver al portfolio
        </Link>
      </div>
    );
  const action = (label: string, description: string) =>
    toast.success(label, { description });
  return (
    <div className="dossier-page">
      <Link className="back-link" href={canonical ? "/app/dossiers" : "/concept-a/portfolio"}>
        <ArrowLeft size={15} />
        Portfolio
      </Link>
      <header className="dossier-header">
        <div>
          <div className="dossier-meta">
            <span className="status active">Activo</span>
            <span>{dossier.typeLabel}</span>
            <span>Actualizado {formatDate(dossier.updatedAt, true)}</span>
          </div>
          <h1>{dossier.title}</h1>
          <p>{dossier.objective}</p>
          <div className="owner-line">
            <span className="user-avatar">
              {dossier.owner
                .split(" ")
                .map((v) => v[0])
                .join("")}
            </span>
            <span>
              Responsable
              <br />
              <strong>{dossier.owner}</strong>
            </span>
          </div>
        </div>
        <div className="dossier-actions">
          {canonical ? (
            <Link className="vector-primary" href={`/app/dossiers/${id}/reports`}>
              <FileText size={16} />
              Abrir informes
            </Link>
          ) : (
            <>
              <button
                className="vector-secondary"
                onClick={() =>
                  action(
                    "Edición habilitada",
                    "Los cambios se simulan en esta versión del prototipo.",
                  )
                }
              >
                <Pencil size={16} />
                Editar
              </button>
              <button
                className="vector-secondary"
                onClick={() =>
                  action("Enlace copiado", "Enlace sintético al expediente copiado.")
                }
              >
                <Share2 size={16} />
                Compartir
              </button>
              <button className="vector-primary" onClick={() => setTab("Informes")}>
                <FileText size={16} />
                Generar informe
              </button>
              <button
                className="icon-button bordered"
                aria-label="Más acciones"
                onClick={() =>
                  action(
                    "Acciones disponibles",
                    "Añadir tarea, preparar reunión o archivar expediente.",
                  )
                }
              >
                <MoreHorizontal size={18} />
              </button>
            </>
          )}
        </div>
      </header>
      {!canonical && <nav className="dossier-tabs" aria-label="Secciones del expediente">
        {tabs.map((t) => (
          <button
            key={t}
            className={tab === t ? "active" : ""}
            onClick={() => setTab(t)}
          >
            {t}
            {t === "Radar" &&
              related.filter((s) => s.status === "new").length > 0 && (
                <b>{related.filter((s) => s.status === "new").length}</b>
              )}
          </button>
        ))}
      </nav>}
      {canonical && (
        <section className="vector-panel situation-panel">
          <header>
            <div>
              <span className="section-kicker">Resumen sintético identificado</span>
              <h2>Situación actual</h2>
            </div>
            <span className="confidence">Confianza 82%</span>
          </header>
          <p className="living-summary">{dossier.livingSummary}</p>
          <p>
            Esta ficha de demostración conserva el contexto visual. Las secciones
            conectadas a backend se abren mediante las rutas del expediente.
          </p>
          <div className="placeholder-actions">
            <Link className="vector-secondary" href={`/app/dossiers/${id}/signals`}>
              Abrir señales
            </Link>
            <Link className="vector-secondary" href={`/app/dossiers/${id}/documents`}>
              Abrir documentos
            </Link>
          </div>
        </section>
      )}
      {!canonical && tab === "Resumen" && (
        <Summary dossier={dossier} related={related} setSignal={setSignal} />
      )}{" "}
      {tab === "Radar" && <RadarTab related={related} setSignal={setSignal} />}{" "}
      {tab === "Oportunidades" && (
        <CardsTab kind="opportunity" items={dossier.opportunities} />
      )}{" "}
      {tab === "Riesgos" && <CardsTab kind="risk" items={dossier.risks} />}{" "}
      {tab === "Actores" && <ActorsTab dossier={dossier} />}{" "}
      {tab === "Decisiones" && <DecisionsTab dossier={dossier} />}
      {tab === "Informes" && <SyntheticReports />}
      {tab === "Documentos" && <DossierDocuments dossierId={id} />}
      <SignalDrawer
        signal={signal}
        open={!!signal}
        onOpenChange={(o) => !o && setSignal(null)}
      />
    </div>
  );
}

function BackendVectorDossier({
  dossierId,
  routeBase,
}: {
  dossierId: string;
  routeBase: "/app" | "/concept-a";
}) {
  const [dossier, setDossier] = useState<BackendDossier | null>(null);
  const [error, setError] = useState(false);
  const [tab, setTab] = useState<"Documentos" | "Informes">("Documentos");
  useEffect(() => {
    const kickoff = window.setTimeout(() => {
      void api.dossiers.get(dossierId).then(setDossier).catch(() => setError(true));
    }, 0);
    return () => window.clearTimeout(kickoff);
  }, [dossierId]);
  if (error)
    return <div className="not-found"><strong>Expediente no disponible</strong><Link className="vector-primary" href={routeBase === "/app" ? "/app/dossiers" : "/concept-a/portfolio"}>Volver al portfolio</Link></div>;
  if (!dossier) return <div className="dossier-loading"><span/><span/><span/></div>;
  if (routeBase === "/app") {
    return <div className="dossier-page">
      <Link className="back-link" href="/app/dossiers"><ArrowLeft size={15}/>Expedientes</Link>
      <header className="dossier-header"><div><div className="dossier-meta"><span className="status active">{dossier.status}</span><span>{dossier.dossier_type}</span><span>Datos persistentes</span></div><h1>{dossier.title}</h1><p>{dossier.strategic_goal || dossier.description}</p></div><div className="dossier-actions"><Link className="vector-primary" href={`/app/dossiers/${dossier.id}/reports`}><FileText size={16}/>Abrir informes</Link></div></header>
      <section className="vector-panel">
        <header><div><span className="section-kicker">Resumen autoritativo</span><h2>Situación del expediente</h2></div></header>
        <p>{dossier.description || "El expediente todavía no tiene una descripción operativa."}</p>
        <div className="placeholder-actions"><Link className="vector-secondary" href={`/app/dossiers/${dossier.id}/documents`}>Documentos</Link><Link className="vector-secondary" href={`/app/dossiers/${dossier.id}/signals`}>Señales</Link></div>
      </section>
    </div>;
  }
  return <div className="dossier-page">
    <Link className="back-link" href={`${routeBase}/portfolio`}><ArrowLeft size={15}/>Portfolio</Link>
    <header className="dossier-header"><div><div className="dossier-meta"><span className="status active">{dossier.status}</span><span>{dossier.dossier_type}</span><span>Datos persistentes</span></div><h1>{dossier.title}</h1><p>{dossier.strategic_goal || dossier.description}</p></div><div className="dossier-actions"><button className="vector-primary" onClick={() => setTab("Informes")}><FileText size={16}/>Generar informe</button></div></header>
    <nav className="dossier-tabs" aria-label="Secciones del expediente"><button className={tab === "Documentos" ? "active" : ""} onClick={() => setTab("Documentos")}>Documentos</button><button className={tab === "Informes" ? "active" : ""} onClick={() => setTab("Informes")}>Informes</button></nav>
    {tab === "Documentos" ? <VectorDocuments dossierId={dossier.id}/> : <ReportLibrary dossierId={dossier.id} routeBase={routeBase}/>} 
  </div>;
}

function Summary({
  dossier,
  related,
  setSignal,
}: {
  dossier: ReturnType<typeof useOracle>["dossiers"][number];
  related: Signal[];
  setSignal: (s: Signal) => void;
}) {
  return (
    <div className="dossier-summary">
      <main>
        <section className="vector-panel situation-panel">
          <header>
            <div>
              <span className="section-kicker">Memoria consolidada</span>
              <h2>Situación actual</h2>
            </div>
            <span className="confidence">Confianza 82%</span>
          </header>
          <p className="living-summary">{dossier.livingSummary}</p>
          <div className="insight-grid">
            <article>
              <span>Hechos</span>
              <p>
                Hay {related.length} señales asociadas;{" "}
                {related.filter((s) => s.status === "new").length} siguen
                pendientes de revisión.
              </p>
            </article>
            <article>
              <span>Inferencia</span>
              <p>
                El potencial se mantiene alto, condicionado por una validación
                externa antes del próximo hito.
              </p>
            </article>
            <article>
              <span>Recomendación</span>
              <p>
                {dossier.opportunities[0]?.action ??
                  "Completar la primera revisión estratégica."}
              </p>
            </article>
          </div>
        </section>
        <section className="vector-panel">
          <header>
            <div>
              <span className="section-kicker">
                Última sincronización 09:28
              </span>
              <h2>Radar de señales</h2>
            </div>
            <button
              className="text-button"
              onClick={() =>
                toast.info("Radar del expediente", {
                  description: `${related.length} señales vinculadas en esta vista.`,
                })
              }
            >
              Abrir radar completo
            </button>
          </header>
          <div className="dossier-signal-table">
            {related.length ? (
              related.map((s) => (
                <button key={s.id} onClick={() => setSignal(s)}>
                  <span className="score-ring">{s.relevance}</span>
                  <span>
                    <small>
                      {signalTypeLabel[s.sourceType]} · {s.sourceName}
                    </small>
                    <strong>{s.title}</strong>
                    <em>
                      {formatDate(s.publishedAt, true)} · Confianza{" "}
                      {s.confidence}%
                    </em>
                  </span>
                  <span className={`signal-state ${s.status}`}>
                    {s.status === "new"
                      ? "Nueva"
                      : s.status === "reviewed"
                        ? "Revisada"
                        : s.status === "promoted"
                          ? "Promovida"
                          : "Descartada"}
                  </span>
                  <ChevronRight size={16} />
                </button>
              ))
            ) : (
              <p className="muted">
                La primera sincronización todavía no ha generado señales.
              </p>
            )}
          </div>
        </section>
        <section className="vector-panel" id="actores">
          <header>
            <div>
              <span className="section-kicker">
                Nexus · contexto relacional
              </span>
              <h2>Red de actores</h2>
            </div>
            <span className="confidence">
              {dossier.actors.length} vinculados
            </span>
          </header>
          <div className="actor-network">
            <div className="network-core">
              <span>Expediente</span>
              <strong>{dossier.title}</strong>
            </div>
            {dossier.actors.map((a, i) => (
              <button
                key={a.id}
                className={`actor-node node-${i}`}
                onClick={() =>
                  toast.info(a.name, {
                    description: `${a.role} · Influencia ${a.influence} · Alineación ${a.alignment}`,
                  })
                }
              >
                <span>
                  {a.name
                    .split(" ")
                    .map((v) => v[0])
                    .join("")}
                </span>
                <strong>{a.name}</strong>
                <small>{a.role}</small>
              </button>
            ))}
          </div>
        </section>
      </main>
      <aside>
        <ScorePanel dossier={dossier} />
        <section className="vector-panel next-actions">
          <span className="section-kicker">Siguiente mejor acción</span>
          <h2>
            {dossier.opportunities[0]?.action ?? "Definir hipótesis inicial"}
          </h2>
          <p>
            Recomendación basada en oportunidad, plazo y capacidad de control.
          </p>
          <button
            className="vector-primary"
            onClick={() =>
              toast.success("Tarea añadida", {
                description: "Asignada a Lucía Herrera · vence el 15 jul.",
              })
            }
          >
            <ClipboardList size={16} />
            Convertir en tarea
          </button>
          <small>Confianza 84% · 3 evidencias</small>
        </section>
        <section className="vector-panel milestone-panel">
          <header>
            <h2>Próximos hitos</h2>
            <CalendarPlus size={17} />
          </header>
          <strong>{dossier.nextMilestone}</strong>
          <p>
            {formatDate(dossier.nextMilestoneDate)} · Responsable:{" "}
            {dossier.owner}
          </p>
          <button
            className="text-button"
            onClick={() =>
              toast.success("Reunión preparada", {
                description: "Se ha creado un briefing de reunión sintético.",
              })
            }
          >
            Preparar reunión
          </button>
        </section>
        <MonitorPanel />
      </aside>
    </div>
  );
}
function ScorePanel({
  dossier,
}: {
  dossier: ReturnType<typeof useOracle>["dossiers"][number];
}) {
  return (
    <section className="vector-panel score-panel">
      <header>
        <h2>Lectura estratégica</h2>
        <ShieldCheck size={17} />
      </header>
      <div className="main-score">
        <strong>{dossier.healthScore}</strong>
        <span>
          Salud
          <br />
          <small>+3 esta semana</small>
        </span>
      </div>
      <div className="score-lines">
        <span>
          Oportunidad <b>{dossier.opportunityScore}</b>
          <i>
            <em style={{ width: `${dossier.opportunityScore}%` }} />
          </i>
        </span>
        <span>
          Riesgo <b>{dossier.riskScore}</b>
          <i className="risk">
            <em style={{ width: `${dossier.riskScore}%` }} />
          </i>
        </span>
      </div>
      <details>
        <summary>Cómo se calcula</summary>
        <p>
          Combina señales, ajuste estratégico, avance de hitos y exposición.
          Última evaluación: 10 jul, 09:28.
        </p>
      </details>
    </section>
  );
}
function MonitorPanel() {
  const [active, setActive] = useState(true);
  return (
    <section className="vector-panel monitor-panel">
      <header>
        <div>
          <span className="section-kicker">Adaptador conectado</span>
          <h2>Signal Avanza</h2>
        </div>
        <span className="connected">● Conectado</span>
      </header>
      <p>12 fuentes · sincronización cada 30 min</p>
      <label>
        <input
          type="checkbox"
          checked={active}
          onChange={(e) => {
            setActive(e.target.checked);
            toast.success(
              e.target.checked ? "Monitor activado" : "Monitor pausado",
            );
          }}
        />
        Monitor activo
      </label>
      <button
        className="vector-secondary"
        onClick={() =>
          toast.success("Sincronización completa", {
            description: "No hay señales nuevas desde las 09:28.",
          })
        }
      >
        <Radio size={15} />
        Sincronizar ahora
      </button>
    </section>
  );
}
function RadarTab({
  related,
  setSignal,
}: {
  related: Signal[];
  setSignal: (s: Signal) => void;
}) {
  return (
    <section className="vector-panel tab-panel">
      <header>
        <div>
          <span className="section-kicker">Inbox asociado</span>
          <h2>Radar de señales</h2>
        </div>
        <span className="signal-live">● Signal Avanza conectado</span>
      </header>
      <div className="dossier-signal-table">
        {related.map((s) => (
          <button key={s.id} onClick={() => setSignal(s)}>
            <span className="score-ring">{s.relevance}</span>
            <span>
              <small>
                {signalTypeLabel[s.sourceType]} · {s.sourceName}
              </small>
              <strong>{s.title}</strong>
              <em>{s.whyItMatters}</em>
            </span>
            <span className={`signal-state ${s.status}`}>{s.status}</span>
            <ChevronRight size={16} />
          </button>
        ))}
      </div>
    </section>
  );
}
function CardsTab({
  kind,
  items,
}: {
  kind: "opportunity" | "risk";
  items: Array<{
    id: string;
    title: string;
    score: number;
    level?: RiskLevel;
    action?: string;
    mitigation?: string;
  }>;
}) {
  return (
    <section className="tab-panel card-tab">
      <header>
        <div>
          <span className="section-kicker">
            {kind === "opportunity"
              ? "Impulso estratégico"
              : "Protección del avance"}
          </span>
          <h2>{kind === "opportunity" ? "Oportunidades" : "Riesgos"}</h2>
        </div>
        <button
          className="vector-primary"
          onClick={() =>
            toast.success(
              kind === "opportunity"
                ? "Oportunidad creada"
                : "Riesgo registrado",
            )
          }
        >
          Añadir {kind === "opportunity" ? "oportunidad" : "riesgo"}
        </button>
      </header>
      <div className="object-cards">
        {items.map((item) => (
          <article key={item.id} className={kind}>
            <span>
              {kind === "opportunity"
                ? "Oportunidad cualificada"
                : `Riesgo ${item.level ? riskLabel[item.level] : "Sin clasificar"}`}
            </span>
            <strong>{item.title}</strong>
            <div className="object-score">
              {item.score}
              <small>/ 100</small>
            </div>
            <p>{kind === "opportunity" ? item.action : item.mitigation}</p>
            <footer>
              <button
                className="vector-secondary"
                onClick={() =>
                  toast.info(item.title, {
                    description:
                      "Análisis simulado con puntuación, plazo y siguiente acción.",
                  })
                }
              >
                Abrir análisis
              </button>
              <button
                className="text-button"
                onClick={() =>
                  toast.info("Evidencias sintéticas", {
                    description: `Fuentes que respaldan «${item.title}».`,
                  })
                }
              >
                Ver evidencias
              </button>
            </footer>
          </article>
        ))}
      </div>
    </section>
  );
}
function ActorsTab({
  dossier,
}: {
  dossier: ReturnType<typeof useOracle>["dossiers"][number];
}) {
  return (
    <section className="tab-panel actor-tab">
      <header>
        <div>
          <span className="section-kicker">Nexus disponible</span>
          <h2>Mapa de actores</h2>
        </div>
        <button
          className="vector-primary"
          onClick={() =>
            toast.success("Actor vinculado", {
              description: "La vinculación es simulada en este prototipo.",
            })
          }
        >
          <Users size={16} />
          Vincular actor
        </button>
      </header>
      <div className="actor-matrix">
        <div className="matrix-axis y">Influencia →</div>
        <div className="matrix-axis x">Alineación →</div>
        {dossier.actors.map((a) => (
          <button
            key={a.id}
            style={{
              left: `${Math.max(8, a.alignment - 8)}%`,
              bottom: `${Math.max(10, a.influence - 42)}%`,
            }}
            onClick={() =>
              toast.info(a.name, {
                description: `${a.role} · Influencia ${a.influence} · Alineación ${a.alignment}`,
              })
            }
          >
            <span>
              {a.name
                .split(" ")
                .map((v) => v[0])
                .join("")}
            </span>
            <strong>{a.name}</strong>
            <small>{a.role}</small>
          </button>
        ))}
      </div>
    </section>
  );
}
function DecisionsTab({
  dossier,
}: {
  dossier: ReturnType<typeof useOracle>["dossiers"][number];
}) {
  return (
    <section className="tab-panel decisions-tab" id="decisiones">
      <header>
        <div>
          <span className="section-kicker">Memoria y trazabilidad</span>
          <h2>Decisiones y actividad</h2>
        </div>
        <button
          className="vector-primary"
          onClick={() =>
            toast.success("Decisión registrada", {
              description:
                "Se ha añadido una decisión sintética a la memoria del expediente.",
            })
          }
        >
          Registrar decisión
        </button>
      </header>
      <div className="timeline">
        {dossier.timeline.map((t) => (
          <article key={t.id}>
            <span className={`timeline-icon ${t.type}`}>
              {t.type === "decision" ? (
                <CheckCircle2 />
              ) : t.type === "meeting" ? (
                <Users />
              ) : (
                <Radio />
              )}
            </span>
            <div>
              <small>{formatDate(t.date)}</small>
              <strong>{t.title}</strong>
              <p>{t.detail}</p>
              <button
                className="text-button"
                onClick={() =>
                  toast.info("Evidencia abierta", {
                    description: `Trazabilidad sintética de «${t.title}».`,
                  })
                }
              >
                <Link2 size={13} />
                Ver evidencia
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
