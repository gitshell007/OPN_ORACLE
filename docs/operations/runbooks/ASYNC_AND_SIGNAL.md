# Celery y Signal Avanza

## Backlog o fallos de Celery

**Síntomas:** colas crecen, jobs `queued/publishing/running` superan SLO, heartbeats stale, retries o
fallos terminales aumentan, informes/documentos no avanzan.  
**Confirmación:** separar por cola (`default`, `signals`, `ai`, `documents`, `notifications`,
`maintenance`), comprobar workers y un único beat, Redis/DB, edad del job, lease/task ID y excepción
saneada. Correlacionar por `job_id`; no confiar solo en estado Redis.  
**Mitigación:** pausar el productor causante; escalar únicamente la cola saturada dentro de límites
DB/CPU; ejecutar reconciliador/recovery previsto; dejar que fencing e idempotencia descarten
entregas antiguas. No marcar éxito manualmente ni matar tareas con efecto externo sin analizar la
ventana de crash.  
**Rollback:** revertir handler/configuración reciente; drenar workers antiguos antes de reactivar.
Restaurar concurrencia gradualmente y vigilar retry storm.  
**Escalado:** owner de dominio y SRE si backlog supera 15 min o falla > 5 %; security si payload o
tenant no coincide. Cierre: cola estable, jobs terminales correctos y muestra de efectos únicos.

## Signal Avanza degradado

**Síntomas:** health de conexión en error, sync atrasado, outbox/inbox crece, 429/5xx/timeouts,
webhooks con firma/replay rechazados o cursor inmóvil.  
**Confirmación:** revisar por conexión/monitor sin exponer secretos; separar fallo de contrato,
credencial, red, circuit breaker, rate limit y payload inválido; comprobar timestamp, event ID,
cursor y última sincronización. No enviar payload real a un tercero durante diagnóstico.  
**Mitigación:** abrir circuito/pausar monitores; respetar `Retry-After` y backoff; conservar inbox/
outbox durable; rotar credencial solo con procedimiento bilateral. La UI debe mostrar degradación,
no inventar sincronización.  
**Rollback:** volver a versión de adapter/contrato compatible; reanudar una conexión canario y luego
el resto. Nunca retroceder cursor sin deduplicación verificada.  
**Escalado:** owner Oracle + owner Signal; security ante firmas inválidas sostenidas o sospecha de
secreto. Cierre: reconciliación sin duplicados, cursor monotónico y backlog drenado.

