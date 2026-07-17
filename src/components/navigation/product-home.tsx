"use client";

import {
  ApiError,
  api,
  type OracleReport,
  type components,
} from "@oracle/api-client";
import {
  AlertTriangle,
  ArrowUpRight,
  Bell,
  BriefcaseBusiness,
  CalendarDays,
  FileChartColumn,
  FileSearch,
  ListTodo,
  Plus,
  RadioTower,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { HydratedActionButton } from "@/components/ui/async-action-button";
import { CreateProductDossierDialog } from "./create-product-dossier-dialog";
import {
  productLinkedResourceLabel,
  productStatusLabel,
} from "@/lib/product-copy";

type Home = components["schemas"]["HomeResponse"];

const ATTENTION_ICONS: Record<string, typeof BriefcaseBusiness> = {
  opportunity: Sparkles,
  opportunities: Sparkles,
  risk: ShieldAlert,
  risks: ShieldAlert,
  signal: RadioTower,
  signals: RadioTower,
  meeting: CalendarDays,
  meetings: CalendarDays,
  decision: ListTodo,
  document: FileSearch,
};

export function ProductHome() {
  const auth = useAuth();
  const [home, setHome] = useState<Home | null>(null);
  const [reports, setReports] = useState<OracleReport[]>([]);
  const [notificationUnread, setNotificationUnread] = useState(0);
  const [degraded, setDegraded] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setDegraded([]);
    try {
      const homeResult = await api.home.get();
      setHome(homeResult);
      const [reportResult, notificationResult] = await Promise.allSettled([
        auth.can("report.read") ? api.reports.list(1, 5) : Promise.resolve(null),
        auth.can("notifications.read") ? api.notifications.list(1, 5) : Promise.resolve(null),
      ]);
      const unavailable: string[] = [];
      if (reportResult.status === "fulfilled") setReports(reportResult.value?.data ?? []);
      else unavailable.push("informes");
      if (notificationResult.status === "fulfilled")
        setNotificationUnread(notificationResult.value?.meta.unread_count ?? 0);
      else unavailable.push("notificaciones");
      setDegraded(unavailable);
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.problem.detail
          : "No se pudo cargar el inicio de Oracle.",
      );
    } finally {
      setLoading(false);
    }
  }, [auth]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  const isFirstRun = home?.dossier_total === 0;

  if (loading) {
    return <div className="product-home-loading" role="status">Cargando situación de la cartera…</div>;
  }
  if (error) {
    return (
      <div className="inline-error" role="alert">
        {error}
        <button onClick={() => void load()}>Reintentar</button>
      </div>
    );
  }

  return (
    <div className="product-home">
      <section className="page-heading">
        <div>
          <div className="eyebrow">Situación global</div>
          <h1>Inicio</h1>
          <p>Prioriza expedientes y resultados de la organización activa.</p>
        </div>
        {auth.can("dossier.write") && (
          <HydratedActionButton className="vector-primary" onClick={() => setCreateOpen(true)}>
            <Plus size={16} /> Nuevo expediente
          </HydratedActionButton>
        )}
      </section>
      {degraded.length > 0 && (
        <div className="inline-warning" role="status">
          Inicio disponible con datos parciales: {degraded.join(", ")} no responden ahora.
        </div>
      )}

      {isFirstRun ? (
        <section className="vector-panel home-onboarding" aria-labelledby="home-onboarding-title">
          <span className="section-kicker">Primer paso</span>
          <h2 id="home-onboarding-title">Tu primer radar estratégico empieza aquí</h2>
          <p>Crea un expediente para reunir señales, actores, oportunidades y decisiones en un mismo contexto trazable.</p>
          {auth.can("dossier.write") && (
            <HydratedActionButton className="vector-primary" onClick={() => setCreateOpen(true)}>
              <Plus size={16} /> Crear el primer expediente
            </HydratedActionButton>
          )}
        </section>
      ) : <>
      <section className="home-metrics" aria-label="Resumen operativo">
        {home?.metrics.filter((metric) => metric.available).map((metric) => (
          <Link href={metric.href} key={metric.key}>
            {metric.key === "risks" ? <AlertTriangle size={19} /> : <ArrowUpRight size={19} />}
            <span>{metric.label}</span><strong>{metric.count ?? "—"}</strong>
          </Link>
        ))}
        <Link href="/app/notifications">
          <Bell size={19} /><span>Sin leer</span><strong>{notificationUnread}</strong>
        </Link>
      </section>

      <div className="home-grid">
        <section className="vector-panel home-attention">
          <header>
            <div><span className="section-kicker">Priorización operativa</span><h2>Trabajo que requiere atención</h2></div>
            <Link className="text-button" href="/app/dossiers">Ver cartera</Link>
          </header>
          {home?.attention.length ? (
            <div className="home-dossier-list">
              {home.attention.map((item) => (
                <Link href={item.href} key={`${item.kind}:${item.id}`}>
                  {(() => {
                    const Icon = ATTENTION_ICONS[item.kind ?? ""] ?? BriefcaseBusiness;
                    return <Icon size={16} aria-hidden="true" />;
                  })()}
                  <span className="home-attention-copy">
                    <strong>{item.title}</strong>
                    <small>
                      <b className="attention-kind-label">{productLinkedResourceLabel(item.kind)}</b>
                      <span>{item.dossier_title}</span>
                      <span>{productStatusLabel(item.status)}</span>
                    </small>
                  </span>
                  <span>{item.score === null ? "Siguiente hito" : `Puntuación ${item.score}`} · {item.due_at ? new Date(item.due_at).toLocaleDateString("es-ES") : "Sin fecha"}</span>
                </Link>
              ))}
            </div>
          ) : (
            <div className="empty-admin">
              <ArrowUpRight size={28} />
              <strong>No hay elementos prioritarios</strong>
              <p>{home?.dossier_total ? "Los expedientes accesibles no requieren atención inmediata." : "Crea el primer expediente para empezar a organizar señales y decisiones."}</p>
            </div>
          )}
        </section>

        <aside className="home-side">
          <section className="vector-panel">
            <header><div><span className="section-kicker">Salidas</span><h2>Informes recientes</h2></div></header>
            {reports.length ? reports.map((report) => (
              <Link className="home-compact-row" href={`/app/reports/${report.id}`} key={report.id}>
                <FileChartColumn size={16} /><span><strong>{report.title}</strong><small>{productStatusLabel(report.status)}</small></span>
              </Link>
            )) : <p className="reporting-hint">No hay informes accesibles todavía.</p>}
          </section>
          <section className="vector-panel home-jobs-panel">
            <header><div><span className="section-kicker">Auditoría</span><h2>Procesos y actividad</h2></div></header>
            <p className="reporting-hint">
              Los trabajos en segundo plano viven ahora junto al registro de auditoría para revisar
              cuándo se ejecutaron, su estado y los fallos con contexto.
            </p>
            <Link className="vector-secondary" href="/app/admin/audit?view=processes">
              Ver procesos
            </Link>
          </section>
        </aside>
      </div>
      </>}
      <CreateProductDossierDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}
