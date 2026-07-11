# Signal Avanza

## Objetivo y procedimiento

Operar Signal mediante adapter. Verificar outbox, cursor, HMAC, replay e idempotencia según
[ASYNC_AND_SIGNAL.md](./runbooks/ASYNC_AND_SIGNAL.md). Signal HTTP real sigue deshabilitado.

## Fallo

Pausar sincronización y conservar señales persistidas. No habilitar HTTP sin contrato y credencial
bilaterales confirmados.

