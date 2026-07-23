# Preguntas abiertas

## Carrera CSRF al subir durante la carga inicial de documentos

- **Estado:** resuelta en Prompt 72 el 2026-07-23.
- **Evidencia:** Playwright obtuvo un token nuevo desde `/api/v1/auth/csrf` y lo envió sin cambios
  en el POST multipart, pero el servidor respondió `403 csrf_failed` cuando varias lecturas de la
  página de documentos seguían en vuelo. La misma subida pasa al esperar el estado cargado.
- **Causa confirmada:** la raíz no era una pérdida de escritura Redis. `GET /csrf` renovaba el token
  en cada lectura; dos lecturas seguidas invalidaban el primer token antes de la mutación.
- **Corrección aplicada:** la lectura de `/csrf` devuelve el secreto vigente de sesión y solo lo
  crea si falta. Login, reautenticación, cambio de contraseña y cambio de tenant siguen rotándolo.
  El E2E funcional ya no espera el empty state antes de subir documentos.

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
- Las pruebas backend marcadas como `integration` requieren PostgreSQL/Redis reales y, en el
  entorno estándar del agente, Docker disponible. Sin Docker local no se ejecutan de verdad fuera
  de CI; esto refuerza que el workflow `CI` de Pull Request no puede ser opcional antes de publicar.
- Los snapshots PLACSP fijados antes de Prompt 38 no contienen `documents` ni `is_ute`. No se hace
  migración automática para no reescribir evidencia histórica; si aparecen muchos expedientes
  afectados, decidir entre refijado manual, reparación administrativa por `folder_id` o backfill
  auditable desde Signal.
- ClamAV sigue pospuesto por decisión operativa. Mientras `DOCUMENT_ALLOW_OFFICIAL_UNSCANNED=true`
  esté activo, solo documentos oficiales PLACSP ya auditados pueden citarse sin antivirus. Retirar el
  flag y volver a exigir `DOCUMENT_SCANNER_MODE=clamav` en cuanto se despliegue el servicio.

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

- Pendiente de Signal/compliance para inteligencia competitiva: decidir si se autoriza Gemini vía
  OpenRouter como secundario, con clasificación máxima, redacción, presupuesto y conjunto explícito
  de errores recuperables. Oracle no cableará proveedor ni modelo por D-015. También falta un
  contrato demostrado para búsqueda booleana Y/O/NO, agrupación de expedientes y estimación de
  renovaciones; la UI no debe prometer esas capacidades hasta medirlas.

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
- Pendiente Signal: en la auditoría productiva del 2026-07-17 se observaron adjudicaciones de
  organismos distintos, entre ellos Renfe Viajeros y Aeropuerto de Teruel, cuyo campo de lote se
  mostraba como `LOTE A41050113`. Ese valor tiene forma de CIF/NIF de ITURRI, S.A. y no de número de
  lote. Oracle ya evita presentarlo como lote cuando llega en `lot_id`, pero queda pendiente revisar
  en Signal la serialización CODICE/PLACSP para confirmar el campo XML original y corregir el mapeo
  en origen. Los `folder_id` exactos no venían incluidos en el prompt 36 y deben extraerse de la
  búsqueda productiva que reprodujo el caso.
- Pendiente Signal/BORME: la ficha cronológica de Oracle solo puede mostrar los siete campos que
  Signal devuelve hoy (`action`, `company`, `date`, `person`, `province`, `role`, `source_url`). Si
  producto quiere reemplazar la visita al BOE para detalles como ampliaciones de capital, objeto
  social o texto completo del acto, Signal debe extraer y exponer ese contenido como contrato nuevo;
  Oracle no lo inventa. También falta un discriminador `counterpart_kind` en las consultas de
  empresa: `person` contiene tanto personas físicas como firmas (por ejemplo, ERNST & YOUNG SL).
  Hasta que Signal lo clasifique, Oracle muestra esas contrapartes sin enlace y no deduce el tipo
  por el nombre.
- Pendiente Signal para el informe competitivo ejecutivo: confirmar o actualizar en el
  administrador de Signal la `task_key` **`competitive_procurement_intelligence`** para el consumer
  `opn-oracle`, con salida JSON estructurada y `max_output_tokens=16000` para `v2`. Oracle declara
  ese presupuesto, pero las tareas gobernadas pueden ser pisadas por Signal; si Signal queda en
  5000, el informe de 1200-2000 palabras puede truncar con JSON incompleto. Oracle no cablea
  proveedores ni modelos para esta tarea y no se ha modificado el repositorio de Signal.
- Resuelto en Signal el 2026-07-18: `entity_dossier_intelligence` ya figura en el catálogo y en la
  política efectiva del consumer `opn-oracle`, con salida estructurada y presupuesto ampliado para
  informes largos de entidad. Queda pendiente únicamente validar desde una sesión Oracle que el
  flujo completo del informe de entidad ya no devuelve `task_not_allowed`.
- Resuelto en Signal el 2026-07-18: `dossier_completion_wizard` ya está dado de alta para
  `opn-oracle` con `ollama/qwen3.5:9b`, fallback `ollama_titan/qwen3.6:27b`, cloud cerrado,
  `json_mode`, `structured_output`, `require_explicit_task`, `max_output_tokens=3500` y
  `timeout_seconds=180`. Signal documenta smoke real contra `POST /api/v1/ai/run` con consumidor
  temporal Oracle y JSON válido; en este workspace se ha reejecutado la suite local de Signal con
  `577 passed`. Queda pendiente solo el E2E desde la UI/API de Oracle con sesión o fixture
  desplegado.

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
