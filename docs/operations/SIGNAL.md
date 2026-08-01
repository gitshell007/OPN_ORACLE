# Signal Avanza

## Objetivo y procedimiento

Operar Signal mediante adapter. Verificar outbox, cursor, HMAC, replay e idempotencia según
[ASYNC_AND_SIGNAL.md](./runbooks/ASYNC_AND_SIGNAL.md). La conexión HTTP se provisiona por tenant:
Oracle conserva la credencial cifrada y el navegador nunca llama a Signal directamente.

En el piloto de producción de Memoria Sol, `opn-oracle` usa un consumer tenant-scoped con
`monitor:write`, `signal:read`, `webhook:manage` y `entity:read`. Preguntar e Informe libre aplican
política local-first: `ollama/qwen3.5:9b` como primario y
`ollama_titan/qwen3.6:27b` como fallback gobernado. OpenRouter no forma parte de esas dos task keys;
su presencia en el catálogo general no autoriza uso ni gasto para este workflow.

## Fallo

Pausar el monitor o deshabilitar el consumer y conservar señales persistidas. Ante fallo del
provider IA, usar el kill switch del consumer; no ampliar providers, task keys o tenants sin una
decisión de rollout auditable.
