# Operación de Celery y Redis

OPN Oracle usa PostgreSQL como autoridad del estado de cada trabajo. Redis transporta mensajes y
resultados efímeros; perder Redis no elimina el historial durable y el reconciliador vuelve a
publicar jobs `queued/publish_pending` con el mismo `task_id` e idempotency key.

## Procesos y colas

- `worker-default`: `default,maintenance`;
- `worker-signals`: `signals`;
- `worker-ai`: `ai`;
- `worker-documents`: `documents`;
- `worker-notifications`: `notifications`;
- un único `beat` por entorno.

Arranque local: `docker compose -f compose.dev.yml up --build`. Para diagnóstico usa
`celery -A opn_oracle.celery_entry:celery inspect ping`; no publiques Flower ni Redis.
Los workers hacen `acks_late`, prefetch 1, serialización JSON, UTC y parada gradual de 45 s.

## Redis

Usa DB/prefijos separados: aplicación/cache `0`, sesiones `1`, rate limit `2`, broker `3` y
resultados `4`. Producción debe usar ACL/password o TLS, red privada y `noeviction`: no se permite
expulsar sesiones o mensajes para recuperar memoria. Monitoriza memoria y escala antes del límite.

## Idempotencia, reintento y crash windows

Cada enqueue persiste primero `BackgroundJob`, su hash de payload y un payload JSON allowlisted de
menos de 32 KiB. Si publicar falla, queda `publish_pending`; beat lo reconcilia. Una repetición usa
el mismo registro y el wrapper retorna el resultado si ya terminó. Los fallos temporales aplican
backoff exponencial con jitter; mensajes públicos no contienen excepciones, trazas ni secretos.
La cancelación es cooperativa (`cancel_requested`) y no mata procesos.

El reconciliador reclama filas con `FOR UPDATE SKIP LOCKED`, persiste `publishing` y solo después
contacta al broker. Una reclamación abandonada se recupera tras dos minutos; `task_id`, hash e
idempotencia durable hacen segura una entrega repetida. No reduzcas esa ventana por debajo del
timeout de conexión al broker.

El dispatcher de schedules bloquea filas vencidas con `FOR UPDATE SKIP LOCKED`. Crear el job y
avanzar `next_run_at` ocurre en la misma transacción; la publicación solo empieza tras el commit.
La clave incluye schedule y la ocurrencia UTC, por lo que un reinicio no duplica el job.

## Correo y tokens

Los argumentos Celery de correo contienen solo `kind` y `user_id`: nunca token, URL secreta,
password ni credenciales SMTP. El token se deriva de forma estable con HMAC desde el secreto de
aplicación y el UUID del job, y PostgreSQL solo conserva su hash. El mismo job reutiliza
`delivery_key`, token y `Message-ID`. Los adapters declaran `supports_idempotency`:
`CaptureEmailSender` deduplica y permite retry; SMTP puro declara `false` y aplica at-most-once.
Antes de llamar a SMTP persiste `delivery_started_at`. Si el proceso cae antes o después de que el
servidor acepte el mensaje, el outcome queda desconocido y no se reenvía: puede perderse esa
entrega, pero nunca duplicarse; el usuario debe solicitar un nuevo reset. SMTP también deduplica en
memoria llamadas directas repetidas con la misma clave. `delivered_at` y el marcador del job se
persisten tras el envío. Fallo terminal o cancelación revoca el token. El usuario debe conservar
membership activa en el tenant del job.

Los schedules `daily` y `weekly` guardan hora local, weekday y zona IANA. En cambios DST se usa la
primera ocurrencia de una hora ambigua; una hora inexistente se normaliza al primer instante válido
posterior. `weekly_digest` recibe siempre la zona del schedule. Cleanup y expiración recorren
también tenants suspendidos/archivados; solo los dispatchers de negocio se limitan a tenants activos.

`oracle.signal.sync_monitor` usa el puerto reemplazable `SignalAvanzaAdapter`; en fase 07 el mock
determinista valida el monitor tenant-scoped, actualiza cursor/último sync y devuelve contadores.
Cada transición de task emite log estructurado con `job_id`, `tenant_id`, `correlation_id`, tipo y
estado, nunca con el payload.

## Recuperación

1. Comprueba PostgreSQL, Redis y `maintenance.dispatch_queued_jobs`.
2. Busca jobs `running` con heartbeat antiguo; no edites resultados ni fuerces `SUCCESS` en Redis.
3. Marca para reconciliación únicamente mediante herramientas/API operativas auditadas.
4. Escala workers por cola; no ejecutes dos beats salvo prueba controlada del dispatcher.

## API y diagnóstico

`GET /api/v1/jobs` solo devuelve trabajos solicitados por el usuario, asociados a expedientes a
los que tiene acceso o, para administradores, los del tenant. Cancelar y reintentar requieren el
ETag actual mediante `If-Match`; ambas acciones quedan auditadas. Un fallo de Redis durante un
reintento manual devuelve el job en `publish_pending`, no pierde la solicitud ni expone el error.

Los healthchecks de Compose hacen ping al nodo Celery concreto. Beat no tiene endpoint propio:
Docker supervisa su proceso y el dispatcher DB es idempotente. En producción usa un único beat,
alerta por jobs `publishing` antiguos, heartbeat vencido, cola creciente y memoria Redis.
`maintenance.recover_stale_jobs` cerca los task IDs cuyo heartbeat supera el hard timeout más 60
segundos y los devuelve a `publish_pending`; una entrega antigua queda ignorada por su task ID.
Cada ejecución reclama además un `execution_lease_id` persistido. Una segunda entrega concurrente
ve el lease activo y no ejecuta el handler; un worker recuperado solo puede completar, fallar o
reintentar mediante el lease que todavía posee. El takeover se permite únicamente tras expirar.
