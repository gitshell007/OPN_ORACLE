# Matriz de controles y alegaciones comerciales · OPN Oracle

> **BORRADOR · requiere revisión jurídica y validación del despliegue antes de enviar o firmar**

| Campo | Valor |
|---|---|
| Versión | `0.1.0-g21` |
| Owner | OPN · cumplimiento comercial (borrador producto) |
| Estado | `borrador interno · no contractual` |
| Fecha | 2026-08-06 |
| Base de código | `d472aeb7ff62a1fb8fff69086c63752fc37e5b39` |

## Leyenda de estados

| Estado | Significado |
|---|---|
| `verified` | Existe evidencia versionada en el repo de la **capacidad de producto** descrita |
| `partial` | Existe base en código/docs, pero incompleta, gated o no suficiente para promesa comercial plena |
| `planned` | Intención de roadmap; **no** está implementado como presente |
| `not_available` | No existe en producto; no debe venderse como presente |
| `needs_deployment_confirmation` | Depende del entorno operativo; este turno no lo verifica |

**Regla:** «diseñado», «disponible en código» y «activo en el despliegue del cliente» **no son sinónimos**.

Owner genérico de filas: `producto` (código), `ops` (despliegue), `legal` (contrato), `comercial` (mensaje).

## Tabla de controles (≥15)

| ID | Control / claim | Estado | Evidencia en repo | Owner | Lenguaje comercial **permitido** | Lenguaje **prohibido** |
|---|---|---|---|---|---|---|
| C01 | Aislamiento multi-tenant con RLS PostgreSQL | `verified` | [../security/MULTITENANCY.md](../security/MULTITENANCY.md); políticas en migraciones/tests de integración | producto | «El producto aplica aislamiento por tenant en repositorio y RLS en PostgreSQL.» | «Imposible el acceso cross-tenant en cualquier despliegue» |
| C02 | RBAC por tenant (roles owner/admin/editor/analyst/viewer/auditor) | `verified` | `apps/api/src/opn_oracle/platform/rbac.py`; [../security/MULTITENANCY.md](../security/MULTITENANCY.md) | producto | «Permisos por rol de tenant seedados de forma idempotente.» | «Cumple cualquier matriz RBAC del cliente sin personalización» |
| C03 | Registro de auditoría de acciones (`AuditEvent`) | `verified` | `apps/api/src/opn_oracle/platform/models.py` (`AuditEvent`); `apps/api/src/opn_oracle/platform/audit.py` | producto | «Hay auditoría append-oriented de acciones de plataforma/tenant.» | «Trazabilidad completa de todo acceso humano y máquina sin lagunas» |
| C04 | Autenticación por contraseña con Argon2id | `verified` | `apps/api/src/opn_oracle/auth/passwords.py` | producto | «Las contraseñas se almacenan con hash Argon2id.» | «Autenticación enterprise completa» |
| C05 | Sesión con cookie HttpOnly + CSRF en mutaciones | `verified` | [../api/CONTRACT_OVERVIEW.md](../api/CONTRACT_OVERVIEW.md); `apps/api/src/opn_oracle/config.py` | producto | «Sesión basada en cookie HttpOnly con token CSRF en mutaciones.» | «Sesión inmune a todo ataque web» |
| C06 | MFA (TOTP/WebAuthn/etc.) | `not_available` | Ausencia en `apps/api/src` (sin módulos MFA/TOTP/WebAuthn de producto) | producto | «MFA no está implementado hoy; puede negociarse como hito.» | «MFA disponible» / «MFA activo» |
| C07 | SSO / SAML / OIDC | `not_available` | [../strategy/ORACLE_PRODUCT_GAP_ANALYSIS.md](../strategy/ORACLE_PRODUCT_GAP_ANALYSIS.md); roadmap gated | producto / comercial | «SSO no existe hoy; en Enterprise puede comprometerse por contrato.» | «SSO disponible» / «login corporativo listo» |
| C08 | Cifrado en tránsito (TLS) | `needs_deployment_confirmation` | Plantillas y runbook [../operations/TLS.md](../operations/TLS.md); `compose.prod.yml` + Nginx | ops | «El diseño de despliegue contempla TLS terminado en proxy; hay que confirmar el entorno del cliente.» | «TLS activo en todos los despliegues» sin evidencia |
| C09 | Cifrado en reposo del almacenamiento principal (disco/volumen PG) | `needs_deployment_confirmation` | No hay evidencia de full-disk encryption obligatoria en repo | ops | «El cifrado de volumen del host es decisión/confirmación de despliegue.» | «Cifrado en reposo activo» como hecho de producto |
| C10 | Cifrado de credenciales de integración en BD (AES-256-GCM) | `verified` | `apps/api/src/opn_oracle/platform/models.py` (`ApiCredential`); `apps/api/src/opn_oracle/integrations/service.py` | producto | «Las credenciales de integración se modelan cifradas (AES-256-GCM) con clave fuera de PostgreSQL.» | «Todos los datos en BD están cifrados campo a campo» |
| C11 | Cifrado SSE en object storage S3 cuando se usa backend S3 | `partial` | `documents/storage.py` (`ServerSideEncryption: AES256`); documentos gated | producto / ops | «Si se usa S3 compatible, el adaptador solicita SSE AES-256.» | «Cifrado en reposo de documentos siempre activo» |
| C12 | Backups lógicos PostgreSQL y prueba de restore aislado (scripts) | `partial` | [../operations/BACKUP_RESTORE.md](../operations/BACKUP_RESTORE.md); `scripts/backup-production.sh`, `scripts/restore-test-production.sh` | ops | «Existen scripts de backup lógico y restore aislado verificable.» | «Backup off-host y DR garantizados» / «PITR activo» |
| C13 | Backup cifrado off-host | `partial` | `scripts/backup-offsite.sh`; default `ORACLE_OFFSITE_ENABLED=0` en docs | ops | «Hay pipeline opcional de copia cifrada off-host; activación y destino por confirmar.» | «Copia off-host activa en todos los clientes» |
| C14 | PITR (point-in-time recovery) | `not_available` | Sin runbook/implementación PITR como capacidad afirmada | ops | «PITR no se ofrece como capacidad documentada del producto hoy.» | «PITR activo» |
| C15 | Exportación de datos de negocio (CSV allowlisted) con TTL y purge | `verified` | `apps/api/src/opn_oracle/reporting/exports.py`; `apps/api/src/opn_oracle/config.py` (`EXPORT_TTL_HOURS`) | producto | «El producto permite exportaciones CSV acotadas con caducidad y purga.» | «Portabilidad RGPD completa de todo el tenant en un clic» |
| C16 | Retención y purge de documentos (soft-delete, grace, legal hold) | `partial` | `documents/models.py`, `documents/service.py`, task `maintenance.documents_retention` | producto | «Hay modelo de retención/purge y legal hold para documentos cuando el módulo está habilitado.» | «Retención contractual de todas las categorías ya cerrada» |
| C17 | Supresión automatizada de tenant completo al fin de contrato | `not_available` | No hay flujo de offboarding/erasure total de tenant documentado como completo | producto / legal | «La supresión de fin de contrato requiere procedimiento operativo y acuerdo; no hay botón único verificado.» | «Borramos todo automáticamente al día D» |
| C18 | Residencia de datos en UE | `needs_deployment_confirmation` | Sin evidencia versionable de región única de producción en este turno | ops / legal | «La residencia operativa se confirma por despliegue y contrato; no se afirma de forma genérica aquí.» | «Todos los datos residen en la UE» |
| C19 | IA con guardrails, allowlist de evidencia y revisión humana de artefactos | `partial` | [../operations/AI_RUNTIME.md](../operations/AI_RUNTIME.md); rutas de human-review en `ai/routes.py` | producto | «La IA está deshabilitada por defecto; cuando se habilita hay política, auditoría y revisión humana de artefactos candidatos.» | «IA certificada» / «sin riesgo de alucinación» |
| C20 | Certificaciones ISO 27001 / SOC 2 / ENS | `not_available` | Sin certificados ni declaraciones de certificación en repo | legal / comercial | «No disponemos de certificación ISO/SOC/ENS publicada en este paquete.» | «Estamos certificados ISO/SOC/ENS» |
| C21 | Plan de respuesta a incidentes documentado | `verified` | [../operations/INCIDENT_RESPONSE.md](../operations/INCIDENT_RESPONSE.md); runbook [../operations/runbooks/SECURITY_INCIDENTS.md](../operations/runbooks/SECURITY_INCIDENTS.md) | ops | «Existe procedimiento documentado de respuesta a incidentes en el repositorio.» | «SLA de notificación 24h garantizado» sin contrato |
| C22 | Correo transaccional (invitaciones/reset) | `partial` | `MAIL_BACKEND` capture/smtp/graph en `config.py`; Graph en `compose.prod.yml` | ops | «El producto soporta envío por SMTP o Microsoft Graph; el backend activo depende del despliegue.» | «Siempre enviamos con Microsoft 365 en UE» |
| C23 | DPO nombrado y publicado | `not_available` | Sin designación formal en repo | legal | «DPO / contacto de privacidad: `[POR CONFIRMAR]`.» | «Tenemos DPO registrado en AEPD» sin evidencia |
| C24 | Fail-closed de features sensibles (documentos, Signal HTTP, IA) | `verified` | `apps/api/src/opn_oracle/config.py`; [../operations/AI_RUNTIME.md](../operations/AI_RUNTIME.md); [../operations/DOCUMENTS_EVIDENCE_SEARCH.md](../operations/DOCUMENTS_EVIDENCE_SEARCH.md) | producto | «Varias capacidades sensibles permanecen cerradas hasta configuración explícita y gates.» | «Producción ya opera con todas las features abiertas» |

## Tabla de trazabilidad comercial (afirmación → evidencia → certeza → texto usable)

| # | Afirmación | Fichero / ruta | Certeza | Texto que ventas puede usar |
|---|---|---|---|---|
| 1 | Multi-tenant con RLS | `docs/security/MULTITENANCY.md` | alta (producto) | «Aislamos datos por cliente con RLS y contexto de tenant en backend.» |
| 2 | Roles RBAC seed | `apps/api/src/opn_oracle/platform/rbac.py` | alta (producto) | «Roles de sistema por tenant: owner, admin, editor, analyst, viewer, auditor.» |
| 3 | Auditoría de acciones | `apps/api/src/opn_oracle/platform/models.py` | alta (producto) | «Registramos eventos de auditoría de acciones relevantes.» |
| 4 | Hash de contraseñas Argon2id | `apps/api/src/opn_oracle/auth/passwords.py` | alta (producto) | «No guardamos contraseñas en claro; usamos Argon2id.» |
| 5 | CSRF + cookie HttpOnly | `docs/api/CONTRACT_OVERVIEW.md` | alta (producto) | «La sesión usa cookie HttpOnly y CSRF en cambios de estado.» |
| 6 | Credenciales de integración cifradas | `apps/api/src/opn_oracle/platform/models.py` | alta (producto) | «Tokens de integración se almacenan cifrados (AES-256-GCM).» |
| 7 | Exports CSV con caducidad | `apps/api/src/opn_oracle/reporting/exports.py` | alta (producto) | «Puedes exportar datasets permitidos; los ficheros caducan y se purgan.» |
| 8 | Runbook de incidentes | `docs/operations/INCIDENT_RESPONSE.md` | alta (doc ops) | «Tenemos procedimiento de respuesta a incidentes documentado.» |
| 9 | Backup/restore scripts | `docs/operations/BACKUP_RESTORE.md` | media (ops/código) | «Dispone de backup lógico y prueba de restore aislado; el off-host se confirma por entorno.» |
| 10 | IA fail-closed + revisión humana | `docs/operations/AI_RUNTIME.md` | media (producto configurable) | «La IA no está abierta por defecto; los artefactos pasan por controles y revisión humana.» |
| 11 | MFA | (ausencia en código de producto) | alta de **no disponibilidad** | «Hoy no hay MFA; si lo necesitas, se planifica por contrato.» |
| 12 | SSO/SAML/OIDC | `docs/strategy/ORACLE_PRODUCT_GAP_ANALYSIS.md` | alta de **no disponibilidad** | «SSO no está construido; es hito Enterprise gated por contrato.» |
| 13 | PITR | (sin implementación afirmada) | alta de **no disponibilidad** | «No ofrecemos PITR como capacidad actual.» |
| 14 | Residencia UE | (sin evidencia de despliegue en este turno) | baja hasta confirmación | «La ubicación del hosting se detalla en el anexo de despliegue del contrato.» |
| 15 | Certificaciones | (sin certificados en repo) | alta de **no disponibilidad** | «No afirmamos ISO/SOC/ENS en este paquete.» |
| 16 | Readiness producción global | `docs/security/READINESS_REPORT.md`, `docs/legal/PRODUCTION_READINESS_STATEMENT.md` | alta (doc) | «No declaramos production-ready global; el alcance se acota por piloto/contrato y despliegue.» |
| 17 | Off-host backup | `scripts/backup-offsite.sh`, `docs/operations/P2_OPS_READINESS.md` | media (opcional) | «Existe pipeline opcional de copia cifrada fuera del host; hay que confirmar si está activo.» |
| 18 | Retención documentos | `apps/api/src/opn_oracle/documents/models.py` | media (feature gated) | «Los documentos tienen política de retención, soft-delete y legal hold cuando el módulo está activo.» |

## Resumen de brechas honestas (mínimo 5 no-`verified`)

1. **C06 MFA** — `not_available`
2. **C07 SSO** — `not_available`
3. **C14 PITR** — `not_available`
4. **C17 Erasure total de tenant** — `not_available`
5. **C20 Certificaciones** — `not_available`
6. **C09 Cifrado en reposo de disco** — `needs_deployment_confirmation`
7. **C18 Residencia UE** — `needs_deployment_confirmation`
8. **C12/C13 Backups productivos medidos** — `partial`

## Uso por comercial

1. Consultar esta matriz antes de responder un RFP.
2. Si el estado no es `verified`, no convertir la frase en garantía contractual sin legal.
3. Enviar junto con [CUESTIONARIO_DUE_DILIGENCE_COMERCIAL.md](./CUESTIONARIO_DUE_DILIGENCE_COMERCIAL.md).
