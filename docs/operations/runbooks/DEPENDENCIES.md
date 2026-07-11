# API y dependencias síncronas

## API caída o readiness fallando

**Síntomas:** `/health/live` no responde o no devuelve 200; `/health/ready` devuelve 503; Nginx
registra 502/504; tasa 5xx o latencia crece.  
**Confirmación:** comprobar desde loopback y desde el proxy; distinguir liveness de readiness;
revisar estado/restarts de web y API, últimos logs JSON por `request_id`, CPU/RAM/FD y conectividad
a PostgreSQL/Redis. No usar `/ready` como carga continua.  
**Mitigación:** retirar la instancia no-ready; si live funciona, degradar temporalmente flujos que
dependan del componente caído; limitar tráfico abusivo; reiniciar solo un proceso tras capturar
logs/estado.  
**Rollback:** volver a la imagen/configuración anterior si el fallo sigue a un release; no ejecutar
migraciones inversas si el binario anterior es compatible, y seguir el runbook de release para
cualquier downgrade.  
**Escalado:** SRE inmediato si live cae > 2 min o 5xx > 5 % durante 5 min; engineering owner si una
ruta concreta; security si hay patrón de abuso. Verificar al cerrar live, ready, login, `/app`, job
de prueba y ausencia de error sostenido.

## PostgreSQL no disponible o pool agotado

**Síntomas:** ready marca database unavailable, timeouts de checkout, 500/503, jobs bloqueados,
`opn_db_pool_checked_out` cerca del límite.  
**Confirmación:** conectividad con credencial runtime, `pg_isready`, sesiones activas/esperas/locks,
uso de conexiones por proceso, espacio/WAL/IO y queries lentas. Nunca pegar DSN en chat o ticket.  
**Mitigación:** pausar productores asíncronos no críticos, reducir concurrencia worker, cancelar solo
queries claramente runaway mediante procedimiento auditado y preservar transacciones. Si es
saturación, no aumentar el pool sin comprobar `max_connections` y memoria.  
**Rollback:** revertir release/query causante; restaurar concurrencia gradualmente. Una migración se
revierte solo si su downgrade fue probado y no destruye datos.  
**Escalado:** DBA/SRE inmediato ante corrupción, réplica/backup afectado o > 5 min; product owner si
se activa modo lectura. Cierre: RLS bajo rol runtime, pool estable, lag cero y smoke de escritura.

## Redis no disponible

**Síntomas:** login/sesiones/rate limit fallan, publicación Celery queda `publish_pending`, ready
marca Redis unavailable. PostgreSQL sigue siendo autoridad.  
**Confirmación:** ping autenticado desde red privada, memoria/evictions, `noeviction`, persistencia,
latencia y separación de DB de sesiones/rate/broker/result. No publicar Redis o Flower.  
**Mitigación:** cortar nuevos logins si la sesión no puede validarse; no hacer fallback a memoria;
mantener jobs durables en PostgreSQL y dejar que el reconciliador republique tras recuperación;
reducir producers para evitar tormenta.  
**Rollback:** revertir configuración/ACL/TLS reciente. Tras recuperar, restaurar workers por cola,
vigilar duplicados idempotentes y permitir expirar sesiones perdidas; no reconstruir verdad desde
el result backend.  
**Escalado:** SRE inmediato; security si Redis pudo quedar accesible o sin autenticación. Cierre:
sesión nueva/revocación, rate limit, publicación/recovery y DBs lógicas verificadas.

