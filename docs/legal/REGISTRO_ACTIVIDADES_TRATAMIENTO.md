# Registro de actividades de tratamiento (orientativo) · OPN Oracle

> **BORRADOR · requiere revisión jurídica y validación del despliegue antes de enviar o firmar**

| Campo | Valor |
|---|---|
| Versión | `0.1.0-g21` |
| Owner | OPN · cumplimiento comercial (borrador producto) |
| Estado | `borrador interno · no contractual` |
| Fecha | 2026-08-06 |
| Base de código | `044e35a8ef696faf53d3d108387d0cbed06a99dc` |

## Notas de uso

- Este RAT es **orientativo** a partir del modelo de datos y la documentación del repositorio.
- No sustituye el registro formal del art. 30 del responsable ni del encargado.
- Los `unknown` / `[POR CONFIRMAR]` se dejan **visibles a propósito**.
- Base jurídica indicada = hipótesis de trabajo para revisión legal, no dictamen.

## Tratamiento T1 — Identidad, autenticación y sesiones

| Campo | Valor |
|---|---|
| Nombre | Gestión de cuentas de usuario y sesiones |
| Responsable | Cliente (usuarios de su organización) |
| Encargado | Prestador OPN Oracle `[POR CONFIRMAR entidad]` |
| Finalidades | Autenticar, mantener sesión, recuperar acceso, administrar membresías |
| Base jurídica (hipótesis) | Ejecución de contrato con el usuario/organización (art. 6.1.b); interés legítimo de seguridad (art. 6.1.f) en logs de sesión — **revisión legal pendiente** |
| Categorías de interesados | Empleados/colaboradores del cliente invitados a la plataforma |
| Categorías de datos | Email (CITEXT), display name, password_hash, status, email_verified_at, last_login_at, session_hash, IP, user-agent summary, idle/absolute expiry |
| Origen | El propio interesado / admin del tenant |
| Destinatarios | Personal de soporte del encargado con necesidad; proveedor de correo si envío activo |
| Transferencias | `[POR CONFIRMAR según MAIL_BACKEND y hosting]` |
| Plazos | Sesión: idle por defecto 30 min / absoluta 12 h; remember 14 días (config). Tokens de reset/invitación con expiración. Retención histórica de filas de sesión/auditoría de login: **unknown sin política contractual** |
| Medidas | Argon2id; cookie HttpOnly; CSRF; rate limits documentados en contrato API |
| Evidencia repo | `platform/models.py` (`User`, `UserSession`); `auth/passwords.py`; `config.py` (`SESSION_*`) |

## Tratamiento T2 — Administración multi-tenant y RBAC

| Campo | Valor |
|---|---|
| Nombre | Tenants, workspaces, roles y permisos |
| Finalidades | Aislar clientes, autorizar acciones, invitar usuarios |
| Base jurídica (hipótesis) | Ejecución del contrato de servicio (art. 6.1.b) |
| Interesados | Usuarios del tenant; invitados |
| Datos | Tenant name/slug/settings; memberships; roles; invitations (token hash); platform_role super_admin |
| Destinatarios | Admins del tenant; superadmin de plataforma (acceso excepcional auditado) |
| Transferencias | No por el tratamiento en sí; dependen del hosting |
| Plazos | Mientras el tenant esté activo + obligaciones post-contractuales `[POR CONFIRMAR]` |
| Medidas | RLS en tablas tenant-scoped; roles de sistema; auditoría de admin |
| Evidencia | [../security/MULTITENANCY.md](../security/MULTITENANCY.md); `platform/rbac.py` |

## Tratamiento T3 — Contenido de inteligencia del expediente (negocio del tenant)

| Campo | Valor |
|---|---|
| Nombre | Expedientes estratégicos y objetos de negocio |
| Finalidades | Soporte a inteligencia comercial/estratégica del cliente (señales, actores, riesgos, oportunidades, informes, vigilancias, etc.) |
| Base jurídica (hipótesis) | Ejecución de contrato (art. 6.1.b) respecto de datos del cliente; ver T5 para personas en fuentes públicas |
| Interesados | Usuarios que generan contenido; terceros mencionados en el contenido |
| Datos | Dossiers, objetivos, señales, actores, items de procurement, conversaciones, tareas, meetings, reports, exports metadata, etc. (modelos bajo `opn_oracle/oracle`, `reporting`) |
| Origen | Usuario del tenant; integraciones (p. ej. Signal Avanza); documentos subidos |
| Destinatarios | Usuarios autorizados del mismo tenant; workers internos; integraciones configuradas |
| Transferencias | Depende de integraciones activas `[POR CONFIRMAR]` |
| Plazos | Mientras el expediente/tenant exista; **no hay TTL global de negocio verificado** → brecha a pactar |
| Medidas | Tenant scoping + RLS; permisos de dossier; auditoría de acciones sensibles |
| Evidencia | `oracle/models.py`; exports en `reporting/exports.py` |

## Tratamiento T4 — Documentos y evidencias (feature gated)

| Campo | Valor |
|---|---|
| Nombre | Carga, análisis y retención de documentos |
| Finalidades | Adjuntar y explotar documentos como evidencia en expedientes |
| Base jurídica (hipótesis) | Ejecución de contrato (art. 6.1.b) |
| Interesados | Personas identificables dentro de documentos |
| Datos | Ficheros, hashes, chunks, estados de procesado, retention_until, purge_after, legal_hold |
| Destinatarios | Usuarios con permiso documents.*; posible scanner antivirus; object storage |
| Transferencias | Si storage S3-compatible externo: región del bucket `[POR CONFIRMAR]` |
| Plazos | Política por tenant: default modelado 365 días retención + 30 días gracia de purge (código); configurable en `DocumentRetentionPolicy` |
| Medidas | Soft-delete, legal hold, scanner ClamAV cuando se configure, fail-closed sin S3+ClamAV en prod estable |
| Estado de activación | `DOCUMENTS_ENABLED` y backend de storage — **activación por despliegue** |
| Evidencia | `documents/models.py`, `documents/service.py`, [../operations/DOCUMENTS_EVIDENCE_SEARCH.md](../operations/DOCUMENTS_EVIDENCE_SEARCH.md) |

## Tratamiento T5 — Inteligencia sobre personas físicas y entidades (fuentes públicas / investigaciones)

| Campo | Valor |
|---|---|
| Nombre | Tratamiento de datos de personas en investigaciones y corpus de fuentes |
| Finalidades | Análisis de red societaria, cargos, adjudicaciones y contexto de mercado para el cliente |
| Base jurídica (hipótesis de trabajo) | Interés legítimo del cliente (art. 6.1.f) y/o misión pública si aplica; **requiere LIA y revisión legal** — ver [BASE_JURIDICA_INVESTIGACIONES.md](./BASE_JURIDICA_INVESTIGACIONES.md) |
| Interesados | Administradores, apoderados, personas mencionadas en fuentes públicas o informes |
| Datos | Nombres, cargos, relaciones societarias, referencias a fuentes; posibles identificadores si el cliente o la fuente los aportan |
| Origen | Fuentes públicas vía Signal u otras integraciones; entrada manual del analista |
| Destinatarios | Usuarios del tenant; no se publica automáticamente fuera del tenant |
| Transferencias | Según proveedor de fuente / IA `[POR CONFIRMAR]` |
| Plazos | Orientación de producto para cargos cesados (p. ej. referencia 4 años en docs de estrategia) **no es TTL técnico global implementado** → marcar como política a formalizar |
| Medidas | Minimización en diseño de investigaciones; evidencia citable; revisión humana de artefactos IA; no puntuar personas como «alto riesgo» sin marco (línea roja documentada en estrategia) |
| Unknowns visibles | Base jurídica definitiva; canal formal de oposición; DPO; licencias exactas de cada fuente en el despliegue |

## Tratamiento T6 — Inteligencia artificial (resúmenes, candidatos, informes asistidos)

| Campo | Valor |
|---|---|
| Nombre | Generación y revisión de artefactos de IA |
| Finalidades | Asistir al analista con resúmenes y candidatos; no sustituir la decisión humana por defecto |
| Base jurídica (hipótesis) | Ejecución de contrato (art. 6.1.b) + interés legítimo en eficiencia; transparencia art. 50 AI Act como práctica defensiva documentada en estrategia — **revisión legal pendiente** |
| Interesados | Usuarios; terceros mencionados en el contexto del expediente |
| Datos | Snapshots de contexto, prompts (no se loguean completos según runtime doc), hashes, métricas, outputs candidatos, decisión humana accept/reject |
| Destinatarios | Runtime IA (mock / Signal→Ollama u otros proveedores aprobados en Signal) |
| Transferencias | Cloud secundario solo si se aprueba en Signal; Oracle no fuerza credenciales cloud |
| Plazos | Artefactos y `AIAuditLog`: **TTL contractual unknown**; purga no documentada como política global |
| Medidas | `AI_ENABLED` fail-closed; políticas por tenant; evidence allowlist; human review; kill switch |
| Evidencia | [../operations/AI_RUNTIME.md](../operations/AI_RUNTIME.md); `ai/routes.py` |

## Tratamiento T7 — Auditoría, jobs, métricas y seguridad operativa

| Campo | Valor |
|---|---|
| Nombre | Audit events, jobs durables, logs y métricas |
| Finalidades | Seguridad, depuración, accountability, operación del servicio |
| Base jurídica (hipótesis) | Interés legítimo (art. 6.1.f) / obligación legal cuando aplique |
| Interesados | Usuarios y, indirectamente, sujetos de recursos auditados |
| Datos | action, resource_type/id, actor_id, result, request/correlation ids, metadata JSON (sin secretos por diseño) |
| Destinatarios | Operadores del encargado; posible stack de observabilidad `[POR CONFIRMAR]` |
| Plazos | **Sin TTL de `AuditEvent` verificado en código** → brecha a pactar |
| Medidas | Redacción en logs; métricas de baja cardinalidad; append-only de auditoría en runtime |
| Evidencia | `AuditEvent` model; [../security/READINESS_REPORT.md](../security/READINESS_REPORT.md) |

## Tratamiento T8 — Notificaciones por correo

| Campo | Valor |
|---|---|
| Nombre | Envío de invitaciones, resets y notificaciones |
| Finalidades | Entregar mensajes transaccionales del servicio |
| Base jurídica (hipótesis) | Ejecución de contrato (art. 6.1.b) |
| Datos | Email destino, contenido del mensaje transaccional |
| Destinatarios | Backend `capture` (dev), SMTP, o Microsoft Graph según config |
| Transferencias | Posible (Graph/Microsoft) — **activación y región por confirmar** |
| Plazos | El proveedor de correo puede retener logs propios `[POR CONFIRMAR DPA del proveedor]` |
| Evidencia | `notifications/email.py`; `MAIL_BACKEND` en `config.py` |

## Tratamiento T9 — Copias de seguridad

| Campo | Valor |
|---|---|
| Nombre | Backup y restore de PostgreSQL (y objetos si aplica) |
| Finalidades | Continuidad y recuperación |
| Base jurídica (hipótesis) | Interés legítimo / ejecución de contrato |
| Datos | Copia del conjunto de datos del sistema en el alcance del dump |
| Destinatarios | Operadores; destino off-host si está habilitado |
| Transferencias / residencia | Destino off-host `[POR CONFIRMAR]` |
| Plazos | Default documentado de retención de backups 30 días (`BACKUP_RETENTION_DAYS` / ops); off-host y RPO/RTO de despliegue **por confirmar** |
| Medidas | Scripts con validación de catálogo; off-site cifrado opcional; restore en entorno aislado |
| Evidencia | [../operations/BACKUP_RESTORE.md](../operations/BACKUP_RESTORE.md) |

## Mapa rápido de unknowns

| Tema | Estado |
|---|---|
| Entidad jurídica exacta del encargado y del hosting | `[POR CONFIRMAR]` |
| Región/país del/de los servidores en servicio al cliente | `[POR CONFIRMAR]` |
| Subencargados **activos** en ese servicio | Ver tabla de confirmación |
| DPO | No designado en repo |
| TTL global de auditoría y de datos de negocio | No verificado → no inventar |
| Procedimiento contractual de fin de servicio | Parcial (exports sí; erasure total no cerrado) |
| Licencias y bases de cada fuente de inteligencia en el despliegue | Parcial / por fuente |

## Enlaces

- [DPA_BORRADOR.md](./DPA_BORRADOR.md)
- [PRIVACIDAD_RETENCION_Y_SUPRESION.md](./PRIVACIDAD_RETENCION_Y_SUPRESION.md)
- [SUBENCARGADOS_Y_RESIDENCIA.md](./SUBENCARGADOS_Y_RESIDENCIA.md)
