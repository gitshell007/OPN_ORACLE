# Celery

## Objetivo y procedimiento

Diagnosticar workers, beat, colas y jobs sin duplicar ejecuciones. Seguir
[CELERY_REDIS.md](./CELERY_REDIS.md) y [ASYNC_AND_SIGNAL.md](./runbooks/ASYNC_AND_SIGNAL.md). Se
espera ping, un beat, backlog estable y estado durable reconciliable.

## Fallo

No purgar Redis ni reencolar masivamente. Preservar `job_id`, leases y fencing antes de reiniciar.

