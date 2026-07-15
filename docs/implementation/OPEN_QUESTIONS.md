# Preguntas abiertas

## Bloqueantes de fase

- Ninguna para completar auditoría y fundación Flask local.
- El contrato y repositorio reales de Signal Avanza quedaron confirmados el 11 de julio de 2026.
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
- Falta destino y política de retención de backups offsite; ya no bloquea UAT/despliegue rápido,
  pero sí debe cerrarse antes de operación estable con datos críticos.
- Falta proveedor/registry y estrategia de despliegue.
- Microsoft Graph está elegido: tenant/client IDs configurados y remitente previsto `info@opnconsultoria.com`; falta crear/materializar client secret y verificar `Mail.Send` application + admin consent.
- No registrar en este documento la contraseña SSH ya facilitada por el usuario.

## Producto y UX

- `CANONICAL_UI=vector` está resuelto.
- Definir cuándo retirar del árbol principal el concepto Horizon y si debe conservarse solo como referencia histórica.
- Confirmar si la densidad compacta/equilibrada/cómoda se persiste por usuario global o por membership/tenant.

## Signal Avanza

- Resuelto: productor `/Users/gitshell/PycharmProjects/opn_signal`, contrato `2026-07-01`, URL
  `https://signal.opnconsultoria.com/api/v1/oracle`, API key, scopes y allowlist de tenants.
- Resuelto: cursor opaco ligado a tenant/monitor, retención de 365 días y límite 1–200.
- Resuelto: HMAC-SHA256 V2 sobre `timestamp.raw_body`, tolerancia de cinco minutos y rotación con
  solape máximo de 24 horas.
- Resuelto el 2026-07-14: el consumer `opn-oracle` en Signal ya dispone de `entity:read`. Oracle
  producción verificó `/api/v1/entity-intel/graph` para
  `IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA` con respuesta 200, 50 nodos, 101 enlaces y
  `truncated=false`.
- Resuelto en Fase 4b: Oracle persiste snapshots PLACSP fijados al expediente en
  `dossier_procurement_items`, crea evidencia interna citable y alimenta el snapshot de
  `tender.v1`. Queda pendiente de producto la UI específica para seleccionar y fijar desde la lista
  de resultados.
- Resuelto el 2026-07-15: Signal tiene commiteados los lookups PLACSP por `folder_id` que Oracle
  necesita en runtime y el runbook de Oracle documenta el despliegue coordinado con backfill.
- Resuelto el 2026-07-15: el smoke público de Oracle cubre la presencia protegida de
  `entity-intel`, `procurement` y el redirect anónimo de la pantalla de grafo `/app/actors`.

## IA y compliance

- Pendiente definir región de datos, clasificación máxima, redacción y presupuesto permanente.
  Se ha autorizado diseñar `dossier_situation_summary` con Ollama `qwen3.5:9b` primario y OpenRouter
  `google/gemini-3.5-flash` secundario. La activación cloud sigue cerrada hasta resolver esos gates;
  el resto de tareas de `opn-oracle` conserva su política vigente.
- Resuelto en código en Signal: la task homóloga `dossier_situation_summary` dispone de
  catálogo/allowlist aislado, sanitización de `per_task_settings`, fallback elegible, límite de
  coste y propagación de proveedor/modelo reales. Sigue pendiente únicamente el E2E con consumer
  efímero y los gates de activación cloud indicados arriba.
- Política de redacción/PII, retención de prompts y respuestas, presupuesto y kill switch.
- Confirmar si la IA arranca deshabilitada en producción hasta aprobación formal.
- Confirmar requisitos ENS y retención/auditoría aplicables al primer release.
