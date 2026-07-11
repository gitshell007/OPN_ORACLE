import Link from "next/link";

export interface PlaceholderAction {
  label: string;
  href: string;
}

export function ProductPlaceholder({
  eyebrow,
  title,
  description,
  actions = [],
}: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: readonly PlaceholderAction[];
}) {
  return (
    <div className="settings-page product-placeholder">
      <section className="page-heading">
        <div>
          <div className="eyebrow">{eyebrow}</div>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
      </section>
      <section className="settings-section" aria-labelledby="screen-status-title">
        <header>
          <h2 id="screen-status-title">Estructura de producto preparada</h2>
          <p>
            La ruta, permisos y navegación ya son definitivos. Su tabla y flujos
            conectados se completarán en una próxima actualización; esta pantalla
            no muestra datos simulados como si fueran reales.
          </p>
        </header>
        <dl className="placeholder-contract">
          <div>
            <dt>Fuente prevista</dt>
            <dd>Información autorizada de Oracle</dd>
          </div>
          <div>
            <dt>Estado</dt>
            <dd>Preparada para su próxima activación</dd>
          </div>
        </dl>
        {actions.length > 0 && (
          <div className="placeholder-actions">
            {actions.map((action) => (
              <Link className="vector-secondary" href={action.href} key={action.href}>
                {action.label}
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
