"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { ArrowRight, Building2, Link2, UserRound, X } from "lucide-react";
import type { RefObject } from "react";
import { useMemo, useState } from "react";
import type { EntityIntelGraphNode, EntityIntelKind } from "@oracle/api-client";

const KIND_LABELS: Record<EntityIntelKind, string> = {
  company: "Empresa",
  person: "Persona",
};

export interface EntityDetailRelation {
  id: string;
  label: string;
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
  const kind = entity ? entityKind(entity) : "company";
  const metadata = asRecord(entity?.metadata);
  const registryId = entity
    ? firstValue({ ...metadata, ...entity }, ["registry_id", "identifier", "tax_id", "nif", "norm", "id"])
    : null;
  const dates = useMemo(() => (entity ? dateEntries(entity) : []), [entity]);
  const status = entity ? statusValue(entity) : null;
  const role = entity
    ? firstValue({ ...metadata, ...entity }, ["graph_role", "role", "relationship_role"])
    : null;

  function close(nextOpen: boolean) {
    if (!nextOpen) setPendingRelation(null);
    onOpenChange(nextOpen);
  }

  if (!entity) return null;

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
            {registryId ? `Identificador registral: ${registryId}` : "Sin datos registrales"}
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
                  onClick={() => onNavigate(pendingRelation.kind, pendingRelation.label)}
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
                    <dd>{status ?? "Sin datos registrales"}</dd>
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
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
