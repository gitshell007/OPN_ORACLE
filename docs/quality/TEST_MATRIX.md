# Matriz de requisitos y pruebas

**Leyenda:** `PASS` evidencia ejecutada; `PARTIAL` cobertura real con caso pendiente; `GAP` no
ejecutable todavía. Los nombres de archivo son relativos al repositorio.

| ID | Área / requisito | Evidencia automatizada principal | Estado | Gap o siguiente evidencia |
|---|---|---|---|---|
| DB-01 | Roles migrator/runtime y runtime sin DDL/BYPASSRLS | `test_integration_multitenancy.py` | PASS | Revalidar en host fase 14 |
| DB-02 | RLS A/B, sin contexto y pool reutilizado | `test_integration_multitenancy.py`, `test_integration_oracle_domain.py` | PASS | Ampliar matriz por endpoint nuevo |
| DB-03 | FK compuesta y nested mismatch | `test_integration_oracle_domain.py`, `test_documents.py` | PASS | — |
| DB-04 | base→head, drift y downgrade/reupgrade | suite de integración y gates por fase | PASS | Restore desde backup en fase 15 |
| AUTH-01 | Fijación/rotación y sesión durable | `test_auth_security.py`, `test_integration_auth.py` | PASS | Verificar cookie Secure tras TLS real |
| AUTH-02 | CSRF, token cruzado y Origin | `test_auth_security.py`, `test_integration_auth.py`, `test_security_surface.py` | PASS | — |
| AUTH-03 | Anti-enumeración y rate limit | `test_auth_security.py`, `tests/e2e/smoke.spec.ts` | PASS | Carga sostenida en staging |
| AUTH-04 | Reset/invite replay y expiración | `test_integration_auth.py`, `test_jobs.py` | PASS | SMTP real fase 14/15 |
| AUTH-05 | Revocación, logout-all, usuario/tenant suspendido | `test_integration_auth.py` | PASS | — |
| AUTH-06 | Open redirect y cambio tenant/cache stale | `test_auth_security.py`, `api-client.test.ts`, E2E | PASS | — |
| AUTH-07 | Cambio de rol/permisos y sesión stale/escalada | `test_integration_auth.py`, `test_integration_multitenancy.py` | PASS | La sesión abierta pierde el permiso en la siguiente petición |
| API-01 | JSON/content type/unknown fields | `test_auth_security.py`, tests de rutas por módulo | PARTIAL | Completar política transversal para las 240 operaciones OpenAPI |
| API-02 | Tamaño, paginación, sort/search allowlist | `test_contract.py`, `test_documents.py`, `test_integration_oracle_domain.py` | PASS | Fuzz acotado en F13 |
| API-03 | SQLi/XSS strings y escape de informes | `test_reporting.py`, tests de búsqueda | PARTIAL | E2E XSS almacenado y CSP |
| API-04 | SSRF/redirect/URL allowlist | `test_signal_avanza.py`, `test_documents.py`, `test_reporting.py` | PASS | Transporte HTTP Signal sigue fail-closed |
| API-05 | Mass assignment/optimistic concurrency/race | `test_integration_oracle_domain.py`, `test_integration_auth.py` | PASS | — |
| TEN-01 | CRUD/list/filter/search tenant A/B | tests `test_integration_*` por dominio | PASS | Consolidar catálogo endpoint→caso F13 |
| TEN-02 | Bulk IDs mixtos | `test_integration_oracle_domain.py` | PARTIAL | Jobs/notificaciones/export bulk explícito |
| TEN-03 | Download/export/object key A/B | `test_documents.py`, `test_integration_reporting_extra.py` | PASS | S3 real fase 14 |
| TEN-04 | Jobs/notificaciones/audit A/B | `test_integration_jobs.py`, `test_integration_reporting_extra.py` | PASS | — |
| TEN-05 | Superadmin frente a tenant-admin, motivo/auditoría | `test_integration_auth.py`, `tests/e2e/smoke.spec.ts` | PASS | Fresh/MFA productiva pendiente |
| JOB-01 | Estado durable, idempotencia y payload allowlist | `test_jobs.py`, `test_integration_jobs.py` | PASS | — |
| JOB-02 | Worker real, retry, fencing y crash windows | `test_integration_jobs.py`, módulos IA/docs/reporting | PASS | Redis restart/poison task explícito F13 |
| JOB-03 | Beat duplicado y dispatcher concurrente | `test_integration_jobs.py`, `test_alerts.py` | PARTIAL | Dos evaluadores físicos pendiente |
| SIG-01 | Contrato, schemas y mock determinista | `test_signal_avanza.py` | PASS | Contrato productor no confirmado |
| SIG-02 | HMAC, replay, secreto rotado y body alterado | `test_signal_avanza.py` | PASS | — |
| SIG-03 | Duplicado, outbox/inbox, cursor y recovery | `test_signal_avanza.py`, integraciones | PASS | 429/5xx/timeout con fake server ampliado |
| AI-01 | Registry/schema estricto y JSON inválido | `test_ai_runtime.py` | PASS | — |
| AI-02 | Evidence allowlist/cross-tenant/inventada | `test_ai_runtime.py`, integración IA | PASS | — |
| AI-03 | Prompt injection, PII/secret redaction y contradicción | fixtures `ai_eval_cases.json`, `test_ai_runtime.py` | PASS | Mantener corpus adversarial |
| AI-04 | Disabled/quota/timeout/reviewer/fencing/coste | `test_ai_runtime.py`, integración IA | PASS | Proveedor real bloqueado por decisión contractual |
| DOC-01 | Upload, MIME/magic, límites y traversal | `test_documents.py` | PASS | Sandbox de parser productivo fase 14 |
| DOC-02 | ZIP ratio/CSV/PDF defectuoso y cuarentena | `test_documents.py` | PASS | ClamAV/EICAR real fase 14 |
| DOC-03 | FTS/evidence/provenance/retención A/B | `test_documents.py` | PASS | S3 y reconciliación de huérfanos fase 14 |
| REP-01 | Snapshot/hash/reviewer/publicación | `test_reporting.py`, `test_integration_reporting_extra.py` | PASS | Renderer PDF productivo pendiente |
| REP-02 | CSV injection, alcance y enlace firmado | `test_reporting.py`, `test_integration_reporting_extra.py` | PASS | — |
| REP-03 | Alertas/digest/quiet hours/idempotencia | `test_alerts.py`, `test_integration_alerts.py` | PASS | Evaluadores físicamente concurrentes |
| WEB-01 | Componentes: carga/error/403/empty/mutación | 21 suites Vitest | PASS | — |
| WEB-02 | E2E Flask/PostgreSQL/Redis escritorio/móvil | `tests/e2e/*.spec.ts` | PASS | 6 skips móviles intencionados, incluida una comprobación redundante de sesión |
| WEB-03 | Teclado, foco, axe y consola | pruebas de shell + E2E F13 | PARTIAL | Ampliar a rutas productivas críticas |
| WEB-04 | CSP/headers/cache y XSS no ejecutable | tests Next/Flask F13 | PARTIAL | Verificación exterior tras Nginx/TLS |
| PERF-01 | Escenarios HTTP reproducibles | `tests/performance/` y `PERFORMANCE_BUDGET.md` | PARTIAL | Baseline local medido; repetir con volumen y entorno estable de staging |
| PERF-02 | N+1/índices/query plans críticos | tests de conteo y migraciones | PARTIAL | `EXPLAIN ANALYZE` con volumen fase 13/14 |
| OBS-01 | Logs estructurados/redacción/request-correlation | `test_app.py`, tests de jobs | PASS | Agregación externa fase 14 |
| OBS-02 | Métricas API/auth protegidas y acumuladores acotados | `common/metrics.py`, `test_app.py` | PARTIAL | Métricas multiproceso/colas/Signal/IA/docs y backend de series fase 14 |
| SCAN-01 | Ruff/mypy/ESLint/TS/dependency/secret/code scan | comandos de readiness F13 | PARTIAL | Imagen, SBOM y licencia al existir build prod |
| DAST-01 | Baseline local contra rutas propias | `tests/security/dast_baseline.py`: 13/13 contra Gunicorn | PASS | Repetir ZAP/baseline en staging autorizado; no escanear producción |
| OPS-01 | Runbooks API/DB/Redis/Celery/Signal/seguridad | `docs/operations/runbooks/` | PARTIAL | Validar durante despliegue |
| PROD-01 | Smoke externo y headers/TLS/cert | fase 14 | GAP | Bloquea release, no fase 13 local |
| PROD-02 | Backup/restore y RPO/RTO medidos | fase 15 | GAP | Bloquea release |
| PROD-03 | Scan imagen y puertos externos | fases 14–15 | GAP | Bloquea release |
