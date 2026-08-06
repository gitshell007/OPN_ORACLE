# Carpeta de cumplimiento comercial · OPN Oracle

> **BORRADOR · requiere revisión jurídica y validación del despliegue antes de enviar o firmar**

| Campo | Valor |
|---|---|
| Versión del paquete | `0.1.0-g21` |
| Owner | OPN · cumplimiento comercial (borrador producto) |
| Estado | `borrador interno · no contractual` |
| Fecha de corte documental | 2026-08-06 |
| Base de código inventariada | `d472aeb7ff62a1fb8fff69086c63752fc37e5b39` (`sv2/g19-recorrido-vivo`) |
| Prompt origen | `SV2-G21-CARPETA-CUMPLIMIENTO-COMERCIAL` |

## Para qué sirve este paquete

Conjunto de **borradores honestos** orientados a legal, compras o seguridad de un prospecto.
Responde, con evidencia versionable del repositorio, a:

1. Qué datos trata el producto y con qué finalidad.
2. Quién puede acceder (roles) y qué terceros pueden intervenir.
3. Qué controles existen en **código/producto**, cuáles son **parciales**, cuáles son **planificados**
   y cuáles **dependen del despliegue concreto** (no consultado en este turno).
4. Qué **no** se puede afirmar todavía (certificaciones, residencia operativa, MFA, SSO, cifrado en
   reposo del host, SLA, ENS/ISO/SOC, DPO nombrado, etc.).

No es un dictamen jurídico, no es un DPA firmable tal cual y no sustituye la revisión de un abogado
ni la validación del entorno operativo.

## Distinción obligatoria (leer antes que nada)

| Capa | Qué es | Qué no es |
|---|---|---|
| **Producto / código** | Capacidades implementadas y documentadas en este repositorio | Garantía de que están activas en un cliente |
| **Despliegue concreto** | Configuración, host, región, backups off-host, TLS emitido, proveedores activos | Inferible solo por leer el código |
| **Compromiso contractual** | Cláusulas negociadas y firmadas con el cliente | Estos borradores |

Cualquier dato de residencia, hostname, subencargado activo o medida de infra no verificable en el
repo aparece como **`[POR CONFIRMAR]`** o estado `needs_deployment_confirmation`.

## Orden de lectura recomendado

1. [PRODUCTION_READINESS_STATEMENT.md](./PRODUCTION_READINESS_STATEMENT.md) — veredicto por alcance y límites.
2. [CUESTIONARIO_DUE_DILIGENCE_COMERCIAL.md](./CUESTIONARIO_DUE_DILIGENCE_COMERCIAL.md) — respuestas cortas reutilizables.
3. [MATRIZ_CONTROLES_Y_ALEGACIONES.md](./MATRIZ_CONTROLES_Y_ALEGACIONES.md) — qué se puede decir en comercial y qué no.
4. [REGISTRO_ACTIVIDADES_TRATAMIENTO.md](./REGISTRO_ACTIVIDADES_TRATAMIENTO.md) — tratamientos y categorías.
5. [SUBENCARGADOS_Y_RESIDENCIA.md](./SUBENCARGADOS_Y_RESIDENCIA.md) — terceros y geografía.
6. [PRIVACIDAD_RETENCION_Y_SUPRESION.md](./PRIVACIDAD_RETENCION_Y_SUPRESION.md) — plazos, export y borrado.
7. [BASE_JURIDICA_INVESTIGACIONES.md](./BASE_JURIDICA_INVESTIGACIONES.md) — datos de personas en inteligencia.
8. [DPA_BORRADOR.md](./DPA_BORRADOR.md) — encargo art. 28 (borrador para abogado).

## Inventario PRE (estado real observado en repo, sin producción)

| Área | Hallazgo verificado en repo | Estado comercial |
|---|---|---|
| Producto | Inteligencia estratégica multi-tenant centrada en expediente (`StrategicDossier`) | Describible |
| Auth | Sesión cookie + CSRF; contraseñas Argon2id; sin MFA/SSO en código | Parcial |
| Aislamiento | RLS PostgreSQL + scoping de repositorio + RBAC por tenant | Capacidad de producto verificada |
| Auditoría | `AuditEvent` append-only; `AIAuditLog` con revisión humana de artefactos IA | Capacidad de producto verificada |
| Correo | Backends `capture` / `smtp` / `graph` (Microsoft Graph) configurables | Activación **por confirmar** por despliegue |
| IA | Fail-closed por defecto; modo `signal` gobierna tareas vía Signal/Ollama; cloud secundario no forzado desde Oracle | Parcial / configurable |
| Documentos | Módulo con retención, soft-delete, legal hold, storage local o S3; gates productivos | Feature gated |
| Backups | Scripts `pg_dump`, restore aislado, off-host opcional cifrado | Parcial; off-host y RPO/RTO de despliegue **por confirmar** |
| Exportación | CSV allowlisted con TTL y purge | Capacidad de producto verificada |
| Residencia de datos | No hay evidencia versionable de región operativa única | **Por confirmar** en due diligence de despliegue |
| Certificaciones | No hay ISO/SOC/ENS/certificados en repo | `not_available` |
| Readiness producción | Informe de seguridad y GO/NO-GO de release marcan límites vigentes | Ver `PRODUCTION_READINESS_STATEMENT.md` |

## Documentos del paquete

| Documento | Contenido |
|---|---|
| [DPA_BORRADOR.md](./DPA_BORRADOR.md) | Encargo de tratamiento (art. 28 RGPD) en borrador |
| [REGISTRO_ACTIVIDADES_TRATAMIENTO.md](./REGISTRO_ACTIVIDADES_TRATAMIENTO.md) | RAT orientativo |
| [SUBENCARGADOS_Y_RESIDENCIA.md](./SUBENCARGADOS_Y_RESIDENCIA.md) | Terceros y residencia |
| [PRIVACIDAD_RETENCION_Y_SUPRESION.md](./PRIVACIDAD_RETENCION_Y_SUPRESION.md) | Retención, export, supresión |
| [BASE_JURIDICA_INVESTIGACIONES.md](./BASE_JURIDICA_INVESTIGACIONES.md) | Personas físicas en investigaciones |
| [MATRIZ_CONTROLES_Y_ALEGACIONES.md](./MATRIZ_CONTROLES_Y_ALEGACIONES.md) | Controles y lenguaje permitido |
| [CUESTIONARIO_DUE_DILIGENCE_COMERCIAL.md](./CUESTIONARIO_DUE_DILIGENCE_COMERCIAL.md) | Q&A comercial |
| [PRODUCTION_READINESS_STATEMENT.md](./PRODUCTION_READINESS_STATEMENT.md) | Veredicto de aptitud por alcance |

## Validación local

```bash
python3 scripts/validate_legal_compliance_pack.py
```

El script comprueba presencia de documentos, encabezado obligatorio, metadatos de versión/owner/estado,
enlaces relativos, evidencia de filas `verified` y un scanner adversario de lenguaje absoluto prohibido.

## Qué no hace este paquete

- No implementa MFA, SSO, cifrado de disco, PITR ni controles de seguridad técnica nuevos.
- No consulta ni modifica producción, servidores, secretos ni datos reales de clientes.
- No nombra clientes, hostnames privados, IPs, credenciales ni rutas de secretos.
- No declara «apto para producción» de forma global.
- No sustituye el asesoramiento de un profesional del derecho.

## Propietario y mantenimiento

- **Owner del borrador:** equipo producto/operaciones OPN (hasta asignación de DPO o responsable de cumplimiento formal `[POR CONFIRMAR]`).
- **Revisión jurídica:** pendiente antes de envío a prospecto o firma.
- **Revisión de despliegue:** pendiente para rellenar campos `[POR CONFIRMAR]`.
- **Cadencia sugerida:** actualizar el paquete cuando cambien subencargados, finalidades, retención o el veredicto de readiness.

## Enlaces técnicos de apoyo (no cliente-facing por sí solos)

- [../security/READINESS_REPORT.md](../security/READINESS_REPORT.md)
- [../security/MULTITENANCY.md](../security/MULTITENANCY.md)
- [../operations/BACKUP_RESTORE.md](../operations/BACKUP_RESTORE.md)
- [../operations/AI_RUNTIME.md](../operations/AI_RUNTIME.md)
- [../operations/INCIDENT_RESPONSE.md](../operations/INCIDENT_RESPONSE.md)
- [../releases/v0.1.0-rc.1/GO_NO_GO.md](../releases/v0.1.0-rc.1/GO_NO_GO.md)
