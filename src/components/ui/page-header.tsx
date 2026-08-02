import type { ReactNode } from "react";

export interface PageHeaderProps {
  /** Antetítulo en versalitas. Sustituye a los `span.section-kicker` sueltos. */
  eyebrow?: ReactNode;
  title: ReactNode;
  /** Párrafo descriptivo bajo el título. */
  description?: ReactNode;
  /** Línea de metadatos (estado · tipo · fecha). */
  meta?: ReactNode;
  /** Botones o enlaces alineados a la derecha. */
  actions?: ReactNode;
  /** Nivel semántico. Por defecto h1: una página, un h1. */
  as?: "h1" | "h2";
  /** id del encabezado, para `aria-labelledby` de la sección que encabeza. */
  id?: string;
  className?: string;
  "data-testid"?: string;
}

/**
 * Cabecera única de página. Antes cada sección pintaba su propio bloque con su
 * propio tamaño y márgenes, así que dos pestañas contiguas no se parecían.
 */
export function PageHeader({
  eyebrow,
  title,
  description,
  meta,
  actions,
  as: Tag = "h1",
  id,
  className,
  "data-testid": testId = "page-header",
}: PageHeaderProps) {
  return (
    <header
      className={`opn-page-header${className ? ` ${className}` : ""}`}
      data-testid={testId}
    >
      <div className="opn-page-header__text">
        {eyebrow ? <span className="opn-page-header__eyebrow">{eyebrow}</span> : null}
        <Tag className="opn-page-header__title" id={id}>
          {title}
        </Tag>
        {description ? (
          <p className="opn-page-header__description">{description}</p>
        ) : null}
        {meta ? <div className="opn-page-header__meta">{meta}</div> : null}
      </div>
      {actions ? <div className="opn-page-header__actions">{actions}</div> : null}
    </header>
  );
}
