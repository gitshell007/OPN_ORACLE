# 34 — Ficha de entidad con grafo relacional (BORME/CNMV/EPO/noticias vía Signal) (P2, feature nueva)

> Lee `18_UX_REMEDIATION_OVERVIEW.md` (reglas comunes) y `AGENTS.md`. La parte de **datos ya está
> hecha y desplegada en Signal**; NO toques Signal: consume sus endpoints. Al terminar cada fase,
> despliega (D-022) y verifica en real. Feature grande: ejecútala **por fases con gate entre ellas**.

## Qué se construye

Una **«Ficha de entidad»** (empresa o persona física) para inteligencia de competidores/actores:
cargos e histórico registral (BORME), hechos relevantes (CNMV), patentes (EPO), noticias, y un
**grafo relacional interactivo** de vínculos con otras empresas/personas. No confundir con el
`StrategicDossier`: esto es una ficha 360º de una entidad externa, complementaria al expediente.

## Regla de arquitectura NO negociable (corrige el borrador original)

El navegador **NUNCA llama a Signal ni ve la API key** (AGENTS.md §2.2/§5: sin secretos ni
integraciones en el cliente). Todo pasa por **Flask**:

```
Vector (browser) → Flask /api/v1/entity-intel/* → Signal https://signal.opnconsultoria.com
```

- Nuevo módulo backend `apps/api/src/opn_oracle/integrations/entity_intel.py` (+ rutas): cliente
  HTTP server-side con host allowlist, timeouts, y traducción de los Problem Details de Signal
  (RFC 7807) a los errores de Oracle. Sigue el patrón de `SignalGovernedLLMProvider`
  (`ai/provider.py`) y la config existente: reutiliza `SIGNAL_AI_BASE_URL`/`SIGNAL_AI_ALLOWED_HOSTS`
  o define `SIGNAL_ENTITY_*` equivalentes con secretos vía allowlist `*_FILE` (D-009). La API key
  de `opn-oracle` y el `X-OPN-External-Tenant-ID` se inyectan **en el servidor**, derivando el
  tenant externo de la conexión Signal existente del tenant activo — nunca del cliente.
- Permisos: lecturas bajo `actor.read` (ya existe). Cache corta server-side (p. ej. 5–15 min por
  entidad/endpoint) para respetar el fair-use de EPO y no castigar a Signal; rate limit razonable.
- Endpoints proxy mínimos (mismos contratos que Signal, documentados en OpenAPI + cliente TS):
  `suggest`, `registry`, `graph`, `patents`, `disclosures`, `news`, `dossier`.

## Contratos de Signal (reales, verificados por el productor)

- Auth: `/api/v1/registry/*` → `X-API-Key`; `/api/v1/oracle/entity/*` → además
  `X-OPN-External-Tenant-ID` y scope `entity:read` (ya provisionado). Errores RFC 7807 con
  `retryable`.
- `GET /api/v1/registry/suggest?q=&kind=company|person&limit=10` →
  `{kind, suggestions:[…nombres registrales exactos…]}`. **CRÍTICO:** todo casa por nombre
  registral exacto («Iberdrola» a secas da 0). Flujo SIEMPRE: teclear → suggest → elegir nombre
  exacto → usar ese nombre en el resto.
- `GET /api/v1/registry/{company|person}?name=&limit=200` →
  `{items:[{company,person,role,action("nombramiento"|"cese"|"socio"),date,province,source_url}],
  companies, roles, total}`.
- `GET /api/v1/oracle/entity/graph?name=&type=company|person&depth=1|2&active_only=` →
  `{center:"type:norm", nodes:[{id,label,type,norm,is_center,degree}],
  edges:[{source(persona),target(empresa),role,roles,active,date}], truncated, note}`.
  `id` = `"company:<norm>"`/`"person:<norm>"`.
- `GET /api/v1/oracle/entity/patents?applicant=&since_year=` →
  `{available, reason?, total, items:[{pub_number,country,kind,date,title,applicants,ipc,url}], note}`.
- `GET /api/v1/oracle/entity/disclosures?issuer=` → `{items:[{nreg,link,pub_date,type,body,feed,
  feed_label,occurred_at}], errors, note}` (solo recientes).
- `GET /api/v1/oracle/entity/news?q=` → `{items:[{title,url,snippet,source,provider}]}`.
- `GET /api/v1/oracle/entity/dossier?name=&type=` → `{entity, sections:{registry,graph,patents,
  disclosures,news}}` con `ok` por sección (degradación independiente).
- Si un endpoint devuelve 403 `entity_service_disabled`, el servicio está deshabilitado en el
  admin de Signal (`/admin/oracle-entity`): muéstralo con copy honesto, no como error genérico.

## UI (Vector, español, denso y accionable)

- **Ubicación:** sección global **Actores** — añade una entrada «Buscar entidad» (buscador con
  autocompletado por `suggest`, selector Empresa/Persona) y ruta de ficha
  `/app/actors/entity/<type>/<norm>` (o querystring equivalente registrado en el registro tipado
  de rutas). Además, desde un actor de expediente cuyo nombre case, ofrece «Ver ficha registral».
- **Ficha con pestañas:** Perfil (identificación, provincia, nº de vínculos) · Órganos y cargos
  (tabla histórico: rol, acción, fecha, provincia, enlace fuente; **activo** = su acto más
  reciente no es `cese`; activos destacados vs cesados sin usar solo color) · Hechos relevantes
  (CNMV: tipo, fecha, enlace + aviso de que no hay histórico libre) · Patentes (nº, título,
  solicitantes, fecha, enlace Espacenet) · Noticias. Carga inicial con `dossier` (1 llamada);
  refrescos por sección con los endpoints individuales; cada sección degrada por separado (`ok`).
- **Grafo interactivo profesional** (nada de imagen estática):
  - Librería: el stack de AGENTS §13 lista React Flow, pero para un grafo de red con layout de
    fuerzas (~60–200 nodos) la herramienta adecuada es **Cytoscape.js + layout `fcose`**.
    Adóptala y **registra la decisión en `DECISIONS.md`** (desviación justificada: red relacional
    ≠ diagrama de flujo). Carga diferida (dynamic import) para no engordar el bundle global.
  - Nodos: color por tipo (empresa/persona) + forma o icono (no solo color, WCAG), tamaño por
    `degree`, nodo central (`is_center`) resaltado.
  - Aristas: etiqueta `role`; sólida = activo, discontinua = cesado; tooltip con `roles` + `date`.
  - Interacción: clic = panel lateral con detalle del nodo/arista; botón «Expandir» (nueva llamada
    `graph` centrada en ese nodo y fusión de nodos/aristas sin duplicar); doble clic = abrir la
    ficha de esa entidad; zoom/arrastre; filtros (solo activos → `active_only`, por tipo de cargo,
    por provincia); buscar/resaltar nodo; exportar PNG. Respeta `truncated` («grafo acotado a N
    nodos; expande manualmente»).
- **Límites SIEMPRE visibles** (vienen en los `note`): el grafo son vínculos de administración +
  socio único del BORME — **no** capital social ni % accionarial (deja un hook visual/copy para
  una futura fuente de pago tipo eInforma/Axesor/Orbis); CNMV solo recientes; homónimos BORME sin
  desambiguar (ofrece filtro por provincia/empresas); EPO bajo fair-use.
- **Puente al dominio Oracle (diferenciador):** desde la ficha, acción «Registrar como actor» /
  «Vincular a expediente» que reutilice el flujo existente de actores (crea o reutiliza el actor
  canónico, revisión humana, procedencia = ficha registral). Pequeño pero clave para que esta
  inteligencia alimente los expedientes.

## Fases con gate (verifica cada una en real antes de seguir)

- **F1:** proxy Flask (`suggest` + `graph`) + buscador con autocompletado + grafo básico
  renderizado. Verificación real: `suggest("IBERDROLA")` → elegir
  `IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA` → grafo ~60 nodos/107 aristas (dato probado por el
  productor). No des nada por hecho sin ejercitarlo contra Signal real.
- **F2:** endpoint `dossier` + ficha completa con las 5 secciones y degradación por sección.
- **F3:** expandir/fusionar, filtros, export PNG, panel lateral, «Registrar como actor», pulido y
  accesibilidad (teclado sobre lista de nodos como alternativa al canvas).

## Calidad y verificación

- Tests backend: cliente entity_intel con **mock determinista** (patrón MockSignalAvanzaAdapter),
  mapeo de errores 7807, cache y permisos; sin credenciales reales en tests.
- Frontend: Vitest de buscador/ficha/fusión de grafo (la lógica de fusión de nodos/aristas debe
  ser una función pura testeable); Playwright del flujo buscador→ficha (gated si no hay Signal).
- OpenAPI reexportado + cliente TS sin drift. `ruff format --check .` incluido.
- Documenta variables nuevas y actualiza `STATUS.md` por fase; decisión de librería en
  `DECISIONS.md`; si algo del contrato de Signal no cuadra en real, regístralo en
  `OPEN_QUESTIONS.md` y coordina con el productor (no lo parchees en silencio).

## Despliegue

Por fase: checks locales completos; **CI manual** (D-024) al menos en F1 (dependencia nueva y
superficie de integración) y F3; D-022 (backup local + restore aislado, release inmutable,
`oracle-control update`, smoke + health). Verificación funcional autenticada en producción con la
entidad IBERDROLA de arriba, sin errores de consola.

## No hacer

- Nada de llamadas del navegador a Signal ni API keys/tenant externo en el cliente.
- No scraping propio ni fuentes nuevas: solo los endpoints listados.
- No presentar los vínculos BORME como estructura accionarial.
- No convertir la ficha en un CRM: es inteligencia de entidad al servicio de los expedientes.
