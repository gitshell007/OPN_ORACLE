# 81 — Pagar la deuda visible antes del feedback (P1.5 · API + UX)

> Prompt de producto para Codex, **backend + frontend**. Cierra las cuatro deudas declaradas
> en el informe del prompt 80 (commit `d7b2885`) antes de abrir el P2 (feedback
> relevante/no-relevante y replanificación). Las cuatro están medidas hoy en `master`; no hay
> ninguna funcionalidad nueva de producto aquí — solo contrato, frescura y correlación. El P2
> construirá encima de esto, así que la calidad del cierre importa más que la velocidad.

## 1 — El perfil comparable no dice cuándo se midió

`measured_at` no existe ni en `ComparableProfileResponseSchema` ni en
`comparable_procurement.py` (verificado por búsqueda hoy). El perfil se cachea 6 horas por
tenant y empresa, así que el usuario puede estar mirando cifras de hace medio día sin
saberlo — y el paso 1 del wizard las presenta como actuales.

- Añade el instante de cómputo al payload del perfil (el momento en que se construyó el
  agregado, no el del hit de caché) y muéstralo en la UI del wizard y donde el perfil se
  pinte: «Perfil medido hace N horas». Con el TTL de 6 h, esa frase es la diferencia entre
  frescura honesta y frescura fingida.
- Mismo criterio que `cache_hit`/`cached_seconds` en el resto de endpoints de procurement:
  el consumidor siempre sabe qué está mirando y de cuándo es.

## 2 — Autocomplete CPV: la taxonomía es local, el navegador no la necesita entera

Medido hoy: `cpv_2008_es.json` pesa **499.613 bytes** (9.454 códigos). Enviarla al navegador
engordaría el bundle sin necesidad: la búsqueda debe ser un endpoint determinista de Oracle.

- Nuevo endpoint de sugerencia CPV (por prefijo de código y por subcadena de etiqueta, con
  el mismo folding de acentos que ya usa el tokenizador versionado), servido desde la
  taxonomía local — cero llamadas a Signal, cacheable, con rate limit y longitud mínima de
  consulta que tú decides y declaras.
- La UI lo consume en los chips CPV del wizard con el patrón de combobox accesible ya medido
  en `procurement-workspace.tsx`: sugerencias que ayudan, texto libre que no se bloquea, sin
  petición por tecla. Todo chip CPV muestra código + etiqueta; un código válido tecleado a
  mano que exista en la taxonomía queda etiquetado igual.
- Los códigos que no existen siguen el camino ya construido: descartados visibles, nunca
  silencio.

## 3 — Un 422 sin estructura es un contrato roto a medias

Medido en `procurement_search_profile_routes.py`: conviven
`_problem(422, detail=str(error), code="validation_error")` (línea 153, texto plano) con
respuestas que sí llevan `errors=` estructurado (líneas 141 y 274). Y los 422 del preview en
`procurement_routes.py` interpolan la excepción en `detail` con f-string. El prompt 80 tuvo
que pintar errores «cuando el backend los estructura» — ese «cuando» es la deuda.

- Unifica: **todo** 422 de plan, aceptación, preview y guardado lleva `errors` estructurado
  con la ruta del campo culpable (los `loc` de Pydantic ya la contienen; no la tires al
  convertirla en string). `detail` queda para humanos; `errors` para la UI.
- Documenta la forma en el contrato OpenAPI y actualiza el cliente y la UI del wizard para
  pintar el error sobre el chip o campo exacto en el 100 % de los casos, eliminando
  cualquier parseo de `detail` que haya quedado en el frontend.
- Test de contrato: cada ruta de validación de las cuatro superficies devuelve la forma
  unificada — un 422 de texto plano nuevo debe hacer fallar la suite.

## 4 — La correlación artefacto↔perfil debe sobrevivir a la sesión

Medido: `ProcurementSearchProfile.ai_artifact_id` existe con FK compuesta a
`ai_artifacts(id, tenant_id)`. La deuda declarada está en el viaje de vuelta y entre
sesiones: al reabrir el wizard en una sesión nueva, la UI no puede afirmar de forma
inequívoca si el artifact de `tender-search-wizard/latest` ya fue aceptado, en qué perfil y
como qué versión.

- Mide el hueco exacto y ciérralo por contrato, no por heurística de cliente: quien consulta
  `latest` debe poder saber si ese artifact tiene aceptación (perfil, versión) y quien
  consulta un perfil debe poder recuperar el artifact generador — con tenant scoping
  intacto en ambas direcciones.
- En la UI: al reabrir con un artifact ya aceptado, el wizard lo dice («Aceptado como v2 el
  23-07») y ofrece regenerar o revisar, en vez de presentar como propuesta fresca algo que
  ya es memoria. Nada de re-disparar generación en silencio (D-066 sigue).
- El diff conceptual plan-propuesto vs plan-aceptado ya es posible con las dos piezas; no
  construyas visualización de diff todavía — solo garantiza que las dos piezas son
  recuperables e inequívocas. La visualización llegará con la replanificación del P2.

## Verificación exigida

- Tests backend: `measured_at` presente y estable bajo hit de caché; sugerencia CPV por
  código y por etiqueta con folding; forma unificada del 422 en las cuatro superficies;
  correlación artifact↔perfil en ambas direcciones con aislamiento de tenant probado.
- Tests frontend: chip CPV etiquetado desde sugerencia y desde código manual; error 422
  pintado en el campo culpable sin parsear `detail`; estado «ya aceptado» al reabrir.
- **Cada test nuevo verificado por mutación**: di qué mutaste y qué test cayó.
- Gates completos de ambos lados, nombrados por separado: `ruff check`,
  `ruff format --check`, `mypy src`, suite backend con integración, regeneración de OpenAPI
  + cliente TypeScript sin deriva; `npm run typecheck`, `npm run lint`, `npx vitest run`,
  `npm run build`, y el spec Playwright del wizard en ambos breakpoints.
- Smoke visual con sesión real: frescura del perfil visible, autocomplete CPV en acción, un
  422 pintado sobre su chip, y la reapertura con artifact aceptado.

## Qué NO hacer

- No empieces el P2: ni `ProcurementSearchRun`, ni feedback, ni replanificación, ni diffs
  visuales de planes.
- No envíes la taxonomía CPV completa al navegador ni la dupliques en el frontend.
- No aflojes rate limits para «arreglar» la frescura o el autocomplete: presupuesto antes
  que excepciones.
- No conviertas la correlación en inferencia de cliente (comparar hashes en el navegador):
  es contrato de API o no es.
- No toques el agente, el prompt del wizard ni la evaluación: el gate de calidad del modelo
  real se cierra por su propia vía (registro de `tender_search_wizard` en Signal y re-run
  del harness), no en este prompt.
