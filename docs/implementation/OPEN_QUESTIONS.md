# Preguntas abiertas

## Aislamiento de sesión en gates largos con Redis local

- **Estado:** no reproducida tras limpiar Redis y repetir 528/528; mantener observación.
- **Evidencia:** tres recorridos completos del backend llegaron respectivamente a fallos aislados
  de autenticación tras más de 200 pruebas: doble lectura CSRF con 403, listado de sesiones con 401
  y descarga de informe desde un segundo cliente con 401. Cada prueba pasó al ejecutarse sola; el
  último recorrido completó 527 pruebas, una caída y 84,09 % de cobertura.
- **E2E relacionado:** el recorrido WCAG de escritorio perdió la sesión durante una navegación
  larga, mientras el mismo recorrido móvil pasó. Un reintento dirigido quedó en
  `/login?next=/app`.
- **Decisión de alcance:** no esconder la intermitencia ni cambiar autenticación dentro de la fase
  del grafo. Un recorrido limpio posterior pasó 528/528 y alcanzó 84,09 %. El CI del SHA exacto
  sigue siendo gate de publicación; si la reproduce, debe abrirse un prompt de aislamiento de
  sesiones y datos de test antes de desplegar.

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

- **Prompt 74 · contrato temporal v2:** Signal debe aceptar o ajustar
  `docs/integrations/signal-avanza/CONTRACT_V2_PROPOSAL.md`: `scope=active|historical|all`,
  publicación/plazo/adjudicación por rangos, orden estable, cursor/version del índice, estado
  canónico, métricas de cobertura y persistencia sin pérdidas de búsquedas guardadas. En v1,
  `active=false` significa todo el índice y no «solo inactivas».
- **Prompt 74 · cobertura de pliegos:** falta repetir desde Signal una muestra estratificada y
  reproducible por años que mida adjudicación → expediente/pliego. Oracle no dispone de credencial
  local de servicio y su proxy web no expone ese lookup. Hasta cerrar el gate, el histórico es
  award-céntrico y `scope=historical` de licitaciones permanece deshabilitado.
- **Resuelto en Prompt 76, Solo Oracle:** perfil determinista de empresa comparable y taxonomía CPV
  europea versionada, sin depender de v2, sin persistencia y sin LLM por adjudicación.
- **Resuelto en Prompt 78, Solo Oracle:** el wizard propone un plan dossierless, lo postvalida
  contra CPV/términos locales y solo una aceptación humana crea o versiona
  `ProcurementSearchProfile`. Preview y guardado no ejecutan IA; las vigilancias siguen siendo
  active-only. Capacidades y exclusiones son propiedad de este perfil; `profile_config` no las
  duplica.
- **Resuelto en Prompt 81, Solo Oracle:** el agregado comparable expone `measured_at` estable bajo
  caché; la taxonomía CPV se consulta mediante un autocomplete local acotado; los 422 de plan,
  aceptación, preview y guardado siempre incluyen rutas de campo; y el último artefacto devuelve
  su aceptación exacta (perfil, versión y fecha) sin inferencia de cliente.
- **Resuelto en Prompt 82, Solo Oracle:** el feedback de resultados, su digest y la retirada son
  deterministas y no llaman a IA; solo una replanificación explícita consume
  `tender_search_wizard`, revalida versión/digest y acepta v2 únicamente sobre el perfil objetivo.
- **Resuelto en Prompt 83, Solo Oracle:** vigilancia incremental de búsquedas `active` con memoria
  RLS por `folder_id`, huella material sin `feed_updated_at`, revisión/feedback explícitos,
  retención de 90 días y avisos agrupados sobre el scheduler durable existente. No introduce cursor
  ficticio, histórico ni llamadas LLM.
- **Pendiente Signal:** registrar/autorizar `tender_search_wizard` para el consumer productivo si
  Oracle usa `AI_MODE=signal`. El código funciona también en disabled/mock/ollama, pero Oracle no
  modifica unilateralmente el catálogo ni la allowlist gobernada de Signal.
- **Pendiente smoke Signal real:** ejecutar una búsqueda guardada y un barrido de vigilancia desde
  un entorno con `SIGNAL_AVANZA_MODE=http` y credencial del consumer. El entorno local mantiene
  `SIGNAL_AVANZA_MODE=mock` y `ORACLE_AI_MODE=disabled`, por lo que ningún resultado mock se
  presentará como verificación productiva.
- **Pendiente contrato v2:** declarar formalmente que `keywords` es hoy una subcadena literal
  contigua y sensible a tildes, o sustituirlo por una sintaxis booleana versionada. Oracle v1 usa
  sondas independientes y no concatena chips.
- **Pendiente calidad:** el modelo local real no igualó el recall combinado determinista de ITURRI;
  la UI debe presentar la propuesta como candidata y conservar los agregados medidos, no vender el
  LLM como mejora demostrada. La replanificación gobernada ya compara versiones con feedback, pero
  siempre mediante revisión explícita.

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
- Observación no bloqueante de roles: la UI ya hace visible cualquier categoría `other` y enumera
  su etiqueta canónica, pero ITURRI SA e ITURRIN SA no aportaron roles sin clasificar en la línea
  base productiva de Prompt 73. Antes de ampliar el catálogo debe medirse qué valores reales caen en
  `other`; no se añadirán alias ni categorías por semejanza del texto.
- Pendiente Signal para cobertura informativa real: `/api/v1/oracle/entity/news` continúa siendo
  una búsqueda web por nombre, sin fecha de publicación ni desambiguación de entidad. Oracle filtra
  de forma conservadora y no cita los descartes, pero una pestaña de noticias propiamente dicha
  requiere que Signal integre una fuente periodística con URL canónica, fecha, medio y contrato de
  identidad verificable. No se simularán fechas ni se usará IA para suplir ese contrato.
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

## Investigaciones empresariales trazables

- Producto autorizó iniciar la Fase 0 de
  `docs/product/INVESTIGATION_WORKBENCH_PROPOSAL.md`. ORACLE-EXP-INV-01 deja protocolo, arnés,
  fixture sintético, medición PLACSP/Ollama y borradores ERD/OpenAPI; no autoriza todavía
  migraciones, endpoints, task keys ni fuentes runtime nuevas.
- Pendiente medir en un spike la cobertura real de participantes no adjudicatarios. PLACSP
  estructura adjudicatario y el recuento comunicado de licitadores participantes, pero no
  garantiza una lista nominal completa; la identidad de admitidos, excluidos o perdedores puede
  residir solo en el perfil, actas, valoraciones y resoluciones. El diagnóstico vivo del
  2026-07-23 encontró 124/124 `TenderResult` con `ReceivedTenderQuantity` y cero nodos nominales de
  no adjudicatarios en una página 643, pero no es una muestra aleatoria. INV-02 ya congeló y sorteó
  96 unidades de 643/1044; queda etiquetar descarga, relevancia, contenido nominal, rol y lista
  reconciliable. Oracle no prometerá exhaustividad ni transformará «no localizado» en «no se
  presentó».
- Pendiente Signal: contrato incremental de participantes por expediente/lote, con documento,
  página/fragmento, rol y cobertura; y `counterpart_kind` fiable para no inferir por el nombre si
  una contraparte BORME es persona física o jurídica. Signal ya expone
  `ReceivedTenderQuantity` como entero nullable por adjudicación/lote; Oracle lo conserva sin
  sumarlo. El consumer temporal autenticado se creó y revocó correctamente, pero no hay endpoint
  inverso, no se ha reparseado histórico y el sondeo de 496 entradas no halló una revisión/versionado
  aprovechable. Producción sigue con cero adjudicaciones pobladas hasta planificar un backfill
  explícito `force=True` y cache-only.
- Pendiente etiquetado BORME: INV-02 enumeró 95.711 artículos, sorteó 72 antes del detector y
  preparó 192 candidatos. La segmentación exhaustiva doble ciego y la adjudicación de 72
  aserciones challenge siguen en 0/72; ningún `counterpart_kind` puede promoverse por nombre o
  sufijo.
- Pendiente documentos PLACSP: INV-03 congeló el core doble ciego de 24 unidades e intentó sus 145
  referencias. La repetición autorizada recuperó 130 PDF/DOCX; 125 dieron texto nativo y los cinco
  restantes ya dan OCR local candidato en 32 páginas (dos vacías), con SHA-256, página y revisión
  humana obligatoria. Su smoke alcanzó 17/18 schemas, 13/18 chunks estructurales y 4/4 merges, pero
  ninguna cita OCR sustituye verificación contra imagen/gold. ClamAV ya no es bloqueo del benchmark
  interno por D-065. Quedan cuatro errores HTTP, seis respuestas desconocidas y tres ZIP fuera del
  parser actual.
- Pendiente gold INV-03/04: las hojas A=96/B=24 existen vacías, pero siguen 0 completadas y 0
  adjudicadas. `qwen3.5:9b` por documento completo validó 6/10 schemas, 5/10 estructuras y cero
  aserciones. El chunking/merge ya tiene smoke real candidato con 12/12 schemas, 5/12 chunks
  estructurales y 2/2 merges finales válidos sobre dos documentos; ampliado después con `chunk/v1`
  a 18/18 schemas, 11/18 chunks estructurales y 4/4 merges finales válidos sobre cuatro documentos.
  El intento `chunk/v2` con múltiples citas y las ventanas literales de INV-06 empeoraron y se
  descartaron como extractor activo. La cuarentena ya puede revalidarse y reparsearse offline sin
  red; OCR local añade candidatos, no evidencia de igual fuerza que el texto nativo. Extractor
  candidato, reviewer bloqueante, promoción automática y métricas precision/recall continúan en
  `NO-GO` hasta gold. El pack A/B ya está preparado con índices opacos: 130 documentos disponibles
  en 16 expedientes, y estados `not_acquired` visibles sin sustitución. La acción pendiente no es
  técnica: etiquetado humano y adjudicación.
- Pendiente frontera D-028: decidir si Signal entrega un corpus exploratorio congelado y Oracle
  conserva solo manifest, hashes, extractos y fuentes promovidas, o si la investigación justifica
  una excepción explícita para retener payloads/PDFs completos con licencia, volumen, retención y
  borrado definidos.
- Pendiente decidir acceso autorizado, coste y condiciones de uso de notas/certificaciones del
  Registro Mercantil. No se automatizará vaciado masivo ni se sortearán autenticación, CAPTCHA o
  límites de fuente. El spike debe evaluar si compensa verificar de forma puntual los 5–10 nodos
  que sostengan tesis materiales, registrando licencia, fuente y coste por run, y medir qué campos
  aporta realmente una nota frente a la certificación probatoria.
- Pendiente compliance/DPO: finalidad, base jurídica, ponderación, información del artículo 14,
  derechos, retención y necesidad de EIPD para enlazar trayectorias profesionales de personas
  físicas entre fuentes. El workflow propuesto excluye vida privada, categorías especiales y
  decisiones adversas automatizadas.
- Pendiente benchmark local antes de elegir bandas de modelo, contexto y presupuesto. Oracle
  enviaría solo task keys gobernadas por Signal; si producto exige local, Signal fijaría Ollama y
  cloud desactivado para esas tareas. Debe medir también el reviewer con errores sembrados antes de
  elegir `reject_output`, reparación o bloqueo por sección; la validación determinista de citas no
  se delega al modelo. Primer microbenchmark resuelto: `qwen3.5:9b` con `think=false` logró 17/17
  schemas, cero reparaciones y p95 21,9 s, pero extracción exacta 0/4 y reviewer con 50 % de recall
  de categoría y un falso rechazo; `reject_output` y creación de participaciones quedan en no-go.
  Sin `think=false`, 34/34 llamadas agotaron salida y 0/17 schemas validaron. Pendiente abrir un
  cambio aislado del adapter local, ampliar corpus y medir el 27B, que no está instalado.
- Pendiente fijar la ventana temporal por finalidad y evidencia. No se adopta automáticamente un
  corte de cuatro años como política de relevancia, expansión o retención.
