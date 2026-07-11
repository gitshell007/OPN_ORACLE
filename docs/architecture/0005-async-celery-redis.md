# ADR 0005 — Trabajo asíncrono con Celery y Redis

- **Estado:** accepted
- **Fecha:** 2026-07-10

## Contexto

La demo simula latencia en el navegador. El producto requerirá sincronización de señales, parsing de documentos, IA, informes, notificaciones y mantenimiento, operaciones incompatibles con el tiempo de una petición HTTP. No existe infraestructura asíncrona actual.

## Decisión

Usar Celery integrado con la application factory Flask. Redis actuará como broker y result backend, además de sesiones/rate limiting/caché con separación lógica y configuración segura. El estado durable y visible de cada trabajo residirá en PostgreSQL mediante `BackgroundJob`.

Se definirán las colas `default`, `signals`, `ai`, `documents`, `notifications` y `maintenance`. Worker y beat serán procesos separados. Las tareas recibirán IDs y contexto mínimo, serán idempotentes y usarán retry con backoff/jitter y límites soft/hard.

## Alternativas consideradas

- **Ejecutar tareas en la petición Flask:** descartado por latencia, timeouts y reintentos inseguros.
- **Background tasks de Node:** descartadas por la frontera autoritativa.
- **RQ/Dramatiq:** viables, pero no seleccionadas frente al requisito explícito y madurez operativa de Celery.
- **Usar solo el result backend como historial:** descartado; Redis puede perderse sin perder verdad de negocio.

## Consecuencias y riesgos

- Hay que coordinar transacción DB y enqueue para evitar trabajos fantasma; se prevé patrón outbox.
- La entrega es al menos una vez: toda tarea debe tolerar duplicados.
- Los argumentos no pueden contener secretos ni objetos ORM serializados.
- El despliegue y readiness deberán verificar worker y beat por separado.

## Cuestiones pendientes

- Concretar política de retención/cancelación de resultados y jobs.
- Definir concurrencia, límites y routing por cola tras medir cargas.
- Elegir estrategia de publicación outbox y reconciliación.
