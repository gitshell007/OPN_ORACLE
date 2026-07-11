# ADR 0002 — Frontera frontend/backend e interfaz canónica

- **Estado:** accepted
- **Fecha:** 2026-07-10

## Contexto

El frontend actual usa Next.js App Router y un `OracleRepository` mock. No realiza llamadas de red ni contiene autenticación. Dos conceptos conviven en rutas separadas: Vector (`concept-a`) y Horizon (`concept-b`). El usuario ha elegido explícitamente el primero como base.

## Decisión

Establecer `CANONICAL_UI=vector`. Vector Command Center es la única interfaz destinada a evolucionar hacia producto. Horizon queda como prototipo comparativo no canónico y descartable; conservarlo por ahora no implica paridad futura ni duplicación de funcionalidades.

Next.js se limita a presentación, navegación, accesibilidad, validación de conveniencia y consumo del cliente TypeScript generado desde OpenAPI Flask. Flask decide autenticación, autorización, tenant context, reglas de dominio, persistencia, auditoría, jobs e integraciones.

El frontend permanecerá inicialmente en la raíz para evitar una migración simultánea. Su eventual traslado a `apps/web` será un cambio mecánico posterior. La integración de Vector empezará mediante una implementación HTTP compatible con la abstracción existente.

## Alternativas consideradas

- **Mantener Vector y Horizon como productos equivalentes:** descartado; duplicaría UI, E2E y mantenimiento.
- **Crear una interfaz híbrida:** descartado; mezclaría navegación, densidad y patrones incompatibles.
- **Mover el frontend ya a `apps/web`:** aplazado para no mezclar reorganización con la fundación Flask.
- **Usar Next.js como BFF autoritativo:** descartado; vulneraría la frontera Python/Node.

## Consecuencias y riesgos

- Las nuevas pantallas y flujos productivos se implementarán solo en Vector.
- Horizon puede seguir usando fixtures hasta su archivo/retirada expresa y no será criterio de paridad.
- `OracleProvider` accede hoy a fixtures y almacenamiento además del repositorio; debe desacoplarse gradualmente.
- El cliente generado no debe contener lógica manual ni secretos.
- Los route guards del frontend mejoran UX, pero nunca autorizan una operación.

## Cuestiones pendientes

- Decidir cuándo retirar el selector A/B y qué hacer con Horizon: rama, tag, archivo o eliminación.
- Diseñar el mapeo entre DTO OpenAPI y modelos de presentación de Vector.
- Definir estrategia de caché de server state al iniciar la integración.
