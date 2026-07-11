# ADR 0006 — Signal Avanza detrás de un adaptador

- **Estado:** accepted
- **Fecha:** 2026-07-10

## Contexto

La UI muestra Signal Avanza de forma simulada, pero no existe conexión ni contrato técnico confirmado. Oracle necesita crear/actualizar/pausar monitores y sincronizar señales sin acoplar el dominio, los jobs o Vector a una API externa concreta.

## Decisión

Definir en Python un contrato `SignalAvanzaAdapter` con operaciones de monitor y sincronización. Habrá una implementación mock determinista para desarrollo/tests y una implementación HTTP real con versión explícita, timeout, autenticación y observabilidad.

Los webhooks reales usarán HMAC, timestamp y protección contra replay. La ingesta será idempotente por event/provider ID o hash y conservará payload bruto y representación normalizada. El frontend nunca llamará Signal Avanza directamente.

## Alternativas consideradas

- **Llamar Signal desde componentes React:** descartado por secretos, CORS, auditoría y acoplamiento.
- **Incluir el cliente HTTP dentro del dominio:** descartado por dificultar mock, tests y evolución del proveedor.
- **Esperar al contrato real antes de avanzar:** descartado; el mock y el puerto estable permiten construir Oracle sin bloquear el core.
- **Replicar Signal dentro de Oracle:** descartado; Signal es la capa de ingesta/normalización, Oracle aporta contexto estratégico.

## Consecuencias y riesgos

- El contrato interno debe mapear explícitamente versiones externas.
- Los retries pueden duplicar entregas; la idempotencia se diseña desde el primer esquema.
- Los payloads pueden contener datos no confiables y prompt injection; deben validarse y aislarse.
- Las credenciales se almacenarán cifradas/rotables y nunca llegarán al frontend o logs.

## Cuestiones pendientes

- Confirmar URL, versión, autenticación, schemas, cursores y límites reales.
- Confirmar firma, ventana de replay y política de reintentos de webhooks.
- Acordar ownership y evolución del contrato entre los repositorios Oracle y Signal.
