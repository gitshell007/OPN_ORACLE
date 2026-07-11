# Mapeo provisional Signal Avanza ↔ OPN Oracle

**Estado:** propuesta de frontera anticorrupción; pendiente de validar con Signal  
**Última revisión:** 2026-07-10

## 1. Principios

- `StrategicDossier` es la unidad central de Oracle; Signal no necesita conocerla.
- `Watchlist` y `SignalMonitor` producen una configuración externa versionada.
- IDs de tenant, dossier y usuario de Oracle permanecen internos. No autorizan nada en Signal.
- IDs externos de Signal son opacos y siempre se relacionan mediante una `IntegrationConnection` tenant-scoped.
- El raw externo se conserva protegido; la representación normalizada se valida antes de entrar en el dominio.
- Hechos, inferencias, recomendaciones y decisiones permanecen separados.
- La cobertura de sources/tipos y los campos externos exactos están abiertos; no se simula soporte.

## 2. Watchlist/monitor Oracle → monitor Signal

| Oracle | Signal propuesto | Regla |
|---|---|---|
| `IntegrationConnection.id` | Credencial/account autenticado | Mapping interno; no se serializa como autorización |
| `SignalMonitor.id` | `client_monitor_id` | UUID opaco del cliente; correlación, no tenant |
| `SignalMonitor.external_id` | `id` | Lo asigna Signal y Oracle lo guarda scoped por conexión |
| `Watchlist.query` / términos | `query`, `keywords` | Normalizar espacios; límites externos por confirmar |
| entidades vigiladas | `entities[]` | `name` + `type`; taxonomía abierta |
| idiomas | `languages[]` | BCP 47 propuesto; confirmar variantes admitidas |
| geografías | `geographies[]` | ISO 3166/M49 propuesto; confirmar formato |
| tipos de fuente | `source_types[]` | Solo valores declarados soportados por Signal |
| cadencia | `cadence` | ISO 8601 duration propuesta; mínimos/máximos abiertos |
| estado local deseado | `status` | `active`, `paused`, `disabled`; transición asíncrona vía outbox |
| snapshot configuración | `config_version`, `config_hash` | Permite explicar qué vigilancia produjo una señal |
| suscripción callback | `callback_subscription_id` | Identificador opaco; nunca secreto |
| dossier/tenant/usuario | — | No se envían; Oracle conserva la relación interna |

Oracle mantiene por separado estado deseado y observado para no tratar un fallo transitorio de Signal como una edición de intención del usuario.

## 3. Señal Signal → `Signal`

| Signal externo | Oracle normalizado | Regla |
|---|---|---|
| `id` | `Signal.external_id` | Dedupe por conexión/proveedor + external ID |
| `monitor_id` | `SignalMonitor.external_id` | Resuelve monitor y tenant; no se confía en tenant del body |
| `type` | `Signal.signal_type` | Mapeo explícito; desconocido se conserva/aisla, no se fuerza |
| `title` | `Signal.title` | Texto plano, límites y sanitización |
| `summary` | `Signal.summary` | Texto/excerpt permitido; HTML se sanitiza o rechaza |
| `source.name` | fuente/provenance metadata | No implica credibilidad por sí solo |
| `source.url` | URL de evidencia/fuente | Validar esquema; no fetch automático no confiado |
| `source.published_at` | `published_at` | RFC 3339 UTC |
| `source.credibility_score` | metadata de proveedor | Conservar origen; no reemplaza score Oracle |
| `language` | `language` | Normalizar formato confirmado |
| `entities[]` | entidades/tags normalizados | No crea actores automáticamente sin triage |
| `tags[]` / `categories[]` | metadata normalizada | Taxonomías externas, no permisos ni decisiones |
| `content_hash` | `raw_hash` / hash proveedor | Validar prefijo/algoritmo; Oracle puede calcular hash propio |
| `observed_at` | fecha observada | UTC; semántica por confirmar |
| `created_at` | fecha de creación proveedor | No sustituye `ingested_at` de Oracle |
| `provenance.connector` | metadata de procedencia | Campo externo no confiable, se valida |
| `provenance.monitor_config_version` | versión de snapshot | Debe enlazar una configuración conocida o marcar divergencia |
| envelope/raw | almacenamiento raw protegido | Acceso restringido y retención acordada |

Una señal se enlaza a uno o varios expedientes mediante `DossierSignal`. La ingesta no crea directamente `Opportunity`, `RiskItem`, `Decision` ni `Task`; esas entidades nacen del triage y reglas de Oracle con evidencia y auditoría.

## 4. Tipos candidatos y cobertura

| Tipo canónico candidato | Significado para Oracle | Soporte Signal |
|---|---|---|
| `news` | Noticia o artículo | Abierto |
| `official_publication` | Publicación oficial | Abierto |
| `social_signal` | Señal procedente de red/social | Abierto |
| `company_signal` | Cambio o anuncio empresarial | Abierto |
| `market_signal` | Indicador o movimiento de mercado | Abierto |
| `regulatory_signal` | Norma, consulta o cambio regulatorio | Abierto |
| `tender_or_grant` | Licitación, ayuda o convocatoria | Abierto |
| `relationship_signal` | Relación o cambio entre actores | Abierto |
| `internal_document` | Documento autorizado del cliente | Abierto |
| `risk_signal` | Clasificación orientativa del proveedor | Abierto; no crea riesgo Oracle |
| `opportunity_signal` | Clasificación orientativa del proveedor | Abierto; no crea oportunidad Oracle |

Signal debe publicar cobertura real, conectores, licencias y tipos no soportados. Hasta entonces el mock puede ofrecer fixtures sintéticos, pero no representa cobertura productiva.

## 5. Estados y salud

| Signal | Oracle observado | Acción Oracle |
|---|---|---|
| `draft` | `pending` | Espera activación/reconciliación |
| `active` | `active` | Sync/webhook habilitados |
| `paused` | `paused` | Conserva histórico, no espera nuevos runs |
| `disabled` | `disabled` | No borra histórico |
| `error` | `error`/`degraded` | Error seguro, retry/reconcile según clasificación |
| valor desconocido | `unknown`/`degraded` | Conservar raw y alertar; no asumir activo |

La salud de conexión propuesta (`healthy`, `degraded`, `error`, `disabled`) es propia de Oracle y puede agregarse desde reachability, auth, backlog, sync y webhook. No se deriva de un único score externo.

## 6. Dedupe y procedencia

Orden de resolución propuesto:

1. conexión/tenant resueltos por credencial o suscripción;
2. monitor externo resuelto dentro de esa conexión;
3. event ID deduplicado en inbox para webhooks;
4. señal deduplicada por proveedor + external ID;
5. hash de contenido usado como segunda defensa y para detectar cambios;
6. nuevo/cambiado crea o actualiza vínculos `DossierSignal` idempotentes;
7. triage Oracle se encola fuera de la transacción de recepción.

El mismo evento por polling y webhook produce un único efecto. Un mismo contenido legítimamente asociado a varios monitores puede crear varios registros de ingesta pero debe converger en la política de identidad de `Signal` que se cierre con los contract tests.

## 7. Campos y decisiones abiertas

- taxonomía, obligatoriedad y límites de source types, entities, languages y geographies;
- formato de cadence y restricciones de scheduler;
- semántica de update parcial y concurrencia de `config_version`;
- schema definitivo de señal, nullability y política de enum desconocido;
- identidad de una señal compartida entre monitores/conexiones;
- diferencia entre `observed_at`, `created_at`, `published_at` e ingesta;
- algoritmo/formato de `content_hash` y canonicalización;
- reglas de licencia, excerpt y retención de raw;
- cobertura real de tipos y conectores;
- política ante versión de monitor desconocida o señal eliminada/corregida.

El adaptador HTTP real permanece desactivado hasta que estas decisiones críticas estén confirmadas o tengan una compatibilidad explícita documentada.
