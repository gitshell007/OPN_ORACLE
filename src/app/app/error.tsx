"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";
import { useEffect } from "react";

export default function ProductError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Oracle product route failed", error);
  }, [error]);

  return (
    <div className="product-route-state product-route-error" role="alert">
      <AlertTriangle aria-hidden="true" />
      <div>
        <strong>No se pudo abrir esta vista</strong>
        <p>
          Tu sesión continúa activa. Reintenta la carga; si el servicio sigue
          degradado, conserva el identificador de la solicitud mostrado por la API.
        </p>
        <button className="vector-primary" onClick={reset}>
          <RefreshCw size={15} /> Reintentar
        </button>
      </div>
    </div>
  );
}
