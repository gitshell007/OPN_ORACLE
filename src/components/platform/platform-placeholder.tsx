export function PlatformPlaceholder({
  title,
  description,
  api,
}: {
  title: string;
  description: string;
  api: string;
}) {
  return (
    <div className="platform-page">
      <header className="admin-heading">
        <div>
          <p className="eyebrow">Contexto de plataforma</p>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
      </header>
      <section className="admin-form-card">
        <header>
          <div>
            <h2>Estructura preparada</h2>
            <p>
              La integración visual y de permisos está cerrada. La fuente se
              conecta en fase 12 solo si el backend la ofrece de forma segura.
            </p>
          </div>
        </header>
        <p>
          <strong>Fuente prevista:</strong> {api}
        </p>
      </section>
    </div>
  );
}
