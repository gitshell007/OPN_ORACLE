export default function ProductLoading() {
  return (
    <div className="product-route-state" role="status" aria-live="polite">
      <span className="product-route-spinner" aria-hidden="true" />
      <div>
        <strong>Preparando tu contexto de Oracle…</strong>
        <p>Estamos cargando únicamente los datos autorizados de la organización activa.</p>
      </div>
    </div>
  );
}
