# Runtime IA de Oracle

La fase 09 funciona cerrada por defecto y no configura ningún proveedor externo. Las peticiones HTTP solo encolan `BackgroundJob`; el worker de la cola `ai` construye un snapshot tenant-scoped, reserva cuota, ejecuta el provider y el revisor de evidencia y persiste auditoría y un artefacto candidato.

## Modos y variables

- `AI_ENABLED=false` y `AI_MODE=disabled`: configuración por defecto, sin inferencia.
- `AI_ENABLED=true` y `AI_MODE=mock`: únicamente desarrollo, CI y evals offline deterministas.
- `AI_DEFAULT_MODEL=mock-oracle-v1`: debe pertenecer al allowlist de la política del tenant.
- `AI_MOCK_SEED=opn-oracle-deterministic`: semilla estable del mock.

`AI_MODE=mock` falla al arrancar en producción. No existe adapter real ni fallback externo en esta fase. Habilitar un proveedor real requiere otra implementación, revisión de privacidad/clasificación, estimador de coste, allowlists y credenciales confirmadas.

## Guardrails durables

Cada tenant necesita una `AITenantPolicy` habilitada, sin `kill_switch`, cuyo provider coincida con el modo global. La política limita modelos, clasificación, contexto/output, llamadas diarias, concurrencia tenant-global y presupuesto mensual soft/hard. Las reservas y el slot se serializan en PostgreSQL; una lease stale terminaliza intento/auditoría y libera coste reservado.

Los outputs se validan con Pydantic estricto. Todos los `evidence_ids`, incluidos los anidados, deben estar en el snapshot del expediente. El resultado de generación pasa por `EvidenceReviewerOutput`; un error o veredicto `fail` no crea artefacto. Los artefactos quedan `candidate` hasta una revisión humana, que crea una fila inmutable y nunca reescribe el output histórico.

## Operación

Ejecuta un worker que consuma la cola `ai` y mantén activo el schedule `maintenance.recover_stale_jobs`. Para degradar inmediatamente, establece el kill switch de las políticas o `AI_ENABLED=false`; los análisis nuevos responderán como no disponibles sin inventar resultado. Los logs no contienen prompts completos: `AIAuditLog` conserva hashes, versiones, fuentes, métricas, clasificación, redacción y estado.

Los evals offline y sus métricas (`schema_pass`, cobertura de evidencia, claims no soportados, clasificación, aceptación humana, latencia y coste) viven en `apps/api/tests/fixtures/ai_eval_cases.json` y `opn_oracle.ai.evals`.
