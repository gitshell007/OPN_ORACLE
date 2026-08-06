# Subencargados y residencia de datos · OPN Oracle

> **BORRADOR · requiere revisión jurídica y validación del despliegue antes de enviar o firmar**

| Campo | Valor |
|---|---|
| Versión | `0.1.0-g21` |
| Owner | OPN · cumplimiento comercial (borrador producto) |
| Estado | `borrador interno · no contractual` |
| Fecha | 2026-08-06 |
| Base de código | `044e35a8ef696faf53d3d108387d0cbed06a99dc` |

## Principios de esta lista

1. Solo se nombran proveedores o componentes **verificables en el repositorio** (código, compose, docs).
2. **Configurable pero no confirmado en el despliegue del cliente** → estado `por confirmar` o
   `configurable · no afirmar activo`.
3. No se inventan ubicaciones. La residencia operativa del servicio al cliente es
   **`[POR CONFIRMAR por despliegue]`**.
4. «Signal Avanza» y componentes OPN se tratan con honestidad de rol (producto hermano / infra
   propia), sin asumir personalidad jurídica ni región sin evidencia contractual.

## Residencia (capa de despliegue)

| Pregunta | Respuesta honesta |
|---|---|
| ¿Dónde residen los datos del tenant en producción? | **`[POR CONFIRMAR]`** — este turno no consulta producción |
| ¿El código impone UE? | **No** hay control de producto que por sí solo garantice residencia UE |
| ¿Qué puede decir ventas hoy? | «La residencia se define en el anexo de despliegue del contrato; el diseño contempla hosting controlado por OPN o del cliente, no un multi-cloud opaco por defecto.» |
| ¿Qué no puede decir ventas? | «Todos los datos residen en la UE» / «nunca salen de España» sin evidencia |

Dominio de referencia en runbooks de ops (no prueba de residencia de datos de clientes): ver
documentación de TLS/ops en `docs/operations/` (p. ej. plantillas orientadas a despliegue OPN).
No se reproducen hostnames de clientes ni secretos.

## Tabla de subencargados / terceros / componentes de tratamiento

| Nombre | Servicio | Datos que puede tratar | Región | Rol | Estado de confirmación | Notificación de cambio |
|---|---|---|---|---|---|---|
| Infraestructura de hosting del servicio Oracle | Cómputo, disco, red del despliegue | Datos de aplicación del tenant en reposo/tránsito interno | `[POR CONFIRMAR]` | Encargado infra / subencargado de hosting | **por confirmar** (despliegue) | Según DPA; alta impacto |
| PostgreSQL | Base de datos principal | Contenido de negocio, identidad, auditoría | Misma que el host `[POR CONFIRMAR]` | Componente de datos (suele ser autoalojado) | **diseño autoalojado en compose**; instancia concreta por confirmar | Alta |
| Redis | Sesiones, colas, caché, rate limit | IDs de sesión, jobs, datos efímeros — no fuente de verdad de negocio | Misma que el host `[POR CONFIRMAR]` | Componente de soporte (suele ser autoalojado) | **diseño autoalojado en compose** | Media |
| Signal Avanza (producto OPN) | Ingesta/normalización de señales, monitores, entity intel, gobierno de tareas IA | Identificadores de tenant externos, consultas, eventos de fuentes, tareas IA gobernadas | `[POR CONFIRMAR en contrato Signal]` | Proveedor de integración / posible subencargado o corresponsable según flujo | **Contrato de integración documentado en repo**; activación HTTP fail-closed hasta config | Alta — notificar si cambia productor o región |
| Fuentes públicas vía Signal (p. ej. corpus PLACSP/BORME referenciados en docs) | Datos de contratación y societarios de origen público | Datos de entidades y personas en fuentes | Origen público; copia en Signal/Oracle según pipeline | Fuente / productor de datos | **referenciadas en documentación de producto**; cobertura y licencia exacta por confirmar por fuente | Media |
| Microsoft Graph (Microsoft) | Envío de correo (`MAIL_BACKEND=graph`) | Email de destinatarios y contenido transaccional | Según tenant Microsoft del emisor `[POR CONFIRMAR]` | Subencargado de mensajería si está activo | **configurable en código y plantilla prod**; **no afirmar activo** sin validar despliegue | Alta si se activa/cambia |
| SMTP genérico | Envío de correo | Igual que arriba | Según servidor SMTP `[POR CONFIRMAR]` | Subencargado de mensajería si está activo | **configurable**; dev usa loopback fail-closed | Alta si se activa |
| Ollama / modelos locales (vía Signal en modo aprobado) | Inferencia IA | Contexto de expediente / prompts de tarea gobernada | Típicamente local al entorno Signal `[POR CONFIRMAR]` | Subprocesador de IA si activo | **documentado como primario local en runtime**; no es cloud por defecto | Alta si se cambia a cloud |
| Proveedor IA cloud secundario (aprobación en Signal; p. ej. menciones operativas a rutas cloud) | Inferencia de respaldo | Contexto acotado de tarea | `[POR CONFIRMAR]` | Subencargado IA | **no forzado desde Oracle**; requiere aprobación de clasificación/redacción/presupuesto en Signal | Alta — solo con autorización |
| Object storage S3-compatible | Ficheros de documentos/exports/reportes | Objetos binarios y metadatos de storage | Región del bucket `[POR CONFIRMAR]` | Subencargado de storage si no es disco local del host | **configurable**; prod estable de documentos exige S3; local solo UAT controlada | Alta |
| ClamAV | Antivirus de documentos | Contenido de ficheros escaneados | Suele ser red privada del despliegue `[POR CONFIRMAR]` | Encargado técnico de escaneo | **configurable**; gate de documentos | Media |
| Emisor ACME / certificados (p. ej. Let's Encrypt en runbook TLS) | Certificados TLS | Datos de dominio/validación, no el contenido del tenant | Público (ACME) | Proveedor de PKI | **runbook de ops**; no trata el contenido de BD | Baja |
| Observabilidad externa (APM, log drain SaaS) | Métricas/logs | Posibles identificadores en logs si se habilita | `[POR CONFIRMAR]` | Subencargado | **no hay proveedor SaaS de observabilidad afirmado como activo en producto** | Alta si se añade |
| OpenRouter u otros brokers cloud de modelos | Inferencia alternativa | Contexto de prompts | `[POR CONFIRMAR]` | Subencargado IA | Aparece en herramientas/scripts de health; **no se afirma como path productivo de Ask** en docs de desarrollo recientes | No usar en discurso comercial como activo sin confirmación |

## Roles genéricos de acceso humano (sin nombres de personas)

| Rol | Acceso típico | Condición |
|---|---|---|
| Usuarios del cliente | Solo su tenant y permisos RBAC | Autenticación de producto |
| Admin del tenant del cliente | Membresías, política IA del tenant, config local | Rol owner/admin |
| Operador del prestador | Despliegue, backups, incidentes | Procedimiento interno |
| Superadmin de plataforma | Acceso excepcional a un tenant con motivo y auditoría | Capacidad de producto documentada; uso restringido |

## Política de cambio y notificación (propuesta para legal)

1. Mantener esta tabla versionada en el repositorio o anexo contractual.
2. Clasificar cambios: **alto** (hosting, región, IA cloud, correo, storage) / medio / bajo.
3. Notificar al cliente los cambios de alto impacto con preaviso `[POR CONFIRMAR: días]`.
4. No añadir subencargado de tratamiento de datos del cliente en silencio.

## Qué falta confirmar antes de enviar a un prospecto concreto

- [ ] Entidad legal del hosting y región del/de los servidores del servicio ofrecido
- [ ] Si Microsoft Graph / SMTP está activo y bajo qué tenant
- [ ] Si Signal HTTP está habilitado para ese cliente y mapeo de tenant
- [ ] Si documentos e IA están habilitados y con qué backends
- [ ] Destino y cifrado de backup off-host
- [ ] Existencia de observabilidad SaaS externa
- [ ] Mecanismos de transferencia internacional si los hay

## Enlaces

- [DPA_BORRADOR.md](./DPA_BORRADOR.md)
- [REGISTRO_ACTIVIDADES_TRATAMIENTO.md](./REGISTRO_ACTIVIDADES_TRATAMIENTO.md)
- [../operations/AI_RUNTIME.md](../operations/AI_RUNTIME.md)
- [../integrations/signal-avanza/CONTRACT_V1.md](../integrations/signal-avanza/CONTRACT_V1.md)
