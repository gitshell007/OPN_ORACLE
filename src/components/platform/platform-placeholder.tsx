export function PlatformPlaceholder({
  title,
  description,
}: {
  title: string;
  description: string;
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
              La estructura visual y los permisos están preparados. La fuente de
              información se conectará cuando pueda garantizarse un acceso seguro.
            </p>
          </div>
        </header>
        <p>
          <strong>Disponibilidad prevista:</strong> pendiente de conexión segura
        </p>
      </section>
    </div>
  );
}
