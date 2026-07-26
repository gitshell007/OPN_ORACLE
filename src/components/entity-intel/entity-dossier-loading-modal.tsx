"use client";

import { Building2, Check, Loader2, Sparkles, UserRound } from "lucide-react";
import {
  useEffect,
  useState,
  type CSSProperties,
} from "react";
import { createPortal } from "react-dom";
import type { EntityIntelKind } from "@oracle/api-client";

const DOSSIER_STAGES = [
  {
    id: "identity",
    label: "Identidad y perfil",
    detail: "Resolviendo la denominación en Signal y el perfil base",
  },
  {
    id: "registry",
    label: "Órganos y cargos",
    detail: "Cargando actos societarios y vista de cargos BORME",
  },
  {
    id: "network",
    label: "Red de relaciones",
    detail: "Preparando grafo, contrapartes y vínculos",
  },
  {
    id: "sources",
    label: "Fuentes complementarias",
    detail: "Hechos relevantes, patentes y menciones web",
  },
] as const;

export function EntityDossierLoadingModal({
  open,
  progress,
  stageIndex,
  entityName,
  entityKind,
  finishing,
  reloading = false,
}: {
  open: boolean;
  progress: number;
  stageIndex: number;
  entityName: string;
  entityKind: EntityIntelKind;
  finishing: boolean;
  reloading?: boolean;
}) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  if (!mounted || !open) return null;

  const clamped = Math.max(0, Math.min(100, Math.round(progress)));
  const ringStyle = {
    ["--analytics-progress" as string]: String(clamped),
  } as CSSProperties;
  const KindIcon = entityKind === "person" ? UserRound : Building2;
  const kindLabel = entityKind === "person" ? "persona" : "empresa";

  return createPortal(
    <div
      className="analytics-progress-overlay entity-dossier-progress-overlay"
      role="dialog"
      // No usamos aria-modal: el overlay bloquea puntero/visualmente, pero no
      // deja la página "inert" (rompe getByRole en tests y algunos AT).
      aria-busy={!finishing}
      aria-labelledby="entity-dossier-progress-title"
      aria-describedby="entity-dossier-progress-desc"
      data-finishing={finishing ? "true" : "false"}
    >
      <div className="analytics-progress-backdrop" aria-hidden="true" />
      <div
        className={`analytics-progress-card entity-dossier-progress-card${finishing ? " is-complete" : ""}`}
      >
        <div className="analytics-progress-glow" aria-hidden="true" />
        <div className="analytics-progress-orbit" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>

        <div className="analytics-progress-ring-wrap" style={ringStyle} aria-hidden="true">
          <div className="analytics-progress-ring">
            <svg viewBox="0 0 120 120">
              <circle className="analytics-progress-track" cx="60" cy="60" r="52" />
              <circle
                className="analytics-progress-value"
                cx="60"
                cy="60"
                r="52"
                style={{
                  strokeDasharray: `${2 * Math.PI * 52}`,
                  strokeDashoffset: `${2 * Math.PI * 52 * (1 - clamped / 100)}`,
                }}
              />
            </svg>
            <div className="analytics-progress-center">
              {finishing ? (
                <Check size={28} strokeWidth={2.4} aria-hidden="true" />
              ) : (
                <Sparkles size={24} aria-hidden="true" />
              )}
              <strong>{clamped}%</strong>
            </div>
          </div>
        </div>

        <div className="analytics-progress-copy">
          <p className="analytics-progress-kicker">
            <Loader2 size={14} className="analytics-progress-spin" aria-hidden="true" />
            Inteligencia de entidad · Signal
          </p>
          <h2 id="entity-dossier-progress-title">
            {finishing
              ? "Ficha lista"
              : reloading
                ? "Actualizando ficha…"
                : "Cargando ficha de entidad…"}
          </h2>
          <p id="entity-dossier-progress-desc" className="entity-dossier-progress-entity">
            <KindIcon size={15} aria-hidden="true" />
            <span>
              {entityName}
              <small> · {kindLabel}</small>
            </span>
          </p>
          <p className="entity-dossier-progress-sub">
            {finishing
              ? "Perfil, cargos, grafo y fuentes complementarias ya están disponibles."
              : "Oracle consulta Signal y ensambla la ficha 360º en el servidor."}
          </p>
        </div>

        <ol className="analytics-progress-stages">
          {DOSSIER_STAGES.map((stage, index) => {
            const state =
              finishing || index < stageIndex
                ? "done"
                : index === stageIndex
                  ? "active"
                  : "pending";
            return (
              <li key={stage.id} className={`analytics-progress-stage is-${state}`}>
                <span className="analytics-progress-stage-mark" aria-hidden="true">
                  {state === "done" ? <Check size={12} strokeWidth={2.5} /> : index + 1}
                </span>
                <div>
                  <strong>{stage.label}</strong>
                  <small>{stage.detail}</small>
                </div>
              </li>
            );
          })}
        </ol>

        <div
          className="analytics-progress-bar"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={clamped}
          aria-label="Progreso de carga de la ficha"
        >
          <span style={{ width: `${clamped}%` }} />
        </div>
      </div>
    </div>,
    document.body,
  );
}

export const ENTITY_DOSSIER_STAGE_COUNT = DOSSIER_STAGES.length;
