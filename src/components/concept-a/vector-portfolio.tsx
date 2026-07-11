"use client";

import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  CalendarClock,
  CheckSquare,
  ChevronLeft,
  ChevronRight,
  Columns3,
  Filter,
  ListChecks,
  MoreHorizontal,
  Search,
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api, type BackendDossier } from "@oracle/api-client";
import { toast } from "sonner";
import { useOracle } from "@/components/shared/oracle-provider";
import { recentChanges } from "@/lib/oracle/fixtures";
import { formatDate, riskLabel, signalTypeLabel } from "@/lib/oracle/format";
import type {
  Density,
  RiskLevel,
  Signal,
  StrategicDossier,
} from "@/lib/oracle/types";
import { SignalDrawer } from "./signal-drawer";

type SortKey =
  | "title"
  | "opportunityScore"
  | "riskScore"
  | "newSignals"
  | "updatedAt";
const columns = [
  "tipo",
  "salud",
  "oportunidad",
  "riesgo",
  "señales",
  "hito",
  "actualizado",
] as const;

export function VectorPortfolio() {
  const pathname = usePathname();
  const routeBase = pathname.startsWith("/app") ? "/app" : "/concept-a";
  const { dossiers, signals, settings, loading, saveSettings } = useOracle();
  const [query, setQuery] = useState("");
  const [risk, setRisk] = useState<RiskLevel | "all">("all");
  const [status, setStatus] = useState("all");
  const [type, setType] = useState("all");
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({
    key: "riskScore",
    dir: "desc",
  });
  const [selected, setSelected] = useState<string[]>([]);
  const [visible, setVisible] = useState<string[]>([...columns]);
  const [columnsOpen, setColumnsOpen] = useState(false);
  const [signal, setSignal] = useState<Signal | null>(null);
  const [backendDossiers, setBackendDossiers] = useState<BackendDossier[]>([]);
  useEffect(() => {
    const kickoff = window.setTimeout(() => {
      void api.dossiers.list().then((result) => setBackendDossiers(result.data)).catch(() => setBackendDossiers([]));
    }, 0);
    return () => window.clearTimeout(kickoff);
  }, []);
  const filtered = useMemo(
    () =>
      dossiers
        .filter(
          (d) =>
            (!query ||
              `${d.title} ${d.owner} ${d.objective}`
                .toLowerCase()
                .includes(query.toLowerCase())) &&
            (risk === "all" || d.riskLevel === risk) &&
            (status === "all" || d.status === status) &&
            (type === "all" || d.type === type),
        )
        .sort((a, b) => {
          const av = a[sort.key],
            bv = b[sort.key];
          const comparison =
            typeof av === "number" && typeof bv === "number"
              ? av - bv
              : String(av).localeCompare(String(bv), "es");
          return comparison * (sort.dir === "asc" ? 1 : -1);
        }),
    [dossiers, query, risk, status, type, sort],
  );
  const newSignals = signals
    .filter((s) => s.status === "new")
    .sort((a, b) => b.relevance - a.relevance)
    .slice(0, 5);
  const allSelected =
    filtered.length > 0 && filtered.every((d) => selected.includes(d.id));
  const doSort = (key: SortKey) =>
    setSort((v) => ({
      key,
      dir: v.key === key && v.dir === "desc" ? "asc" : "desc",
    }));
  const sortIcon = (name: SortKey) =>
    sort.key === name ? (
      sort.dir === "asc" ? (
        <ArrowUp size={13} />
      ) : (
        <ArrowDown size={13} />
      )
    ) : (
      <ArrowUpDown size={13} />
    );
  const density = (value: Density) =>
    saveSettings({ ...settings, density: value }).then(() =>
      toast.success(
        `Densidad ${value === "compact" ? "compacta" : value === "balanced" ? "equilibrada" : "cómoda"}`,
      ),
    );

  return (
    <div className="portfolio-page">
      <section className="page-heading">
        <div>
          <div className="eyebrow">Viernes, 10 de julio · 09:30</div>
          <h1>Command Center</h1>
          <p>
            Prioriza cambios, decide el siguiente movimiento y protege el avance
            del portfolio.
          </p>
        </div>
        <div className="portfolio-health">
          <span>Salud del portfolio</span>
          <strong>75</strong>
          <small>+3 desde la última revisión</small>
        </div>
      </section>
      <section className="attention-strip" aria-label="Resumen de atención">
        <div>
          <span className="metric-icon opportunity">
            <Sparkles size={17} />
          </span>
          <p>
            <strong>4 oportunidades</strong>
            <small>Dos requieren decisión esta semana</small>
          </p>
        </div>
        <div>
          <span className="metric-icon risk">
            <Filter size={17} />
          </span>
          <p>
            <strong>2 riesgos altos</strong>
            <small>Aurora concentra la mayor exposición</small>
          </p>
        </div>
        <div>
          <span className="metric-icon signal">
            <ListChecks size={17} />
          </span>
          <p>
            <strong>7 señales nuevas</strong>
            <small>Cinco superan relevancia 80</small>
          </p>
        </div>
        <div>
          <span className="metric-icon neutral">
            <CalendarClock size={17} />
          </span>
          <p>
            <strong>3 hitos próximos</strong>
            <small>El primero vence en 2 días</small>
          </p>
        </div>
      </section>
      {!!backendDossiers.length && <section className="vector-panel backend-dossiers" aria-labelledby="backend-dossiers-title"><header><div><span className="section-kicker">PostgreSQL · tenant activo</span><h2 id="backend-dossiers-title">Expedientes operativos</h2></div><span className="confidence">{backendDossiers.length} disponibles</span></header><div>{backendDossiers.map((item) => <Link key={item.id} href={`${routeBase}/dossiers/${item.id}`}><span><strong>{item.title}</strong><small>{item.dossier_type} · {item.status}</small></span><span>Documentos e informes <ChevronRight size={15}/></span></Link>)}</div></section>}
      <div className="vector-dashboard-grid">
        <section className="vector-panel changes-panel">
          <header>
            <div>
              <span className="section-kicker">Desde tu última visita</span>
              <h2>Qué ha cambiado</h2>
            </div>
            <button
              className="text-button"
              onClick={() => toast.info("Cambios marcados como revisados")}
            >
              Marcar todo revisado
            </button>
          </header>
          <div className="change-list">
            {recentChanges.map((item, i) => (
              <button
                key={item.title}
                onClick={() =>
                  i === 1
                    ? location.assign(`${routeBase}/dossiers/aurora`)
                    : toast.info(item.title, { description: item.detail })
                }
              >
                <span
                  className={`change-kind ${item.kind.toLowerCase().replace("ó", "o")}`}
                >
                  {item.kind}
                </span>
                <span>
                  <strong>{item.title}</strong>
                  <small>{item.detail}</small>
                </span>
                <ChevronRight size={16} />
              </button>
            ))}
          </div>
        </section>
        <aside className="vector-panel brief-panel">
          <header>
            <div>
              <span className="section-kicker">Síntesis trazable</span>
              <h2>Oracle Brief</h2>
            </div>
            <span className="confidence">Confianza 84%</span>
          </header>
          <p className="brief-intro">
            El portfolio mantiene impulso, pero dos decisiones concentran el
            valor de esta semana.
          </p>
          <ol>
            <li>
              <b>1</b>
              <span>
                <strong>Validar partner local para DACH</strong>
                <small>La nueva financiación reduce el coste de entrada.</small>
              </span>
            </li>
            <li>
              <b>2</b>
              <span>
                <strong>Resolver permisos de Aurora</strong>
                <small>El cambio de fecha eleva la exposición a 86.</small>
              </span>
            </li>
            <li>
              <b>3</b>
              <span>
                <strong>Decidir go / no-go de Horizonte</strong>
                <small>Encaje 94 · ventana de 2 días.</small>
              </span>
            </li>
          </ol>
          <button
            className="vector-secondary"
            onClick={() =>
              toast.success("Informe en preparación", {
                description:
                  "El informe ejecutivo incluirá 12 evidencias sintéticas.",
              })
            }
          >
            Generar informe ejecutivo
          </button>
          <footer>
            <span>Hechos: 8</span>
            <span>Inferencias: 3</span>
            <span>Fuentes: 12</span>
          </footer>
        </aside>
      </div>
      <section className="vector-panel dossiers-panel" id="expedientes">
        <header>
          <div>
            <span className="section-kicker">8 expedientes activos</span>
            <h2>Portfolio de expedientes</h2>
          </div>
          <div className="table-actions">
            <button
              className="vector-secondary"
              disabled={!selected.length}
              onClick={() =>
                toast.success(
                  `${selected.length} expedientes añadidos a revisión`,
                )
              }
            >
              <CheckSquare size={15} />
              Revisar selección
            </button>
            <div className="popover-anchor">
              <button
                className="icon-button bordered"
                aria-label="Elegir columnas"
                onClick={() => setColumnsOpen((v) => !v)}
              >
                <Columns3 size={17} />
              </button>
              {columnsOpen && (
                <div className="columns-popover">
                  <strong>Columnas visibles</strong>
                  {columns.map((c) => (
                    <label key={c}>
                      <input
                        type="checkbox"
                        checked={visible.includes(c)}
                        onChange={() =>
                          setVisible((v) =>
                            v.includes(c)
                              ? v.filter((x) => x !== c)
                              : [...v, c],
                          )
                        }
                      />
                      {c[0].toUpperCase() + c.slice(1)}
                    </label>
                  ))}
                </div>
              )}
            </div>
            <div className="segmented density-control" aria-label="Densidad">
              <button
                aria-pressed={settings.density === "compact"}
                onClick={() => density("compact")}
              >
                C
              </button>
              <button
                aria-pressed={settings.density === "balanced"}
                onClick={() => density("balanced")}
              >
                E
              </button>
              <button
                aria-pressed={settings.density === "comfortable"}
                onClick={() => density("comfortable")}
              >
                A
              </button>
            </div>
          </div>
        </header>
        <div className="table-toolbar">
          <label className="search-field">
            <Search size={16} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Buscar expediente, objetivo o responsable…"
              aria-label="Buscar expedientes"
            />
          </label>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            aria-label="Filtrar por estado"
          >
            <option value="all">Todos los estados</option>
            <option value="active">Activo</option>
            <option value="paused">Pausado</option>
          </select>
          <select
            value={type}
            onChange={(e) => setType(e.target.value)}
            aria-label="Filtrar por tipo"
          >
            <option value="all">Todos los tipos</option>
            <option value="project">Proyecto</option>
            <option value="market">Mercado</option>
            <option value="tender_or_grant">Convocatoria</option>
            <option value="strategic_account">Cuenta</option>
            <option value="partnership">Alianza</option>
            <option value="regulatory_affair">Regulación</option>
          </select>
          <select
            value={risk}
            onChange={(e) => setRisk(e.target.value as RiskLevel | "all")}
            aria-label="Filtrar por riesgo"
          >
            <option value="all">Todo riesgo</option>
            <option value="critical">Crítico</option>
            <option value="high">Alto</option>
            <option value="medium">Medio</option>
            <option value="low">Bajo</option>
          </select>
          {(query || risk !== "all" || status !== "all" || type !== "all") && (
            <button
              className="text-button"
              onClick={() => {
                setQuery("");
                setRisk("all");
                setStatus("all");
                setType("all");
              }}
            >
              Limpiar filtros
            </button>
          )}
        </div>
        <div className="table-scroll">
          {loading ? (
            <TableSkeleton />
          ) : (
            <table className="dossier-table">
              <thead>
                <tr>
                  <th className="check-cell">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={() =>
                        setSelected(
                          allSelected ? [] : filtered.map((d) => d.id),
                        )
                      }
                      aria-label="Seleccionar todos"
                    />
                  </th>
                  <th>
                    <button onClick={() => doSort("title")}>
                      Expediente {sortIcon("title")}
                    </button>
                  </th>
                  {visible.includes("tipo") && <th>Tipo</th>}
                  {visible.includes("salud") && <th>Salud</th>}
                  {visible.includes("oportunidad") && (
                    <th>
                      <button onClick={() => doSort("opportunityScore")}>
                        Oportunidad {sortIcon("opportunityScore")}
                      </button>
                    </th>
                  )}
                  {visible.includes("riesgo") && (
                    <th>
                      <button onClick={() => doSort("riskScore")}>
                        Riesgo {sortIcon("riskScore")}
                      </button>
                    </th>
                  )}
                  {visible.includes("señales") && (
                    <th>
                      <button onClick={() => doSort("newSignals")}>
                        Señales {sortIcon("newSignals")}
                      </button>
                    </th>
                  )}
                  {visible.includes("hito") && <th>Próximo hito</th>}
                  {visible.includes("actualizado") && (
                    <th>
                      <button onClick={() => doSort("updatedAt")}>
                        Actualizado {sortIcon("updatedAt")}
                      </button>
                    </th>
                  )}
                  <th>
                    <span className="sr-only">Acciones</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((d) => (
                  <DossierRow
                    key={d.id}
                    d={d}
                    selected={selected.includes(d.id)}
                    toggle={() =>
                      setSelected((v) =>
                        v.includes(d.id)
                          ? v.filter((x) => x !== d.id)
                          : [...v, d.id],
                      )
                    }
                    visible={visible}
                    routeBase={routeBase}
                  />
                ))}
              </tbody>
            </table>
          )}
          {!loading && !filtered.length && (
            <div className="empty-state">
              <SlidersHorizontal size={28} />
              <strong>No hay expedientes con estos filtros</strong>
              <p>
                Prueba a ampliar los criterios o limpia los filtros activos.
              </p>
              <button
                className="vector-secondary"
                onClick={() => {
                  setQuery("");
                  setRisk("all");
                  setStatus("all");
                  setType("all");
                }}
              >
                Limpiar filtros
              </button>
            </div>
          )}
        </div>
        <footer className="table-footer">
          <span>
            {filtered.length} de {dossiers.length} expedientes ·{" "}
            {selected.length} seleccionados
          </span>
          <div>
            <button disabled aria-label="Página anterior">
              <ChevronLeft size={16} />
            </button>
            <b>1</b>
            <button disabled aria-label="Página siguiente">
              <ChevronRight size={16} />
            </button>
          </div>
        </footer>
      </section>
      <div className="vector-lower-grid" id="radar">
        <section className="vector-panel signals-panel">
          <header>
            <div>
              <span className="section-kicker">
                Signal Avanza · sincronizado 09:28
              </span>
              <h2>Señales por revisar</h2>
            </div>
            <span className="signal-live">● En directo</span>
          </header>
          <div className="signal-list">
            {newSignals.map((s) => (
              <button key={s.id} onClick={() => setSignal(s)}>
                <span className="score-ring">{s.relevance}</span>
                <span>
                  <small>
                    {signalTypeLabel[s.sourceType]} · {s.sourceName}
                  </small>
                  <strong>{s.title}</strong>
                  <em>
                    Confianza {s.confidence}% ·{" "}
                    {formatDate(s.publishedAt, true)}
                  </em>
                </span>
                <ChevronRight size={17} />
              </button>
            ))}
          </div>
        </section>
        <section className="vector-panel priorities-panel" id="prioridades">
          <header>
            <div>
              <span className="section-kicker">Acción y protección</span>
              <h2>Prioridades</h2>
            </div>
          </header>
          <div className="priority-row opportunity">
            <span>Oportunidad · 94</span>
            <strong>Licitación Horizonte Digital</strong>
            <small>Decidir go / no-go antes del 12 jul</small>
            <Link href={`${routeBase}/dossiers/horizonte`}>
              Abrir expediente <ChevronRight size={14} />
            </Link>
          </div>
          <div className="priority-row risk">
            <span>Riesgo · 86</span>
            <strong>Permisos de Planta Aurora</strong>
            <small>Confirmar vía alternativa esta semana</small>
            <Link href={`${routeBase}/dossiers/aurora`}>
              Abrir expediente <ChevronRight size={14} />
            </Link>
          </div>
          <div className="next-meeting">
            <CalendarClock size={19} />
            <span>
              <small>Próxima reunión</small>
              <strong>Mesa de alineación · Northstar</strong>
              <em>21 jul · 10:30 · 4 participantes</em>
            </span>
            <button
              onClick={() =>
                toast.success("Briefing preparado", {
                  description:
                    "Incluye objetivo, actores y 6 preguntas recomendadas.",
                })
              }
            >
              Preparar
            </button>
          </div>
        </section>
      </div>
      <SignalDrawer
        signal={signal}
        open={!!signal}
        onOpenChange={(o) => !o && setSignal(null)}
      />
    </div>
  );
}

function DossierRow({
  d,
  selected,
  toggle,
  visible,
  routeBase,
}: {
  d: StrategicDossier;
  selected: boolean;
  toggle: () => void;
  visible: string[];
  routeBase: string;
}) {
  return (
    <tr className={selected ? "selected" : ""}>
      <td className="check-cell">
        <input
          type="checkbox"
          checked={selected}
          onChange={toggle}
          aria-label={`Seleccionar ${d.title}`}
        />
      </td>
      <td className="sticky-name">
        <Link href={`${routeBase}/dossiers/${d.id}`}>
          <strong>{d.title}</strong>
          <small>
            {d.owner} ·{" "}
            <span className={`status ${d.status}`}>
              {d.status === "active" ? "Activo" : "Pausado"}
            </span>
          </small>
        </Link>
      </td>
      {visible.includes("tipo") && <td>{d.typeLabel}</td>}
      {visible.includes("salud") && (
        <td>
          <span className="inline-score">
            <i style={{ width: `${d.healthScore}%` }} />
            {d.healthScore}
          </span>
        </td>
      )}
      {visible.includes("oportunidad") && (
        <td>
          <b className="opportunity-score">{d.opportunityScore}</b>
        </td>
      )}
      {visible.includes("riesgo") && (
        <td>
          <span className={`risk-badge ${d.riskLevel}`}>
            {riskLabel[d.riskLevel]} · {d.riskScore}
          </span>
        </td>
      )}
      {visible.includes("señales") && (
        <td>
          <span className={d.newSignals ? "new-count" : ""}>
            {d.newSignals}
          </span>
        </td>
      )}
      {visible.includes("hito") && (
        <td>
          <strong className="milestone">{d.nextMilestone}</strong>
          <small>{formatDate(d.nextMilestoneDate)}</small>
        </td>
      )}
      {visible.includes("actualizado") && (
        <td>{formatDate(d.updatedAt, true)}</td>
      )}
      <td>
        <button
          className="row-menu"
          aria-label={`Acciones de ${d.title}`}
          onClick={() =>
            toast.info(d.title, {
              description:
                "Abrir el expediente para editar, informar o archivar.",
            })
          }
        >
          <MoreHorizontal size={17} />
        </button>
      </td>
    </tr>
  );
}
function TableSkeleton() {
  return (
    <div className="table-skeleton" aria-label="Cargando expedientes">
      {Array.from({ length: 6 }, (_, i) => (
        <span key={i} />
      ))}
    </div>
  );
}
