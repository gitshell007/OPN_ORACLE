import { FileQuestion } from "lucide-react";
import Link from "next/link";

export default function ProductNotFound() {
  return (
    <div className="product-route-state" role="status">
      <FileQuestion aria-hidden="true" />
      <div>
        <strong>No encontramos este recurso</strong>
        <p>
          Puede haberse eliminado o no estar disponible en la organización activa.
          Oracle no confirma recursos fuera de tu ámbito autorizado.
        </p>
        <Link className="vector-primary" href="/app">
          Volver al inicio
        </Link>
      </div>
    </div>
  );
}
