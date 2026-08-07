# Privacidad, retención y supresión · OPN Oracle

> **BORRADOR · requiere revisión jurídica y validación del despliegue antes de enviar o firmar**

| Campo | Valor |
|---|---|
| Versión | `0.1.0-g21` |
| Owner | OPN · cumplimiento comercial (borrador producto) |
| Estado | `borrador interno · no contractual` |
| Fecha | 2026-08-06 |
| Base de código | `044e35a8ef696faf53d3d108387d0cbed06a99dc` |

## Regla de honestidad sobre plazos

Si **no** hay TTL o job de borrado real verificado, se marca **brecha contractual / unknown**.
**No se inventan plazos** para quedar bien en un RFP.

## 1. Reglas por categoría de datos

| Categoría | Retención en producto (evidencia) | Borrado / purge | Estado |
|---|---|---|---|
| Sesiones de usuario | Idle default 30 min; absoluta 12 h; remember idle 168 h / absoluta 14 días (`SESSION_*` en config) | Expiración y revocación de sesión | **Plazos de sesión verificados**; retención de filas históricas de `user_sessions` **unknown** |
| Tokens invitación / reset | Expiración por campo `expires_at`; se almacena hash | Uso único / revocación | Parcial verificado |
| Contraseñas | Hash Argon2id mientras la cuenta exista | Al deshabilitar cuenta no implica wipe automático de todo el historial | Cuenta: procedimiento admin |
| Contenido de expediente (dossiers, señales, actores, etc.) | **Sin TTL global de negocio verificado** | Borrado lógico/operativo según permisos y procedimientos; no hay política única documentada | **Brecha:** pactar en contrato |
| Documentos | `DocumentRetentionPolicy`: default código `retention_days=365`, `purge_grace_days=30`; `purge_after` tras soft-delete (+30d en servicio) | Task `maintenance.documents_retention` / `purge_due_documents`; **legal_hold** bloquea borrado | **Capacidad verificada si módulo activo**; feature gated |
| Exports CSV | `EXPORT_TTL_HOURS` default 24 | `purge_expired_exports` en mantenimiento | **Verificado** |
| Audit events | **Sin TTL verificado en código** | Append-only en runtime (no borrado por app ordinaria) | **Brecha / unknown** — no inventar años |
| AI artifacts / AIAuditLog | Sin política de retención global documentada como TTL | Revisión humana no borra historial de output (inmutabilidad de revisión descrita en runtime) | **Unknown** |
| Jobs / outbox | Operativa de workers; no es archivo de negocio | Recovery/stale jobs documentados en ops | Operativo |
| Logs de aplicación | Rotación/retención de host **por despliegue** | `[POR CONFIRMAR ops]` | needs_deployment_confirmation |
| Backups PostgreSQL | Default documentado ~30 días (`BACKUP_RETENTION_DAYS` / runbooks) | Rotación del script de backup | **Parcial**; off-host y destino por confirmar |
| Datos en Redis | Efímeros (sesión/cola/caché) | Pérdida de Redis no borra la fuente de verdad PG | Diseño documentado |

## 2. Exportación y devolución

| Capacidad | Qué hay | Límite |
|---|---|---|
| Exports CSV allowlisted | Datasets permitidos, columnas/filtros validados, job asíncrono, descarga firmada temporal, caducidad y purge | No es un «export GDPR one-click» de todo el tenant |
| Informes / PDF | Flujo de reporting del producto | Depende de permisos y features |
| Devolución al fin de contrato | Debe combinarse: exports disponibles + extracción operativa acordada (dump lógico acotado, etc.) | Procedimiento y formato **`[POR CONFIRMAR en contrato]`** |
| Portabilidad art. 20 | Asistencia razonable | Alcance exacto de campos = negociación + capacidad real |

Evidencia: `apps/api/src/opn_oracle/reporting/exports.py`.

## 3. Borrado al terminar el contrato

### 3.1 Lo que el producto permite hoy (parcial)

- Soft-delete y purge diferido de **documentos** (si el módulo está habilitado), respetando legal hold.
- Purge de **exports** caducados.
- Deshabilitar usuarios, revocar sesiones, archivar/suspender tenant a nivel de estado de modelo.
- Procedimientos operativos de demo hygiene (`scripts/demo_tenant_hygiene.py` y docs de ops) orientados a entornos controlados — **no** equivalen a un derecho de supresión contractual genérico.

### 3.2 Lo que **no** está cerrado como producto

| Elemento | Estado |
|---|---|
| Botón o job único «borrar todo el tenant y derivados» | **No verificado / not_available como flujo completo** |
| Purga automática de todas las filas de auditoría | **No verificado** |
| Borrado coordinado en backups (todas las copias) | Solo por rotación natural de retención de backup + procedimiento manual |
| Borrado en subencargados (correo, Signal, S3) | Requiere procedimiento por sistema **`[POR CONFIRMAR]`** |
| Certificado de destrucción | **`[POR CONFIRMAR plantilla operativa]`** |

### 3.3 Procedimiento propuesto (borrador operativo para legal)

1. T0: solicitud escrita del cliente / fin de contrato.
2. T0–T1: congelar accesos no esenciales; export acordado.
3. T1: borrado en sistemas activos (cuenta/tenant) según runbook **`[POR CONFIRMAR]`**.
4. T2: solicitud de borrado a subencargados aplicables.
5. T3: esperar rotación de backups o purga excepcional documentada.
6. T4: emitir constancia de ejecución (sin incluir datos de otros clientes).

**No firmar plazos ficticios** (p. ej. «30 días y desaparece de backups») sin que ops valide la retención real del despliegue.

## 4. Backups y logs

| Tema | Hecho de producto/docs | Implicación de privacidad |
|---|---|---|
| Backup local lógico | Scripts `backup-production.sh` con manifiesto y checksums | Las copias contienen datos personales del alcance del dump |
| Restore aislado | `restore-test-production.sh` en red/volumen efímeros | Pruebas no deben usar datos reales de cliente sin control |
| Off-host | Opcional, cifrado, default deshabilitado en docs | Si está off, el RPO off-site no existe |
| Logs | Redacción de secretos como objetivo de diseño | Pueden quedar IDs; retención de ficheros de log = host |

## 5. Legal hold

- Campo `legal_hold` en documentos: el soft-delete responde 409 si está activo.
- No hay un «legal hold global de tenant» documentado como entidad única.
- Conservación por litigio debe pactarse y aplicarse operativamente (incluidos backups).

## 6. Evidencias de ejecución (qué se puede enseñar sin secretos)

| Evidencia | Ejemplo |
|---|---|
| Config de TTL de exports | Valor `EXPORT_TTL_HOURS` del entorno (sin secretos) |
| Política de documentos del tenant | Filas de `document_retention_policies` (metadatos) |
| Jobs de mantenimiento | Nombres de tasks Celery de retention/purge |
| Backup | `MANIFEST.txt` / checksums / restore evidence (sin filas de datos) |
| Auditoría de borrados | `AuditEvent` de acciones de delete cuando existan |

## 7. Brechas a no maquillar en comercial

1. TTL global de datos de negocio y de auditoría: **no inventar**.
2. Erasure total de tenant: **parcial / procedimiento**, no feature completa.
3. Residencia y destino de backups: **por confirmar en despliegue**.
4. Documentos e IA: retención solo aplica si están habilitados.

## Enlaces

- [DPA_BORRADOR.md](./DPA_BORRADOR.md)
- [REGISTRO_ACTIVIDADES_TRATAMIENTO.md](./REGISTRO_ACTIVIDADES_TRATAMIENTO.md)
- [MATRIZ_CONTROLES_Y_ALEGACIONES.md](./MATRIZ_CONTROLES_Y_ALEGACIONES.md)
- [../operations/BACKUP_RESTORE.md](../operations/BACKUP_RESTORE.md)
