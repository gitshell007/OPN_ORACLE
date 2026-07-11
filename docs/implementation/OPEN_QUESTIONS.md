# Preguntas abiertas

## Bloqueantes de fase

- Ninguna para completar auditoría y fundación Flask local.
- El contrato y repositorio reales de Signal Avanza son necesarios antes de habilitar el adapter HTTP.
- La política/proveedor IA son necesarios antes de permitir llamadas reales.
- La Etapa B de producción requiere revisión del inventario/plan y autorización explícita posterior; la Etapa A y los artefactos locales están preparados.
- La contraseña root expuesta debe rotarse/inutilizarse antes de cualquier despliegue; el hardening SSH necesita autorización separada y sesión de respaldo.

## No bloqueantes

- ¿Se migrará el frontend de la raíz a `apps/web` después de estabilizar `apps/api`?
- ¿Se requieren roles custom en el primer release o solo roles de sistema extensibles?
- ¿Se habilitará pgvector o bastará inicialmente PostgreSQL full-text?
- ¿Se necesita OCR en P1 o queda fuera del alcance inicial?
- ¿Se requiere MFA antes del primer release productivo?
- Revisar en la fase 04 si los accesos runtime a tablas globales de identidad deben reducirse mediante funciones o servicios SQL más estrechos.

## Credenciales e infraestructura

- Hostname, fingerprint SSH y DNS A ya fueron confirmados en la auditoría del 11 de julio de 2026; no existe AAAA.
- Let's Encrypt usa `info@opnconsultoria.com`; certificado y dry-run se verificaron el 11 de julio de 2026.
- Falta email/nombre del primer superadmin; su contraseña debe introducirse de forma interactiva.
- Falta destino y política de retención de backups offsite.
- Falta proveedor/registry y estrategia de despliegue.
- Microsoft Graph está elegido: tenant/client IDs configurados y remitente previsto `info@opnconsultoria.com`; falta crear/materializar client secret y verificar `Mail.Send` application + admin consent.
- No registrar en este documento la contraseña SSH ya facilitada por el usuario.

## Producto y UX

- `CANONICAL_UI=vector` está resuelto.
- Definir cuándo retirar del árbol principal el concepto Horizon y si debe conservarse solo como referencia histórica.
- Confirmar si la densidad compacta/equilibrada/cómoda se persiste por usuario global o por membership/tenant.

## Signal Avanza

- URL base, versión, auth, scopes y tenant mapping.
- Lifecycle exacto de monitor/task, cursor, límites y retención.
- Firma HMAC, tolerancia temporal, rotación y política de reintentos.
- Ubicación del repositorio Signal para ejecutar sus prompts en una sesión separada.

## IA y compliance

- Proveedor/modelos permitidos, región de datos y clasificación máxima autorizada.
- Política de redacción/PII, retención de prompts y respuestas, presupuesto y kill switch.
- Confirmar si la IA arranca deshabilitada en producción hasta aprobación formal.
- Confirmar requisitos ENS y retención/auditoría aplicables al primer release.
