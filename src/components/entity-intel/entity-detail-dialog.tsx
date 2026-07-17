"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { ArrowRight, Building2, Link2, UserRound, X } from "lucide-react";
import type { RefObject } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  api,
  type EntityIntelGraphNode,
  type EntityIntelKind,
  type EntityIntelRegistryAct,
  type EntityIntelRegistryResponse,
} from "@oracle/api-client";
import { registryStatusCounts } from "./registry-status";

const KIND_LABELS: Record<EntityIntelKind, string> = {
  company: "Empresa",
  person: "Persona",
};

export interface EntityDetailRelation {
  id: string;
  label: string;
  routeName?: string;
  kind: EntityIntelKind;
  role: string;
  date?: string | null;
  active?: boolean | null;
  degree?: number | null;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function textValue(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (typeof value === "boolean") return value ? "Sí" : "No";
  return null;
}

function formatDate(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString("es-ES");
}

function entityLabel(entity: EntityIntelGraphNode): string {
  return String(entity.label ?? entity.name ?? entity.norm ?? entity.id ?? "Entidad");
}

function entityRouteName(entity: EntityIntelGraphNode): string {
  return String(entity.norm ?? entity.name ?? entity.label ?? entity.id ?? entityLabel(entity));
}

function entityKind(entity: EntityIntelGraphNode): EntityIntelKind {
  return entity.type === "person" || entity.entityType === "person" ? "person" : "company";
}

function firstValue(record: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const value = textValue(record[key]);
    if (value) return value;
  }
  return null;
}

function dateEntries(entity: EntityIntelGraphNode): Array<[string, string]> {
  const labels: Record<string, string> = {
    created_at: "Alta",
    updated_at: "Última actualización",
    incorporated_at: "Constitución",
    incorporation_date: "Constitución",
    date: "Fecha",
  };
  const metadata = asRecord(entity.metadata);
  const combined = { ...metadata, ...entity } as Record<string, unknown>;
  return Object.entries(combined).flatMap(([key, value]) => {
    if (!/(date|_at)$/i.test(key)) return [];
    const formatted = formatDate(value);
    return formatted ? [[labels[key] ?? key.replaceAll("_", " "), formatted]] : [];
  });
}

function statusValue(entity: EntityIntelGraphNode): string | null {
  const metadata = asRecord(entity.metadata);
  const active = entity.active ?? metadata.active;
  if (typeof active === "boolean") return active ? "Activo" : "Inactivo";
  return firstValue({ ...metadata, ...entity }, ["status", "state", "registry_status"]);
}

function problemMessage(reason: unknown): string {
  return reason instanceof ApiError
    ? reason.problem.detail
    : "No se pudieron cargar datos registrales.";
}

function actTimestamp(act: EntityIntelRegistryAct): number | null {
  const value = act.date ?? act.effective_date;
  if (typeof value !== "string" || !value.trim()) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.getTime();
}

function chronologicalActs(registry: EntityIntelRegistryResponse | null) {
  return [...(registry?.items ?? [])].sort((left, right) => {
    const leftTimestamp = actTimestamp(left);
    const rightTimestamp = actTimestamp(right);
    if (leftTimestamp === null && rightTimestamp === null) return 0;
    if (leftTimestamp === null) return 1;
    if (rightTimestamp === null) return -1;
    return rightTimestamp - leftTimestamp;
  });
}

function actYear(act: EntityIntelRegistryAct): string {
  const timestamp = actTimestamp(act);
  return timestamp === null ? "Sin fecha" : String(new Date(timestamp).getFullYear());
}

function actsByYear(acts: EntityIntelRegistryAct[]) {
  const groups = new Map<string, EntityIntelRegistryAct[]>();
  for (const act of acts) {
    const year = actYear(act);
    groups.set(year, [...(groups.get(year) ?? []), act]);
  }
  return Array.from(groups.entries());
}

export function EntityDetailDialog({
  open,
  entity,
  relations,
  returnFocusRef,
  onOpenChange,
  onNavigate,
}: {
  open: boolean;
  entity: EntityIntelGraphNode | null;
  relations: EntityDetailRelation[];
  returnFocusRef?: RefObject<HTMLElement | null>;
  onOpenChange(open: boolean): void;
  onNavigate(kind: EntityIntelKind, name: string): void;
}) {
  const [pendingRelation, setPendingRelation] = useState<EntityDetailRelation | null>(null);
  const [registry, setRegistry] = useState<EntityIntelRegistryResponse | null>(null);
  const [registryLoading, setRegistryLoading] = useState(false);
  const [registryError, setRegistryError] = useState<string | null>(null);
  const registryCache = useRef(new Map<string, EntityIntelRegistryResponse>());
  const kind = entity ? entityKind(entity) : "company";
  const metadata = asRecord(entity?.metadata);
  const registryId = entity
    ? firstValue({ ...metadata, ...entity }, ["registry_id", "identifier", "tax_id", "nif", "norm", "id"])
    : null;
  const dates = useMemo(() => (entity ? dateEntries(entity) : []), [entity]);
  const status = entity ? statusValue(entity) : null;
  const routeName = entity ? entityRouteName(entity) : "";
  const role = entity
    ? firstValue({ ...metadata, ...entity }, ["graph_role", "role", "relationship_role"])
    : null;

  function close(nextOpen: boolean) {
    if (!nextOpen) setPendingRelation(null);
    onOpenChange(nextOpen);
  }

  useEffect(() => {
    const handle = window.setTimeout(() => setPendingRelation(null), 0);
    return () => window.clearTimeout(handle);
  }, [entity?.id, entity?.norm, open]);

  useEffect(() => {
    if (!open || !entity) return undefined;
    const lookupName = entityRouteName(entity);
    const cacheKey = `${kind}:${lookupName}`;
    const cached = registryCache.current.get(cacheKey);
    if (cached) {
      setRegistry(cached);
      setRegistryError(null);
      setRegistryLoading(false);
      return undefined;
    }
    let cancelled = false;
    setRegistry(null);
    setRegistryError(null);
    setRegistryLoading(true);
    void api.entityIntel.registry({ name: lookupName, type: kind, limit: 100, offset: 0 })
      .then((result) => {
        if (cancelled) return;
        registryCache.current.set(cacheKey, result);
        setRegistry(result);
      })
      .catch((reason) => {
        if (!cancelled) setRegistryError(problemMessage(reason));
      })
      .finally(() => {
        if (!cancelled) setRegistryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [entity, kind, open]);

  if (!entity) return null;
  const counts = registryStatusCounts(registry?.items ?? [], kind);
  const acts = chronologicalActs(registry);
  const groupedActs = actsByYear(acts);
  const profile = registry?.profile;
  const loadedActs = registry?.items.length ?? 0;
  const totalActs = typeof registry?.total === "number" ? registry.total : loadedActs;
  const countScope = totalActs > loadedActs && loadedActs > 0
    ? ` de los últimos ${loadedActs} actos`
    : "";

  return (
    <Dialog.Root open={open} onOpenChange={close}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content
          className="dialog-content entity-detail-dialog"
          role="dialog"
          aria-modal="true"
          onCloseAutoFocus={(event) => {
            if (returnFocusRef?.current) {
              event.preventDefault();
              returnFocusRef.current.focus();
            }
          }}
        >
          <Dialog.Title className="entity-detail-title">
            <span className={`entity-kind-chip ${kind}`}>
              {kind === "person" ? <UserRound size={14} /> : <Building2 size={14} />}
              {KIND_LABELS[kind]}
            </span>
            {entityLabel(entity)}
          </Dialog.Title>
          <Dialog.Description>
            {registryId ? `Identificador registral: ${registryId}` : "Vista rápida registral"}
          </Dialog.Description>
          <Dialog.Close className="dialog-close" aria-label="Cerrar">
            <X size={18} />
          </Dialog.Close>

          {pendingRelation ? (
            <section className="entity-confirm-step" aria-live="polite">
              <h3>¿Quieres consultar los datos de {pendingRelation.label}?</h3>
              <p>
                Se cerrará esta ficha y el grafo se recargará usando esa entidad como nuevo centro.
              </p>
              <div className="dialog-actions">
                <button className="vector-secondary" type="button" onClick={() => setPendingRelation(null)}>
                  Cancelar
                </button>
                <button
                  className="vector-primary"
                  type="button"
                  onClick={() => onNavigate(
                    pendingRelation.kind,
                    pendingRelation.routeName ?? pendingRelation.label,
                  )}
                >
                  <ArrowRight size={15} />
                  Consultar
                </button>
              </div>
            </section>
          ) : (
            <div className="entity-detail-body">
              <section>
                <h3>Identificadores</h3>
                <dl className="entity-detail-pairs">
                  <div>
                    <dt>Nombre</dt>
                    <dd>{entityLabel(entity)}</dd>
                  </div>
                  <div>
                    <dt>Identificador registral</dt>
                    <dd>{registryId ?? "Sin datos registrales"}</dd>
                  </div>
                </dl>
              </section>

              <section>
                <h3>Estado y fechas</h3>
                <dl className="entity-detail-pairs">
                  <div>
                    <dt>Estado</dt>
                    <dd>{profile?.status ?? status ?? "Sin datos registrales"}</dd>
                  </div>
                  {profile?.constitution_date || profile?.first_act_date ? (
                    <div>
                      <dt>{profile.constitution_date ? "Constitución" : "Primer acto BORME publicado"}</dt>
                      <dd>{formatDate(profile.constitution_date ?? profile.first_act_date) ?? "Sin fecha"}</dd>
                    </div>
                  ) : null}
                  <div>
                    <dt>Vínculos activos</dt>
                    <dd>{registryLoading ? "Cargando..." : `${counts.active}${countScope}`}</dd>
                  </div>
                  <div>
                    <dt>Ceses detectados</dt>
                    <dd>{registryLoading ? "Cargando..." : `${counts.ended}${countScope}`}</dd>
                  </div>
                  {dates.length ? dates.map(([label, value]) => (
                    <div key={`${label}-${value}`}>
                      <dt>{label}</dt>
                      <dd>{value}</dd>
                    </div>
                  )) : (
                    <div>
                      <dt>Fechas</dt>
                      <dd>Sin datos registrales</dd>
                    </div>
                  )}
                </dl>
              </section>

              <section>
                <h3>Cronología BORME</h3>
                {registryLoading ? (
                  <p className="entity-empty-state">Cargando actos registrales...</p>
                ) : registryError ? (
                  <p className="entity-empty-state">{registryError}</p>
                ) : acts.length ? (
                  <div className="entity-acts-timeline">
                    <p className="entity-section-note">
                      Mostrando {loadedActs} de {totalActs} actos cargados desde Signal. La ficha no
                      sustituye al BORME oficial: Signal no entrega el texto íntegro del acto, solo
                      persona, cargo, acción, fecha, provincia y cita.
                    </p>
                    {groupedActs.map(([year, yearActs]) => (
                      <div className="entity-acts-year" key={year}>
                        <h4>{year}</h4>
                        {yearActs.map((act, index) => (
                          <article key={`${act.source_url ?? "act"}-${act.date ?? "sin-fecha"}-${index}`}>
                            <time dateTime={act.date ?? undefined}>{formatDate(act.date) ?? "Sin fecha"}</time>
                            <dl>
                              <div>
                                <dt>Persona</dt>
                                <dd>{act.person ?? "No indicada"}</dd>
                              </div>
                              <div>
                                <dt>Cargo</dt>
                                <dd>{act.role ?? act.act_type ?? "Acto registral"}</dd>
                              </div>
                              <div>
                                <dt>Acción</dt>
                                <dd>{act.action ?? "Acto"}</dd>
                              </div>
                              <div>
                                <dt>Provincia</dt>
                                <dd>{act.province ?? "No indicada"}</dd>
                              </div>
                            </dl>
                            {act.source_url ? (
                              <a href={act.source_url} target="_blank" rel="noreferrer">
                                Cita BOE
                              </a>
                            ) : (
                              <span className="entity-empty-state">Sin cita BOE</span>
                            )}
                          </article>
                        ))}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="entity-empty-state">Sin datos registrales.</p>
                )}
              </section>

              <section>
                <h3>Rol en el grafo</h3>
                <dl className="entity-detail-pairs">
                  <div>
                    <dt>Rol</dt>
                    <dd>{role ?? (entity.is_center ? "Entidad central" : "Entidad relacionada")}</dd>
                  </div>
                  <div>
                    <dt>Grado</dt>
                    <dd>{typeof entity.degree === "number" ? `${entity.degree} conexiones` : `${relations.length} conexiones directas`}</dd>
                  </div>
                </dl>
              </section>

              <section>
                <h3>Relaciones directas</h3>
                {relations.length ? (
                  <div className="entity-relation-list">
                    {relations.map((relation) => (
                      <button
                        type="button"
                        key={relation.id}
                        onClick={() => setPendingRelation(relation)}
                      >
                        <span>
                          <strong>{relation.label}</strong>
                          <small>{KIND_LABELS[relation.kind]} · {relation.role}</small>
                        </span>
                        <Link2 size={15} />
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="entity-empty-state">Sin relaciones directas en este grafo.</p>
                )}
              </section>
              <div className="dialog-actions">
                <button
                  className="vector-primary"
                  type="button"
                  onClick={() => onNavigate(kind, routeName)}
                >
                  <ArrowRight size={15} />
                  Ver ficha completa
                </button>
              </div>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
