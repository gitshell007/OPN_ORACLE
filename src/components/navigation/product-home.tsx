"use client";

import {
  ApiError,
  api,
  type OracleReport,
  type components,
} from "@oracle/api-client";
import {
  AlertTriangle,
  Bell,
  ArrowUpRight,
  FileChartColumn,
  Plus,
  RefreshCw,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/components/auth/auth-provider";
import { CreateProductDossierDialog } from "./create-product-dossier-dialog";
import {
  productJobTypeLabel,
  productLinkedResourceLabel,
  productStatusLabel,
} from "@/lib/product-copy";

type Job = components["schemas"]["JobResponse"];
type Home = components["schemas"]["HomeResponse"];

export function ProductHome() {
  const auth = useAuth();
  const [home, setHome] = useState<Home | null>(null);
  const [reports, setReports] = useState<OracleReport[]>([]);
  const [notificationUnread, setNotificationUnread] = useState(0);
  const [jobs, setJobs] = useState<Job[]>([]);
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
      const [reportResult, notificationResult, jobResult] = await Promise.allSettled([
        auth.can("report.read") ? api.reports.list(1, 5) : Promise.resolve(null),
        auth.can("notifications.read") ? api.notifications.list(1, 5) : Promise.resolve(null),
        api.jobs.list(1, 5),
      ]);
      const unavailable: string[] = [];
      if (reportResult.status === "fulfilled") setReports(reportResult.value?.data ?? []);
      else unavailable.push("informes");
      if (notificationResult.status === "fulfilled")
        setNotificationUnread(notificationResult.value?.meta.unread_count ?? 0);
      else unavailable.push("notificaciones");
      if (jobResult.status === "fulfilled") setJobs(jobResult.value.data);
      else unavailable.push("procesos");
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

  const failedJobs = jobs.filter((item) => item.status === "failed").length;
  const isFirstRun = home?.dossier_total === 0;

  if (loading) {
    return <div className="product-home-loading" role="status">Cargando situación de la cartera…</div>;
  }
  if (error) {
    return (
      <div className="inline-error" role="alert">
        {error}
        <button onClick={() => void load()}><RefreshCw size={15} /> Reintentar</button>
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
          <button className="vector-primary" onClick={() => setCreateOpen(true)}>
            <Plus size={16} /> Nuevo expediente
          </button>
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
            <button className="vector-primary" onClick={() => setCreateOpen(true)}>
              <Plus size={16} /> Crear el primer expediente
            </button>
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
                  <span><strong>{item.title}</strong><small>{productLinkedResourceLabel(item.kind)} · {item.dossier_title} · {productStatusLabel(item.status)}</small></span>
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
            <header><div><span className="section-kicker">Procesos</span><h2>Trabajos recientes</h2></div>{failedJobs > 0 && <span className="status critical">{failedJobs} fallidos</span>}</header>
            {jobs.length ? <div className="home-jobs-list">{jobs.map((job) => (
              <div className="home-compact-row" key={job.id}>
                <RefreshCw size={16} /><span><strong>{productJobTypeLabel(job.job_type)}</strong><small>{productStatusLabel(job.status)} · {job.progress}%</small></span>
              </div>
            ))}</div> : <p className="reporting-hint">No hay trabajos recientes.</p>}
          </section>
        </aside>
      </div>
      </>}
      <CreateProductDossierDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}
