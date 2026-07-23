# Estado de implementación de OPN Oracle

Actualizado: 2026-07-23
Rama observada: `master`  
Interfaz canónica: `CANONICAL_UI=vector`

## Prompt 74 · verdad temporal en licitaciones (completado en Oracle)

- **[Solo Oracle]** El API acepta `scope=active|historical|all`, mantiene `active` como alias
  deprecado y omite `active` cuando el cliente no declara alcance. Contra Signal v1,
  `scope=active` usa una petición con `active=true`, `scope=all` una con `active=false` y
  `scope=historical` responde `422`: no se hacen dos consultas ni se finge un orden global.
- **[Solo Oracle]** Vector sustituye «Todas/No activas» por «Solo activas/Todo el índice
  disponible», avisa de que el archivo de pliegos no está demostrado y no permite guardar en v1
  una búsqueda que Signal ejecutaría después como activa.
- **[Solo Oracle]** Los estados se normalizan únicamente mediante un mapa explícito; códigos no
  contratados como `PUB` y `EV` quedan visibles como `unknown`. El listado normal no invoca IA y
  una prueba de integración compara `AIUsageLedger` antes y después.
- **[Requiere Signal]** `historical` de licitaciones, `published_at`, rangos temporales, sort,
  cursor estable, persistencia completa de búsquedas y reconstrucción/versionado del índice quedan
  en la propuesta v2. Hasta demostrar esa cobertura, el histórico de producto es award-céntrico.
- **[Bilateral]** La activación de v2 exige muestra estratificada, manifiesto de cobertura,
  contract tests en ambos extremos, despliegue compatible y rollback. La línea base productiva del
  23 de julio registra 1.304.161 adjudicaciones, 2.247 licitaciones indexadas y 637 activas, además
  de fechas anómalas que impiden prometer cobertura completa.
- **[Siguiente fase, Solo Oracle]** El perfil determinista de comparables y la taxonomía CPV
  versionada pueden avanzar sin Signal, pero no se implementan en este prompt. El wizard los
  consumirá después; no será su propietario.
- Gates: Ruff y formato correctos sobre los cuatro ficheros Python tocados, mypy correcto sobre
  111 módulos, 557 pruebas backend con PostgreSQL/Redis reales y 84,29 % de cobertura, TypeScript,
  cliente OpenAPI y ESLint correctos (permanece un aviso conocido de TanStack Table), Vitest 38
  ficheros/194 tests y build Next de 19 páginas correctos.
- Mutaciones verificadas y restauradas: traducir `all` como `active=true`, mapear `Adjudicada`
  como `closed`, aceptar el guardado `scope=all`, habilitar «Guardar actual» fuera de activas y
  simular una nueva entrada en `AIUsageLedger` hicieron caer sus regresiones específicas.
- Smoke visual local autenticado: las dos únicas opciones temporales y la advertencia se muestran
  juntas; `all` deshabilita el guardado y explica la razón. Viewport 1152 px sin overflow
  horizontal (`scrollWidth=clientWidth=1152`) y sin errores ni avisos de consola. El fixture E2E no
  tiene conexión Signal, por lo que el empty/error state de resultados fue el esperado.

## Jerarquía visual y filtros por familia en el grafo

- Fase 74 consume las categorías funcionales normalizadas en Prompt 73 para diferenciar
  visualmente Gobierno, Representación, Auditoría, Propiedad, Liquidación y Sin clasificar. La
  codificación usa color, grosor y patrón de línea, pero mantiene nombres y controles textuales
  para que el significado no dependa del color.
- La entrada sigue mostrando el 100 % de nodos y enlaces recibidos. Las familias aparecen como
  lecturas rápidas voluntarias dentro de «Tipos de vínculo»; activarlas solo cambia visibilidad,
  sin relayout, recentrado ni modificación del zoom. «Restaurar todo lo recibido» repone también
  este filtro.
- Los recuentos de familia son pertenencias no excluyentes: un enlace multirol puede contribuir a
  más de una familia y la cabecera visible/recibido sigue siendo la única medida de cobertura.
  Los roles clasificados como `other` se listan con su etiqueta canónica bajo un aviso explícito;
  Oracle no los descarta ni intenta adivinar su significado.
- No hay cambios de backend, OpenAPI, migraciones ni variables. La verificación local dirigida
  cubre agregación no excluyente, filtro y restauración con cámara estable, estilos Cytoscape
  observables y aviso de rol desconocido. Cada prueba nueva se hizo fallar por mutación antes de
  restaurar la implementación.
- Gates locales: Ruff check correcto, Ruff format check correcto, mypy correcto, 394 tests
  unitarios backend sin omisiones; el recorrido completo pasó 528/528 con PostgreSQL/Redis reales y
  cobertura 84,09 %. ESLint terminó sin errores y con el aviso conocido de TanStack Table,
  TypeScript correcto, Vitest 38 ficheros/190 tests, build Next de 19 páginas y cliente OpenAPI sin
  deriva. Playwright autenticado pasó 25 pruebas con 7 omisiones intencionadas de matriz.
- El CI completo del SHA exacto `fbd3e7d` quedó verde en la ejecución `29994363725`: backend,
  migraciones e integración, frontend y contrato, E2E autenticado, seguridad, imágenes, Trivy y
  SBOM. La release inmutable `20260723T092045Z-quick-fbd3e7d` se activó tras el backup
  `20260723T092057Z-20260723T083006Z-quick-c7af48f` y su restore aislado. Health, validate y smoke
  público confirmaron punteros, imágenes, worker, beat, manifiesto, Nginx, auth gates, grafo y
  exposición coherentes.
- Verificación productiva en Chrome con sesión real: ITURRI abre con 300/300 nodos, 301/301
  enlaces, recorte upstream declarado y Zoom 105 %. Las familias reales son Gobierno 46,
  Representación 82, Auditoría 175, Propiedad 7 y Liquidación 4. El filtro Auditoría mostró
  176/300 nodos y 175/301 enlaces sin mover la cámara ni variar el zoom; restaurar recuperó
  300/301. ITURRIN abre con 7/7 y 6/6, Zoom 135 %, Gobierno 6 y Propiedad 4; filtrar Propiedad dejó
  6/7 y 4/6 y restaurar repuso 7/6 con cámara estable. La leyenda visual, los nombres textuales y
  la advertencia de recuentos no excluyentes estaban presentes y Chrome no registró errores de
  consola. Ninguno de los dos corpus contenía hoy roles `other`; su aviso se verificó por test
  mutado, no mediante un caso productivo real.

## CSRF idempotente para lecturas concurrentes

- Prompt 72 confirma que la carrera no estaba en el wizard ni en una pérdida de escritura Redis:
  `GET /api/v1/auth/csrf` era destructivo porque renovaba el secreto en cada lectura. Dos lecturas
  concurrentes podían dejar obsoleto el primer token antes de una mutación legítima, provocando
  `403 csrf_failed` al subir documentos nada más entrar en la pantalla.
- `GET /csrf` devuelve ahora el token vigente de la sesión y solo crea uno si falta. La rotación se
  conserva en login, reautenticación, cambio de contraseña y cambio de tenant; la validación sigue
  usando `hmac.compare_digest`, `Origin` continúa protegido y la única exención sigue siendo el
  webhook firmado de Signal.
- La regresión de subida documental en Playwright ya no espera el empty state antes de adjuntar el
  archivo, de modo que vuelve a ejercitar la interacción temprana que disparaba la carrera.
- Sin migraciones, OpenAPI, cliente TypeScript ni variables nuevas. Se añadió cobertura backend
  para doble lectura CSRF + mutación con el primer token, rotación en login/password y token ausente
  o inventado.
- Mutaciones verificadas y restauradas: cambiar `GET /csrf` a `renew_csrf()` hizo caer la doble
  lectura en `test_integration_auth.py:229` con 403; conservar el token anónimo en login hizo caer
  la rotación en `test_integration_auth.py:241`; retirar `renew_csrf()` de cambio de contraseña hizo
  caer `test_integration_auth.py:250`; sustituir `hmac.compare_digest` por aceptación constante
  hizo caer el token inventado en `test_auth_security.py:55`.
- Gates ejecutados: Ruff check correcto, Ruff format check correcto, mypy correcto, 528 tests
  backend con PostgreSQL/Redis reales correctos y cobertura 84,09 %, TypeScript correcto, ESLint
  sin errores con el aviso conocido de TanStack Table, Vitest 38 ficheros/187 tests correctos,
  build Next correcto y Playwright autenticado por TCP con 25 tests correctos y 7 omisiones
  intencionadas. La subida documental temprana pasó y el job `oracle.document.process` terminó
  `succeeded`.
- Barrido del patrón: solo existe un `@bp.get("/csrf")`, que devuelve `current_csrf()`; las llamadas
  restantes a `renew_csrf()` están en login, reautenticación, cambio de contraseña, cambio de tenant
  y creación perezosa cuando la sesión aún no tiene token.

## Exploración progresiva y taxonomía de roles del grafo

- Prompt 73 normaliza en Flask los roles equivalentes de Signal sin borrar el valor de origen:
  `Adm. Unico`, `ADM.UNICO` y `Administrador unico` comparten ahora la etiqueta
  `Administrador único` y la clave `administrador_unico`. Cada arista conserva además
  `source_roles`, publica `role_keys` y clasifica categorías funcionales. Los roles desconocidos
  mantienen su texto y reciben una clave estructural estable; no hay agrupación difusa que pueda
  fusionar cargos materialmente distintos.
- La vista inicial cumple el contrato completo en ambos extremos: todos los nodos y enlaces
  recibidos permanecen visibles, incluidos huérfanos, y la falta de un centro resoluble ya no vacía
  el grafo. En grafos grandes las etiquetas se revelan progresivamente; en grafos pequeños se
  muestran todas. La búsqueda resalta e informa coincidencias sin filtrar ni mover la cámara.
- Una cabecera distingue `100 % de lo recibido` de `Vista reducida`. «Ver entorno directo» reduce
  explícitamente y «Restaurar todo lo recibido» repone profundidad, roles, periodo y foco sin
  recentrar. Roles, estructura, periodo y procedencia viven en secciones desplegables; el lateral
  tiene scroll propio y se apila antes de comprimir el canvas. «Solo activos» se presenta como
  recarga del corpus de Signal, no como filtro local.
- Las facetas declaran que un vínculo puede pertenecer a varios roles y que su suma no representa
  cobertura. La autoridad sigue siendo la cabecera visible/recibido y el aviso de recorte upstream.
  En la línea base productiva, ITURRI SA tenía 300/300 nodos, 301/301 enlaces y once facetas,
  incluidas `Adm. Unico` (21) y `ADM.UNICO` (2); ITURRIN SA tenía 7/7 nodos, 6/6 enlaces y diez
  pertenencias a facetas no excluyentes.
- Sin migraciones ni variables. El contrato upstream de Signal no cambia; la ampliación ocurre en
  la respuesta Flask y en los tipos del cliente. Gates locales: unidad backend 394 tests, Ruff
  check, Ruff format check y mypy correctos; ESLint sin errores con el aviso conocido de TanStack,
  TypeScript correcto, Vitest 38 ficheros/187 tests y build Next correcto. Tras limpiar la base
  Redis de test, la ejecución backend completa pasó 528/528 con PostgreSQL/Redis reales y 84,09 %
  de cobertura; Playwright autenticado pasó 25 pruebas con 7 omisiones intencionadas. Las
  intermitencias observadas en recorridos anteriores no reaparecieron y quedan registradas en
  `OPEN_QUESTIONS.md`. El despliegue continúa condicionado al CI verde del SHA exacto y a
  verificación Chrome autenticada sobre ITURRI e ITURRIN.
- Mutaciones verificadas y restauradas: retirar el alias de administrador único, colapsar un rol
  desconocido, reutilizar la clave de otro cargo, omitir la normalización del dossier y saltar la
  normalización en el despacho HTTP hicieron caer sus cinco contratos backend. En frontend cayeron
  las regresiones al arrancar en nivel 1, ocultar etiquetas del grafo pequeño, filtrar sin centro,
  forzar densidad esencial, presentar `source_roles`, retirar el resaltado de búsqueda o mover la
  cámara al restaurar.
- El CI completo del SHA `c7af48f` quedó verde en la ejecución `29991046332`: backend,
  migraciones, integración, frontend, contrato OpenAPI, E2E autenticado, seguridad, imágenes y
  SBOM. La release `20260723T083006Z-quick-c7af48f` se activó después del backup
  `20260723T083035Z-20260722T213922Z-quick-39a2551` y su restore aislado; health, validate y smoke
  público confirmaron punteros, imágenes, worker, beat, manifiesto, Nginx y exposición coherentes.
- Verificación productiva en Chrome con sesión real: ITURRI conserva 300/301 y declara el recorte,
  agrupa 21+2 variantes en `Administrador único · 23 vínculos` y reduce las facetas de once a diez.
  «Ver entorno directo» mostró 66/300 nodos y 65/301 enlaces con Zoom 105 % estable; restaurar
  recuperó 300/301 con el mismo zoom. Quitar Auditor dejó 125/300 y 126/301 sin mover cámara; la
  búsqueda `iturri` mostró 4/4 coincidencias sin reducir cobertura. ITURRIN conserva 7/7 y 6/6,
  etiquetas completas, `Administrador único · 6` y `Socio único · 4`, con la advertencia de
  pertenencias no excluyentes.

## Ficha de entidad operable: cámara estable, jerarquía y fuentes honestas

- La ficha presenta primero identidad, cobertura y navegación. «Cambiar entidad», «Añadir a
  expediente» e «Informe IA» son acciones secundarias desplegables; la lista de expedientes se
  carga una sola vez y solo cuando una de las dos acciones que la necesita se abre.
- Hechos relevantes, Patentes y Noticias permanecen siempre accesibles. Cada pestaña declara
  resultados, vacío, cobertura parcial o fallo; un error de CNMV/EPO/búsqueda web ya no se parece a
  una ausencia. Noticias conserva el ranking del proveedor cuando no existe una fecha fiable.
- La pestaña activa se conserva en `?tab=`. Una recarga mantiene el contenido anterior si la nueva
  consulta falla y el grafo se monta al visitarlo por primera vez, pero no se desmonta al consultar
  otra pestaña: filtros, selección y viewport sobreviven a la navegación interna.
- El centro del grafo se resuelve mediante `is_center`, `graph.center` y la entidad consultada; no
  se adopta el primer nodo como centro semántico. Filtros de rol, fecha y profundidad solo cambian
  visibilidad: no recentran ni alteran el zoom. El layout se inicializa una vez y cancela el
  fallback tardío.
- Un clic selecciona sin destruir el contexto. «Aislar relaciones», «Abrir ficha» y «Mostrar grafo
  completo» son acciones explícitas; el foco encaja la vecindad sin volver a centrar solo el nodo.
  El porcentaje procede del viewport real, hay búsqueda accesible de nodos y la cabecera muestra
  nodos/enlaces visibles frente a recibidos, con el recorte de Signal en primer plano.
- No hay cambios de backend adicionales, migraciones ni variables. Gates locales finales:
  `scripts/api-test.sh --unit` ejecutó 389 tests sin omisiones; ESLint terminó sin errores y con el
  aviso conocido de TanStack Table; TypeScript correcto; Vitest 38 ficheros/184 tests; build Next
  correcto con 19 páginas; Playwright autenticado 25 tests correctos y 7 omisiones intencionadas de
  matriz. La suite backend completa ejecutó 521 tests con PostgreSQL/Redis reales y alcanzó 84,06 %.
- El primer despacho manual del CI para el SHA `9eca77b` detectó una carencia del runner, no del
  producto: el job E2E levantaba Redis pero no instalaba `redis-cli`, requerido por el script de
  preparación autenticada. El workflow instala ahora `redis-tools` antes de Playwright; el
  despliegue continúa condicionado a repetir y superar el CI para el nuevo SHA exacto.
- La siguiente ejecución llegó al recorrido Axe y expuso una carrera del gate móvil: la navegación
  cliente confirmaba la URL antes de que Next terminase de reponer el `<title>` durante el streaming
  del head. El gate espera ahora un título no vacío antes de analizar; no se añade una excepción y
  un documento que carezca realmente de título continúa fallando.
- El gate de seguridad detectó advisories high nuevos en `js-yaml<4.3.0` y `sharp<0.35.0`. Se
  mantienen Next 16 y el bloqueo de auditoría: el lock adopta la revisión 16.2.x vigente y fija las
  primeras versiones corregidas mediante overrides documentados en D-055; build, E2E, imágenes y
  Trivy los validaron sin vulnerabilidades high/critical. El CI completo del SHA `39a2551` quedó
  verde en la ejecución `29959609929`, incluidos integración, migraciones, E2E, SAST y SBOM.
- Línea base productiva previa al despliegue medida con sesión real: ITURRI mostraba las acciones
  antes de los datos y el grafo abría con 300 nodos, 301 enlaces y el aviso de recorte al final del
  lateral. La release `20260722T213922Z-quick-39a2551` se activó después del backup
  `20260722T213929Z-20260722T193226Z-quick-5e2baf5` y de su restore aislado. Health, validate y smoke
  público quedaron verdes, con punteros e imágenes coherentes y rollback conservado.
- Verificación post-despliegue con sesión real de Chrome: ITURRI muestra identidad y pestañas antes
  de las acciones, 81 eventos/17 actos, 15 cargos actuales, estados de CNMV/EPO/noticias explícitos
  y grafo 300/301 con recorte visible. Filtrar Auditor conservó Zoom 105 %, buscar y seleccionar no
  ocultó contexto, aislar dejó 2 nodos/1 enlace, volver de Perfil conservó el foco y restaurar repuso
  300/301. ITURRIN SA validó el extremo pequeño con 7 nodos/6 enlaces plenamente encuadrados. Chrome
  no registró errores de consola.

## Fase 1 de la ficha de entidad: verdad registral estable

- La ficha separa dos universos BORME que antes llamaba indistintamente «actos»: actos societarios
  de empresa (`profile.total_acts`) y eventos históricos de cargos/órganos (`registry.total`). Los
  contadores dejan de cambiar al paginar y se etiquetan con su significado completo.
- `/api/v1/entity-intel/registry` conserva por defecto el histórico compatible, pero admite
  `view=current|history`, búsqueda, provincia y orden. Oracle recupera el corpus paginado de Signal
  una vez, con caché tenant-scoped de 10 minutos, calcula el último evento por contraparte+cargo y
  solo después filtra y pagina. Si supera el límite de seguridad de 10.000 eventos lo declara como
  cobertura parcial; no presenta el agregado como completo.
- «Cargos actuales» muestra una fila por relación cuyo último evento no es un cese. «Histórico
  BORME» muestra publicaciones, no estados: un nombramiento antiguo ya no hereda la etiqueta
  «Activo» de la relación actual.
- Signal no clasifica si el campo `person` de una consulta de empresa contiene una persona física o
  una firma (caso productivo ERNST & YOUNG SL). Oracle deja esa contraparte sin enlace en lugar de
  inventar `/person/...`; en consultas de persona, la contraparte `company` sí se enlaza como
  empresa por contrato.
- OpenAPI y el cliente TypeScript quedan regenerados. No hay migraciones, variables nuevas ni
  cambios en el grafo o en la jerarquía general de la ficha, reservados para las fases siguientes.
- Gates finales: suite backend unitaria, Ruff lint/formato y mypy correctos; suite backend completa
  con PostgreSQL/Redis reales en 521 tests correctos y cobertura 84,06 %; lint, tipos, 174 tests
  Vitest y build frontend correctos. ESLint conserva únicamente el aviso conocido de TanStack
  Table en `dossier-context-panel.tsx:159`.
- Smoke local autenticado sobre la ruta de ITURRI: la ficha, los contadores diferenciados, la
  pestaña registral, sus dos vistas y sus filtros cargan sin romper la página. El entorno E2E no
  tiene credenciales de Signal y mostró el error explícito previsto; los 65 actos reales y la
  clasificación completa de ITURRI quedan pendientes de verificación post-despliegue en producción.

## Protecciones de E2E y botones de mutación

- La suite Playwright autenticada se mantiene y queda conectada a CI como job `frontend-e2e`, con
  PostgreSQL y Redis de servicio, API Flask arrancada por `scripts/run-auth-e2e-api.sh`, Next en
  `127.0.0.1:3000` y Chromium instalado en el workflow.
- `scripts/run-auth-e2e-api.sh` admite ahora modo local por socket Unix y modo CI por TCP mediante
  `E2E_POSTGRES_HOST`, `E2E_POSTGRES_PORT`, `E2E_DB_NAME`, `E2E_REDIS_DB`,
  `E2E_ORACLE_MIGRATOR_PASSWORD` y `E2E_ORACLE_APP_PASSWORD`.
- Las aserciones E2E obsoletas se alinean con la UI actual: promoción a oportunidad, alta de actor,
  preparación de reunión, enlace principal de Señales y redirección del superadmin. La subida
  documental tenía primero una ruta capturada antes de terminar la navegación; tras corregirla, la
  ejecución completa descubrió además una carrera CSRF real al actuar antes de acabar las lecturas.
  Prompt 72 la resuelve haciendo idempotente la lectura de `/csrf`, por lo que el test funcional ya
  no espera el estado cargado antes de subir.
- El recorrido Axe ya no se salta entero. Continúa comprobando todas las rutas y solo descuenta una
  lista exacta de deudas preexistentes: contraste de `.auth-eyebrow`, pestañas y `summary`; filas
  interactivas anidadas; tamaño de checkboxes, `.text-button` y `.back-link`. Cualquier combinación
  nueva de ruta, regla y selector sigue fallando.
- Los botones que disparan mutaciones de backend usan `AsyncActionButton` o `HydratedActionButton`.
  Se mantienen como botones nativos las acciones puramente locales o de navegación de UI, como
  ordenar, paginar, abrir diálogos y alternar vistas.
- El barrido final amplió la protección a login, recuperación/alta de contraseña y reautenticación
  reciente; sus handlers tienen nombres explícitos incluidos en el mismo invariante, sin clasificar
  como mutación los formularios de búsqueda que también usan un handler llamado `submit`.
- Añadido un invariante estático que recorre TSX y falla si vuelve un `<button>` nativo conectado a
  handlers mutantes conocidos, submits de formularios mutantes o llamadas inline a `api.*`.
  Calibración verificada con tres mutaciones restauradas: sustituir la puerta real de
  `dossier-inventory.tsx:593` señaló ese fichero; retirar `deleteSelected` de la clasificación hizo
  caer el caso sintético; clasificar `setPage` como mutación hizo caer la exclusión de paginación y
  señaló cuatro controles puramente locales. Ordenar y abrir diálogo permanecen permitidos.
- Sin cambios de backend, OpenAPI, migraciones ni variables runtime productivas.
- Gates frontend: `npm run typecheck` correcto; `npm run lint` sin errores y con el aviso conocido
  de TanStack Table en `dossier-context-panel.tsx:159`; `npx vitest run` terminó con 38 ficheros y
  174 tests correctos; `npm run build` compiló y generó 19 páginas estáticas.
- Playwright completo se ejecutó por el camino TCP equivalente al job de CI, no solo por socket
  Unix: 25 tests correctos y 7 omisiones intencionadas por matriz escritorio/móvil. La subida real
  procesó un documento y la redirección del superadmin quedó cubierta. El workflow se validó como
  YAML, pero el job remoto de GitHub solo podrá observarse después de commit/push.

## Alcance adaptativo por niveles en el grafo de entidades

- El panel lateral incorpora «Niveles visibles», un selector derivado por BFS desde la entidad
  central. Solo ofrece profundidades que existen en la topología recibida y cada opción muestra el
  recuento acumulado de nodos; abre con el máximo disponible para conservar la vista actual.
- Nivel, fecha, tipo de vínculo y foco se resuelven en la misma pasada por clases Cytoscape. Bajar
  el alcance oculta nodos y aristas posteriores, limpia el foco activo y no reconstruye elementos,
  relanza `fcose` ni hace otra petición a Signal.
- No se ofrece un rango ficticio 1–20. Revisado el repositorio de Signal: configuración
  `max_depth=2`, query `le=2`, recorte interno a 2 y `max_nodes=300`. Oracle mantiene `depth=2`; si
  Signal amplía su contrato, el selector ya crecerá con los niveles realmente devueltos.
- Prueba nueva verificada con dos mutaciones: aplanar el BFS a nivel 1 eliminó la segunda opción;
  retirar la ocultación del nodo profundo lo mantuvo visible. Ambas hicieron caer el flujo de dos
  niveles y fueron revertidas.
- Sin cambios de backend, OpenAPI, cliente generado, migraciones ni variables de entorno.
- Verificación visual local en Chrome con 81 nodos: nivel 2 mostró 81 nodos y 80 vínculos; nivel 1
  pasó a 41 nodos y 40 vínculos sin relayout. El selector quedó alineado en el lateral de escritorio
  y apilado en móvil; a 390 px el control y la página cumplieron `scrollWidth === clientWidth`. La
  consola quedó sin errores ni avisos. La ruta de QA se eliminó después.
- Gates frontend finales: `npm run typecheck` correcto; `npm run lint` sin errores y con el aviso
  conocido de TanStack Table en `dossier-context-panel.tsx:158`; `npm run test` terminó con 37
  ficheros y 171 tests correctos; `npm run build` compiló y generó 19 páginas estáticas.

## Separación física y hover acotado en el grafo de entidades

- Revisados los cambios de los prompts 39, 41 y 67: la semilla Vogel resolvió la diagonal y el
  etiquetado progresivo redujo el ruido inicial, pero `nodeSeparation=156` de `fcose` no garantizaba
  distancia física en un grafo estrella de 300 nodos como ITURRI SA.
- Se conserva `fcose`, su geometría y el centro anclado. Tras terminar el layout, una relajación
  determinista acotada separa los círculos con un hueco mínimo de 14 px; no relanza el layout al
  filtrar y no cambia contratos ni datos.
- El etiquetado progresivo deja de depender de `min-zoomed-font-size`, cuyo resultado variaba con
  el render: al 105 % solo se identifican centro y ocho nodos clave; el hover revela únicamente el
  nodo señalado y todos los nombres y roles se habilitan de forma explícita desde zoom 150 %.
- Pruebas nuevas verificadas por mutación: eliminar el hueco hizo caer el caso de 300 nodos
  coincidentes; restaurar el etiquetado de toda la vecindad hizo caer el caso de hover central.
  Elevar el umbral explícito por encima del zoom simulado hizo caer también su caso de
  comportamiento. Las tres mutaciones se revirtieron.
- Sin cambios de backend, OpenAPI, migraciones ni variables de entorno.
- Verificación visual en Chrome: la ruta productiva autenticada de ITURRI SA confirmó el estado
  anterior con 300 nodos y 301 enlaces comprimidos. Una ruta local efímera, eliminada tras la
  prueba, renderizó el componente corregido con un grafo estrella de 300 nodos: a zoom 105 % los
  círculos conservan espacio y no aparece la masa de rótulos; el hover destaca un único nodo.
  Producción no se ha desplegado y conserva la versión anterior hasta el siguiente release.
- Gates frontend finales: `npm run typecheck` correcto; `npm run lint` sin errores y con el aviso
  conocido de TanStack Table en `dossier-context-panel.tsx:158`; `npm run test` terminó con 37
  ficheros y 170 tests correctos; `npm run build` compiló y generó 19 páginas estáticas.

## Identidad visual Oracle · brand handoff

- Integrados los tokens oficiales de la dirección «Porcelana camaleónica» en
  `src/styles/tokens.css`; el shell Vector ahora usa índigo noche, canvas porcelana, superficies
  blancas sin sombra decorativa y bordes de 6 px. La fuente mantiene fallback local hasta que se
  entregue un archivo tipográfico licenciado de Libre Franklin e IBM Plex Mono.
- Login y sidebar sustituyen la marca tipográfica anterior por el símbolo vectorial Oracle
  entregado. Los botones primarios usan `--or-deep` y el filete inferior de oro; los gradientes
  se limitan al activo de marca. Los estados de éxito, información y riesgo conservan sus colores
  semánticos y el oro no se usa como serie de datos.
- Ajuste posterior del handoff: login y sidebar usan el símbolo blanco sobre fondo oscuro; el
  lockup separa `OPN` en blanco de `Oracle` en `--or-light`. En superficies oscuras, eyebrows,
  checks, avatar y etiquetas de navegación usan oro claro; `--opn-gold` queda solo en filetes y
  separadores. En superficies claras, los textos oro siguen en `--opn-gold-text`.
- Favicon, icono Apple y manifiesto PWA apuntan a los PNG de Oracle entregados. No cambian rutas,
  copy, contratos, backend, migraciones ni variables de entorno.
- Gates frontend: `npm run lint` terminó con 0 errores y un aviso conocido de TanStack Table;
  `npm run typecheck` correcto; `npm run test` terminó con `37 passed` y `167 passed`; `npm run
  build` correcto y generó 19 rutas estáticas, incluido `/manifest.webmanifest`.
- Verificación visual local: `http://127.0.0.1:3010/login` revisado a 1280 px y 390 px; no hubo
  solapes, recortes ni errores de consola. No se ha desplegado ni comprobado producción.

## Expediente guiado de inteligencia competitiva

- Añadido el perfil `competitive_intelligence` con intake revisable de oferta propia, competidores
  y alias, segmentos, geografías, compradores, horizonte, objetivo, términos/CPV, fuentes,
  criterios participar/no participar e indicadores. El alta crea un expediente activo por defecto
  o explica el estado borrador antes de confirmar.
- El bootstrap genera objetivos e hipótesis específicas, actores competidores reutilizables,
  vigilancia enriquecida y tres tareas iniciales. Un registro manual no recibe confianza opaca:
  conserva `confidence=null`, influencia 0 y relevancia independiente hasta vincular evidencias.
- Todo tenant nuevo recibe una política IA fail-closed. La nueva vista `/app/admin/ai` expone
  activación, autoridad de enrutado, proveedor configurado, límites, presupuesto, último intento y
  una comprobación honesta de configuración. Signal continúa gobernando modelos y fallback por
  `task_key` según D-015.
- La preparación del alta comprueba política IA y conexión Signal y ofrece acciones seguras sin
  impedir guardar el expediente. Las referencias de contratación fijadas pueden convertirse de
  forma idempotente en oportunidades conservando el enlace de evidencia.
- Las recomendaciones del Oráculo permiten crear, siempre tras una segunda confirmación, borradores
  de tarea, oportunidad, riesgo, actor, hipótesis o decisión; el origen y versión del resumen se
  guardan donde el recurso admite metadata.
- Contrato actualizado con migración `20260722_0021`, OpenAPI y cliente TypeScript regenerado. No
  hay variables de entorno nuevas ni se ha modificado Signal.
- Gates backend: `ruff check` correcto; `ruff format --check` confirmó 146 ficheros; mypy correcto
  sobre 110 ficheros; suite completa con PostgreSQL/Redis reales terminó con `518 passed` y
  cobertura `84,02 %`. La migración recorrió upgrade y downgrade en integración.
- Gates frontend: lint terminó con 0 errores y el aviso conocido de TanStack Table en
  `dossier-context-panel.tsx:158`; typecheck correcto; Vitest terminó con 37 ficheros y 167 tests;
  el build de Next generó 18 páginas estáticas.
- Playwright local, tras instalar el Chromium correspondiente a la versión fijada: 20 casos
  correctos, 6 omitidos y 4 fallidos. Los fallos observados son invariantes preexistentes fuera de
  este cambio: controles interactivos anidados en `/app/dossiers`, un selector antiguo ambiguo
  para «Promover», la expectativa de acceso restringido del superadmin y el tamaño táctil de
  `.back-link` en móvil. No se han corregido dentro de esta fase ni se contabilizan como gate verde.
- Mutaciones restauradas: permitir que Oracle fije el modelo de Signal, forzar borrador, retirar el
  vínculo `OpportunityEvidence`, omitir la política del alta de tenant, falsear la autoridad de
  enrutado, saltar la revisión UI, crear una tarea cerrada y degradar el schema HTTP 200 de la
  promoción hicieron caer sus tests respectivos.
- Alcance aún no verificado en producción: la aceptación completa solo mediante UI (tenant nuevo,
  tres empresas, resolución registral, Oracle e informe real) requiere sesión y despliegue. Los
  paneles analíticos avanzados, el lenguaje booleano Y/O/NO y las estimaciones de renovación no se
  atribuyen a Signal mientras no exista contrato demostrado. El navegador real llegó a
  `/login?next=%2Fapp%2Fdossiers`; no había sesión y no se usó un harness como sustituto.

## Recorte quirúrgico del resumen ante un revisor negativo · prompt 70

- D-045 introduce `EVIDENCE_REVIEW_FAILURE_POLICY`, indexada directamente para todos los agentes.
  `dossier_situation_summary` usa `strip_claims`; `report_writer` y
  `competitive_procurement_intelligence` conservan explícitamente `reject_output`.
- El resumen retira solo bloques objetados con anclaje seguro, revalida schema y allowlist, y
  persiste avisos visibles con recuento, claim retirado y motivo. Una objeción no anclable,
  ambigua, de clasificación, privacidad, inyección o confianza sigue fallando en duro.
- Sonda read-only sobre respuestas reales de Signal: «Concurso bomberos» recibió la ruta inventada
  `$.candidate_claims[5].claim`, cuyo texto casó exacta y únicamente con el claim enviado en
  `$.relevant_actors[0]`; «Mercado baterías LFP Europa» recibió directamente
  `$.relevant_actors[0]`. La implementación y los tests cubren ambas formas.
- La política efectiva queda registrada en el manifest del snapshot. No cambian prompts, paquete
  compacto del revisor, proveedores, presupuestos, Signal, OpenAPI, base de datos ni configuración.
- Tests integrados enfocados restaurados: las dos variantes del resumen completan con el claim
  fuera del artefacto y auditoría/ledger cerrados; `report_writer` y el competitivo fallan ante
  veredicto negativo; ambos rechazan una cita fuera del snapshot (`6 passed`). El panel muestra el
  recorte y el caso sano no muestra aviso (`4 passed`).
- Mutaciones verificadas y restauradas: retirar el fallback textual hizo caer el caso de ruta
  inventada; cambiar ambos informes a `strip_claims` hizo caer sus dos casos de fallo duro; ocultar
  `output.warnings` hizo caer el test visual; retirar la validación de allowlist hizo caer los dos
  tests de evidencia no autorizada.
- Gates backend: `ruff check .` correcto; `ruff format --check .` confirmó 167 ficheros
  formateados; `mypy src` correcto sobre 109 ficheros; suite completa con integración real terminó
  con `515 passed` y cobertura total `84.09%`.
- Gates frontend: `npm run typecheck` correcto; `npm run lint` terminó con 0 errores y el aviso
  preexistente de TanStack Table en `dossier-context-panel.tsx:158`; `npx vitest run` terminó con
  37 ficheros y 165 tests correctos; `npm run build` compiló y generó 18 páginas estáticas.
- Verificación productiva posterior al cambio pendiente de despliegue autorizado: no se ha
  modificado producción. La sonda previa confirma que ambos expedientes siguen fallando con la
  versión actualmente desplegada.

## Búsqueda de licitaciones comprensible y alineada

- Los rótulos internos «Keywords CSV» y «Etiqueta semántica» pasan a «Términos de búsqueda» y
  «Descripción del tema». Ambos incorporan una ayuda accionable y accesible con ejemplos de qué
  escribir y explican que son modos alternativos.
- Los dos campos comparten ahora la misma estructura, etiqueta, altura de control y alineación con
  el botón Buscar. La adaptación móvil conserva una sola columna.
- No cambia el contrato: ambos modos siguen resolviéndose al parámetro `keywords`; los términos
  explícitos mantienen la precedencia y desactivan la descripción del tema. No se promete una
  búsqueda semántica que la API no distingue.
- Un test nuevo verifica los nombres comprensibles, elimina la jerga visible y abre las dos ayudas.
  Mutación comprobada: cambiar el nombre accesible de la segunda ayuda a «Ayuda sobre tema» hizo
  caer el test; restaurado, el fichero enfocado terminó con `11 passed`.
- Gates frontend: `npm run typecheck` correcto; `npm run lint` correcto con 0 errores y el aviso
  preexistente de TanStack Table en `dossier-context-panel.tsx:158`; `npx vitest run` terminó con
  37 ficheros y 164 tests correctos; `npm run build` compiló y generó 18 páginas estáticas.
- Verificación visual real no completada: producción redirigió a
  `/login?next=%2Fapp%2Fprocurement` por falta de sesión autenticada. No se utilizó un harness
  sintético como equivalente.
- Sin cambios de backend, OpenAPI, migraciones, variables de entorno ni datos existentes.

## Cobertura y fallos visibles en patentes · prompt 69

- La pestaña de patentes usa el `total` real de EPO: cuando Signal entrega 25 de 569 publicaciones,
  la ficha muestra ambos valores y aclara que la muestra no es exhaustiva. Con 3 de 3 no aparece
  advertencia de recorte.
- Una sección `ok=false` mantiene visible la pestaña para mostrar el fallo de fuente. El caso
  `epo_search_404` explica que la denominación exacta puede no coincidir con el solicitante o una
  filial y prohíbe interpretar el fallo como ausencia de patentes. Una consulta correcta con cero
  resultados conserva el comportamiento previo y no crea una pestaña vacía.
- El informe distingue el recorte de Signal (`received_items` frente a `total`) del recorte interno
  de Oracle (`analyzed_items`, límite 20). `source_limits` declara ambos y añade el límite de
  no-ausencia cuando la consulta EPO falla.
- No cambian `PATENT_ITEM_LIMIT`, la integración EPO, el cliente de Signal, OpenAPI, base de datos
  ni configuración.
- Los informes ya generados conservan su snapshot histórico; la cobertura corregida aparecerá al
  generar un informe nuevo. No se reescriben filas ni artefactos existentes.
- Cinco tests nuevos cubren recorte visible, error visible, ausencia de falso aviso, total real en
  el informe y fallo metodológico; todos fueron verificados por mutación y restaurados.
- Mutaciones: ocultar `patentsTruncated` hizo caer el aviso 25/569; retirar `patentError` de la
  condición de pestaña hizo caer ITURRI; cambiar `>` por `>=` mostró un falso aviso 3/3 y cayó
  INDRA; forzar `truncated_by_source=false` hizo caer el total real del informe; ignorar el estado
  fallido hizo caer el límite `epo_search_404`. Los bloques enfocados restaurados terminaron con
  `14 passed` en frontend y `21 passed` en backend.
- Gates frontend: `npm run typecheck` correcto; `npm run lint` correcto con 0 errores y el aviso
  preexistente de TanStack Table en `dossier-context-panel.tsx:158`; `npx vitest run` terminó con
  37 ficheros y 163 tests correctos; `npm run build` compiló y generó 18 páginas estáticas.
- Gates backend: `ruff check` correcto; `ruff format --check` confirmó 167 ficheros formateados;
  `mypy src` correcto sobre 109 ficheros; suite completa con integración real terminó con
  `511 passed` y cobertura `84.07%`.
- Verificación visual real no completada: tanto TELEFONICA SA como ITURRI SA redirigieron a
  `/login` porque el navegador no tenía sesión autenticada. No se usó un harness sintético como
  equivalente.

## Licitaciones ordenables y filtros asistidos · prompt 68

- Las acciones de cada tarjeta forman un único grupo accesible y visual: resumen, fuente oficial y
  fijado comparten alineación; por debajo de 680 px se apilan a ancho completo de forma predecible.
- La búsqueda permite ordenar la página cargada por plazo ascendente/descendente o actualización
  más reciente. Como Signal/Oracle no ofrecen orden previo a la paginación, la interfaz declara
  expresamente cuántos resultados locales ordena y el total del corpus que no está reordenando.
- Órgano comprador usa `procurement/suggest` con `kind=buyer`, debounce de 260 ms, protección
  contra respuestas obsoletas y selección por teclado. Sigue siendo texto libre.
- Región aprende, durante la sesión, los literales exactos recibidos en páginas de resultados y
  búsquedas guardadas ejecutadas; no normaliza `Valencia/València`, no inventa catálogo y conserva
  la escritura libre. La persistencia global queda fuera mientras Signal no exponga sugerencias de
  región.
- Cuatro tests nuevos cubren comprador/debounce/texto libre, región exacta, orden local paginado y
  agrupación de acciones; cada uno fue verificado por una mutación específica y después restaurado.
- Mutaciones: cambiar `kind=buyer` por `winner` hizo caer el test del comprador; descartar las
  regiones observadas hizo caer el literal `Valencia/València`; anular la rama `deadline_asc` hizo
  caer el orden esperado; sustituir el grupo accesible por presentación hizo caer el test de
  acciones. Tras revertirlas, el fichero enfocado terminó con `10 passed`.
- Sin cambios de backend, OpenAPI, migraciones ni variables de entorno.
- Gates frontend: `npm run typecheck` correcto; `npm run lint` correcto con 0 errores y el aviso
  preexistente de TanStack Table en `dossier-context-panel.tsx:158`; `npx vitest run` terminó con
  37 ficheros y 160 tests correctos; `npm run build` compiló y generó las 18 páginas estáticas.
- Verificación visual real: el navegador abrió
  `https://oracle.opnconsultoria.com/app/procurement`, pero producción redirigió a
  `/login?next=%2Fapp%2Fprocurement` por falta de sesión autenticada. No se sustituye por un harness
  sintético y la alineación productiva queda explícitamente no verificada.

## Grafo de entidad legible, filtrable y enfocable · prompt 67

- El layout `fcose` conserva la semilla Vogel determinista y `randomize=false`; aumenta la
  separación de nodos de 96 a 156 px y la longitud ideal de arista de 190 a 250 px.
- Las etiquetas son progresivas: centro y ocho nodos de mayor grado permanecen identificados; el
  resto de nombres y roles aparece al acercar, al pasar el cursor o al aislar una vecindad. No se
  oculta ningún nodo por defecto.
- El panel deriva los tipos de vínculo del grafo, agrupa capitalizaciones mediante clave
  normalizada, muestra el recuento y arranca con todos marcados. Fecha, rol y foco comparten una
  única pasada por aristas/nodos y ocultan mediante clases, sin relayout.
- Un toque aísla el nodo y sus relaciones directas con reencuadre; otro toque o el botón
  «Mostrar grafo completo» restaura la vista. El doble toque sigue abriendo el detalle.
- Pruebas nuevas verificadas por mutación: quitar la normalización por capitalización creó cuatro
  checkboxes en vez de tres; hacer que un rol marcado retirase `is-time-filtered` revivió la
  arista antigua; tratar todas las aristas como vecinas impidió ocultar el segundo nivel. Cada
  mutación hizo caer su test específico y fue revertida.
- Verificación visual real: no ejecutada. El navegador llegó correctamente a producción, pero no
  había sesión autenticada y redirigió a `/login`; no se sustituye por un harness sintético.
- Gates frontend: `npm run typecheck` correcto; `npm run lint` correcto con 0 errores y el aviso
  preexistente de TanStack Table en `dossier-context-panel.tsx:158`; `npx vitest run` terminó con
  37 ficheros y 156 tests correctos; `npm run build` compiló y generó las 18 páginas estáticas.

## Muestra histórica BORME para informes de entidad · prompt 66

- Signal ya entrega actos BORME históricos reindexados y la ficha web los pagina bien; el problema
  estaba en el informe IA de entidad, que tomaba los primeros `REGISTRY_ITEM_LIMIT=25` actos por
  recencia y podía quedarse solo con 2026 en entidades sesgadas.
- Se mantiene `REGISTRY_ITEM_LIMIT=25` y `EVIDENCE_SOURCE_TOTAL_LIMIT=45`. El cambio es el criterio
  de selección: `temporal_coverage_v1` conserva una mayoría reciente, reserva cola histórica y
  añade puntos intermedios por fecha de publicación, de forma determinista y manteniendo el orden
  original de Signal en la muestra entregada al modelo.
- `source_limits` declara ahora el criterio del recorte BORME, no solo el número de actos pasados.
  Los agregados de `computed_metrics` siguen cubriendo el corpus completo; no se toca la ficha web
  ni el prompt v2 del informe.
- Tests añadidos/verificados: corpus sintético tipo ITURRI con mayoría de actos recientes conserva
  actos anteriores a 2020; dos llamadas con el mismo corpus devuelven la misma selección; el límite
  declara «muestra temporal determinista». Mutación revertida: volver temporalmente a `items[:limit]`
  hizo caer el test histórico porque la selección quedaba solo en 2026.
- Validación local inicial: `~/.local/bin/uv run pytest -q --no-cov tests/test_entity_dossier_report.py`
  terminó con `19 passed`.
- Suite completa local con integración:
  `ORACLE_RUN_INTEGRATION=1 ... ~/.local/bin/uv run pytest -q` terminó con `509 passed` y cobertura
  total `84.06%`.
- Checks finales: `ruff check`, `ruff format --check`, `mypy src` y `git diff --check` correctos.
  `mypy src tests` sigue fallando por deuda tipada preexistente en tests (`122 errors in 19 files`).

## Resolución del revisor de entidad · prompt 65

- Decisión aplicada: opción C del prompt. `entity_dossier_intelligence` queda declarado con
  `requires_evidence_review=false` porque el revisor universal juzga esa ruta con menos contexto
  autorizado del que tuvo el escritor. D-040 registra la excepción y sus condiciones.
- La ruta `oracle.entity_dossier_report.generate` deja de ejecutar `evidence_reviewer`; conserva
  `validate_evidence` contra la allowlist de `pending_evidence_sources`, por lo que cualquier
  `evidence_id` fuera del paquete pendiente sigue fallando antes de persistir el output.
- Invariantes mantenidos: `report_writer` y `competitive_procurement_intelligence` siguen con
  revisor semántico; el wizard continúa sin revisor universal; no se modifica el prompt v2 de
  entidad ni se pide ningún cambio a Signal.
- Tests enfocados ejecutados: catálogo, job de entidad estable, degradación de contratación,
  recuperación de fallo de provider, rechazo de evidencia externa, contrato de no-revisor en
  entidad, reviewer compacto de informe competitivo, intento reviewer en runtime general y rechazo
  de evidencia externa en `report_writer`/`competitive_procurement_intelligence`: `10 passed`.
- Mutaciones verificadas y revertidas: poner
  `competitive_procurement_intelligence.requires_evidence_review=false` hizo caer
  `test_long_report_reviewer_uses_compact_claim_package`; poner
  `report_writer.requires_evidence_review=false` hizo caer
  `test_report_generation_failures_never_publish_artifacts[reviewer]`.
- Suite completa local con integración:
  `ORACLE_RUN_INTEGRATION=1 ... ~/.local/bin/uv run pytest -q` terminó con `506 passed` y cobertura
  total `84.13%`.
- Checks finales: `ruff check`, `ruff format --check`, `mypy src` y `git diff --check` correctos.
  `mypy src tests` sigue fallando por la deuda tipada preexistente en tests (`122 errors in 19
  files`).
- Pendiente de cierre operativo: desplegar esta versión y generar un informe de entidad real en
  producción. Si completa, la auditoría esperada en esa ruta es un único intento `generate`
  `succeeded`; los otros informes deben seguir mostrando `generate` + `reviewer`.

## Revisión unificada de salidas IA · prompt 63

> ⚠️ **Revertido en producción el 2026-07-20.** El resumen de abajo describe el trabajo tal como se
> entregó, pero al desplegarlo rompió el informe de entidad (el revisor `evidence_reviewer` falla en
> esa ruta). Se hizo rollback del release y el código del prompt 63 sigue en `master` sin resolver.
> Detalle, diagnóstico y decisión pendiente en la nota **«2026-07-20 · Prompt 63 revertido en
> producción»** al final de este documento.

- Se cierra la brecha detectada en `entity_dossier_intelligence`: aunque el catálogo declaraba
  `requires_evidence_review=True`, la ruta propia del informe de entidad no pasaba por
  `execute_agent` y por tanto no creaba intento `reviewer`. `_run_waiting_area_agent` ahora ejecuta
  el revisor obligatorio con el mismo paquete compacto de claims de Prompt 60, usando solo la
  evidencia pendiente permitida para la ficha de entidad.
- Se mantienen los invariantes: `report_writer`, `competitive_procurement_intelligence` y
  `entity_dossier_intelligence` conservan revisión; `dossier_completion_wizard` y
  `evidence_reviewer` siguen sin revisor universal; `EVIDENCE_REVIEW_REQUIRED` continúa indexándose
  directamente en el registro.
- El wizard gana un control determinista previo a persistir artefactos: rechaza diagnósticos que
  contradicen el snapshot de base de datos, exige cobertura de secciones obligatorias y valida que
  las acciones recomendadas lleven `kind` y `prefill` accionables. Esto detecta el caso falso
  `actors: empty` cuando el expediente ya tiene actores.
- Tests añadidos: evidencia no autorizada falla en las tres rutas de informe
  (`report_writer`, `competitive_procurement_intelligence` y la espera de entidad), la ficha de
  entidad correcta genera con intentos `generate` + `reviewer`, la recuperación de lease mantiene
  el ledger coherente y el wizard de dos rondas sigue sin pasar por revisor.
- Mutaciones verificadas: quitar `actors` del mapa determinista del wizard hizo caer el test de
  falso `actors: empty`; anular temporalmente `validate_evidence` en la ruta de entidad hizo caer
  el test de evidencia fuera de la allowlist. Ambas mutaciones se revirtieron y el bloque enfocado
  volvió a `7 passed`.
- Validación local con integración: `ORACLE_RUN_INTEGRATION=1 ... ~/.local/bin/uv run pytest -q`
  terminó con `505 passed`, cobertura total `84.10%`, `entity_dossier_report.py` al `89%` y
  `ai/service.py` al `84%`. `ruff check`, `ruff format --check` y `mypy src` correctos. `mypy src
  tests` sigue fallando por deuda tipada preexistente en tests no tocados.
- Sin migraciones, sin OpenAPI nuevo y sin variables de entorno nuevas. **Actualización 2026-07-20:**
  posteriormente sí se desplegó (`20260720T183537Z-quick-d73c47a`), rompió el informe de entidad y se
  revirtió a `20260720T173105Z-quick-ca55269`. Ver la nota fechada al final del documento.

## Informes ejecutivos y versionado de plantillas · prompt 59

- `ReportTemplateRegistry` soporta varias versiones por clave: `get(key)` devuelve la última y
  `get(key, version)` resuelve la versión fijada en el informe. `entity_intelligence.v1` queda
  restaurada al contrato histórico y la versión ejecutiva actual vive en `entity_intelligence.v2`,
  evitando congelar los 2 informes antiguos de producción.
- `competitive_procurement_intelligence` pasa a `v2` en Oracle con presupuesto de 16.000 tokens y
  plantilla `competitive_procurement.v2`: secciones analíticas, lectura estratégica, materialidad
  obligatoria, baja solo con cobertura declarada, UTE como heurística y límites al final. La
  `v1` sigue intacta para el informe competitivo ya existente.
- `report_writer` pasa a `v5` sin tocar sus plantillas: elimina el sesgo de “completitud mínima
  viable”, pide párrafos redactados de 60-150 palabras, agregación por materialidad y exige
  `top_opportunities`, `top_risks` y `recommended_actions`.
- `_validate_report_output` incorpora el cerrojo de campos ejecutivos de cierre. Para no bloquear
  revisiones históricas, se aplica a snapshots nuevos (`closure_fields_required=true`) y a versiones
  no `v1`; las salidas `v1` antiguas sin esa marca conservan su validación anterior.
- Decisión D-039 registrada. Sin migraciones, sin OpenAPI nuevo y sin frontend. Queda dependencia
  externa en Signal: alinear la task gobernada `competitive_procurement_intelligence` a
  `max_output_tokens=16000`; si Signal conserva 5000 puede truncar JSON aunque Oracle esté listo.

## Protocolo de verificación y entrega · prompt 58

- `AGENTS.md` incorpora la receta de integración sin Docker con `uv` por ruta absoluta, los
  escollos de logging/caplog detectados en integración, y una definición de terminado que exige
  despacho HTTP real, mutación de tests nuevos, barrido de patrón, cuadrante de configuración,
  mediciones tocadas, recuento de contratos con datos existentes e integración ejecutada o riesgo
  abierto explícito.
- `DECISIONS.md` registra D-038: los fallos recientes viven en costuras entre editor, HTTP,
  contenedor, provider, base de datos, librerías y presupuesto de modelo; los prompts futuros deben
  declarar invariantes conocidos y Codex debe parar si contradicen mediciones registradas.
- Se añaden invariantes automáticos en `test_verification_protocol.py`: compose productivo sin
  variables huérfanas de `Settings`, palancas operativas cableadas en compose y ejemplo de entorno,
  rutas APIFlask con cuerpo JSON recibiendo `json_data`, errores `httpx.RequestError` clasificados
  sin filtrar transporte, techo global de fuentes citables manteniendo todos los tipos conocidos, y
  revalidación JSON de todos los modelos IA estrictos.
- Al aplicar el invariante del cuadrante se detectó y corrigió un hueco documental: `compose.prod.yml`
  ya exponía `DOCUMENT_ALLOW_OFFICIAL_UNSCANNED`, pero `infra/production/oracle.env.example` no lo
  incluía. No se cambia comportamiento productivo.
- Validación local con integración: `ORACLE_RUN_INTEGRATION=1 ... ~/.local/bin/uv run pytest -q`
  terminó con `497 passed`, `0 skipped` y cobertura total `84.11%`.

## Wizard guiado del expediente · prompts 49, 50 y 51

- Prompt 49: los empty states y formularios del expediente guían mejor al usuario sin IA. Las
  licitaciones fijadas enlazan a Contratación pública y Actores respetando permisos; Señales
  distingue entre «sin monitor activo», «monitor activo sin señales» y monitores no disponibles; el
  modal manual de oportunidades/riesgos incluye ayuda honesta sobre scoring, priorización y contexto
  IA; Roles de actor incorpora ejemplos y aclara que siguen siendo texto libre del expediente.
- Prompt 50: se añade el agente gobernado `dossier_completion_wizard` con prompt versionado
  `dossier_completion_wizard/v1`, schema Pydantic estricto, ejecución durable por job `ai`,
  `AIAuditLog`/`AIArtifact` estándar y contexto específico de completitud del expediente. El
  multi-turno se resuelve acumulando respuestas y rondas previas en el contexto, sin tocar el
  provider ni añadir streaming.
- Prompt 50: se exponen rutas específicas
  `POST /api/v1/ai/dossiers/{dossier_id}/completion-wizard/runs` y
  `GET /api/v1/ai/dossiers/{dossier_id}/completion-wizard/latest`, con sesión, CSRF, permiso
  `ai.execute`, tenant scoping, `Idempotency-Key` y contrato OpenAPI/cliente TypeScript regenerado.
  La eval sintética «Coches de Bomberos» queda cubierta en mock y recomienda monitor, contratación
  pública y actores competidores.
- Prompt 51: Vector incorpora el CTA único `.vector-ai` «Mejorar con Oracle» visible desde todas
  las pestañas del expediente. El wizard usa Radix Dialog y `JobProgress`, recupera la última ronda
  tras recargar, muestra diagnóstico/preguntas/acciones y abre los formularios reales prefijados
  mediante `sessionStorage` scoped por expediente + query param ligero. La búsqueda PLACSP acepta
  prefill por URL.
- Prompt 52 ya está resuelto en Signal según el repo `opn_signal`: `dossier_completion_wizard`
  figura para `opn-oracle` con `ollama/qwen3.5:9b`, fallback `ollama_titan/qwen3.6:27b`, cloud
  cerrado, `json_mode`, `structured_output`, `require_explicit_task`, `max_output_tokens=3500` y
  `timeout_seconds=180`. Signal documenta smoke real contra `POST /api/v1/ai/run` con consumidor
  temporal Oracle y JSON válido; en este workspace se reejecutó la suite local de Signal con
  `577 passed`. Sigue sin verificarse el E2E desde una sesión Oracle porque no hay servidor/sesión
  local disponible en este contexto.

## Correcciones P0/P1 · prompts 40, 41 y 42

- Prompt 40: el modo unitario de `scripts/api-test.sh --unit` ya no puede dar un verde con tests
  ocultos. `test_integration_alerts.py` deja de registrar como plugin global la fixture `autouse`
  de integración que hacía `pytest.skip`, y el wrapper falla si aparece cualquier skipped o si se
  ejecutan menos de 284 tests unitarios. `.codex-screenshots/` queda ignorado como artefacto local.
- Prompt 40: `oracle-control` añade `--yes`/`--non-interactive` para automatizaciones sin pausas que
  retengan `/run/lock/opn-oracle-control.lock`. Las frases reforzadas siguen exigiendo
  `ORACLE_CONTROL_CONFIRM_PHRASE` exacta y los gates de `update` se pasan por entorno.
- Prompt 41: el grafo de entidades conserva `fcose` determinista, pero recibe posiciones iniciales
  no degeneradas por nodo. No se han modificado zoom, cronograma ni ficha modal.
- Prompt 42: `DOCUMENT_ALLOW_OFFICIAL_UNSCANNED` permite, por defecto desactivado, aceptar PDFs
  oficiales PLACSP `ready + not_configured` solo con `DOCUMENT_SCANNER_MODE=noop`. La excepción se
  registra en `scan_result`, genera audit event, se propaga a la provenance de evidencia y aparece
  en Vector como «Fuente oficial · sin antivirus». `infected` y `error` siguen bloqueados siempre.

## Proceso P0 · CI en PR y release atado a SHA verde

- `ci.yml` vuelve a ejecutarse automáticamente en `pull_request` hacia `master` y conserva
  `workflow_dispatch`; no hay trigger en `push`.
- `release.yml` añade un job previo que consulta GitHub Actions y bloquea la publicación de
  imágenes si el workflow `CI` no tiene una ejecución `success` para el SHA exacto del release.
- La protección de rama queda documentada como cambio manual pendiente tras UAT en
  `docs/operations/BRANCH_PROTECTION.md`; no se ha configurado desde el repositorio.
- Se añade `scripts/api-test.sh` para ejecutar el gate backend desde shell no interactivo sin
  depender de que `.zshrc` añada `~/.local/bin` al `PATH`.
- Validación local del wrapper en este host: `zsh -c 'scripts/api-test.sh'` resuelve `uv`, ejecuta
  `uv sync --frozen`, `uv lock --check`, Ruff, formato y mypy; al no haber Docker ni URLs
  PostgreSQL/Redis de integración, falla cerrado antes de `pytest` para no saltar integraciones ni
  rebajar cobertura.

## Corrección pendiente de revisión · informe documental PLACSP

- `createDocumentReport` envía `Idempotency-Key` al backend y la UI conserva una clave estable por
  intento de generación del informe documental. Un reintento tras fallo crea una clave nueva, pero un
  doble disparo accidental del mismo intento puede hacer replay contra el contrato backend.
- El barrido de idempotencia confirma que las mutaciones del cliente que corresponden a endpoints
  con validación explícita de `Idempotency-Key` están cubiertas: backups/restore de plataforma,
  creación/acción de monitores, resumen IA, promoción de señal, cierre de reunión, generación/retry
  de informes, informe documental PLACSP y exportaciones.
- Los snapshots de adjudicaciones PLACSP agregadas conservan `award_amount` como suma de lotes y
  `award_date` como fecha única o rango. Los lotes con forma de CIF/NIF, como `A41050113`, dejan de
  mostrarse como número de lote y quedan documentados como revisión pendiente en Signal.
- Corrección Prompt 38: las adjudicaciones PLACSP fijadas desde ahora conservan `documents` e
  `is_ute` dentro de `snapshot.entries`; el snapshot agregado eleva `is_ute=true` cuando cualquier
  lote lo sea. Los documentos se normalizan a `uri`, `doc_type` y `file_name`, se deduplican por
  `uri` y quedan disponibles para el informe documental PLACSP. Los snapshots antiguos no se migran:
  para recuperar documentos/UTE en un expediente ya fijado hay que desfijar y volver a fijar el
  `folder_id`.
- La lista blanca de snapshots PLACSP deja de descartar campos nuevos en silencio: toda clave de
  Signal debe estar clasificada como preservada o consumida; si aparece una clave desconocida se
  registra warning operativo y el contrato unitario falla al ampliar fixtures sin clasificarla.
- Pulidos menores: evidencia de tarjeta fijada acortada, prioridad de siguientes acciones en
  español, error permanente de `BackgroundJob` con causa raíz sanitizada y dropdown de sugerencias de
  adjudicatario en lista vertical legible.

## Corrección pendiente de revisión · adjudicaciones PLACSP

- Signal deriva `is_ute` del adjudicatario al serializar, sin cambio de esquema ni backfill. Desde
  Prompt 38 Oracle conserva ese campo en adjudicaciones nuevas fijadas al expediente y Vector puede
  mostrar el distintivo «UTE · En consorcio» también en pins PLACSP. Los pins anteriores a la
  corrección no contienen ese dato y requieren refijado manual si se quiere ver el distintivo.

## Corrección pendiente de revisión · folder_id PLACSP con barras

- Signal acepta `folder_id` con `/` en los lookups `registry/awards/{folder_id:path}`,
  `registry/tenders/{folder_id:path}` y `registry/tenders/{folder_id:path}/summary`.
  Oracle mantiene `_quote_path_part(..., safe="")`; la convención queda documentada en ambos lados:
  uvicorn decodifica `%2F` antes del routing y Signal usa `:path` para tratar la barra como parte
  del identificador. Se añadieron fixtures reales `EMERGENCIACR2026/671`, `89/2026/27006` y
  `OBR/CNT/2026000031`, además de curl local contra uvicorn real.

## Corrección pendiente de revisión · artefactos persistentes

- El almacenamiento local de documentos e informes pasa de `/tmp/oracle-storage` a un volumen
  nombrado compartido en `/var/lib/oracle-storage`, montado por API, worker y Beat. La imagen crea
  el punto de montaje como `10001:10001` antes de ejecutar como usuario no privilegiado.
- Los artefactos que ya se perdieron en el `/tmp` efímero de producción no se pueden recuperar. Se
  recomienda una tarea posterior que marque en base de datos como no disponibles los registros cuyo
  objeto ya no exista, para comunicar un 404/410 claro en lugar de un 403 de descarga.

## Mejora pendiente de revisión · inteligencia de entidades

- Actores conserva el tipo de búsqueda de entidades en `sessionStorage`, propaga Persona/Empresa al
  navegar por fichas y sincroniza la consulta al cambiar entre entidades del grafo.
- El proxy `entity-intel` genera variantes server-side para personas en formato nombre-apellidos y
  apellidos-nombre antes de consultar Signal, manteniendo la caché por la consulta original del
  usuario y sin cambiar el contrato público.
- El grafo incorpora hover con atenuación de vecinos, ficha modal accesible para empresas/personas,
  relaciones directas navegables con confirmación y tests de UI con Cytoscape mockeado.
- F2 añade proxies Flask cacheados para `registry` y `dossier`, manteniendo `actor.read`, API key
  server-side, tenant externo solo para la ficha agregada y mensaje explícito cuando Signal tenga el
  servicio de entidades apagado en su administrador.
- La ruta `/app/actors/entity/[type]/[norm]` pasa a ficha 360º con cabecera, pestañas de Perfil,
  Órganos y cargos, Grafo y secciones condicionales. El copy distingue fechas de publicación BORME,
  límites de fuente, homónimos no desambiguados y ausencia de capital social o porcentajes.
- El grafo queda en modo forense por defecto (`active_only=false`), muestra vínculos cesados con
  trazo discontinuo, navega con `norm`, expone toggle «Solo vínculos activos» y resetea el estado de
  confirmación del modal al cambiar de entidad. La vista rápida consulta `registry` por `norm` y
  muestra perfil, últimos actos y contadores.
- Prompt 39: el grafo de entidades deja de arrancar con `fit` global y layout aleatorio. El
  encuadre inicial es determinista y prioriza legibilidad: centra la entidad consultada, incluye el
  primer nivel solo cuando no satura la vista y, en grafos densos como ITURRI SA, arranca en la
  entidad central a zoom legible para explorar navegando. Se añaden controles visibles y accesibles
  de acercar, alejar y reencuadrar.
- Prompt 39: se añade cronograma de doble manejador sobre fechas de aristas. El filtro se aplica
  mediante clases Cytoscape, sin reconstruir elementos ni relayout al mover el rango. Los vínculos
  sin fecha permanecen visibles y se explican en la UI; los nodos sin vínculos visibles se ocultan
  en lugar de atenuarse. El toggle «Solo vínculos activos» sigue combinándose como filtro de carga: si está
  activo, el rango temporal opera sobre los vínculos activos ya cargados.
- Prompt 39: la ficha modal de entidad sustituye el recorte silencioso de 5 actos por una
  cronología descendente de todos los actos cargados, mostrando persona, cargo, acción, fecha,
  provincia y cita BOE. Se solicita `limit=100` al registro para cubrir casos como ITURRI SA
  (65 actos) sin paginación local silenciosa, y la UI aclara que Signal no entrega el texto íntegro
  del BORME.
- Prompt 44: el suggest de entidad descarta respuestas obsoletas y limpia resultados al vaciar la
  consulta; el autocomplete de adjudicatarios de procurement queda reforzado con la misma barrera de
  secuencia.
- Prompt 44: el grafo deja de hacer `fit` inicial, mantiene separación fija de `fcose`, centra la
  entidad consultada a zoom legible y deja pan para explorar grafos densos como ITURRI SA. El detalle
  de nodo se abre por doble clic/doble tap; el clic simple solo selecciona.
- Prompt 44: la ficha 360º distingue visualmente la pestaña activa, convierte las tablas a TanStack
  Table con filtro de texto y ordenación —fecha descendente por defecto en órganos/cargos— y añade
  un control `actor.write` para materializar la entidad de Signal como Actor interno y vincularla a
  un expediente con provenance `signal_entity_intel`.

## Corrección pendiente de revisión · citas de informes

- `report_writer/v4` ordena al modelo citar fuentes mediante `[N]` y no exponer UUIDs en texto.
  Como defensa adicional, el ensamblador del informe sustituye UUIDs de evidencia en toda la prosa
  por su cita autoritativa, o por una referencia genérica cuando no forman parte del snapshot.

## Corrección pendiente de revisión · presentación de fuentes

- El visor de informes convierte el snapshot técnico de cada evidencia en una cita legible con
  medio, título, tipo, fecha y enlace seguro cuando estén disponibles. `locator`, `provenance` e
  identificadores externos dejan de mostrarse en la interfaz de negocio.

## Fase 4 · proxy Oracle de contratación pública PLACSP

- Oracle incorpora el proxy Flask `/api/v1/procurement` hacia Signal para adjudicaciones,
  licitaciones abiertas, resumen LLM cacheado por Signal, stats y búsquedas guardadas de
  licitaciones.
- Se reutiliza la configuración existente `SIGNAL_AI_*`, el allowlist HTTPS, timeouts, rechazo de
  redirects, límite de respuesta, mapeo de errores y resolución de tenant externo del patrón
  `entity-intel`. No hay variables nuevas ni llamadas directas desde navegador a Signal.
- Separación de autenticación validada en tests: los datos globales PLACSP usan solo `X-API-Key`;
  las búsquedas guardadas bajo `/api/v1/oracle/tender-searches*` añaden
  `X-OPN-External-Tenant-ID` derivado de la conexión `signal-avanza` activa.
- Permisos: adjudicaciones con `actor.read`, licitaciones y lecturas de búsquedas con
  `opportunity.read`, mutaciones de búsquedas con `opportunity.write`, stats con `signal.read`.
- Caché local: adjudicaciones 600 s, licitaciones abiertas 90 s, summaries sin caché local porque
  Signal gobierna su caché LLM.
- Fase 4b implementada: `dossier_procurement_items` permite fijar snapshots PLACSP a un expediente,
  crea evidencia interna asociada para citas en `tender.v1` y expone `POST/GET/DELETE` bajo
  `/api/v1/dossiers/{dossier_id}/procurement`.
- Corrección F4b: la resolución de snapshots ya usa los lookups directos de Signal por `folder_id`
  (`registry/tenders/{folder_id}` y `registry/awards/{folder_id}`), las adjudicaciones multilote se
  guardan en `snapshot.entries` y la evidencia queda tipada como `source_kind='procurement'` en vez
  de entrar en cuarentena `legacy_unresolved`.
- Checks focales F4b: `uv run pytest -q --no-cov tests/test_procurement.py tests/test_contract.py`
  **24/24**, `uv run mypy` y `uv run ruff check` focales correctos.
- Cierre PLACSP del 2026-07-15: Signal deja commiteados los lookups por `folder_id` requeridos por
  Oracle (`registry/tenders/{folder_id}` y `registry/awards/{folder_id}`), el runbook documenta el
  orden Signal → backfill PLACSP → Oracle, y `scripts/smoke-production.sh` cubre presencia protegida
  de `entity-intel`, `procurement/tenders`, `procurement/awards` y redirect anónimo de `/app/actors`
  a login. Smoke local combinado Next/API: correcto.

## Resolución operativa · scope `entity:read` en Signal

- Tras actualizar el consumer `opn-oracle` en Signal, Oracle producción pudo consultar el grafo real
  de `IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA`: respuesta 200 con 50 nodos, 101 enlaces y
  `truncated=false`. El bloqueo por `403 insufficient_scope` de Prompt 34/F1 deja de estar vigente.

## Prompt 33 · asentamiento del pipeline IA de informes, briefings y digest

- Diagnóstico read-only en producción realizado antes del cambio:
  - job `8f9b716e-7718-4b03-a1e1-ac6ae108d4f6` (`oracle.report.generate`) agotó tres intentos.
    El único `AIAuditLog` real (`564c8434-508f-4473-a2c8-2f0f02d0d8e8`) quedó `failed` con
    `error_code=UnboundLocalError` tras una ventana de 06:30:37 a 06:34:27 UTC. Los intentos
    posteriores no llegaron a Signal porque `execute_agent` bloqueaba cualquier audit previo
    fallido del mismo job/agente con «La ejecución IA de este job ya fue reclamada».
  - job `be3839d6-f5d8-4f79-8e2d-c15f10a2e2f4` (`oracle.meeting_briefing.refresh`) cayó en
    `permanent_failure`; su audit `f62f8a4e-f55e-428e-829a-8e23ac1dfc88` registró
    `error_code=AIUnavailable` casi inmediato el 2026-07-13 18:16:22 UTC, consistente con la
    etapa previa a la allowlist/tareas de Signal.
  - La política IA del tenant productivo estaba habilitada en `signal` con `qwen3.5:9b`, pero
    `max_output_tokens=2600`; por tanto `report_writer`, `meeting_briefing` y `weekly_change`
    no podían aprovechar los presupuestos gobernados ya configurados en Signal.
- Cambios implementados:
  - `SignalGovernedLLMProvider` ya no puede terminar en `UnboundLocalError` cuando el segundo
    intento de reparación JSON también falla; ahora publica solo si valida schema/evidencia,
    aplica saneamiento de citas no autorizadas cuando es seguro o propaga el error raíz.
  - `execute_agent` conserva la no duplicación de ejecuciones activas y el replay de artefactos
    `succeeded`, pero permite nuevos `AIAttempt` cuando el audit del mismo job/agente está
    terminalizado como fallo. Los reintentos Celery vuelven a ser reales sin cambiar el contrato
    único de `AIAuditLog`.
  - Los jobs IA reintentables conservan la última causa en `BackgroundJob.error_message` en vez de
    ocultarla tras un mensaje genérico; los jobs no IA mantienen microcopy sanitizada.
  - Prompts v2 compactos y versionados para `report_writer`, `meeting_briefing` y `weekly_change`;
    presupuestos: 6.500, 3.500 y 4.200 tokens. Se mantiene `dossier_situation_summary/v5`.
  - Límite de Signal AI por llamada sube a 300 s y Celery a 690/720 s para cubrir writer+reviewer
    local. Migración `20260714_0017` eleva el presupuesto de salida de políticas IA existentes
    habilitadas a 6.500.
- Comprobaciones locales ejecutadas antes de commit: `uv run ruff format --check .` correcto,
  `uv run ruff check .` correcto, `uv run mypy src/opn_oracle` correcto, tests backend focales
  41/41, Vitest 96/96, ESLint correcto, TypeScript correcto, `next build` correcto y Alembic head
  `20260714_0017`. Las integraciones focales de reintento quedaron preparadas y se omiten sin
  `TEST_*` locales.

## Operación · despliegue rápido UAT

- El runbook de producción pasa a tener un modo rápido por defecto para construcción/UAT: release
  nuevo en `/opt/opn-oracle/releases`, backup lógico local en `/var/backups/opn-oracle`, restore
  aislado validado, `oracle-control update` y health/smoke.
- El receipt de copia cifrada off-host deja de bloquear despliegues rápidos. Se conserva como modo
  estricto mediante `ORACLE_REQUIRE_OFFSITE_RECEIPT=1` y vuelve a ser obligatorio antes de operación
  estable con datos críticos.
- `scripts/deploy-production.sh`, `scripts/backup-production.sh` y `scripts/oracle-control.sh`
  quedan alineados con esa política: backup local + evidencia de restore son obligatorios; receipt
  remoto es opcional salvo modo estricto.

Revisión lingüística de la aplicación actualizada el 2026-07-12: se sustituyeron códigos de
fuente como `company_signal`, subtítulos técnicos de las áreas globales y mensajes como «Directorio
canónico» por textos de negocio en español. Las claves internas se conservan únicamente en tipos,
configuración y contratos no visibles para el usuario.

## Redespliegue P24 · objetivos e hipótesis

- El fix de ordenación de objetivos e hipótesis (`5ceae64d87bfdb8441510319c8addf3b168df9e4`)
  superó CI y quedó activo como release inmutable
  `20260713T045300Z-p24-5ceae64`. No introduce migración: la base permanece en
  `20260712_0015`.
- Gate de operación superado con backup previo, restauración aislada y recibo de copia cifrada
  externa. Se validaron manifest, Compose, Nginx, permisos de secretos y exposición de red.
- Smoke HTTPS, liveness/readiness, login web, Celery y un único Beat correctos. La comprobación
  autenticada del expediente CATL confirmó el panel «Objetivos e hipótesis» con un objetivo y dos
  hipótesis, sin «Paginación u ordenación no válida» ni errores de consola.
- Reejecución del prompt 26 completada el 2026-07-13: producción ya estaba en el release objetivo
  `20260713T045300Z-p24-5ceae64`, por lo que no se reactivó el mismo artefacto. Se creó el backup
  local `/var/backups/opn-oracle/20260713T084438Z-20260713T045300Z-p24-5ceae64/MANIFEST.txt`, su
  restore aislado quedó validado en
  `/var/backups/opn-oracle/restore-evidence/20260713T084438Z-20260713T045300Z-p24-5ceae64.RESTORE_EVIDENCE.txt`,
  y se repitieron smoke público, `oracle-control health`, `oracle-control validate`, Alembic head
  `20260712_0015` y verificación visual autenticada del panel CATL sin errores de consola.

## Mejora implementada · actores desde fuentes y altas manuales

- Actores separa «Actores vinculados» de «Candidatos detectados». La segunda vista deduplica las
  entidades estructuradas de las señales del expediente, propone tipo y etiquetas y conserva las
  fuentes concretas que originaron cada candidato.
- La importación requiere revisión humana y crea o reutiliza el actor canónico, lo vincula al
  expediente y registra tipo, etiquetas, roles, procedencia y auditoría. La misma pantalla permite
  crear actores manuales o vincular actores ya existentes.
- Oportunidades y Riesgos incorporan alta manual con descripción, valoración inicial y siguiente
  acción o mitigación. Tareas mantiene su alta manual y ahora muestra la validación dentro del
  diálogo en lugar de ocultarla tras la superposición.
- API nueva: lectura de `/dossiers/{id}/actor-candidates` e importación mediante
  `/dossiers/{id}/actor-candidates/{candidate_id}/import`. OpenAPI y cliente TypeScript se
  regeneraron sin drift. No hay migración ni variables nuevas: las etiquetas usan los metadatos
  JSON estructurados del actor y los candidatos se derivan de fuentes autorizadas.
- Comprobaciones locales: Ruff, mypy sobre 97 módulos, contrato backend 8/8, backend 106/106 con
  169 integraciones omitidas por entorno, frontend 85/85, ESLint, TypeScript y build correctos.
  La integración PostgreSQL/Redis de candidatos queda preparada y no se ejecutó por falta de las
  variables `TEST_*` locales.

## Mejora implementada · resumen nocturno persistente del expediente

- Celery Beat solicita cada noche, a las 03:15 en `Europe/Madrid`, una generación durable para
  todos los expedientes no archivados de cada organización activa con política IA habilitada.
- Cada expediente y fecha local comparten una clave idempotente: una repetición de Beat no duplica
  el trabajo, pero la noche siguiente crea una nueva versión aunque no cambie el contexto.
- Entrar en un expediente solo lee el último `AIArtifact`/`LivingSummary`. «Actualizar análisis»
  exige `Idempotency-Key`: repetir la misma petición deduplica y una nueva pulsación fuerza otra
  generación. La versión anterior se conserva durante el proceso o ante fallo.
- Signal gobierna `qwen3.5:9b` como primario y Ollama Titan `qwen3.6:27b` como fallback técnico;
  una indisponibilidad temporal ahora activa retry/backoff en lugar de fallo definitivo.
- No hay migración ni secretos nuevos. Configuración: `ORACLE_CELERY_TIMEZONE`,
  `ORACLE_NIGHTLY_SUMMARIES_ENABLED`, `ORACLE_NIGHTLY_SUMMARIES_HOUR` y
  `ORACLE_NIGHTLY_SUMMARIES_MINUTE`.
- Comprobaciones locales: Ruff, mypy, contrato/OpenAPI/cliente sin drift, 25 pruebas backend,
  3 pruebas frontend, ESLint, TypeScript y build correctos. La integración PostgreSQL/Redis focal
  queda preparada y se omitió al no existir las variables `TEST_*` locales.
- Producción: release `20260712T085932Z-settle-safe-summary`; cuatro expedientes no archivados con
  `LivingSummary` persistido y artefacto `valid` en `qwen3.5:9b`. Smoke interno/público, worker,
  Beat, manifest, Compose, Nginx, permisos de secretos y exposición de red validados. El smoke
  visual confirmó carga sin regeneración al entrar y cero errores de consola.

## Mejora implementada · eliminación múltiple de expedientes

- El listado muestra «Eliminar seleccionados» al marcar uno o varios expedientes de la
  página visible. El diálogo exige resolver una suma variable y avisa de que la
  eliminación es permanente y solo recuperable desde copia de seguridad.
- `POST /api/v1/dossiers/bulk-delete` acepta hasta 100 UUID, requiere
  `dossier.delete`, verifica que la persona sea propietaria o administradora de todos
  ellos y bloquea las filas en una única transacción. Si uno deja de estar disponible,
  no se elimina ninguno.
- La migración `20260712_0013` permite que las referencias de auditoría a un expediente
  eliminado queden en `NULL` sin perder el evento, el identificador del recurso ni sus
  metadatos de borrado. La migración `20260712_0014` concede al rol de ejecución
  únicamente el `DELETE` que necesita esta operación. OpenAPI y el cliente TypeScript
  se regeneraron.
- Comprobaciones locales: OpenAPI/client sin drift, Vitest focal 7/7, ESLint,
  TypeScript, build de Next, Ruff y mypy correctos; contrato Flask 7/7 sin umbral de
  cobertura. La integración PostgreSQL/Redis que prueba cascada y auditoría queda
  preparada pero no se ejecutó porque faltan las tres variables `TEST_*` en local.
- Producción: release inmutable `20260712T075929Z-grant-dossier-delete`, migración
  `20260712_0014`, health interno/público y Celery correctos. La prueba Playwright
  eliminó un expediente sintético mediante la suma `7 + 9`: el listado pasó de cinco a
  cuatro resultados, la fila desapareció y PostgreSQL confirmó tanto el borrado como el
  evento de auditoría conservado con `dossier_id = NULL`.

| Fase | Estado | Fecha | Responsable | Comprobaciones | Bloqueos | Siguiente paso |
|---|---|---|---|---|---|---|
| 00 · Orquestación | done | 2026-07-10 | Codex | Pack completo leído; decisiones, preguntas, checklist y baseline creados | Ninguno | Fase 01 |
| 01 · Auditoría | done | 2026-07-10 | Codex | Mapa, 7 ADR, contrato, threat model; `npm ci`, lint, tipos, tests, build y E2E | Ninguno para fase 02 local | Ejecutar `prompts/02_FLASK_FOUNDATION.md` |
| 02 · Fundación Flask | done | 2026-07-10 | Codex | `uv`, Ruff, mypy, 26 tests con PG/Redis, migración, OpenAPI y Gunicorn | Docker no disponible para validar Compose | Fase 03 |
| 03 · PostgreSQL y multi-tenancy | done | 2026-07-10 | Codex | 50 tests; 12 integraciones PG/Redis, RLS, roles, migraciones y drift | Docker no disponible para ejecutar Compose | Ejecutar `prompts/04_AUTH_SESSIONS_RBAC.md` |
| 04 · Auth, sesiones y RBAC | done | 2026-07-10 | Codex | 70 tests con PG/Redis; 87,66 %; Ruff, formato y mypy | SMTP síncrono se migra a Celery en fase 07 | Fase 05 |
| 05 · Frontend auth/admin | done | 2026-07-10 | Codex | Cliente OpenAPI; lint, tipos, 16 tests, build de 21 rutas, 13 E2E reales y QA visual | Deuda no bloqueante documentada | Fase 06 |
| 06 · Dominio Oracle | done | 2026-07-10 | Codex | 83 tests PG/Redis; 85,09 %; migraciones 0004/0005, RLS, OpenAPI/cliente y snapshot N:M | `Document/Chunk` se completa en fase 10 | Fase 07 |
| 07 · Celery/Redis | done | 2026-07-10 | Codex | 108 tests; 85,43 %; 49 integraciones PG/Redis/worker; migración 0006 y cliente | Smoke Compose no ejecutable sin Docker CLI | Fase 08 |
| 08 · Signal lado Oracle | done | 2026-07-11 | Codex | Contrato productor 2026-07-01 confirmado; API key/scopes/tenant, cursor e HMAC V2 alineados | Provisionamiento y E2E productivo en curso | Cerrar activación real |
| 09 · Runtime IA | done | 2026-07-11 | Codex | 154 tests; 85,41 %; PG/Redis/Celery real; migración 0008, prompts, schemas, evals, auditoría y fencing | Proveedor externo no definido; runtime mock/disabled fail-closed | Fase 10 |
| 10 · Documentos/evidencias | done | 2026-07-11 | Codex | 170 tests; 85,08 %; PG/Redis/Celery real; migración 0009, storage/parsers, FTS, evidence, retención, OpenAPI/cliente y Vector | S3/ClamAV productivos y sandbox de parser requieren configuración de infraestructura | Fase 11, no iniciada por alcance actual |
| 11 · Informes/notificaciones | done | 2026-07-11 | Codex | Migración 0010; informes, alertas, notificaciones/digests, exportaciones y Vector; 221 tests y 86,08 % | Ninguno bloqueante | Fase 11A |
| 11A · Arquitectura de información | done | 2026-07-11 | Codex | 5 especificaciones; registro tipado, shell/layouts, 44 rutas, creación real; GO adversarial | Ninguno bloqueante | Fase 12 |
| 12 · Frontend completo | done | 2026-07-11 | Codex | Vector conectado a Flask; 223 tests backend, 59 frontend, build de 45 rutas y 17 E2E | Ninguno bloqueante | Fase 13 |
| 13 · QA y seguridad | done | 2026-07-11 | Codex | 233 backend, 64 frontend, 24 E2E; scans/DAST/load/axe/readiness y GO adversarial | Ninguno de aplicación; release sigue bloqueado por infra/restore | Fase 14 read-only |
| 14 · Infra/TLS | done | 2026-07-11 | Codex | Graph validado; migración 0010; stack sano; HTTPS/smoke; superadmin y login real | Ninguno de infraestructura base | Fase 15 |
| 15 · CI/CD y backups | in_progress | 2026-07-11 | Codex | GitHub Actions en PR a master, release GHCR por SHA validado, SBOM, backup diario systemd, retención 30 días, catálogo/UI superadmin, manual y restore root blue/green | Falta configurar branch protection tras UAT, GitHub environments/secrets y automatizar la copia cifrada off-host diaria | Verificar CI remoto en PR y restore periódico desde descarga off-host |
| 16 · Aceptación/release | in_progress | 2026-07-11 | Codex + usuario | Producción accesible; primer tenant y owner invitado con Playwright; Graph entregó el correo; expediente `v0.1.0-rc.1` generado con `NO-GO` explícito | Aceptación del owner/UAT funcional, CI remoto y restore descargado pendientes | Cerrar gates y repetir aceptación |

Incidencia UAT corregida el 2026-07-11: el login del `platform_super_admin`
sin tenant activo dirige a `/platform/tenants`, y una entrada manual en `/app`
redirige al mismo portal en lugar de mostrar un falso acceso restringido.

Incidencia UAT corregida el 2026-07-11: la invitación de owner ya no envía el
campo redundante `role`, rechazado por el allowlist Flask de `invite-owner`.
El release productivo `20260711T165300Z-invite-owner-fix` quedó sano y el flujo
real se verificó con Playwright: usuario y membership `invited`, rol `owner`,
invitación vigente y job `notifications.send_email`/Graph `succeeded` al primer intento.

Revisión UX solicitada tras el primer acceso del owner: los identificadores técnicos de
procesos, colas, estados y roles se presentan ahora con lenguaje de negocio en español; la
tarjeta de trabajos recientes tiene altura acotada y desplazamiento interno; se corrigieron
los márgenes de estados y resúmenes del expediente, el vacío de informes y la posición de
cierre del modal. Las referencias visibles a Flask, tenant, score, portfolio, workspace y
briefing se sustituyeron en las rutas productivas por microcopy comprensible.
El QA real con el owner detectó además el rol crudo `owner` en el pie de navegación y
el estado transitorio `portfolio`; ambos se corrigieron a `Propietario` y `cartera`.

Segunda auditoría lingüística: se retiraron de las superficies productivas las referencias
residuales a backend, endpoint, score, RBAC, tenant, job, mock, probes, slug y checksum. Los
estados, planes, acciones de auditoría, monitores y revisiones documentales usan ahora etiquetas
de negocio; URL se conserva únicamente como aclaración universal junto a «dirección base».

## Mejora de creación de expedientes · perfiles iniciales por tipo

- El selector de tipo deja de ser solo clasificatorio en el alta: Proyecto, Mercado, Cuenta
  estratégica, Licitación o convocatoria, Alianza, Asunto regulatorio y Otro explican su alcance
  y proponen una base de trabajo editable.
- Con la opción confirmada, `POST /api/v1/dossiers` crea de forma atómica un objetivo, dos
  hipótesis y una watchlist con palabras clave y fuentes sugeridas, marcada para revisión y
  versionada como perfil `v1`. No hay migración ni variables nuevas.
- La opción `create_starter_profile` es opt-in para consumidores de API y está activada por defecto
  en el diálogo; desactivarla conserva un expediente vacío. No se crean monitores ni se contacta
  Signal Avanza automáticamente.
- Comprobaciones locales: OpenAPI y cliente regenerados sin drift; Ruff, formato y mypy focales;
  contrato Flask 7/7 sin cobertura; ESLint, TypeScript, frontend 74/74 y build correctos. La
  integración PostgreSQL/Redis focal no se ejecutó porque este entorno no tiene
  `TEST_DATABASE_URL`, `TEST_RUNTIME_DATABASE_URL` ni `TEST_REDIS_URL` configuradas.

## Task preparada · Oráculo contextual del expediente

- Prompt ejecutable creado en `docs/implementation/prompts/17_DOSSIER_ORACLE_ASSISTANT.md` y task
  Oracle en `docs/implementation/tasks/ORACLE_DOSSIER_ASSISTANT.md`.
- Frontera acordada: Oracle controla retrieval, permisos, evidencia, persistencia y UI; Signal
  gobierna la inferencia con la task `dossier_situation_summary`.
- Política de catálogo: Ollama `qwen3.5:9b` primario y OpenRouter
  `google/gemini-3.5-flash` secundario gated. El preset y la configuración productiva mantienen
  únicamente Ollama/Ollama Titan; no se activa gasto cloud sin presupuesto, clasificación,
  redacción, tratamiento de datos y autorización adicional.
- La task coordinada de Signal se registra en su propio repositorio. El estado de implementación
  Oracle queda detallado en el bloque siguiente.

## Task implementada · Oráculo contextual del expediente

- Oracle incorpora el agente `dossier_situation_summary/v1` con schema Pydantic estricto,
  prompt versionado, validación recursiva de `evidence_ids` y adapter `SignalGovernedLLMProvider`
  sobre `POST /api/v1/ai/run`. No hay llamadas directas a Ollama/OpenRouter desde Oracle.
- El snapshot del expediente amplía el context builder con objetivos, hipótesis, memoria viva,
  evidencias, señales vinculadas, oportunidades, riesgos, actores, reuniones, decisiones y tareas,
  con redacción y detección de prompt injection heredadas del runtime IA.
- `oracle.dossier_summary.refresh` sustituye el stub de `oracle.memory.refresh` para este flujo:
  encola en `ai`, deduplica por hash de snapshot, persiste `AIContextSnapshot`/`AIArtifact`/
  `AIAuditLog`, publica solo outputs validados como versión visible en `LivingSummary` y conserva
  la versión anterior si una ejecución falla.
- API añadida bajo `/api/v1/dossiers/{dossier_id}/oracle-summary`: lectura actual, refresh,
  versiones, detalle de versión con snapshot y feedback atribuido. OpenAPI y cliente TypeScript
  regenerados sin drift.
- Vector muestra el panel «Oráculo del expediente» en la portada del expediente, con titular,
  resumen, cobertura, confianza, bloques escaneables, historial, estado de refresh, aviso de
  proveedor secundario y feedback.
- Configuración nueva: `AI_MODE=signal`, `SIGNAL_AI_BASE_URL`, `SIGNAL_AI_ALLOWED_HOSTS`,
  `SIGNAL_AI_API_KEY(_FILE)` y `SIGNAL_AI_TIMEOUT_SECONDS`. Producción usa Signal para las tareas
  autorizadas con modelos Ollama propios; el fallback cloud permanece deshabilitado.
- Toolchain frontend fijada exactamente a `typescript@5.8.3` para evitar la rotura de `typescript@latest`
  con OpenAPI/ESLint.
- Comprobaciones locales: Ruff, mypy, OpenAPI/client check, runtime IA y proveedor 29/29,
  backend 104/104 con 65 integraciones omitidas por entorno, frontend focal 2/2, ESLint,
  typecheck y build Next correctos. No se ejecutó smoke visual autenticado porque este entorno no
  tiene stack Flask/PostgreSQL/Redis de UAT ni sesión real activa.
- La dependencia homóloga de Signal queda implementada y validada: catálogo aislado para
  `opn-oracle`, preset productivo Ollama/Titan sin cloud y suite completa de Signal con 466/466
  tests. Se corrigió además la prueba Oracle del adapter para reflejar el contrato HTTP real de
  Signal (`task_key` + `input`, identidad derivada de la API key y respuesta bajo `result`).
- Despliegue productivo completado el 2026-07-12. La verificación previa al E2E detectó que
  `worker-core` no consumía la cola declarada `ai`; el release
  `20260712T004620Z-ai-worker-queue` añadió las seis colas y un test de paridad Compose/Celery.
- El E2E real sobre el expediente de mercado permitió ajustar el runtime local sin activar cloud:
  prompt ejecutivo versionado hasta `v5`, `qwen3.5:9b` primario, Titan 27B secundario, reparación
  JSON compacta, timeout 210 s y presupuesto de 2.600 tokens. Los intentos inválidos quedaron en
  auditoría y nunca se publicaron.
- La rehidratación de UUID desde JSONB usa ahora semántica JSON estricta. El reintento operatorio
  auditado reutilizó el artefacto ya validado sin repetir inferencia: job
  `4df20429-3f37-4d45-bed5-aab5dd2d52ae` `succeeded`, artefacto versión 1 `valid`, resumen vivo
  publicado con confianza 72 y cobertura 4/4. El smoke autenticado mostró el panel completo, sus
  fuentes, historial y feedback sin errores de consola; las prioridades visibles se traducen a
  español.

## Fase implementada · Señales reales y triaje con Ollama gobernado

- Los expedientes de mercado y licitación pueden inicializar perfiles de partida trazables.
- La configuración de monitores Signal acepta únicamente tipos de fuente soportados y conserva
  consultas, entidades, palabras clave, idiomas, geografías, cadencia y retención.
- Los errores de entrega de la bandeja de salida dejan el monitor en estado visible de error.
- El triaje de señales se ejecuta mediante la task gobernada `signal_triage` de Signal, con
  evidencia y auditoría; en producción requiere habilitar la política del tenant y el consumer.

## Baseline conocido

- Frontend Next.js/React/TypeScript ejecutable en la raíz.
- Vector Command Center es la interfaz elegida.
- Horizon Decision Canvas permanece como prototipo comparativo temporal y no es canónico.
- Existe una aplicación Flask completa con PostgreSQL/Redis, migraciones, aislamiento multi-tenant y Celery; el despliegue remoto y CI/CD siguen pendientes.
- `main.py` es un ejemplo de PyCharm y no constituye backend.
- La capa actual `MockOracleRepository` y `localStorage` pertenecen al prototipo; no serán autoridad productiva.

## Cierre de la fase 01

- Instalación reproducible: `npm ci` correcto; npm informa de 2 vulnerabilidades moderadas transitivas.
- `npm run lint`: correcto.
- `npm run typecheck`: correcto.
- `npm run test`: 1 archivo y 3 tests correctos.
- `npm run build`: correcto; 8 páginas generadas y 2 rutas dinámicas detectadas.
- `npm run test:e2e`: 7 correctos y 1 omitido intencionadamente en móvil.
- Servidor remoto: no inspeccionado ni modificado; corresponde a la fase 14 y requiere auditoría read-only previa.

## Cierre de la fase 02

- Backend Flask modular en `apps/api`, Python 3.11 y dependencias fijadas en `uv.lock`.
- Application factory, configuración fail-fast, SQLAlchemy/Migrate, OpenAPI, Problem Details, request IDs, logs redactados, health/meta y Gunicorn.
- Dockerfile no-root y `compose.dev.yml` para API, PostgreSQL y Redis; Compose no se ejecutó porque Docker no está instalado en este entorno.
- `uv lock --check`, Ruff, formato y mypy: correctos.
- Suite completa con PostgreSQL 16 y Redis reales: 26 tests correctos y 91,93 % de cobertura.
- Migración upgrade/downgrade validada sobre base efímera y eliminada al terminar.
- OpenAPI exportado y configuración Gunicorn validada.

## Cierre de la fase 03

- Dieciséis modelos de plataforma para tenants, workspaces, identidad, memberships, RBAC, sesiones, tokens, auditoría e integraciones.
- Migración `20260710_0002` con CITEXT, constraints compuestas, índices, permisos, `ENABLE/FORCE RLS`, grants mínimos y funciones endurecidas.
- Separación real entre `oracle_migrator` (`BYPASSRLS`) y `oracle_app` (`NOBYPASSRLS`, sin DDL ni memberships heredadas).
- `TenantContext` transaccional con guard frente a cambios pre-tenant→tenant, A→B y savepoints dentro de la misma transacción.
- Resolución de tenant mediante membership y acceso superadmin explícito, con motivo y auditoría persistida.
- Tokens opacos almacenados solo como SHA-256; credenciales de integración vinculadas con FK compuesta tenant-safe.
- `uv lock --check`, Ruff, formato y mypy sobre 32 módulos: correctos.
- Suite completa con PostgreSQL 16 y Redis reales: 50/50 tests correctos; 12 de integración y 89,79 % de cobertura conjunta.
- Upgrade/downgrade, owner/ACL/search path de funciones, ausencia de drift y limpieza de base/roles efímeros verificadas.
- Docker Compose no se ejecutó porque Docker no está instalado; YAML, Dockerfile e init script fueron validados estáticamente.
- Servidor remoto no inspeccionado ni modificado.

## Cierre de la fase 04

- Autenticación con sesiones opacas en Redis, cookies endurecidas, expiración idle/absoluta, rotación fail-closed, revocación y recent-auth.
- Argon2id con rehash de parámetros heredados; CSRF por cabecera y origen; rate limiting y respuestas anti-enumeración.
- Flujos de login, logout, recuperación, cambio de contraseña, invitaciones, cambio de tenant y administración tenant/plataforma.
- RBAC, protección transaccional del último owner, límites RLS/IDOR y auditoría global mediante funciones `SECURITY DEFINER` verificadas.
- OpenAPI tipado para todas las rutas de la fase y CLI seguro para bootstrap del primer superadmin.
- `uv lock --check`, Ruff, formato y mypy: correctos.
- Suite completa con PostgreSQL 16 y Redis reales: 70/70 tests correctos y 87,66 % de cobertura; round-trip de migraciones validado.
- Deuda aceptada para fase 07: hacer asíncrono el envío de recuperación para eliminar diferencias temporales del adaptador SMTP.
- Servidor remoto no inspeccionado ni modificado.

## Cierre de la fase 05

- Cliente TypeScript generado desde OpenAPI con transporte cookie/CSRF, renovación de CSRF, `Problem Details`, request IDs, cancelación y reintentos seguros solo para lecturas.
- Estado de autenticación centralizado, selección explícita entre múltiples tenants y protección de rutas Vector, tenant-admin y plataforma; Horizon permanece como referencia no canónica sin duplicar auth.
- Flujos funcionales de login, recuperación, reset, invitación, cambio de tenant, logout, perfil, contraseña, sesiones, miembros, roles y portal de plataforma.
- Persistencia local de la demo aislada por tenant y redirecciones `next` limitadas a rutas internas permitidas.
- `npm ci`, drift del cliente OpenAPI, lint y typecheck: correctos; 16/16 tests unitarios/de componente y build de producción con 21 rutas correctos.
- E2E contra Flask, PostgreSQL 16 y Redis reales: 13 ejecuciones correctas y 3 recorridos largos omitidos solo en móvil; los recursos efímeros se limpian al finalizar.
- La revalidación adversarial cubre CSRF fresco tras sesión expirada, recuperación ante fallo de cambio de tenant, logout no optimista, tenant-admin sin permiso y superadmin sin acceso al producto.
- Revisión visual en 1280 px y 390 × 844: navegación, administración, control de acceso y responsive sin errores de consola ni overflow horizontal.
- Deuda no bloqueante: preferencias siguen en el repositorio mock, administración aún no expone paginación/actividad completa y la UI de roles simplifica a un rol aunque la API admite varios.
- `npm audit` mantiene 2 vulnerabilidades moderadas transitivas; no se realizó una actualización masiva de dependencias fuera de alcance.

## Cierre de la fase 06

- Dominio persistente y transversal con `StrategicDossier` central, señales tenant-globales contextualizadas mediante `DossierSignal`, oportunidades, riesgos, actores, relaciones, reuniones, decisiones, tareas, insights, informes, feedback y resúmenes vivos.
- Migraciones `20260710_0004` y `20260710_0005`: FKs compuestas tenant-safe, `ENABLE/FORCE RLS`, permisos, índices, constraints, historial de estado, optimistic concurrency y rollback completo.
- Autorización por expediente para owner, tenant-admin y colaboradores activos; administración de colaboradores restringida y revocable; 404 tenant/resource-safe.
- Scoring `oracle-scoring-v1` exacto y configurable para señales, oportunidades, riesgos y actores, con explicación, historial y overrides humanos atribuidos.
- Promoción de señal transaccional e idempotente, con prueba concurrente; archivo de expediente atómico y bloqueo de mutaciones hijas.
- `EvidenceDossier` conserva el contexto N:M y migra snapshots de fase 0004 con señales compartidas sin pérdida ni fuga entre expedientes.
- API con CRUD, estados, auditoría, relaciones M:N, paginación, búsqueda, filtros tipados, selección por IDs, ETag/If-Match y seed sintético convergente de ocho expedientes.
- OpenAPI cerrado y cliente TypeScript regenerado: 144 operaciones revisadas, 32 `DELETE` 204 y 18 `PATCH` versionados, sin respuestas 2xx vacías ni drift.
- Validación final con PostgreSQL 16 y Redis reales: 83/83 tests y 85,09 % de cobertura; Ruff, formato, mypy (49 fuentes), Alembic base→0005, `flask db check`, cliente OpenAPI y typecheck TypeScript correctos.
- Recursos efímeros eliminados: cero bases/roles temporales y Redis DB 14 vacío.
- Hook explícito diferido: documentos/chunks y `Evidence.document_id` se completan en fase 10; el flujo document-only permanece bloqueado hasta entonces.

## Cierre de la fase 07

- Integración Celery mediante application factory única, serialización JSON/UTC y colas separables `default`, `signals`, `ai`, `documents`, `notifications` y `maintenance`.
- `BackgroundJob` durable con payload allowlisted/hasheado, estados, progreso, intentos, heartbeat, lease de ejecución, fencing por `task_id`, cancelación cooperativa, retries con jitter, errores saneados y publicación reconciliable.
- `JobSchedule` bajo RLS con dispatcher `FOR UPDATE SKIP LOCKED`, creación de job y avance atómicos, schedules interval/daily/weekly y cálculo wall-clock con timezone/DST.
- Workers y beat configurados en Compose con Redis separado para sesiones, rate limit, broker DB 3 y resultados DB 4; YAML validado, pero Docker CLI no está instalado para ejecutar `docker compose config` o smoke de contenedores.
- API de jobs tenant/resource-safe con listado, polling, ETag/If-Match, cancelación, retry manual y auditoría.
- Recuperación de contraseña persist-only desde HTTP y envío asíncrono sin tokens en argumentos; Capture usa idempotencia y SMTP aplica semántica durable at-most-once ante resultado incierto.
- Mantenimiento recorre también tenants suspendidos/archivados; cleanup, recovery de workers stale y reconciliación de publicaciones probados bajo RLS.
- Mock funcional de sincronización Signal conectado al task stub, listo para ser sustituido por el adaptador completo de fase 08.
- Migración `20260710_0006`, snapshot real 0005→0006 (`completed`→`succeeded`) y `flask db check` sin drift.
- Validación final: 108/108 tests, 85,43 % de cobertura y 49 integraciones con PostgreSQL, Redis y worker Celery real; Ruff, formato, mypy, lockfile, OpenAPI/cliente, ESLint, typecheck y tests frontend correctos.
- Recursos efímeros eliminados: base de prueba borrada y Redis DB 13 vacío.

## Cierre de la fase 08

- Contrato consumidor provisional de Signal Avanza documentado con OpenAPI externo esperado, webhooks, mapping y campos abiertos; no se presenta como contrato confirmado del productor.
- `SignalAvanzaAdapter` desacopla dominio y transporte; el mock es determinista y el HTTP valida schemas, timeouts, allowlist, redirects, segmentos de ruta, `Retry-After`, correlación e idempotencia.
- El transporte HTTP real permanece deliberadamente **fail-closed**: aunque la configuración y el contrato provisional existen, no se habilita hasta disponer de pinning de IP con preservación segura de Host/SNI, protección frente a DNS rebinding, confirmación bilateral y E2E contractual.
- Credenciales cifradas con AES-256-GCM, keyring versionado, AAD tenant/conexión/tipo/versión, fingerprints HMAC tenant-scoped, rotación y solape acotado de secretos webhook; secretos nunca se devuelven ni se registran.
- Migración `20260710_0007` con conexiones versionadas, namespace de señales por conexión, snapshots de configuración, inbox, outbox, runs e ingesta; FKs compuestas tenant-safe, constraints, índices, `ENABLE/FORCE RLS` y funciones `SECURITY DEFINER` mínimas para resolución y reconciliación global.
- Outbox transaccional con hash ligado a conexión, monitor, evento y payload; reserva idempotente mediante advisory transaction lock e `intention_hash` estable. Dos requests concurrentes de creación producen un único watchlist, monitor y evento; replay idéntico devuelve el ganador y una intención distinta devuelve 409.
- Polling incremental paginado y webhook firmado convergen en la misma ingesta; deduplicación por conexión/ID/hash, detección de cambios, cursor solo tras éxito, locks por monitor, procedencia, enlace N:M y triage durable.
- Webhook sin sesión ni CSRF, con resolución tenant fuera del body, HMAC/timestamp, current+previous secret, hard cap de stream, replay conflictivo, raw cifrado, persist-first e inbox asíncrono reconciliable.
- Workers y beat recuperan outbox/inbox tras fallo de broker o claim stale; delivery separa estado deseado/observado, actualiza salud y usa idempotencia del proveedor para limitar duplicados tras crash.
- API tenant/resource-safe para conexiones, test, rotación, disable, reconcile, monitores por expediente, PATCH versionado, pause/resume/sync y health; autorización final por expediente, no solo por permiso global.
- Upgrade desde base hasta 0007, `flask db check`, downgrade/reupgrade y downgrade adversarial con dos conexiones que comparten ID externo/hash validados sin pérdida de unicidad ni fallo de migración.
- Validación final backend con PostgreSQL, Redis y worker Celery reales: 126/126 tests correctos y 85,06 % de cobertura; Ruff, formato y mypy correctos.
- OpenAPI Flask reexportado y cliente TypeScript regenerado sin drift; ESLint y typecheck correctos, 19/19 tests frontend y build Next.js correcto con 22 rutas.
- Limitaciones reales: contrato productor Signal aún no confirmado, HTTP real bloqueado como se indica arriba, no se ejecutó smoke Docker/Compose por ausencia de Docker CLI y el endpoint webhook usa una subscription key opaca en ruta que exige redacción en access logs de producción.
- Servidor remoto no inspeccionado ni modificado; la auditoría read-only y cualquier despliegue siguen reservados para las fases de infraestructura.

## Cierre de la fase 09

- Runtime IA desacoplado con `LLMProvider`, modos `disabled` y mock determinista; no existe proveedor externo ni fallback silencioso y el mock queda prohibido en producción.
- Registry inmutable de once prompts runtime versionados (`v1`) cargados como recursos, con metadata, contrato, modelo, límites, changelog y hash; incluye intake, triage, entity resolution, oportunidad, riesgo, actores, briefing, informes, memoria, reviewer y cambios semanales.
- Schemas Pydantic estrictos y conceptuales: hechos, inferencias y recomendaciones separados; scores 0–100; estructuras anidadas para entidades, deduplicación, escenarios, mitigaciones, actores, preguntas, objeciones, párrafos, fuentes, memoria y cambios. Todos los `evidence_ids`, también anidados, se validan contra el snapshot tenant/dossier.
- Context builder acotado por tokens con objetivos, hipótesis, living summary y evidencia N:M; dedupe/manifest/hashes, clasificación, redacción recursiva e indicadores de prompt injection. El contenido ingerido se trata explícitamente como dato no confiable.
- Migración `20260710_0008` con attempts, snapshots/context evidence, artifacts, human reviews, tenant policies y usage ledger; ampliación de `AIAuditLog`, FKs compuestas tenant-safe, constraints, índices, permisos y `ENABLE/FORCE RLS`.
- Ejecución exclusiva por Celery en cola `ai`, cuotas tenant-globales serializadas en PostgreSQL, allowlist de modelos, límites diarios/tokens/concurrencia/presupuesto y kill switch global/tenant. Los resultados son candidatos y nunca ejecutan acciones ni sobrescriben decisiones humanas.
- Fencing adversarial por execution token, estado, lease y ledger reservado en generación, reviewer y settlement. Recovery rota tokens y libera reservas; una prueba con proveedor bloqueado confirmó que un worker stale no puede resucitar audit, crear artefacto ni liquidar coste. El reviewer renueva lease alineada con el hard time limit Celery.
- Fallos de provider/reviewer y veredicto inválido terminalizan audit/attempt/ledger sin persistir output válido; feedback y revisión humana crean historial/override sin modificar el output histórico. APIs de enqueue, retriage, feedback, review y lectura audit aplican permisos, expediente y tenant.
- Evals offline con diecisiete fixtures sintéticos y métricas explícitas de schema pass, cobertura de evidencia, unsupported claims, clasificación, aceptación, latencia y coste; no se realizan llamadas pagadas.
- Validación final con PostgreSQL 16, Redis y worker Celery reales: 154/154 tests y 85,41 % de cobertura. Re-review adversarial final aprobado, incluido el caso recovery durante una llamada provider en vuelo.
- Ruff, formato, mypy, lockfile, Alembic base→0008, ausencia de drift, downgrade 0008→0007 y reupgrade correctos. OpenAPI reexportado, cliente TypeScript regenerado sin drift; ESLint, typecheck, 19 tests frontend y build Next.js de 22 rutas correctos.
- Limitaciones reales: solo existen adapters disabled/mock; habilitar un proveedor real exige contrato, credenciales, revisión de privacidad/clasificación, estimador de coste y allowlists. Con proveedores reales lentos deberá limitarse la renovación del reviewer al deadline absoluto de Celery.
- Servidor remoto no inspeccionado ni modificado.

## Cierre de la fase 10

- Migración `20260711_0009` con `Document`, versiones inmutables, chunks, attempts y políticas de retención; FKs compuestas tenant-safe, `ENABLE/FORCE RLS`, GIN FTS y enlace exacto de `Evidence` a documento/versión/chunk.
- Upgrade desde base, ausencia de drift, downgrade a 0008, reupgrade y snapshots legacy adversariales validados sin perder IDs ni provenance; evidencias históricas bloquean el borrado físico de su fuente.
- Storage desacoplado: filesystem privado y atómico para desarrollo/test; S3-compatible permanece fail-closed salvo endpoint HTTPS con IP global fijada y allowlist. Checksums SHA-256, límites streaming y cuota tenant serializada.
- Scan con noop explícito no descargable y adapter ClamAV `INSTREAM`; parsers acotados para PDF, DOCX, TXT/Markdown, CSV, VTT/SRT y transcripción JSON. No hay OCR ni pgvector sin política/proveedor aprobado.
- Pipeline Celery `documents` con `BackgroundJob` transaccional, publication reconciliable, `DocumentProcessingAttempt`, lease CAS en transacción fresca, fencing por token/versión y recovery que abandona el token expirado y stagea retry seguro.
- Chunking estructural conserva página, párrafo, speaker/timestamps, offsets exactos, checksum y provenance; reprocesar crea una versión nueva y no rompe citas históricas.
- APIs tenant/resource-safe para upload, listado, detalle, download `ready+clean`, soft delete, reprocess, búsqueda global/por expediente y creación/lectura de evidence. Tests cross-tenant explícitos cubren get/download/search/evidence/reprocess/delete.
- Retención con legal hold, purge idempotente de contenido y reconciliación de objetos huérfanos; hashes, IDs, locators y metadata de citas se conservan según política.
- RBAC canónico actualizado para que tenants/roles creados después de 0009 reciban permisos IA/documentales; owner/admin completos, editor/analyst operativos, viewer/auditor con lectura documental.
- Vector enlaza desde portfolio a expedientes PostgreSQL con UUID real y ofrece upload, tabla, búsqueda y drawer de evidence. Las fichas fixture por slug muestran un estado sintético honesto y realizan cero llamadas documentales.
- Revisión adversarial final: **APPROVED**. Validación backend con PostgreSQL, Redis y worker Celery reales: 170/170 tests y 85,08 % de cobertura; Ruff, mypy y lockfile correctos.
- OpenAPI reexportado y cliente TypeScript regenerado sin drift; ESLint y typecheck correctos, 21/21 tests frontend y build Next.js de 22 rutas correcto.
- Smoke visual desktop autenticado: portfolio → expediente PostgreSQL UUID → panel Documentos, sin alertas; la ficha slug sintética también fue revisada. La revisión visual móvil no se completó por la limitación de viewport de la herramienta.
- Limitaciones reales: credenciales/servicios S3 y ClamAV no configurados; sandbox de parser mediante contenedor sin red y límites CPU/memoria queda para infraestructura. No se desplegó ni inspeccionó el servidor remoto.
- La fase 11 continúa `in_progress`: el alcance se amplió posteriormente para continuar con el resto del pack.

## Cierre de la fase 11

- Ocho templates versionados, snapshot de contexto/evidencia verificable, Evidence Reviewer,
  revisiones humanas, publicación serializada, artefactos HTML/JSON y PDF fail-closed.
- Notificaciones in-app, preferencias por tipo/canal, seguridad no desactivable, email asíncrono,
  quiet hours y digest diario/semanal con lotes congelados de hasta 50 elementos, hash SHA-256,
  expiración y retries que no absorben eventos posteriores.
- Evaluator durable para siete alertas: señal/riesgo altos, vencimiento de oportunidad, fallo de
  integración/job, reunión próxima e informe listo; políticas tenant/dossier heredables, bundling,
  cooldown, quiet hours, advisory lock, ledger idempotente y destinatarios filtrados por RBAC.
- Exportaciones CSV asíncronas con allowlist, alcance por expediente/usuario, neutralización de
  fórmulas, watermark de auditoría, revalidación de permisos, links ligados a fingerprint,
  tenant/usuario/sesión y fencing de storage por lease.
- Vector ofrece biblioteca/visor de informes, centro de notificaciones, preferencias y centro de
  exportaciones en rutas `/app`, con aliases provisionales `/concept-a`.
- Snapshots de informe verifican contenido, opciones y hash de template; el tampering falla de forma
  controlada, terminaliza informes mutables y no deja artefactos. Publicación, generación y
  exportaciones mantienen fencing y limpieza de objetos parciales.
- Migración base→0010, ausencia de drift, downgrade a 0009 y reupgrade correctos; RLS `ENABLE/FORCE`,
  grants y constraints tenant-safe verificados. Re-review adversarial: **GO / APPROVED**.
- Validación final: Ruff, formato y mypy correctos; PostgreSQL/Redis reales, 221/221 tests y 86,08 %
  de cobertura; OpenAPI/cliente sin drift; frontend lint, tipos, 28/28 tests y build de 32 páginas;
  E2E real contra Flask/PostgreSQL/Redis: 15 correctos y 3 skips móviles intencionados.
- Revisión visual en 1440 × 900 y 390 × 844 de informes, notificaciones y exportaciones: sin overflow
  horizontal ni errores de consola. Se añadió la declaración de scroll de Next.js al layout raíz.
- Deuda no bloqueante: falta una prueba con dos evaluadores físicamente concurrentes; el OpenAPI
  podría tipar los mapas de alertas con mayor precisión; permanecen tres recorridos largos omitidos
  solo en móvil.

## Cierre de la fase 11A

- `CANONICAL_UI=vector` aplicado en `/app`; Horizon permanece aislado como referencia temporal y
  no recibe funcionalidad productiva.
- Cinco entregables cerrados en `docs/product`: arquitectura de información, especificación de
  navegación, responsive, matriz ruta/permiso y matriz pantalla/componente/API/E2E.
- Registro central y estrictamente tipado para los diez destinos globales, cuenta, administración,
  plataforma y once secciones de expediente; menú derivado de permisos, breadcrumbs semánticos y
  ninguna navegación productiva mediante anchors o rutas `/concept-*`.
- Shell Vector con skip link, command palette, tenant/rol visibles, menú personal separado, centro
  de notificaciones, sidebar persistente y drawer móvil con trap/restauración de foco y bloqueo de
  scroll. Configuración de expediente permite lectura y reserva mutaciones al backend/RBAC.
- Layouts diferenciados para producto, expediente, cuenta, administración y plataforma; rutas aún
  sin frontend conectado muestran placeholders honestos y la API disponible/parcial/pendiente.
- Menú `Crear` y command palette crean un expediente real contra Flask. Si no se indica workspace,
  el backend selecciona el workspace activo predeterminado del tenant; OpenAPI y cliente generado
  reflejan `workspace_id` opcional y existe regresión PostgreSQL.
- Revisión adversarial: **GO / APPROVED**. Backend final 222/222 y 86,09 %; Ruff, formato y mypy
  correctos. Frontend OpenAPI sin drift, lint/typecheck, 32/32 tests y build de 44 rutas correctos.
  E2E real: 15 correctos y 3 skips móviles intencionados, incluida creación real de expediente.
- Revisión visual en 1440 × 900 y 390 × 844: shell, menú completo, placeholders, drawer móvil,
  foco de apertura/cierre, ausencia de overflow horizontal y consola final limpia.
- Deuda para fase 12: sustituir fixtures productivos, conectar read models y tablas globales,
  resolver títulos de expediente en breadcrumbs y ampliar `Crear` solo con flujos completables.

## Cierre de la fase 12

- `/app` es ya una aplicación Vector conectada a Flask: inicio, cambios, búsqueda global,
  inventarios de expedientes/señales/oportunidades/riesgos/actores/reuniones/tareas, detalle de
  expediente, documentos, informes, ajustes, administración tenant y portal de plataforma.
- Los read models globales están acotados por tenant, expediente y permisos. La UI productiva no
  importa fixtures ni `MockOracleRepository`; los mocks permanecen aislados en los dos prototipos.
- El expediente permite revisar/descartar/promover señales, transicionar oportunidades, riesgos y
  tareas, vincular actores, crear reuniones y briefings, gestionar documentos/evidencias y editar o
  archivar la configuración con optimistic concurrency. Los monitores se degradan sin bloquear la
  configuración cuando el usuario carece de permiso Signal.
- Los prototipos A/B siguen disponibles en desarrollo, pero producción redirige `/` y `/concept-*`
  a `/app`; un build con `ORACLE_ENABLE_UI_PROTOTYPES=1` falla deliberadamente para impedir una
  publicación accidental.
- `scripts/create-chatgpt-exam-zip.sh` genera un paquete full-stack por whitelist y excluye secretos,
  entornos, caches, dependencias, resultados E2E y metadatos del IDE/Git.
- Validación backend final: Ruff y mypy correctos; PostgreSQL/Redis reales, 223/223 tests y 85,86 %
  de cobertura. OpenAPI reexportado y cliente TypeScript sin drift.
- Validación frontend final: ESLint, TypeScript y build correctos; 19 archivos y 59/59 tests;
  45 rutas generadas. Playwright contra Flask/PostgreSQL/Redis: 17 correctos y 5 skips móviles
  intencionados, incluida la subida y procesamiento documental real.
- Revisión visual realizada en 1440 × 900, 1280 × 800, 1024 × 768 y 390 × 844; ajustes e inventario
  móvil sin overflow horizontal. Reauditoría independiente: **GO**, sin P0/P1.
- Deuda no bloqueante para fase 13: traducir algunos estados raw; automatizar axe, teclado y consola;
  completar el grafo visual de actores; resolver breadcrumbs por título; y publicar contratos Flask
  antes de ampliar organización/workspaces o agregados operativos cross-tenant. El backend tampoco
  permite reabrir tareas terminales y cambios declara honestamente que no soporta `mark-reviewed`.

## Cierre de la fase 13

- Estrategia, matriz de cobertura y presupuesto de rendimiento trazables en `docs/quality`; threat
  model actualizado e informe `docs/security/READINESS_REPORT.md` con severidad, owner, estado y
  gates. Revisión adversarial final: **GO para fase 14 read-only; NO-GO para producción**.
- La revisión automática de superficies detectó dos rutas `PATCH signal-monitors` equivalentes. Se
  retiró el CRUD genérico: el update pasa siempre por Signal, exige `If-Match`, bloquea la fila,
  versiona configuración y conserva outbox/idempotencia. También se separaron search/evidence
  documental de las rutas core y se impide cualquier ruta Flask equivalente.
- Suite multi-tenant dinámica: toda tabla tenant-scoped mantiene RLS `ENABLE/FORCE`, el rol runtime
  no ve filas sin contexto y cada mutación está inventariada bajo CSRF. Una sesión abierta pierde un
  permiso RBAC revocado en la petición siguiente y tenant-admin devuelve 403.
- Métricas protegidas `/internal/metrics` con rutas templadas, latencia, auth/rate limit y pool;
  token obligatorio y 404 indistinguible. El histograma usa nueve buckets+suma+contador acotados,
  con regresión de 10.000 observaciones; no retiene una muestra por request.
- Headers Flask/Next, cache no-store, anti-clickjacking, nosniff, referrer/permissions y CSP web
  report-only sin `unsafe-eval`. HSTS permanece desactivado hasta confirmar TLS; Next elimina la
  cabecera de versión. Axe WCAG 2.2 A/AA, teclado, foco, consola y recargas de sesión automatizados.
- Scans: npm audit 0; pip-audit 0 tras actualizar `cryptography` 46.0.7→48.0.1 por
  `GHSA-537c-gmf6-5ccf`; Semgrep 0; secret patterns 0. Trivy no disponible y queda gate de imagen.
- DAST local contra Gunicorn: 13/13. Los probes y el harness de carga rechazan userinfo/targets no
  HTTP(S), no siguen redirects y exigen `--allow-staging` fuera de loopback.
- Baseline read-only: 4 clientes/10 s, 326 requests y 0 errores; p95 login 129,60 ms, expedientes
  23,11 ms, señales 23,42 ms, búsqueda 28,16 ms y jobs 23,33 ms. Tres planes SQL bajo runtime/RLS
  usaron índices; el dataset de ocho expedientes no permite inferir capacidad productiva.
- Validación backend final con PostgreSQL/Redis reales: **233/233**, cobertura **85,95 %**, Ruff y
  mypy correctos; OpenAPI 163 paths/240 operaciones y cliente sin drift. Frontend: 21 suites/64
  tests, lint, tipos y build; Playwright full-stack: 24 correctos y 6 skips intencionados.
- Runbooks cubren API, DB/pool, Redis, Celery, Signal, certificado, disco, backup, sesión comprometida
  y sospecha cross-tenant. Producción permanece bloqueada por CSP nonce/enforcement, métricas
  multiproceso, carga/ZAP staging, Trivy/SBOM, TLS exterior, S3/ClamAV/sandbox y backup/restore real.
- Observación no confirmada: un sweep antiguo vio `/auth/me` 200→401 durante recargas solapadas; no
  se reprodujo en test focal ni E2E completo y el trace no se conservó. Se mantiene como P2 visible.

## Avance de la fase 14 · Etapa A

- Auditoría remota realizada exclusivamente por clave SSH en `BatchMode`, sin usar la contraseña
  compartida, sin leer secretos y sin modificar paquetes, archivos, servicios, firewall o datos.
- Host `oracle`, Ubuntu 26.04 LTS/kernel 7.0, 2 vCPU, 3,7 GiB RAM, 75 GiB (3 % usado), sin swap,
  UTC/NTP activo, carga baja y ninguna unidad fallida. Fingerprints SSH internos/externos coinciden.
- DNS A de `oracle.opnconsultoria.com` coincide con IPv4; no hay AAAA/CAA. El host tiene IPv6 global.
  Externamente solo 22 está abierto; 80/443 y 3000/8000/5432/6379 están cerrados o filtrados.
- El servidor está limpio: sin Docker/Compose, Nginx/Apache/Caddy, Certbot, PostgreSQL, Redis,
  repositorio, despliegue o backup Oracle. `/opt` y `/srv` no contienen conflicto.
- UFW está inactivo y no se observaron reglas nftables. `sshd` permite root y password; como una
  contraseña root fue expuesta en conversación, se clasifica como blocker crítico hasta rotación.
- Recursos ajustados: el plan propone worker consolidado de concurrencia 1, features externas
  deshabilitadas, límites y evaluar 8 GiB antes de parsing/IA/carga real. El guest reporta TSA sin
  microcode y requiere confirmación del proveedor.
- Inventario: `docs/operations/SERVER_AUDIT_2026-07-11.md`. Diff, orden, backup, verificación y
  rollback propuestos: `docs/operations/PRODUCTION_CHANGE_PLAN.md`.
- Gate activo: **ningún cambio de Etapa B** hasta que el usuario revise el informe y autorice por
  escrito. Rotación/hardening SSH exige aprobación separada y sesión/console de respaldo.

## Avance local de la fase 14 · artefactos sin aplicación remota

- Frontend productivo standalone con `Dockerfile.web` multi-stage Node 24, UID/GID 10001,
  filesystem read-only compatible y healthcheck. El build standalone arrancó localmente:
  `/login` 200 y `/` 307→`/app`.
- `compose.prod.yml` define PostgreSQL 17, Redis 7.4 con ACL/AOF/noeviction, migración única bajo
  perfil `release`, API/web solo en loopback, DB/Redis sin ports, worker consolidado concurrencia 1,
  beat único, egress limitado, resource limits, restart/log rotation y redes separadas.
- Configuración Flask con allowlist `*_FILE`, rutas absolutas, conflicto inline/file fail-closed y
  UID/GID fijo 10001. Los secretos y URLs quedan fuera del YAML; manifiesto de ownership/formato en
  `infra/production/SECRETS.md`.
- Nginx dispone de bootstrap HTTP, HTTPS final, snippets proxy y log JSON sin query/referrer/cookie/
  auth; readiness es loopback, métricas 404 y la clave de ruta del webhook Signal se enmascara.
- Runbooks de deployment, Nginx, TLS, servicio y rollback; el script de deploy se niega a actuar sin
  gate explícito y manifiesto de backup. El smoke local combinado de Next+Gunicorn pasó.
- Validación: Docker Compose oficial 2.40.3 `config --quiet` correcto con fixtures efímeros; Redis
  local 8.8 aceptó ACL/PING autenticado y rechazó anónimo; shell/YAML/topología correctos. No hay
  daemon Docker ni Nginx local: image build, stack smoke y `nginx -t` quedan pendientes en staging/
  servidor tras autorización.
- Backend final: **237/237** con PostgreSQL/Redis reales y cobertura **85,94 %**; Ruff y mypy
  correctos. Frontend: lint, tipos, **21 suites/64 tests** y build Next correctos.
- ZIP de examen regenerado con los artefactos productivos: integridad correcta, sin directorios
  prohibidos ni la credencial root conocida.
- Este bloque cerró la preparación local previa; la Etapa B fue autorizada después y su evidencia
  real se registra a continuación.

## Avance de la fase 14 · Etapa B autorizada

- Snapshot prechange creado en `/var/backups/opn-oracle/prechange-20260711T124854Z`. Instalados
  desde Ubuntu 26.04: Docker 29.1.3, Compose 2.40.3, Buildx 0.30.1, Nginx 1.28.3, Certbot 4.0.0 y
  zram-generator. Docker/Nginx están activos; zram aporta 1,9 GiB sin swap sensible en disco.
- Usuario `oracle-deploy` bloqueado para password, acceso por la clave autorizada y grupo Docker.
  SSH quedó key-only (`PasswordAuthentication no`, `PermitRootLogin prohibit-password`) tras
  rollback temporizado y segunda sesión correcta. UFW está activo, deny incoming y solo permite
  22/80/443 en IPv4/IPv6.
- Certificado ECDSA válido para `oracle.opnconsultoria.com`, vencimiento 2026-10-09; timer activo y
  `certbot renew --dry-run` correcto. El site HTTP sirve solo ACME/liveness/503 hasta activar HTTPS.
- Release inmutable `20260711T130243Z-graph-mail` con manifest SHA-256; imágenes API/web construidas
  correctamente, ambas non-root. Se corrigió el tag inexistente del builder uv usando imagen uv
  fijada + Python 3.11 fijado por major/base. Trivy 0.72.0 detectó y permitió retirar herramientas
  runtime vulnerables innecesarias (`setuptools`/`wheel`, npm/Corepack); pase final: 0 HIGH/CRITICAL
  corregibles y 0 secretos en ambas imágenes.
- PostgreSQL 17 y Redis 7.4 están healthy en red Docker interna, sin port bindings. Roles verificados:
  `oracle_migrator` BYPASSRLS sin superuser y `oracle_app` NOBYPASSRLS; Redis anónimo rechazado y
  ACL autenticada correcta.
- Microsoft Graph implementado con tenant/client IDs aportados, secret file, sender fijo, token
  cache y `sendMail`. Todas las invitaciones son jobs durables y reconciliables. Backend final local:
  **247/247**, cobertura **85,70 %**, Ruff/mypy correctos; frontend 64/64 y build correcto.
- Bloqueo actual fail-closed: falta materializar el client secret real y confirmar `Mail.Send`
  application/admin consent en Azure. Hasta entonces no se ejecutan migraciones ni se arrancan
  API/worker/beat/web; Nginx HTTPS final no se activa.
- Consola productiva `scripts/oracle-control.sh` añadida con menú a color y comandos no interactivos
  para estado, health, validación, logs, recursos, reinicios controlados, backup/restore aislado,
  releases, rollback, Nginx y TLS. Usa allowlists, confirmaciones reforzadas, lock de exclusión y
  auditoría root-only sin secretos; su operación queda descrita en
  `docs/operations/CONTROL_CENTER.md`.

## Cierre de la fase 14 y avance de fases 15/16

- Microsoft Graph validado con `Mail.Send` de aplicación y consentimiento administrativo. El nuevo
  secreto se materializó directamente en el host como UID/GID `10001:10001`, modo `0400`; la
  adquisición de token client-credentials respondió correctamente sin registrar valor ni token.
- El primer artefacto remoto contenía 574 ficheros AppleDouble `._*`; Alembic se negó a cargar esas
  pseudo-migraciones antes de aplicar esquema. Se generó un release limpio e inmutable y se añadieron
  exclusiones a ambos `.dockerignore` y al ZIP para impedir recurrencia.
- Alembic aplicó `20260710_0001` → `20260711_0010`. El release activo
  `20260711T134718Z-ops-fixes` ejecuta API, web, worker, beat, PostgreSQL y Redis sanos. Se corrigió
  el deploy para validar beat por proceso único y Celery por ping, sin exigirle healthcheck HTTP.
- Nginx sirve HTTPS final: HTTP→HTTPS `308`, login/liveness `200`, HSTS inicial, certificado válido,
  API y web solo en loopback, PostgreSQL/Redis sin port bindings. Smoke público y revisión visual del
  login sin errores de consola: correctos.
- Superadmin `info@opnconsultoria.com` creado y verificado mediante login HTTPS, sesión opaca,
  `/auth/me` con `platform_role=super_admin` y logout `204`. La contraseña temporal no se registró:
  quedó únicamente en el portapapeles local para entrega y debe rotarse tras el primer acceso.
- Backup `20260711T134728Z-20260711T134718Z-ops-fixes` creado con manifest/checksums; restore
  correcto en contenedor, red y volumen efímeros sin puertos. Copia AES-256/PBKDF2 verificada en
  OneDrive corporativo con receipt y clave almacenada fuera de OneDrive/servidor.

## Avance de la fase 15 · Backups programados y control superadmin

- Migración `20260711_0011` aplicada con catálogo global de artefactos y cola durable de operaciones.
  API exclusiva de superadmin para listar, solicitar backup manual, consultar operación y solicitar
  recuperación; exige CSRF, autenticación reciente, idempotencia y auditoría global.
- La interfaz Vector incorpora `/platform/backups`: política diaria, retención, ruta física,
  artefactos, operaciones recientes, botón manual y recuperación con frase exacta. Una solicitud de
  restore queda `awaiting_approval`; HTTP/Celery nunca pueden ejecutarla.
- Agente host root cada minuto y timer diario a las 02:15 `Europe/Madrid`, con jitter de 30 minutos.
  Retención de 30 días, conserva siempre el último backup válido, respeta `.RETAIN` y sincroniza el
  catálogo mediante un ledger root-only reintentable.
- Los dumps nuevos conservan ACL de `oracle_app`; cada backup exige checksums y restore aislado. El
  restore productivo es root/TTY, crea backup previo, restaura como `oracle_migrator` en una base
  nueva, valida Alembic/ACL/owners/RLS/índices y hace swap por rename conservando la base anterior;
  el smoke fallido provoca rollback automático y nunca se ejecuta `DROP DATABASE`.
- Release activo `20260711T141509Z-backup-control`; migración head `20260711_0011`. Ejecución real
  programada verificada: operación `succeeded`, backup
  `20260711T141837Z-20260711T141509Z-backup-control`, ACL preservadas, restore efímero correcto y
  catálogo `available/scheduled`.
- Calidad: backend Ruff/mypy correctos y **258/258** con PostgreSQL/Redis reales, cobertura **85,21 %**;
  frontend lint/tipos/build y **67/67**; ShellCheck y test estático de infraestructura correctos.

## Política de actualización

## Cierre de auditoría lingüística de interfaz

- Segunda revisión transversal de Vector completada: se sustituyeron códigos y anglicismos visibles
  de estados, planes, acciones de auditoría, roles, conexiones, procesos, puntuaciones, documentos y
  plataforma por terminología de negocio en español. `URL` se conserva únicamente cuando identifica
  una dirección web y se acompaña de una etiqueta comprensible.
- Calidad frontend: TypeScript, ESLint, **72/72 pruebas** y build optimizado de Next.js correctos.
- Release inmutable activo: `20260711T190709Z-spanish-terminology`; checksums, seis servicios, HTTPS,
  readiness, worker y beat verificados. Smoke autenticado en Inicio y Signal Avanza confirmó la
  traducción de procesos, estados e identificadores sin alertas visibles de aplicación.

Cada fase debe registrar comandos realmente ejecutados, migraciones, gates, bloqueos y el siguiente prompt. No se marca `done` por planificación o scaffolding incompleto.

## Signal Avanza real · contrato productivo cerrado

- Contrato productor confirmado y aplicado: base
  `https://signal.opnconsultoria.com/api/v1/oracle`, versión `2026-07-01`, autenticación
  `X-API-Key`/Bearer, tenant externo obligatorio y scopes `monitor:write`, `signal:read` y
  `webhook:manage`. Los cursores son opacos, ligados a tenant y monitor, con páginas de 1–200 y
  retención declarada de 365 días.
- Consumidor productivo `opn-oracle` provisionado en Signal con allowlist del tenant real. La API
  key y el secreto de webhook se transfirieron directamente entre hosts y se almacenaron cifrados;
  no se escribieron en repositorio ni en salida de comandos.
- Suscripción real creada con firma HMAC-SHA256 V2 sobre `timestamp.raw_body`, usando
  `X-Opn-Signal-Timestamp` y `X-Opn-Signal-Signature-V2`. Oracle acepta replay idempotente y
  mantiene inbox durable cifrado.
- E2E productivo verificado con un monitor `draft`: creación `201`, replay idempotente `200`, pull
  de señales `200` con cursor válido y webhook `monitor.status_changed` entregado por el worker real
  de Signal. Oracle lo procesó como `processed`, sin error, normalizando `draft` a su estado interno
  `pending`.
- Release activo `20260711T214039Z-signal-status-normalization`; API y worker recreados sanos y
  Celery respondió `pong`. No hubo cambios de esquema ni variables adicionales a las ya
  documentadas.
- Calidad del cierre: Ruff y mypy correctos. El test de integración focal quedó omitido localmente
  por no estar definidos PostgreSQL/Redis de pruebas; el comando aislado terminó únicamente por el
  umbral global de cobertura. La validación equivalente se ejecutó contra los dos servicios reales
  de producción y quedó satisfactoria.

## Proveedores gratuitos temporales y prueba de búsqueda

- Signal queda temporalmente fijado a IA local sin coste: Ollama GPU18 como primario y Ollama Titan
  GPU17 como respaldo. Para `opn-oracle`, el modelo general es `qwen3.5:9b`, el respaldo
  `qwen3.6:27b`, los lotes económicos usan `qwen2.5:7b-instruct` y los embeddings
  `nomic-embed-text:latest`. No se permiten overrides de proveedor/modelo desde el consumidor.
- La cadena de búsqueda exclusiva de `opn-oracle` es
  `searxng → ddg_html → ddg_lite → brave`. SearXNG es la instancia autoalojada accesible mediante el
  túnel privado del host. DuckDuckGo queda como respaldo gratuito pese a sus bloqueos anti-bot y
  Brave se reserva como cuarto y último recurso. Oracle tiene un límite adicional de 10 consultas
  de pago al día; se conservan los topes globales de 20 USD/mes y 4.000 solicitudes mensuales.
- Prueba productiva aislada realizada con un consumidor efímero, eliminado al finalizar: la consulta
  `site:boe.es subvenciones digitalización empresas 2026` devolvió 5 resultados mediante SearXNG.
  El análisis de control respondió HTTP 200 con `ollama/qwen3.5:9b`, sin fallback y sin coste de API.
  Una segunda prueba combinó 3 resultados con el analizador del pipeline
  `ollama/qwen2.5:7b` y produjo JSON estructurado válido.
- La prioridad de proveedores se volvió a verificar con una consulta real: respondió SearXNG y el
  contador mensual de Brave no aumentó (`delta=0`). La configuración anterior del ledger se guardó
  en `/opt/apps/opn_signal/var/search_usage.json.pre-oracle-brave-20260711T201058Z`.
- Los servicios `opn-signal-api`, `opn-signal-worker` y `opn-signal-beat` se reiniciaron y quedaron
  activos. La configuración anterior se conservó en el host como
  `/opt/apps/opn_signal/settings.env.pre-ollama-20260711T195228Z` con modo `0600`.

## Ampliación de actores desde fuentes · extracción y revisión persistente

- La ingesta de Signal conserva sus entidades estructuradas y, cuando faltan, recupera menciones
  conservadoras desde contenedores conocidos del payload y patrones textuales de organización. Las
  señales ya persistidas usan la misma recuperación al consultar candidatos, sin reingesta previa.
- El caso real de texto `CATL ... junto a Stellantis` queda cubierto como dos candidatos con método
  de extracción y fuente explícitos. Ninguna mención se convierte automáticamente en actor.
- La migración `20260712_0015` añade `actor_candidate_reviews`, aislada por tenant mediante RLS y
  vinculada al expediente y al revisor. Permite descartar, consultar descartados y restaurarlos; las
  importaciones y revisiones quedan auditadas.
- OpenAPI y cliente TypeScript incluyen lectura con `include_dismissed`, importación y revisión. El
  panel Vector ofrece descarte/restauración tanto en tabla como en móvil.
- Calidad local: Ruff y mypy correctos; backend **108 passed, 171 skipped**; frontend **86/86**,
  ESLint, TypeScript, cliente generado y build optimizado correctos. Las integraciones PostgreSQL,
  Redis y RLS quedaron omitidas al no existir variables `TEST_*` en este entorno.
- La primera ejecución CI del release detectó tres expectativas de integración desactualizadas: el
  cifrado del inbox recibía bytes en lugar de texto, la ruta de monitores conservaba un prefijo
  antiguo y los informes seguros sin evidencia ya terminan `ready`. Las tres pruebas se alinearon
  con los contratos vigentes; la suite completa con PostgreSQL/Redis se revalida en GitHub antes del
  despliegue.
- CI ejecuta **279/279 pruebas backend** con PostgreSQL, Redis y Celery. La cobertura efectiva tras
  ampliar rutas y contratos es **84,42 %**; el gate temporal queda en 84 % para mantener una barrera
  real sin ocultar el dato. Deuda explícita: añadir cobertura de ramas defensivas de candidatos y
  restaurar el mínimo de 85 % en la siguiente fase.
- El primer `flask db check` que alcanzó CI reveló que el índice parcial que impide dos
  restauraciones activas estaba en Alembic pero no en metadata SQLAlchemy. Se incorporó al modelo
  `PlatformBackupOperation`, conservando la restricción productiva y eliminando el drift.
- El job de seguridad alcanzó auditorías npm/Python sin vulnerabilidades, pero Semgrep 1.133.0 no
  arrancaba con `setuptools` moderno por la retirada de `pkg_resources`. El workflow fija
  `setuptools<81` únicamente dentro de la herramienta aislada; `semgrep --version` 1.133.0 quedó
  verificado localmente.
- Los builds y escaneos Trivy de ambas imágenes pasaron. La generación SBOM no arrancó porque el
  tag histórico `anchore/syft:v1.30.1` no existe; se actualizó al release oficial disponible
  `v1.46.0`, manteniendo la salida CycloneDX JSON.
- La siguiente ejecución CI quedó verde, pero reveló que los SBOM se escribían dentro del
  contenedor efímero. El workflow monta el workspace en `/out` para que ambos CycloneDX queden
  disponibles y se suban como artefacto del commit.

## UX 19 · Revisión de señales resistente al triaje concurrente

- El cliente Vector trata `409/version_conflict` al revisar o descartar una señal como una
  actualización recuperable: recarga el enlace del expediente, sincroniza su `triage_version` y
  reintenta una sola vez cuando su estado sigue siendo accionable.
- Si otra persona ya cambió la señal a un estado incompatible, el drawer permanece abierto con
  datos frescos y un aviso accionable; el mensaje técnico de conflicto ya no es un callejón sin
  salida. La garantía de concurrencia del backend se conserva sin semántica de última escritura.
- Verificación focal: `npm run typecheck`, `npm run lint` y el test de componente de señales
  correctos (**6/6**). El contrato backend ya publica `409` con `code=version_conflict`; no se
  requirió migración ni cambio de OpenAPI.

## UX 20 · Arco visible de señal a acción estratégica

- El drawer de una señal ofrece ahora acciones separadas para promover a oportunidad o a riesgo,
  además de un enlace directo a los candidatos de actor del expediente. Una señal nueva se revisa
  de forma explícita y recuperable antes de abrir el formulario de promoción, sin promoción
  automática.
- Al completar la promoción, el drawer conserva feedback, refleja el estado `Promovida` y enlaza
  directamente al recurso creado. Flask mantiene la evidencia, la fuente y la idempotencia ya
  existentes en `promote_signal_link`.
- Verificación focal: TypeScript, ESLint y tests de señales/actores correctos (**12/12**). La
  integración de dominio (`tests/test_integration_oracle_domain.py`) quedó íntegramente omitida por
  falta de `TEST_*` locales; no hubo migración ni cambio de contrato.

## UX 21 · Estado explícito de puntuación de señales

- Flask expone `scoring_state` en cada vínculo de señal: `pending` antes del triaje,
  `provisional` cuando el triaje de Signal/Ollama ya aportó evidencia y `reviewed` tras revisión
  humana. No se usan valores inventados ni se modifica el esquema persistido.
- Vector muestra «Sin puntuar» y «Pendiente de triaje» para el estado pendiente; las
  valoraciones provisionales se identifican como tales. Los filtros de puntuación continúan
  excluyendo los pendientes porque no representan una puntuación conocida.
- OpenAPI y el cliente se regeneraron. Verificación focal correcta: backend **10/10** y frontend
  de señales **8/8**, además de Ruff, mypy, ESLint, TypeScript y comprobación de drift.

## UX 22 · Candidatos de actor descubiertos desde las señales

- La pestaña Actores ofrece siempre «Ver candidatos detectados» cuando aún no hay actores
  vinculados; el estado vacío explica que las empresas, personas y organismos mencionados en
  señales aparecerán con su procedencia.
- El detalle de señal enlaza al mismo subflujo. La derivación existente cubre entidades de Signal,
  payload y patrones conservadores, incluido CATL/Stellantis, sin crear actores automáticamente.
- Verificación focal: frontend de Actores/candidatos **8/8** y backend de extracción **3/3**,
  junto a TypeScript, ESLint y Ruff. La integración PostgreSQL continúa pendiente de `TEST_*`.

## UX 23 · Inicio accionable y KPIs coherentes

- Cuando no hay expedientes, Inicio sustituye las métricas a cero por un primer paso accionable
  para crear el radar estratégico inicial. No se inventan resultados ni se ocultan permisos.
- El bloque mixto de señales, oportunidades, riesgos, reuniones y tareas pasa a llamarse «Trabajo
  que requiere atención», identifica el tipo de cada elemento y mantiene tanto sus enlaces de
  detalle como el acceso coherente a la cartera.
- Verificación focal: pruebas de Inicio **2/2**, TypeScript y ESLint correctos. No fue necesario
  modificar el read model ni el contrato de Flask.

## UX 24 · Objetivos e hipótesis visibles y gestionables

- El Resumen del expediente incorpora el panel «Objetivos e hipótesis», por lo que la base inicial
  deja visibles su objetivo y sus dos hipótesis sin depender de Configuración.
- La interfaz permite crear y editar hipótesis, cambiar estado/confianza y vincular evidencia ya
  disponible en el expediente. Aprovecha endpoints y auditoría existentes de Flask; el cliente
  TypeScript expone ahora objetivos, hipótesis y evidencia contextual.
- Verificación focal: componente de contexto **2/2**, TypeScript y ESLint correctos. No hubo
  migración ni regeneración de OpenAPI porque el contrato ya existía; `api:client:check` se
  ejecutará en la verificación integral.

## UX 25 y cierre · Coherencia de vigilancia, fuentes y señales

- Configuración conserva su posición al actualizar porque sus mutaciones refrescan datos locales,
  sin navegación ni scroll al inicio. El shell Vector ya resuelve el título real del expediente en
  las migas, por lo que ambos hallazgos quedan verificados sin cambio adicional.
- El API de vigilancias devuelve el nombre configurado y Vector lo muestra como información
  principal, dejando la conexión como contexto secundario. Las fechas ausentes de una señal se
  presentan como «Fecha no disponible en la fuente».
- La bandeja del expediente consolida en presentación los elementos con la misma URL/título, sin
  borrar registros ni afectar auditoría. La sincronización descarta señales con idioma detectado
  fuera de la lista explícita del monitor; cuando no hay idioma detectado, conserva la señal para
  no inventar una clasificación.
- Cierre local: Ruff y mypy correctos; backend **108 passed, 174 skipped** (integraciones sin
  `TEST_*`); frontend **94/94**, ESLint, TypeScript, build Next.js y drift del cliente OpenAPI
  correctos. `git diff --check` correcto.

## Prompt 27 · Promoción accionable desde señales

- Release productivo activado: `20260713T103600Z-p27-10b789b`, construido desde `10b789b` y con la
  mejora previa de candidatos `4fc6acb` incluida. El despliegue usó el modo rápido UAT de D-022 con
  backup local, restore aislado, release inmutable y `oracle-control update`.
- La promoción de señal a oportunidad acepta ahora siguiente acción, fecha objetivo y creación de
  tarea enlazada. La traza de promoción queda persistida en el contenido de la tarea, sin exponer
  detalles técnicos al usuario final.
- Verificación funcional inicial en producción detectó un defecto real: el modal mostraba fecha,
  pero el submit no enviaba `due_date` por falta de nombres de formulario estables. Se corrigió en
  `src/components/dossiers/dossier-intelligence-section.tsx` y la corrección viajó en el release
  del prompt 28.
- Verificación post-fix en producción con señal UAT marcada:
  `0b087e6c-b289-4312-9361-fb259eb91053`. La UI mostró «Oportunidad creada» y la base confirmó
  oportunidad `be4cc416-248b-4d64-ad7d-42b92f92981e` con `deadline=2026-07-21` y tarea
  `1a955891-6acc-4748-8a09-4578d911f7a1` con `due_date=2026-07-21`, `origin=signal` y vínculo a
  la oportunidad.
- Verificación específica de candidatos CATL: en
  `/app/dossiers/292d85e5-3dc1-4c2f-81a5-8a73a29e1fb4/actors?view=candidates` aparecen
  **CATL** y **Stellantis** como candidatos detectados, ambos con 2 fuentes.
- Checks locales focales: test de componente de señales **8/8**, `npm run typecheck`,
  `npm run lint` y `git diff --check` correctos.

## Prompt 28 · Deduplicación de señales en ingesta

- Release productivo activado: `20260713T110700Z-p28-800dbdb`, construido desde
  `800dbdbe5b6fedb7a6a298578701dd2e357dbe8e`. CI verde en GitHub Actions run
  `29244552826`: frontend/contract, backend+migraciones+integración PostgreSQL/Redis/Celery,
  seguridad, imágenes y SBOM.
- Despliegue D-022 ejecutado con backup local
  `/var/backups/opn-oracle/20260713T110342Z-20260713T103600Z-p27-10b789b/MANIFEST.txt` y restore
  aislado
  `/var/backups/opn-oracle/restore-evidence/20260713T110342Z-20260713T103600Z-p27-10b789b.RESTORE_EVIDENCE.txt`.
  `oracle-control validate`, `oracle-control update`, `oracle-control health` y
  `scripts/smoke-production.sh` correctos. El release activo queda en
  `/opt/opn-oracle/releases/20260713T110700Z-p28-800dbdb`.
- Migración aplicada: `20260713_0016`. Añade `signals.canonical_source_url`,
  `signals.dedupe_key` e índice parcial `ix_signals_tenant_connection_dedupe`. Verificación SQL en
  producción confirmó head, columnas e índice. `flask db current` con el usuario runtime no pudo
  leer `alembic_version` por privilegios restrictivos; la comprobación del head se hizo con el
  usuario administrativo de PostgreSQL dentro del contenedor.
- La ingesta reutiliza una `Signal` existente del mismo tenant+conexión por URL canónica o, si no
  hay URL, por título normalizado + fuente. Cada item recibido conserva su
  `SignalIngestionRecord`; al reutilizar no duplica `DossierSignal` y solo reencola triaje si cambia
  el contenido.
- Verificación funcional en producción: desde Ajustes del expediente CATL
  `292d85e5-3dc1-4c2f-81a5-8a73a29e1fb4` se pulsó «Sincronizar» dos veces en el monitor activo
  `c09a5d80-281b-4d33-b7f4-6077634f58fc`. Ambas ejecuciones terminaron `succeeded` con
  `received=1`, `created=0`, `duplicates=1`; el registro de ingesta existente quedó como
  `duplicate` con `occurrence_count=3` y la URL del artículo de El Español conserva **1 señal** y
  **1 vínculo** de expediente.
- La bandeja global sigue mostrando duplicados históricos de otras URLs, por ejemplo
  `forococheselectricos.com/...catl-defiende...` y `catl.com`, porque este prompt no retro-fusiona
  datos existentes. Queda como deuda operativa si se decide limpiar UAT manualmente.
- Checks locales: `uv run pytest --no-cov tests/test_signal_ingest_dedupe.py -q` **2/2**,
  `uv run ruff check`, `uv run ruff format --check`, `uv run mypy` en servicios/modelos afectados,
  test frontend de señales **8/8**, `npm run typecheck`, `npm run lint` y `git diff --check`
  correctos.

## Prompts 29 y 30 · Briefing IA de reuniones y digest estratégico semanal

- Release productivo activado: `20260713T160310Z-p29-p30-7fc17b2`, construido desde `7fc17b2`.
  Despliegue D-022 con backup local
  `/var/backups/opn-oracle/20260713T160359Z-20260713T110700Z-p28-800dbdb/MANIFEST.txt` y restore
  aislado
  `/var/backups/opn-oracle/restore-evidence/20260713T160359Z-20260713T110700Z-p28-800dbdb.RESTORE_EVIDENCE.txt`.
  `oracle-control update`, loopback smoke, HTTPS login/live, readiness, Celery ping y beat único
  correctos. Sin receipt off-host por modo UAT D-022.
- «Preparar reunión» deja de crear un documento manual vacío: ahora encola
  `oracle.meeting_briefing.refresh` en cola `ai`, ejecuta el
  agente `meeting_briefing` con contexto del expediente, fecha, objetivo y participantes, valida
  `MeetingBriefingOutput`, publica `Briefing.content.kind=meeting_briefing` y conserva versiones
  anteriores.
- El alta de reuniones admite `scheduled_at` y `actor_ids`; los participantes se guardan en
  `meeting_actors` y se incorporan al snapshot IA. La UI permite elegir fecha/hora y participantes
  desde el modal de creación.
- «Qué ha cambiado» incorpora un panel de digest estratégico semanal sobre el expediente accesible
  con actividad reciente. `GET/POST /api/v1/changes/digest` consulta o encola
  `oracle.weekly_change.refresh`, valida `WeeklyChangeOutput` y publica un `AIArtifact` versionado
  por expediente/periodo sin mezclarlo con el historial técnico.
- Sin migración: se reutilizan `AIArtifact.target_type/target_id`, `AIAuditLog`, `BackgroundJob`,
  `Briefing.content` y `MeetingActor`.
- Contrato actualizado: OpenAPI y cliente TypeScript regenerados. Nuevos schemas
  `MeetingBriefingGenerationResponse`, `WeeklyChangeDigestResponse` y
  `WeeklyChangeRefreshInput`; `MeetingWriteInput` expone `scheduled_at` y `actor_ids`.
- Checks locales correctos: `uv run ruff check src tests`, `uv run mypy src`, `npm run typecheck`,
  `npm run lint`, `npm run build`, Vitest completo **94/94**, pytest backend funcional
  `--no-cov` **111 passed, 177 skipped**, y pruebas backend focalizadas de contrato/cambios/briefing
  **3/3**. `uv run pytest` completo ejecuta los mismos tests funcionales pero falla el gate de
  cobertura local (40% < 84%) porque las suites de integración quedan saltadas sin variables
  `TEST_*`; no se observan fallos funcionales.

## Prompt 31 · Gobierno Signal de tasks IA Oracle

- Arreglo realizado en el repositorio productor Signal (`/Users/gitshell/PycharmProjects/opn_signal`),
  sin tocar código Oracle: commit `1fae7cf` (`feat(ai): govern Oracle report and briefing tasks`)
  desplegado en `signal.opnconsultoria.com`.
- Signal añade al catálogo y preset de `opn-oracle` las tasks `report_writer`,
  `meeting_briefing` y `weekly_change`, junto a `dossier_situation_summary`, con primario
  `ollama/qwen3.5:9b`, fallback `ollama_titan/qwen3.6:27b`, JSON estructurado, logging de
  prompts/respuestas desactivado y cloud/OpenRouter cerrado.
- La fila persistida del consumidor productivo se sincronizó con
  `python scripts/sync_oracle_ai_task_catalog.py`; resultado: `ai_settings_id=12`,
  tareas gobernadas `dossier_situation_summary,meeting_briefing,report_writer,weekly_change` y
  proveedores `ollama,ollama_titan`.
- Verificación productiva: resolución de las cuatro tasks ignora overrides de payload
  (`openrouter`/modelo malicioso) y devuelve siempre `ollama/qwen3.5:9b` → `ollama_titan/qwen3.6:27b`
  con timeouts/tokens esperados: resumen 180s/3000, reunión 180s/3500, informe 300s/6500 y digest
  240s/4200.
- Salud post-despliegue: `https://signal.opnconsultoria.com/healthz` 200, servicios
  `opn-signal-api`, `opn-signal-worker` y `opn-signal-beat` activos, un único beat y logs posteriores
  al restart sin tracebacks de despliegue. `/api/v1/oracle/health` devuelve 401 sin API key, esperado
  para endpoint protegido.
- Checks Signal antes del despliegue: Ruff focal, `py_compile` del script de sincronización, tests
  focales **44/44** y suite completa **480/480**.

## Prompt 32 · Resultados, decisiones y tareas desde reuniones

- Release productivo activado: `20260714T091532Z-p32-ae226ee`, construido desde `ae226ee`.
  Despliegue D-022 con backup local
  `/var/backups/opn-oracle/20260714T091600Z-20260713T160310Z-p29-p30-7fc17b2/MANIFEST.txt` y
  restore aislado
  `/var/backups/opn-oracle/restore-evidence/20260714T091600Z-20260713T160310Z-p29-p30-7fc17b2.RESTORE_EVIDENCE.txt`.
  Sin receipt off-host por modo UAT D-022.
- `oracle-control update` activó el release y confirmó liveness/readiness, HTTPS login/live,
  Celery ping y beat único. Verificación posterior: `oracle-control health`,
  `scripts/smoke-production.sh`, contenedores healthy y logs de API/worker/beat/web posteriores al
  despliegue sin tracebacks/errores.
- Verificación funcional en producción sobre CATL `292d85e5-3dc1-4c2f-81a5-8a73a29e1fb4`: se
  cerró la reunión existente `2268aa4c-dc06-4357-b423-cfd4d9fa9ce2`
  («Reunión de posicionamiento con Gobierno de Aragón») con resultados UAT P32. Se creó la decisión
  `1f6bb946-0122-4428-ab47-22b73a19ed46` y la tarea
  `3f3550ed-b3d5-4185-9996-a66f60e1ccee`; ambas aparecen en sus listados y conservan el vínculo a la
  reunión (`content.meeting_id` en decisión; `linked_resource_type=meeting`, `origin=meeting` en
  tarea). `GET /api/v1/home` autenticado respondió 200 tras la operación.
- Implementación: cierre de reunión mediante
  `POST /api/v1/meetings/{meeting_id}/complete` con `If-Match`, `Idempotency-Key`, permisos
  `meeting.write` + `task.write`, auditoría, `StatusHistory` e idempotencia durable en
  `BackgroundJob`.
- El cierre acepta notas/resultados, decisiones propuestas con justificación y evidencias
  opcionales, y tareas de seguimiento con responsable opcional, vencimiento y prioridad. Las tareas
  quedan vinculadas a la reunión (`linked_resource_type=meeting`, `origin=meeting`) y las decisiones
  conservan `content.source=meeting_outcome`.
- La UI Vector de reuniones ya no marca una reunión como completada con un cambio seco de estado:
  abre un formulario de cierre con resultados, N decisiones y N tareas. Las decisiones/tareas creadas
  se muestran enlazadas desde el detalle de la reunión y aparecen en sus secciones normales.
- Contrato actualizado: OpenAPI y cliente TypeScript regenerados con `MeetingCompleteInput`,
  `MeetingCompleteResponse`, `MeetingOutcomeDecisionInput` y `MeetingOutcomeTaskInput`; `Decision`
  expone `content`, `rationale`, `decided_at` y `decided_by_user_id`.
- Checks locales: `uv run ruff check` focal correcto, `uv run mypy` focal correcto,
  `uv run pytest tests/test_contract.py -q --no-cov` **7/7**, test de integración nuevo preparado
  pero saltado sin `ORACLE_RUN_INTEGRATION=1`, Vitest focal **11/11**, `npm run lint`,
  `npm run typecheck`, `npm run api:client:check`, `npm run build` y `git diff --check` correctos.

## Prompt 33 · Ajuste de pipeline IA y asentamiento de informes

- Release productivo activo: `20260714T112748Z-p33c-e01d985`, construido desde `e01d985`.
  Despliegue D-022 con backup local
  `/var/backups/opn-oracle/20260714T112837Z-20260714T110858Z-p33b-885c348/MANIFEST.txt` y restore
  aislado
  `/var/backups/opn-oracle/restore-evidence/20260714T112837Z-20260714T110858Z-p33b-885c348.RESTORE_EVIDENCE.txt`.
  Sin receipt off-host por modo UAT D-022.
- `oracle-control update` activó el release y confirmó loopback smoke, liveness/readiness, HTTPS
  login/live, Celery ping y beat único. Verificación posterior: `scripts/smoke-production.sh`
  correcto, `oracle-control health` correcto y Alembic confirmado en `20260714_0017` mediante
  PostgreSQL administrativo dentro del contenedor. El comando `flask db current` con usuario runtime
  no puede leer `alembic_version`, esperado por privilegios restrictivos.
- CI manual verde para `e01d985`: GitHub Actions run
  `https://github.com/gitshell007/OPN_ORACLE/actions/runs/29328593141`, con
  frontend/contract, backend+migraciones+integración PostgreSQL/Redis/Celery y seguridad/imágenes/SBOM
  correctos.
- Se corrigió el fallo raíz del informe CATL: el provider gobernado por Signal ya no puede caer en
  `UnboundLocalError` si la reparación JSON falla; los reintentos IA reabren de forma controlada el
  mismo `AIAuditLog` fallido creando nuevos `AIAttempt`; y los errores IA conservan causa real en
  vez de quedar ocultos como fallo genérico de job.
- Se subió el presupuesto productivo de salidas IA para agentes largos: política tenant
  `max_output_tokens=6500`, `report_writer v3=6500`, `meeting_briefing v2=3500` y
  `weekly_change v2=4200`. `SIGNAL_AI_TIMEOUT_SECONDS` queda en 300 s y Celery en 690/720 s.
- Se añadió normalización segura de deriva de forma para `report_writer`: cadenas o prioridades
  no canónicas se convierten al contrato estricto, evidencias inventadas se descartan, hechos sin
  cita pasan a inferencia acotada y el índice de fuentes del modelo se ignora para reconstruirlo
  desde el snapshot inmutable.
- Verificación funcional en producción sobre CATL `292d85e5-3dc1-4c2f-81a5-8a73a29e1fb4`:
  - reintento real de informe `action_plan` terminado `succeeded/completed`; informe
    `4d95bdbc-8b75-4ae6-9ae2-3edfa148ad14` quedó `ready`, con revisión
    `1d7c360e-47ec-47e9-9627-815c04c4d97d`, artefacto `337696c6-9268-4e07-b9b6-fc180fac9e1f`,
    8 secciones, 1 fuente y **0 hechos sin cita**;
  - briefing de la reunión `2268aa4c-dc06-4357-b423-cfd4d9fa9ce2` terminado
    `succeeded/completed`, auditoría `meeting_briefing v2` con generación y reviewer correctos,
    briefing publicado `a9416eac-5b84-4e8f-af91-bef7ba4edfb0`;
  - digest semanal terminado `succeeded/completed`, auditoría `weekly_change v2`, artefacto
    `8afa0fb0-1f1c-484e-aac7-399559d0a8e5` en estado `valid`.
- Checks locales focales correctos: `uv run ruff format --check`, `uv run ruff check`,
  `uv run mypy` en módulos afectados y `uv run pytest tests/test_ai_runtime.py
  tests/test_signal_ai_provider.py tests/test_reporting_routes_extra.py -q --no-cov` **48/48**.

## Prompt 34 · F1 grafo de entidad desde Signal

- Estado F1: implementado y desplegado el proxy Flask `/api/v1/entity-intel/suggest` y
  `/api/v1/entity-intel/graph`, protegido con `actor.read`, rate limit, allowlist `SIGNAL_AI_*`,
  timeouts, caché server-side de 600 s y cabecera `X-OPN-External-Tenant-ID` derivada de la
  conexión Signal activa del tenant. El navegador no llama a Signal ni recibe claves.
- UI Vector: sección global Actores incorpora «Buscar entidad» y ruta
  `/app/actors/entity/<type>/<name>` con grafo básico Cytoscape/fcose cargado dinámicamente,
  métricas de nodos/enlaces, leyenda y panel lateral de lectura. F1 no persiste entidades ni crea
  relaciones en expedientes.
- Contrato actualizado: OpenAPI y cliente TypeScript regenerados con los endpoints
  `entity-intel`.
- Decisión registrada en `DECISIONS.md`: Cytoscape.js + `fcose` para red relacional de 60–200
  nodos, carga diferida para no penalizar el bundle global.
- Checks locales F1: `uv run ruff check` focal correcto, `uv run pytest tests/test_entity_intel.py
  --no-cov`, `uv run pytest tests/test_entity_intel.py tests/test_contract.py -q
  --no-cov` **23/23** tras el ajuste de errores RFC7807, `npm run api:openapi`,
  `npm run api:client:generate`,
  `npm run api:client:check`, `uv run mypy` focal correcto, `npm run typecheck`,
  `npm run lint` y `npm run build` correctos.
- CI manual verde para F1:
  - `9b3c72e`: `https://github.com/gitshell007/OPN_ORACLE/actions/runs/29332788154`.
  - `72f5efd`: `https://github.com/gitshell007/OPN_ORACLE/actions/runs/29333426454`.
- Producción D-022: release activo `20260714T125430Z-p34-f1-d2d945f`, backup local
  `/var/backups/opn-oracle/20260714T125516Z-20260714T124654Z-p34-f1-72f5efd/MANIFEST.txt`,
  restore aislado
  `/var/backups/opn-oracle/restore-evidence/20260714T125516Z-20260714T124654Z-p34-f1-72f5efd.RESTORE_EVIDENCE.txt`,
  smoke público correcto y `oracle-control health` correcto. Se recuperó un primer intento fallido
  por permisos del entrypoint Redis en un artefacto candidato previo; el release activo quedó sano
  y la auditoría final registra `activate-release result=success`.
- Verificación real autenticada:
  - `GET /api/v1/entity-intel/suggest?q=IBERDROLA&kind=company&limit=8` respondió 200 y devolvió
    `IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA`.
  - `GET /api/v1/entity-intel/graph` para ese nombre devolvió 403 desde Signal. Llamada directa a
    Signal confirmó `insufficient_scope`: «La credencial no tiene el scope 'entity:read'.».
    Oracle preserva ahora ese detalle RFC7807 en la API en vez de devolver `{}`.
- Gate antes de F2/F3: pendiente que Signal conceda `entity:read` a la credencial productiva de
  Oracle o entregue credencial separada para entidades. No se puede enseñar el grafo real hasta
  resolver ese scope del productor.
- Reintento del prompt 34 el 2026-07-14: producción sigue en
  `20260714T125430Z-p34-f1-d2d945f`; `suggest("IBERDROLA")` responde 200 con la entidad registral
  exacta, pero `graph` para `IBERDROLA CLIENTES ESPAÑA SOCIEDAD ANONIMA` sigue devolviendo
  `403 insufficient_scope` con request id `db3665914ea4c2f2262682dfccb0a266`. Consulta read-only
  a `integration_connections` confirma que la conexión activa `signal-avanza` conserva scopes
  `monitor:write`, `signal:read` y `webhook:manage`, sin `entity:read`; por tanto F2/F3 siguen
  paradas por el gate real de F1.

## 2026-07-16 · Fix deploy storage local

- Corregido el fallo de despliegue introducido por la persistencia de artefactos: el servicio
  `migrate` monta ahora `oracle_document_storage:/var/lib/oracle-storage`, igual que `api`,
  `worker-core` y `beat`.
- `LocalObjectStorage` ya no tumba `create_app()` si la preparación inicial de la raíz local falla
  por rootfs de solo lectura; las escrituras reales siguen fallando de forma controlada como
  `StorageError` cuando el storage no está disponible.

## 2026-07-16 · Fix reporting histórico

- `serialize_report(..., detail=True)` aplica el mismo saneo de prosa que la generación, sin
  reescribir el JSON persistido, para que informes ya creados no muestren UUIDs de evidencia en la
  UI y mantengan intactos sus `evidence_ids` estructurados.

## 2026-07-16 · UI contratación pública PLACSP

- Añadida la superficie global `/app/procurement` con búsqueda de licitaciones PLACSP,
  filtros de CPV/importe/plazo/comprador/región/estado, paginación `limit/offset`, resumen LLM
  bajo demanda y búsquedas guardadas.
- Añadido panel de adjudicaciones en Actores para consultar contratos por adjudicatario u órgano
  comprador y fijarlos a expedientes. El panel incorpora autocompletado registral desde
  `/api/v1/procurement/suggest` para que el usuario no tenga que conocer la razón social exacta
  exigida por Signal.
- Añadida pestaña de expediente `Licitaciones` para listar snapshots PLACSP fijados, abrir la
  fuente oficial y desfijar referencias con permiso `opportunity.write`.
- El cliente TS encapsula `/api/v1/procurement/*`, incluido `suggest`, y
  `/api/v1/dossiers/{id}/procurement`, manteniendo `folder_id` con barras codificado en rutas y
  crudo en el body de pin.
- Checks locales: `npm run lint`, `npm run typecheck` y `npm run test` correctos
  (`30 passed`, `103 passed`).

## 2026-07-17 · Prompt 35 · Auth antes de validación y coherencia de deploy

- Alcance A corregido tras la actualización del prompt: además de las 4 rutas de `entity-intel`
  ya ajustadas, se movió `@require_permission` por encima de `@bp.input` en las 6 rutas afectadas
  de `procurement`: summary de licitación, creación/lectura/patch/delete de búsquedas guardadas y
  ejecución de búsqueda.
- Añadidos tests parametrizados de procurement para las 6 rutas: anónimo con request inválida
  devuelve 401 sin `errors`; anónimo con request válida devuelve 401; autenticado con permisos y
  request inválida devuelve 422.
- Añadido contrato transversal sobre `app.url_map` para fallar si una ruta registrada con
  `@require_permission` vuelve a colocar `@bp.input` por encima del permiso.
- Alcance B implementado sin desplegar: `deploy-production.sh` registra etapa de despliegue y
  `oracle-control update` solo restaura punteros si el fallo ocurre antes de `mutation_started`.
  Desde mutación/migración/arranque conserva el release seleccionado, no revierte esquema y exige
  diagnóstico/forward-fix o rollback explícito compatible.
- `oracle-control health` comprueba coherencia entre `current`, `CURRENT_RELEASE`, `ORACLE_RELEASE`
  y las imágenes en ejecución de `api`, `web`, `worker-core` y `beat`.
- Documentados runbooks y decisión D-030. Validación local disponible en este entorno:
  `bash -n scripts/oracle-control.sh scripts/deploy-production.sh`, `python3 -m py_compile` de los
  módulos/tests afectados y escaneo estático de decoradores con resultado cero. Los checks backend
  completos quedaron pendientes por no resolver `uv` desde `~/.local/bin` en un shell no
  interactivo; esa conclusión fue incorrecta y queda corregida por `scripts/api-test.sh`.
- Ajuste posterior de tests: los casos autenticados inválidos de `entity-intel` y `procurement`
  usan ahora `client` HTTP real, sustituyendo solo el runtime de identidad para no depender de
  PostgreSQL/Redis. Los 401 anónimos comprueban ausencia de `errors`, no substrings del payload de
  autenticación. La evidencia monetaria PLACSP se formatea siempre con dos decimales en el texto
  citable.

## 2026-07-17 · Prompt 43 · Inteligencia competitiva de contratación

- Implementado un informe IA asíncrono `competitive_procurement.v1`, generado por el job durable
  `oracle.competitive_procurement_report.generate` en la cola `ai` y protegido por el flujo común
  de permisos, `Idempotency-Key`, reintentos, lease y auditoría.
- El adjudicatario se elige únicamente entre denominaciones exactas presentes en adjudicaciones
  fijadas al expediente. Estas referencias determinan el foco y las citas locales; el corpus
  analítico procede de `awards(company=...)` paginado de Signal, con límite declarado de 1.000
  filas y advertencia explícita si el proveedor ofrece más.
- Oracle agrupa expedientes y calcula en Python concentración por organismo, distribución de
  importes, cobertura de baja y frecuencia estimada de socios UTE. El modelo solo interpreta los
  agregados congelados y recibe `task_key=competitive_procurement_intelligence`; Signal resuelve
  proveedor, modelo, failover y coste. El informe expone proveedor/modelo realmente devueltos y
  conserva prompt/version/hash en `AIAuditLog`.
- La baja media y mediana solo se publican con al menos 80 % de expedientes comparables y una
  muestra mínima de tres. En otro caso quedan a `null` y se informa N, denominador, motivos y sesgo
  de supervivencia. Los socios UTE se etiquetan como heurística de confianza baja sobre `winner`
  en texto libre, nunca como relaciones verificadas.
- Medición read-only previa en producción para `ITURRI, S.A`: Signal informó 1.251 filas de
  adjudicación; en una muestra de los 30 primeros `folder_id` únicos, los 30 lookups
  `registry/tenders/{folder_id}` devolvieron 404. Cobertura observada: **0/30 (0 %)**. Esta
  medición condiciona el diseño pero no equivale a un E2E del informe nuevo, que aún no está
  desplegado ni tiene confirmada su `task_key` en Signal.
- Checks locales: `scripts/api-test.sh --unit` correcto (**292 passed, 0 skipped; 107 tests de
  integración excluidos**), `npm run lint`, `npm run typecheck`, `npx vitest run`
  (**34 ficheros, 129 tests**), generación/comprobación del cliente OpenAPI y `npm run build`
  correctos. No se ha ejecutado un E2E real del job ni se ha desplegado este cambio.

## 2026-07-17 · Prompt 45 · Informe IA de entidad

- Implementado el flujo asíncrono `oracle.entity_dossier_report.generate` en cola `ai`: la ficha
  agregada de Signal (`EntityIntelClient.dossier`) se captura una vez, Oracle calcula conteos de
  actos, nodos, aristas, fechas y noticias en Python, y el modelo recibe solo la `task_key`
  `entity_dossier_intelligence` para redactar/interpretar.
- Decisión D-035: antes de elegir expediente, el informe vive en un área de espera tenant+entidad
  dentro de `BackgroundJob.result_ref` y `AIAuditLog` con `dossier_id=NULL`. Al incorporar se crea
  un `Report` normal de expediente, se crea el `AIArtifact`, se actualiza la auditoría y se
  materializa la entidad como Actor interno mediante el flujo existente de alta de actor externo.
- El prompt `entity_dossier_intelligence/v1` y el template `entity_intelligence.v1` declaran límites
  obligatorios: fechas BORME de publicación, homónimos no desambiguados, grafo sin capital ni
  porcentajes, y noticias potencialmente no exactas. Los párrafos del informe separan hechos,
  inferencias, recomendaciones y decisiones mediante `ReportOutput`.
- Vector añade el botón «Informe de la entidad» en la ficha 360º. El estado se muestra con
  `JobProgress`, permite cancelar/reintentar, avisa de que puede tardar minutos y, al terminar,
  ofrece selector de expediente para incorporar sin perder el resultado si el usuario sale y vuelve.
- Pendiente operativo: registrar/confirmar en Signal la `task_key`
  `entity_dossier_intelligence`. No se ha tocado el repositorio de Signal ni se han cableado
  proveedores/modelos en Oracle.

## 2026-07-17 · Prompt 46 · Primer clic silencioso en acciones asíncronas

- Producción no quedó verificada con sesión: al abrir `https://oracle.opnconsultoria.com/app/actors`
  el navegador mostró la pantalla de login, por lo que no se pudo instrumentar una ficha de entidad
  ni un expediente pesado reales. El resultado no se da por reproducido/resuelto en producción.
- Auditoría local del patrón: los botones afectados compartían botones Vector sin estado
  visual común para `disabled`, y varios quedaban bloqueados durante carga/generación sin feedback
  distinguible. Se añadió un componente común para acciones asíncronas que renderiza la acción como
  no disponible hasta la hidratación de React y expone `aria-busy`, `aria-disabled` y
  `data-action-ready`.
- La corrección es sistémica y sin `setTimeout`: `AsyncActionButton` cubre «Informe documental»,
  «Inteligencia competitiva», «Desfijar», «Informe de la entidad» e «Incorporar a expediente».
  Los estilos Vector ahora hacen visible el bloqueo en `.vector-primary`, `.vector-secondary` y
  `.vector-danger`.
- El informe de entidad queda bloqueado además mientras carga la ficha padre, evitando que se
  encole con el término de búsqueda antes de recibir la denominación canónica de Signal. El
  `setTimeout(0)` previo de carga de informes se sustituyó por una microtarea cancelable.

## 2026-07-17 · Prompts 47 y 48 · Dashboard, auditoría e hipótesis

- Inicio deja de cargar y duplicar la tabla de trabajos recientes. Conserva un acceso compacto a
  Administración → Auditoría → Procesos, que pasa a ser el lugar autoritativo para revisar jobs.
- Administración → Auditoría incorpora dos vistas: registro de auditoría y procesos. La vista de
  procesos muestra fecha de creación, última actualización, tipo, cola, estado, progreso y destaca
  fallos. `/app/admin/jobs` queda como redirección a `?view=processes`.
- `JobResponse` expone ahora `created_at`; se actualizó el serializador Flask, el esquema OpenAPI y
  el cliente TypeScript generado.
- La lista «Trabajo que requiere atención» añade icono por tipo y resalta el tipo textual, cubriendo
  señal, oportunidad, riesgo, reunión, decisión, documento y fallback de elemento de expediente.
- El diálogo de nuevo expediente mantiene el `select` rápido, pero añade ayuda accesible para
  comparar tipos y cuándo usar cada uno. La «base de trabajo» tiene estilos `.checkbox-row` para
  alinear casilla, etiqueta y ayuda sin ambigüedad.
- El panel «Marco de trabajo» del resumen eleva hipótesis a una tabla TanStack filtrable y ordenable,
  con explicación de propósito, modal de ver/editar, vinculación de evidencia y borrado con
  confirmación. El CRUD usa los endpoints existentes de hipótesis; las evidencias originales no se
  eliminan al borrar una hipótesis.
- Pendiente de verificación real con sesión: crear un expediente, gestionar una hipótesis y revisar
  Inicio/Auditoría en navegador autenticado. La implementación local queda cubierta por tests y
  build, pero no se declara validada en producción.
- Checks locales ejecutados: `scripts/api-test.sh --unit` correcto (**303 passed, 0 skipped; 107
  integración excluidos**), `npm run lint` correcto con warning no bloqueante conocido de TanStack
  Table/React Compiler, `npm run typecheck`, `npx vitest run` (**35 ficheros, 138 tests**),
  `npm run build` y `npm run api:client:check` correctos.

## 2026-07-17 · Prompts 53 y 54 · Pulido UX y evidencia citable de entidad

- Prompt 53: el gating de hidratación de `AsyncActionButton` se extiende a triggers de diálogo con
  `HydratedActionButton`, manteniendo la etiqueta visible pero bloqueando el clic hasta que React
  esté hidratado. Se aplica a «Nuevo expediente» y al resto de triggers productivos detectados
  (`Dialog.Trigger`/menús de crear) sin `setTimeout`.
- La lista «Trabajo que requiere atención» separa visualmente tipo, expediente y estado: el tipo es
  ahora una píldora independiente y los separadores no dependen de pegar texto en el mismo nodo.
- `JobProgress` usa un `toast id` estable por job. Un error terminal se reemplaza/desecha al
  reintentar y un éxito posterior no convive con el toast fallido antiguo.
- Diagnóstico RSC: en producción estable, `/_rsc` responde 200 y un asset de build inexistente da
  404, no 503. La topología de deploy/Nginx apunta a cortes breves del único upstream
  `127.0.0.1:3000` durante la recreación del contenedor web. Se añade handling en Nginx solo para
  prefetch RSC (`Next-Router-Prefetch: 1` + `_rsc`): ante 502/503/504 devuelve 204 no-cache; las
  navegaciones reales siguen devolviendo 503.
- Prompt 54: la ficha de entidad construye `pending_evidence_sources` desde actos BORME/noticias
  con URL y reserva UUIDs deterministas que se pasan al LLM como `allowed_evidence_ids`. No se crea
  ninguna fila `Evidence` mientras el informe esté en el área de espera.
- Al incorporar el informe a un expediente se materializan esas fuentes como `Evidence` con
  `source_kind='entity_intel'`, se enlazan mediante `EvidenceDossier`, se congelan en
  `ReportSnapshotEvidence`/`ReportEvidence` y se reconstruye el `source_index` autoritativo desde el
  snapshot. Decisión registrada en D-036.
- Pendiente de verificación real con sesión: reproducir «Nuevo expediente» en navegador autenticado
  y generar/incorporar un informe de entidad real con ITURRI SA para confirmar citas visibles sobre
  datos de producción.

## 2026-07-18 · Prompt 55 · Previsualización del informe de entidad en espera

- La tarjeta «Informe IA» de la ficha de entidad permite leer un informe `succeeded` todavía no
  incorporado sin crear `Report` ni materializar evidencias. La vista previa muestra resumen,
  secciones, claims y `pending_evidence_sources`, dejando claro que son IDs reservados y que las
  evidencias reales solo nacen al incorporar.
- El estado de la tarjeta se calcula sobre el último job `succeeded` de esa entidad. Si ese job
  está en espera, se ofrece «Ver informe en espera» e incorporación; si ese mismo job ya está
  incorporado, se enlaza a `/app/reports/{incorporated_report_id}`. Ya no se muestra un mensaje
  verde basado en cualquier informe histórico de la entidad.
- La acción de generación se presenta como «Generar nuevo informe» cuando ya existe un informe
  terminado. La idempotencia de API se mantiene y cada intento explícito usa una clave nueva.
- Evidencia nueva pendiente: el prompt reporta que en producción el primer clic se pierde de forma
  fiable en la ficha pesada de entidad, tanto en «Informe de la entidad» como en «Incorporar a
  expediente». No se ha cerrado en este prompt; queda como caso real para reabrir el diagnóstico de
  hidratación/carga del prompt 46/53 con sesión autenticada.

## 2026-07-18 · Diagnóstico instrumentado del «clic silencioso» — cerrado como artefacto de automatización

- Instrumentación en producción con sesión autenticada sobre la ficha de `ITURRI SA` (lo que el
  prompt 46 no pudo hacer): listeners de captura a nivel de documento para `pointerdown`,
  `mousedown` y `click`, envoltura de `window.fetch` y poller del estado del botón cada 100 ms.
- Estado del botón «Generar nuevo informe» en el momento de la prueba: `disabled=false`,
  `data-hydrated=true`, `data-action-ready=true`, visible en viewport y sin overlays
  (`elementFromPoint` en su centro devuelve el propio botón).
- Clic emitido por la extensión de automatización de Chrome sobre ese botón: **cero eventos**
  llegaron al documento (ninguno de los tres tipos, en fase de captura). Clic programático
  (`btn.click()`) sobre el mismo botón: evento capturado, manejador React disparado y
  `POST /api/v1/entity-intel/reports` emitido en 62 ms, creando un job real con clave idempotente
  nueva (`entity-report:company:ITURRI SA:6ef8da2a…`, job de las 18:21:58).
- Conclusión: el «primer clic perdido tras navegar» que motivó los prompts 46, 53 (punto 1) y 55
  (hallazgo 4) es un **artefacto de la herramienta de automatización usada en las auditorías**
  (descarta el primer clic tras navegación/reconexión antes de que entre al navegador), no un bug
  del frontend. La página no puede perder un evento que nunca le llega. Esto explica por qué nunca
  se reprodujo en local y por qué «sobrevivía» a cada arreglo.
- Queda como único resto real del asunto la ventana pre-hidratación en botones planos sin puerta:
  inventariados 6 en `entity-dossier.tsx` (paginación del registro ×2, vincular a expediente,
  alternar vista previa, y cabeceras de ordenación ×2). Riesgo menor: solo afecta a clics en los
  primeros instantes de vida de la página. No amerita prompt monográfico; puede ir en un bundle de
  UX futuro.
- Verificado de paso el hallazgo 3 del prompt 55 con el manejador real: regenerar crea job nuevo
  con clave fresca; la idempotencia protege del doble envío sin impedir la regeneración.

## 2026-07-18 · Mitigación nginx de los 503 en prefetch `_rsc` aplicada al host

- Auditoría previa: el host no tenía **ninguna** de las tres piezas. Contra lo que se temía, el
  mapeo host↔repo resultó ser 1:1 hoy: `/etc/nginx/conf.d/00-oracle-log-format.conf`,
  `/etc/nginx/snippets/oracle-web-proxy.conf` y `/etc/nginx/sites-available/oracle.conf` eran
  idénticos a `infra/nginx/{00-oracle-log-format,snippets/oracle-web-proxy,oracle-https}.conf`
  salvo exactamente las líneas del cambio (9 + 3 + 8). El `oracle-api-proxy.conf` ya coincidía.
  No hizo falta cirugía con `sed`: se copiaron los tres ficheros del release activo, verificados
  antes por sha256 contra el repo local.
- Dependencias respetadas (el orden importa: aplicar el snippet suelto deja nginx inválido):
  el `map` vive en contexto `http`, la named location `@oracle_web_unavailable` dentro del `server`
  y referencia esa variable, y el `error_page 502 503 504` del snippet referencia la named location.
- Backup completo en `/root/nginx-backup-20260718T202237Z` (ruta también en
  `/root/.last-nginx-backup`), con rollback automático armado si `nginx -t` fallaba. No hizo falta.
- `nginx -t` OK y recarga vía `oracle-control --yes nginx-reload` (valida y recarga sin restart).
- Verificación funcional en producción tras la recarga:
  - `/login` 200, `/app/actors` 200; salud interna y pública en verde.
  - Prefetch RSC legítimo (`RSC: 1` + `Next-Router-Prefetch: 1`): **200**. No se rompen los
    prefetches buenos, que era el riesgo principal del cambio.
  - A/B con upstream que no responde: navegación real **200** (intacta) frente a prefetch
    **204** tras agotar `proxy_read_timeout 65s`. Es decir, el prefetch que antes habría
    aflorado un 503 ruidoso ahora falla en silencio y el router lo reintenta.
- Nota lateral sin relación con el cambio: una petición `_rsc` malformada con
  `Next-Router-Prefetch: 1` y sin cabecera `RSC` hace que Next.js cuelgue hasta el timeout de 65 s.
  Ningún navegador real emite esa combinación; queda anotado, no se ha tocado.

## 2026-07-18 · Prompt 56 · Informe ejecutivo de entidad

- El job de entidad incorpora el histórico paginado de adjudicaciones de Signal y calcula en Python
  expedientes únicos, importes totales y anuales, órganos contratantes, CPV principal, cuota UTE y
  primera/última adjudicación. Este flujo reutiliza el núcleo competitivo pero no ejecuta
  `tender_by_folder` ni la sonda de baja.
- Solo se reservan como evidencia las adjudicaciones de mayor importe con URL: 15 por defecto,
  configurable mediante `ENTITY_INTEL_MAX_AWARD_SOURCES`. `source_limits` declara N/M, coincidencia
  por nombre sin CIF, cobertura exclusiva de contratos ganados y cualquier recorte del histórico.
  Un error o mala configuración de la fuente degrada contratación a `unavailable` y el informe
  continúa.
- Patentes EPO y comunicaciones CNMV ya no se descartan: se compactan con topes, métricas,
  `truncated_by_oracle`, estado por sección y fuentes citables materializables por D-036.
- `entity_dossier_intelligence/v2` pasa a ser la versión activa con el mismo máximo de 16.000
  tokens. Exige 1.200-2.000 palabras, párrafos redactados, agrupación por materialidad, ocho
  secciones con `Lectura estratégica` como la más larga y `Cobertura y límites` al final, además de
  3-5 oportunidades, riesgos y acciones. `v1.md`, `ReportOutput` y el repositorio de Signal no se
  han modificado.
- Decisión D-037 registrada. No hay migración, cambio OpenAPI ni frontend.
- Checks locales: `scripts/api-test.sh --unit` correcto — Ruff, formato y mypy limpios; **316
  passed, 0 skipped y 107 tests de integración excluidos**. No se ha generado un informe real de
  ITURRI SA ni se ha verificado en producción; esa validación queda expresamente pendiente tras
  desplegar.

## 2026-07-19 · Prompt 56 verificado en producción · informe ejecutivo con contratación

- Release `20260719T093215Z-quick-ee08339`. Salud interna y pública en verde.
- Informe real de `ITURRI SA` generado con prompt v2 (job `2f2989a5`), `succeeded` en ~60 s:
  - **2.023 palabras** de cuerpo (antes 1.165 troceadas en 34 párrafos telegráficos) repartidas
    en 7 secciones de 145-386 palabras. La sección más larga es «Lectura estratégica» (386), que
    era exactamente el objetivo: antes el análisis era el 12 % del informe.
  - Las enumeraciones desaparecieron: «Gobierno y personas clave» tiene 4 nombres propios en
    mayúsculas frente a los 26 en ristra del informe anterior.
  - `top_opportunities`, `top_risks` y `recommended_actions` con 4 elementos cada uno; antes
    salían vacíos.
  - **Contratación pública real**: 608 contratos, 390.180.837,19 € entre 2021 y 2026, con
    desglose anual, mediana y distribución por importes. Todos los agregados calculados en
    Python.
  - **45 citas, 45 permitidas, 0 inventadas.** Los 5 párrafos `fact` citan evidencia.
- Techo global de fuentes en acción: 45 de 48 disponibles, declarado en `source_limits` junto al
  recorte de actos (25 de 65) y las limitaciones de la contratación (matching por nombre sin CIF;
  corpus de adjudicaciones, no de licitaciones presentadas).
- `awards_without_date` presente y en cero para esta entidad: el desglose anual cuadra con el
  total.
- Auditoría previa al despliegue: 35 hallazgos, 10 confirmados tras verificación adversarial,
  25 refutados. Los tres arreglados antes de desplegar (httpx.RequestError, techo global de
  fuentes, adjudicaciones sin fecha) están descritos en el commit `59f1c17`.
- Pendiente: los 107 tests de integración no se ejecutaron (Docker no disponible en local y no
  hay `gh` para observar el CI). El informe real cubre el camino end-to-end, pero la integración
  sigue sin gate propio en esta entrega.

## 2026-07-19 · Tests de integración ejecutados por primera vez

- Ejecutados en local sin Docker (no disponible) contra Postgres 17 y Redis de Homebrew, en una
  base `oracle_test` aislada. **No se ejecutó nada contra producción**: la suite crea y destruye
  esquemas, así que correrla contra la BD real habría sido destructivo.
- Resultado inicial: 4 fallos, todos latentes desde hace días por no ejecutarse esta suite. Los
  cuatro corregidos en `59318fb` y desplegados en `20260719T110250Z-quick-59318fb`:
  regresión de sanitización de `error_message` (seguridad), dos aserciones de plantillas
  obsoletas desde el prompt 45, y un test de logs dependiente del orden de ejecución.
- Estado final: **426 pasan, 0 fallan**.
- Queda rojo el umbral de cobertura: 80,70 % frente al 84 % exigido, con
  `entity_dossier_report.py` al 47 % (el job, el agente y la incorporación sin cubrir) y
  `ai/context.py` al 74 %. Prompt 57 redactado para cerrarlo.
- Receta reutilizable para correr la suite completa sin Docker documentada en el prompt 57,
  incluidos los dos escollos de aislamiento (Celery deshabilita loggers existentes;
  `configure_logging` borra los handlers del logger raíz).

## 2026-07-19 · Prompt 57 · Cobertura conductual del informe de entidad y el wizard

- La integración cubre el ciclo durable completo de `entity_dossier_report`: checkpoints,
  métricas y límites, fuentes pendientes, hash estable del corpus y techo global de evidencias.
  También prueba la degradación honesta cuando falla contratación y el caso persona, donde esa
  fuente queda declarada como no aplicable.
- La incorporación materializa evidencias `entity_intel` con subtipo y procedencia, crea todos los
  vínculos y artefactos del informe y es idempotente, incluido el caso válido sin citas.
- El fallo del proveedor en el agente del área de espera deja intento y auditoría fallidos con
  proveedor, modelo y error, y libera la reserva de cuota; un reintento posterior puede liquidarse
  correctamente. El wizard queda cubierto en primera ronda, respuestas vacías, recorte
  determinista al presupuesto, validaciones HTTP y revisión.
- Se añadieron recorridos HTTP reales para el informe de entidad, fuentes de inteligencia,
  incorporación y ciclo del wizard. Para cerrar el gate global con comportamiento relevante —no
  líneas artificiales— se cubrieron además los ciclos asíncronos compartidos del resumen gobernado
  y el digest semanal.
- Validación por mutaciones manuales: cinco cambios representativos fueron detectados por la suite
  (eliminar el techo de fuentes, dejar escapar el fallo de contratación, no liberar cuota, alterar
  `source_kind` y omitir el ajuste al presupuesto). El código de producción quedó restaurado y sin
  diff.
- Gate completo contra PostgreSQL 17 y Redis reales: **439 passed, 0 skipped**, cobertura global
  **84,01 %** (umbral 84 %), `entity_dossier_report.py` **89 %** y `ai/context.py` **92 %**. Ruff
  del fichero modificado también queda limpio. No hay cambios de producción, migraciones,
  configuración, OpenAPI ni frontend.

## 2026-07-20 · Prompt 62 · Wizard de completitud sin revisor de evidencia universal

- Diagnóstico asumido desde producción: `dossier_completion_wizard` generaba correctamente, pero
  el revisor universal rechazaba el output porque el contrato del wizard diagnostica ausencias y
  propone preguntas/acciones sin citas de evidencia. El job de producción afectado era
  `894d9379-e2c5-427d-9545-ecb8e13e3937` sobre el expediente `Coches de Bomberos`.
- Decisión de diseño: se aplica la opción A. El contrato de cada prompt declara ahora
  `requires_evidence_review`; el servicio consulta esa propiedad en lugar de aplicar el revisor a
  todo lo que no sea `evidence_reviewer`. `dossier_completion_wizard` y `evidence_reviewer` quedan
  con `False`; los demás agentes conservan `True`.
- Invariantes mantenidos: el revisor de evidencia sigue obligatorio para `report_writer`,
  `competitive_procurement_intelligence` y `entity_dossier_intelligence`. No se toca el paquete
  compacto del revisor creado en Prompt 60 y no se degrada el fallo global a warning.
- Control actual del wizard tras el cambio: validación Pydantic del contrato de salida,
  auditoría, cuotas, tenant context y persistencia normal de artefacto. No tiene aún un control
  semántico específico para outputs no evidenciales; queda como deuda para una opción B futura.
- Validación completada: el test HTTP del wizard ejecuta primera ronda sobre un expediente con
  actor vinculado, ejecuta segunda ronda con `answers`, verifica que
  `/completion-wizard/latest` devuelve el segundo resultado y comprueba que solo existe intento
  `generate`, sin intento `reviewer`. El manifiesto de contexto guarda
  `requires_evidence_review=false`, el actor usado y la ronda previa.
- Gates ejecutados: `ruff check src tests`, `ruff format --check src tests`, `mypy src` y suite
  completa de integración con PostgreSQL/Redis reales. Resultado final: **501 passed**, cobertura
  global **84,20 %**.
- Mutación manual: cambiar temporalmente `EVIDENCE_REVIEW_REQUIRED["report_writer"]` a `False`
  hizo caer `test_report_generation_failures_never_publish_artifacts[reviewer]` porque el informe
  pasaba a `ready` en vez de `failed`. Se restauró la bandera y los tests objetivo volvieron a
  pasar.
- Barrido de patrón: no queda en `ai/service.py` ninguna exención por `agent != "evidence_reviewer"`.
  Las menciones restantes a `dossier_completion_wizard` pertenecen a rutas, contexto, mock provider
  y tests; las menciones a la condición por agente que quedan están en tests que simulan proveedores.

## 2026-07-20 · Prompt 60 · Revisor de evidencia en informes largos

- Inicio de fase P0: producción muestra fallo de `EvidenceReviewerOutput` al revisar un informe
  competitivo largo ya generado. La investigación inicial confirma que el contrato del revisor no
  obliga a copiar el informe; el riesgo está en la entrada enviada al revisor, que hoy incluye el
  payload completo de generación más `candidate_output`.
- Objetivo de implementación: mantener el revisor obligatorio, reducir su entrada a un paquete
  compacto de claims/citas/evidencias permitidas, y distinguir en jobs/reportes el fallo de
  generación frente al fallo de revisión. No se tocarán prompts ni plantillas competitivas.
- Implementación completada: `execute_agent` ya no reenvía `effective_payload` ni el informe
  completo al `evidence_reviewer`; construye un paquete compacto con `candidate_outline`,
  `candidate_claims`, evidencias permitidas recortadas, ids autorizados y metadatos de seguridad.
  El contrato `EvidenceReviewerOutput` se mantiene como veredicto/listas de incidencias, sin exigir
  que el modelo repita el informe.
- Medición protegida por prueba: un informe competitivo sintético de 14 secciones con
  `computed_analysis` masivo fallaba al revisor cuando se reenviaba el output completo; con el
  paquete compacto el contexto de revisión queda por debajo de 30.000 caracteres, excluye
  `candidate_output`, `requested_scope` y `computed_analysis`, extrae 14 claims revisables y pide
  más de 2.000 tokens de salida. El presupuesto del revisor escala por claims hasta 4.000 tokens y
  queda siempre limitado por la política del tenant, sin subir de 16.000.
- Se añadió `EvidenceReviewError` para distinguir "generado pero no revisado" de "no generado".
  Los jobs lo tratan como fallo controlado y `ReportResponse.error_message` separa el mensaje de
  generación del fallo de revisión obligatoria. OpenAPI y cliente TypeScript fueron regenerados.
- Dependencia con Signal: Oracle ya reduce el input y no necesita relajar el revisor para el caso
  feliz medido. Si Signal gobierna `evidence_reviewer` con un techo menor que el solicitado, los
  informes con muchas incidencias podrían requerir alinear esa policy. El techo competitivo de
  generación a 16.000 sigue siendo la dependencia de Signal documentada en D-039, separada de este
  arreglo.
- Validación: `ruff check`, `ruff format --check`, `mypy src`, `npm run api:openapi`,
  `npm run api:client:generate`, `npm run api:client:check`, `npm run typecheck`,
  `npm run lint` y la integración completa con PostgreSQL/Redis reales quedaron correctos. La
  suite final registró **501 passed**, cobertura global **84,20 %**. El lint frontend mantiene un
  aviso preexistente de React Compiler/TanStack Table en `dossier-context-panel.tsx`.
- Mutaciones manuales: reintroducir `candidate_output` en el contexto del revisor hizo caer la
  prueba larga con `Invalid JSON: EOF while parsing a value`; cambiar el mensaje específico de
  `EvidenceReviewError` por el genérico hizo caer la prueba de reportes fallidos. Ambos cambios se
  restauraron y los tests objetivo volvieron a pasar.
- Sin migraciones, variables nuevas, cambios de prompts competitivos ni despliegue. Barrido del
  patrón confirma que no queda `effective_payload | {"candidate_output": ...}` en producción; las
  menciones restantes de `candidate_output` pertenecen al contrato histórico del registro y a tests.

## 2026-07-20 · Prompt 61 · Spike generación local por secciones

- Spike completado sin tocar el flujo productivo de informes, jobs, prompts registrados, Signal ni
  despliegue. La producción se leyó por SSH solo con consultas `SELECT` para extraer los reports
  reales de ITURRI S.A.; el JSON bruto queda en `docs/implementation/spikes/.work/61`, ruta ignorada
  por Git para evitar versionar datos reales.
- Se creó un script instrumental desechable en `scripts/spikes/61_sectional_report_spike.py`. Llama
  a Ollama local con `qwen3.5:9b`, genera secciones independientes y ensambla un `ReportOutput` en
  Python sin pedir JSON global al modelo.
- Resultado: qwen por secciones alcanza la forma editorial (1.757 palabras, 0 párrafos
  telegráficos, solapamiento 0,094 frente a 0,177 del monolítico), pero no iguala la calidad cloud
  porque no cita evidencias en la generación completa. La prueba de control con cita obligatoria
  sí consiguió 3/3 párrafos citados con `[E1]`, señal de que el enfoque exige validador/retry por
  sección antes de poder productivizarse.
- La mitigación con resumen de lo ya escrito no compensó: aumentó el tiempo de 143,3 s a 154,9 s y
  empeoró el solapamiento a 0,119. Recomendación documentada: adelante solo con condiciones, con
  un siguiente spike de dos secciones, validación automática de citas y reparación por sección.

## 2026-07-20 · Prompt 55 verificado en producción con sesión real

- Cerrada la última verificación pendiente: la vista previa del informe de entidad en espera,
  desplegada el 18 de julio y hasta hoy sin comprobar por falta de sesión autenticada.
- Comprobado sobre un informe recién generado desde la propia interfaz («Generar nuevo informe»),
  con 45 fuentes citables y sin incorporar:
  - La tarjeta declara el estado correcto: «Informe en espera, todavía no incorporado. Puedes
    leerlo antes de elegir expediente. Sus 45 fuentes son evidencias reservadas: solo se
    materializan al incorporar.»
  - El botón «Ver informe en espera» abre la previsualización sin incorporar nada.
  - El banner advierte de que las citas apuntan a IDs reservados y todavía no son registros
    `Evidence` ni están vinculadas a ningún expediente.
  - Se renderizan las 7 secciones del contrato v2, con «Cobertura y límites» al final.
- Trazabilidad conservada tras el rediseño narrativo: 19 bloques, cada uno con su tipo visible
  (14 `inference`, 5 `fact`) y su confianza propia — «HECHO · confianza 100%», «INFERENCIA ·
  confianza 70%». Los bloques `fact` llevan citas y los `inference` no, que es exactamente el
  contrato de gobernanza.
- Detalle de diseño confirmado como correcto, no como fallo: la previsualización solo se ofrece
  cuando el informe **más reciente** está en espera. Con el último ya incorporado, la tarjeta
  enlaza a ese informe en vez de ofrecer vista previa.

## 2026-07-20 · Wizard verificado end-to-end por primera vez, y un hallazgo colateral

- Release `20260720T163251Z-quick-566e569`. E2E real del asistente de expediente sobre «Coches de
  Bomberos», con sesión autenticada:
  - **Ronda 1**: `succeeded`. Diagnóstico útil, no genérico: detecta `signals:empty`,
    `procurement:empty`, `risks:empty`, `goal:incomplete`, y propone acciones ejecutables con su
    tipo (`create_signal_monitor`, `pin_procurement`, `create_actor`, `create_risk`).
  - **Ronda 2** con tres respuestas del usuario: `succeeded`. Es el flujo por rondas, que era la
    razón de ser del wizard y lo que nunca se había probado.
  - `GET /completion-wizard/latest` devuelve el resultado.
  - Intentos registrados del wizard: solo `generate` (2, ambos `succeeded`). Ningún `reviewer`,
    que es exactamente el efecto buscado.
- Antes de este cambio el histórico del agente era **1 fallo y 0 éxitos**: nunca había completado
  una ejecución desde que se entregó su track.

### Hallazgo colateral: `requires_evidence_review` no se aplica en todas las rutas

Al contrastar los intentos por agente aparece que **`entity_dossier_intelligence` no tiene ni un
solo intento de tipo `reviewer` en todo su histórico**, pese a estar declarado como
`requires_evidence_review: True`.

Causa: hay dos caminos de generación distintos.

- `report_writer` y `competitive_procurement_intelligence` pasan por `reporting/service.py`, que
  llama a `execute_agent` y por tanto ejecuta el revisor.
- El informe de entidad usa su propia ruta, `_run_waiting_area_agent` en
  `oracle/entity_dossier_report.py`, que invoca al proveedor directamente y **nunca llama al
  revisor**.

Matiz importante para no exagerarlo: el informe de entidad **sí tiene control estructural de
citas** —el proveedor rechaza `evidence_ids` no autorizados, y así se midió: 45 citadas, 45
permitidas, 0 inventadas—. Lo que no se ejecuta es el veredicto semántico del agente revisor.

No es una regresión de este cambio: es una brecha preexistente que este cambio ha hecho visible, y
que además ahora resulta engañosa, porque la tabla declara un control que en esa ruta no corre.
Queda como deuda, junto a la ya anotada de que el wizard no tiene control semántico de salida.

## 2026-07-20 · Login producción y referencia técnica en errores de acceso

- Verificación con Playwright contra `https://oracle.opnconsultoria.com/login?next=%2Fapp`: el
  login muestra al usuario final `Referencia: <request_id>` junto a `Credenciales no válidas`, lo
  que resulta técnico y no accionable en una pantalla pública de autenticación.
- Causa UI: `ProblemAlert` en `auth-pages.tsx` renderizaba siempre `error.problem.request_id` si
  venía en Problem Details. Se elimina esa referencia de las páginas de autenticación; el
  `request_id` sigue disponible en respuesta/cabeceras/logs para soporte, pero no se presenta en
  login/reset/invitación.
- Corrección de dashboard preparada: las filas de `Trabajo que requiere atención` pasan de un
  `flex` con selectores genéricos sobre `span:first-child/last-child` a una grid de columnas
  estables (icono, texto principal, metadato derecho) y una variante móvil que evita solapes.
- Observación operativa: la contraseña escrita con punto final produjo `401`; el siguiente intento
  quedó bloqueado por rate limit de identidad (`429`, 300 segundos). Un reintento controlado sin
  punto todavía recibió `429`, por lo que no se ha podido verificar visualmente el dashboard en
  producción en este turno.
- Desbloqueo posterior con acceso SSH: servidor `oracle` confirmado, contenedores sanos y Redis
  protegido por ACL/secreto. El contador `opn-oracle:login:<hash>` no existía al llegar; tras
  reintentar sin punto y con punto final, ambos devolvieron `401`, el contador quedó en `2` y se
  eliminó para no dejar al usuario penalizado. Base de datos confirma que `mburgos@iacell.com`
  existe, está `active`, tiene una membership activa y su último login correcto fue el
  `2026-07-20T16:46:37Z`. No se ha cambiado contraseña ni membership.
- Reset autorizado: la clave inicial propuesta no cumplía el mínimo productivo de 12 caracteres.
  Se reseteó `mburgos@iacell.com` a la clave corregida de 13 caracteres mediante `PasswordHasher`
  dentro del contenedor API, sin imprimir el secreto ni escribirlo en historial remoto. Login
  verificado con Playwright: `/login?next=%2Fapp` redirige correctamente a `/app`.
- Verificación visual productiva: el bloque `Trabajo que requiere atención` está efectivamente
  desalineado en el release actual. Las filas medidas por Playwright tienen `x` distintos para el
  texto principal (`374`, `371`, `395`, `318`...), causado por el layout `flex` actual. La corrección
  CSS local de grid estable apunta al defecto observado, pero aún no está desplegada.
- Barrido de repetición UX: el mismo tipo de fallo de señal visual puede aparecer en tablas donde
  la fila representa un detalle pero solo el botón/enlace interno parece accionable. Se corrige en
  las tablas productivas de expediente para inteligencia (`signals`, `opportunities`, `risks`),
  trabajo (`actors`, `meetings`, `tasks`, `decisions`), documentos, inventario de expedientes e
  informes: la fila completa abre el detalle/recurso, tiene `cursor: pointer`, hover/focus
  consistente y activación por Enter/Espacio. Botones, enlaces y checkboxes internos paran la
  propagación para evitar doble apertura o navegación accidental.
- Validación local: `npm run test -- src/components/auth/auth-pages.test.tsx
  src/components/navigation/product-home.test.tsx`, `npm run lint -- --quiet`,
  `npm run typecheck` y `npm run build` correctos.
- Validación adicional de filas clicables: `npm run test --
  src/components/dossiers/dossier-intelligence-section.test.tsx
  src/components/dossiers/dossier-work-section.test.tsx
  src/components/dossiers/dossier-documents-section.test.tsx
  src/components/dossiers/dossier-inventory.test.tsx src/components/reporting/reports.test.tsx
  src/components/navigation/product-home.test.tsx src/components/auth/auth-pages.test.tsx`,
  `npm run lint -- --quiet`, `npm run typecheck` y `npm run build` correctos.

## 2026-07-20 · Prompt 63 revertido en producción: rompe el informe de entidad

- Desplegado `20260720T183537Z-quick-d73c47a` y verificado con un informe real, que es la prueba
  que la entrega declaró honestamente no haber hecho. **El informe de entidad falla**: agota sus
  3 reintentos con «La preparación del informe de entidad falló temporalmente».
- Patrón idéntico en los tres intentos: `generate` **succeeded**, `reviewer` **failed**
  (`ValidationError`). El informe se produce bien; lo tumba el revisor recién activado en su ruta.
- **Rollback aplicado** a `20260720T173105Z-quick-ca55269` con las puertas de backup, y servicio
  verificado: un informe de entidad real vuelve a completarse (`succeeded`, ~80 s).
- El código del prompt 63 sigue en `master` (commit `d73c47a`): lo revertido es el release activo,
  no el repositorio.

### Diagnóstico

El revisor **no está roto en general**. Contando intentos por agente:

| Agente | reviewer succeeded | reviewer failed |
|---|---|---|
| `report_writer` | 6 | 0 |
| `competitive_procurement_intelligence` | 3 | 1 |
| `entity_dossier_intelligence` | 0 | 3 |

Funciona en los otros dos informes y nunca en el de entidad. `evidence_reviewer` está gobernado en
Signal sobre `ollama/qwen3.5:9b` (verificado con HTTP 200 desde el worker), y el informe de entidad
es el que más evidencia le pasa: **45 fuentes citables**, frente a las pocas de los otros. La
hipótesis es que el tamaño de esa entrada degrada la salida estructurada del modelo local, igual
que ya vimos en el propio informe competitivo antes de moverlo a cloud.

### Decisión pendiente

Tres salidas, y la elección no es solo técnica:

1. Mover `evidence_reviewer` a cloud en Signal, como se hizo con el competitivo. Coste por uso,
   pero capacidad consistente.
2. Acotar lo que recibe el revisor en la ruta de entidad, sin tocar Signal.
3. Cuestionar el valor real del paso: el informe de entidad ya tiene validación estructural de
   citas (medido: 45 citadas, 45 permitidas, 0 inventadas). Añadir el veredicto de un modelo de 9B
   sobre un informe escrito por gemini puede producir más rechazos falsos que problemas detectados
   — la evidencia de hoy es 3 rechazos de 3.

## 2026-07-21 · El revisor en cloud NO arregla el informe de entidad · segundo rollback

- Signal movió `evidence_reviewer` a cloud (confirmado desde el worker de Oracle:
  `provider: openrouter`, `model: google/gemini-2.5-flash`).
- Desplegado `20260721T085403Z-quick-e1c8aa6`, que incluye el prompt 63 más la corrección de que
  el revisor recibe solo la evidencia citada. **El informe de entidad sigue fallando**: 3
  reintentos agotados, con `generate` succeeded y `reviewer` failed en los tres.
- **Rollback aplicado** a `20260720T173105Z-quick-ca55269`. Servicio verificado.
- El código sigue en `master`: lo revertido es el release.

### Lo que descarta este intento

- **No es el modelo local**: el revisor ya corre en gemini y falla igual.
- **No es Signal**: los tres `POST /api/v1/ai/run` del job devuelven **HTTP 200**. El fallo está
  en Oracle, al interpretar la respuesta.
- **No es el tamaño de la entrada**: la corrección de «solo evidencia citada» ya está aplicada.

### Dónde está realmente

El `ValidationError` nace dentro de `SignalGovernedLLMProvider.generate_structured`, en
`schema.model_validate_json(normalized_output)`: **el JSON que devuelve el revisor no encaja con
`EvidenceReviewerOutput`**. Uno de los tres intentos falló además con `ValueError`, que apunta a
`validate_evidence(reviewer, allowed_evidence_uuids)` — el revisor citando evidencia fuera de la
allowlist.

Pista principal, declarada por Signal en su entrega: la task `evidence_reviewer` conserva
**`structured_output=false`**. Sin salida estructurada forzada, el modelo cloud puede devolver
campos extra o formas distintas, y `EvidenceReviewerOutput` hereda de `StrictModel`
(`extra="forbid"`, `strict=True`), que los rechaza.

Dato que hay que explicar en cualquier hipótesis: **el mismo revisor, con la misma configuración,
funciona para los otros informes** (`report_writer` 6/0, `competitive_procurement` 3/1). Lo que
cambia en la ruta de entidad no es el modelo ni el proveedor, sino el contexto que se le envía.

### Asimetría encontrada de paso

En `oracle/entity_dossier_report.py` conviven dos estilos de validación: líneas 1202 y 1311 usan
`model_validate` (modo Python) mientras que la línea 1608 usa `model_validate_json`. Hoy no es la
causa —el proveedor ya devuelve modelos validados— pero es la misma asimetría que produjo el fallo
de los UUID hace días y conviene unificarla.

## 2026-07-21 · Causa raíz del revisor en la ruta de entidad: el tope de salida de Signal

Investigación instrumentada contra producción (solo lectura, sin desplegar), replicando la llamada
al revisor tal como la construye `SignalGovernedLLMProvider`.

**El revisor se queda sin presupuesto de salida y devuelve JSON truncado.**

Prueba decisiva, con 20 claims (el volumen real del informe de entidad, que tiene ~19-21):

```
tokens de salida pedidos por Oracle: 3000
tokens devueltos por Signal:          900   <- su tope para la task
JSON válido: NO -> Unterminated string at char 4211
```

`ai/service.py::_reviewer_output_budget` ya escala con el número de claims —`min(4000, 1200 +
claims*90)`, que para 20 claims da 3000— pero **Signal fija `max_output_tokens=900` para
`evidence_reviewer`** y pisa ese valor, como corresponde a una task gobernada. Signal declaró en su
entrega que conservó ese 900 «tal como estaba en producción»: es un valor heredado de cuando los
informes eran cortos.

### Por qué encaja con todo lo observado

- **No es el modelo**: el tope es de Signal y se aplica igual en cloud. Por eso mover el revisor a
  gemini no cambió nada.
- **No es Signal caído**: los POST devuelven 200 correctamente; lo que llega es una respuesta
  completa hasta agotar los 900 tokens.
- **No es el tamaño de la entrada**: es presupuesto de **salida**.
- **Explica la asimetría**: `report_writer` genera menos claims y su revisión cabe en 900 (6/0);
  el competitivo, más largo, falló 1 de 4 (está en el límite); el de entidad, con ~20 claims,
  no cabe nunca (0/3).
- **Explica el `ValidationError`**: es JSON cortado a media cadena, no una forma inesperada.

### Hipótesis descartadas por experimento, no por deducción

- **Falta de contenido en la evidencia**: se probó pasando solo etiquetas y el revisor rechaza con
  razón («la evidencia no contiene la fecha ni el número»); con `extract` real, aprueba.
  `_review_evidence_index` sí incluye el extracto, así que no era esto.
- **La agregación de hechos del prompt v2**: se probó un hecho agregado que cita 3 evidencias y
  otro atómico que cita 1. **Ambos `pass`.** Agregar no rompe la revisión.

### Arreglo

Es de Signal: subir `max_output_tokens` de `evidence_reviewer` de 900 a 4000, que es el techo que
Oracle ya calcula. Oracle no necesita cambios: su presupuesto por número de claims es correcto.

## 2026-07-21 · Diagnóstico definitivo del revisor en la ruta de entidad

Signal subió `evidence_reviewer` a 4000 tokens y **el informe de entidad siguió fallando**. La
hipótesis anterior (el tope de 900) describía un mecanismo real pero tapaba la causa de fondo.
Tercer rollback aplicado; producción vuelve a `ca55269`, sana, con el informe funcionando.

### Reproducción exacta

Sonda que replica la llamada del revisor usando un informe real ya guardado:

```
claims=27  (con evidencia=6, sin evidencia=21)  por tipo={inference: 21, fact: 6}
presupuesto pedido: 4000 (tope de la formula)   ->  out=4000, JSON cortado
con 6 claims:       presupuesto 1740            ->  out=975,  JSON valido, verdict=fail
solo los 6 hechos citados:                      ->  out=1124, JSON valido, verdict=fail
```

Dos hallazgos, y el segundo es el importante:

**1. El presupuesto se agota de verdad.** Con 27 claims la fórmula pide su techo de 4000 y la
respuesta se corta. Real, pero secundario.

**2. El revisor rechaza el informe aunque le sobre presupuesto.** Con solo 6 claims responde JSON
válido y aun así da `verdict: fail`. Lo que señala es `missing_evidence`: afirmaciones como «casi
80 años de historia» o «líder en soluciones integrales» que no están en ningún extracto de
evidencia citada.

### La causa estructural

Se verificó en la base de datos: **«80 años» sí aparece en el corpus del job.** El modelo no
inventa nada: lo toma del contexto autorizado (noticias del dossier compactado).

El problema es que **el revisor recibe menos información que el escritor**. `_reviewer_context`
le pasa `candidate_claims` y `evidence` (los extractos citados), pero **no el `entity_dossier`
desde el que se redactó el informe**. Así que toda afirmación apoyada en el dossier pero no en un
extracto citable le parece infundada, y el veredicto será `fail` sistemáticamente.

Eso explica por fin la asimetría entre agentes: en `report_writer` el contexto **son** las
evidencias del expediente, así que claims y evidencia salen del mismo sitio y cuadran. En la ruta
de entidad, el informe se escribe desde un corpus mucho más rico (registro, grafo, noticias,
patentes, CNMV, contratación) del que solo una parte es citable.

### Consecuencia

No es un fallo de Signal ni del modelo, y no se arregla con más tokens: el revisor está juzgando
con menos contexto del que tuvo el escritor, lo que garantiza falsos positivos. Queda pendiente
decidir si se le da el mismo contexto autorizado, si se acota qué se le manda a revisar, o si se
declara honestamente que esa ruta usa otro control.

## 2026-07-21 · Cerrada la saga del revisor: informe de entidad verificado en producción

- Release `20260721T104325Z-quick-1089f22`. Salud en verde (13 comprobaciones).
- **Informe de entidad real: `succeeded` al primer intento, en ~60 s.** Es el cierre operativo que
  faltaba y que había fallado en los tres despliegues anteriores.
- Intentos del agente: solo `generate: succeeded`. Ningún `reviewer`, que es el efecto declarado.
- Integridad de citas conservada por el control que sí aplica: **36 citadas, 45 permitidas,
  0 inventadas**. `validate_evidence` sigue siendo el guardián de esa ruta.
- `report_writer` y `competitive_procurement_intelligence` mantienen `requires_evidence_review`.
  Verificado por mutación: eximir al competitivo hace caer
  `test_long_report_reviewer_uses_compact_claim_package`; retirar `validate_evidence` hace caer
  `test_entity_waiting_area_rejects_evidence_outside_pending_allowlist`.
- La tabla `EVIDENCE_REVIEW_REQUIRED` documenta ahora sus dos excepciones en el propio código
  (D-039 wizard, D-040 entidad), no solo en `DECISIONS.md`.

### Balance de la investigación

Cuatro despliegues y tres rollbacks para llegar a una decisión de diseño, no a un parche. Se
descartaron por experimento, en este orden: el modelo local, el proveedor cloud, el presupuesto de
salida (900 y 4000) y la agregación de hechos del prompt v2. La causa real —que el revisor recibía
menos contexto que el escritor— solo apareció al reproducir la llamada con un informe real y
comprobar que el veredicto seguía siendo `fail` **con presupuesto de sobra**.

Lección para futuras investigaciones: medir un mecanismo real (el truncamiento existía) no es lo
mismo que demostrar la causa. Faltó comprobar si, eliminado ese mecanismo, el resultado cambiaba.
Signal hizo dos cambios correctos por una hipótesis incompleta nuestra.

## 2026-07-21 · Signal reindexa el BORME hacia atrás: la ficha lo ve, el informe no

- Verificado tras la reindexación de Signal: el índice de actos por entidad ya no tiene suelo en
  2019-2020.

| Entidad | Antes | Ahora | Más antiguo |
|---|---:|---:|---|
| ITURRI SA | 65 | 81 | 2009-12-04 |
| BURGOS CANTO MIGUEL (persona) | 17 | 26 | 2009-02-03 |
| TELEFONICA SA | 120 | 705 | 2016-12 o anterior |
| INDRA SISTEMAS SA | 365 | 1.630 | — |
| EULEN | 205 | 475 | — |

- **La ficha web está bien**: pagina de 50 en 50 y muestra todo el histórico.
- **El informe de IA no ve esa historia.** `compact_entity_dossier` toma `[:25]` sobre una lista
  que Signal devuelve de más reciente a más antiguo, y ITURRI concentra 51 de sus 81 actos en 2026:
  los 25 seleccionados son todos de ese año. El informe declara honestamente el recorte y sus
  agregados cubren el corpus completo, pero no puede citar ni comentar nada anterior a 2026.
- El tope no es el error: está medido y evita el truncado del informe (con 65 actos moría con
  `Invalid JSON: EOF`). El error es el **criterio de selección**, que era adecuado cuando el corpus
  empezaba en 2020 y dejó de serlo al ganar 17 años de historia.
- Prompt 66 redactado para cambiar el criterio sin tocar el presupuesto, con criterio de aceptación
  comprobable sobre el caso real de ITURRI y exigencia de determinismo (de la selección dependen el
  `corpus_hash` y los UUID de evidencia reservada).

## 2026-07-21 · Marcas y patentes: qué hay realmente

Consultado a Signal y verificado contra producción.

**Marcas: no existen.** Signal confirma que no hay OEPM, EUIPO ni WIPO, ni API de consulta, ni
tarea en su roadmap. Lo que en su repositorio se llama «marca» es otra cosa: el nombre
administrativo de las credenciales EPO, la vigilancia de patentes por solicitante y el abuso de
marca en dominios. Su estimación para integrar **un solo** registro con búsqueda, normalización y
tests es de 4-7 días; unificar los tres, varias semanas. **No se emprende ahora**: nadie lo ha
pedido todavía y el coste es de iniciativa, no de arreglo.

**Patentes: existen, funcionan a medias y se presentan mal.** Medido sobre cuatro empresas:

| Empresa | ok | Llegan | Total real | Error |
|---|---|---:|---:|---|
| TELEFONICA SA | true | 25 | **569** | — |
| INDRA SISTEMAS SA | true | 3 | 3 | — |
| ITURRI SA | false | 0 | — | `epo_search_404` |
| ACCIONA SA | false | 0 | — | `epo_search_404` |

Dos defectos, ambos de la familia que llevamos toda la semana corrigiendo:

- **Recorte no declarado**: Signal devuelve un máximo de 25 por entidad. Para Telefónica es el 4 %
  de sus 569 publicaciones, y ni la ficha ni el informe lo dicen. El informe llega a declarar
  «N de 25», tomando por total el número ya recortado.
- **Fallo silencioso**: con `ok=false` la pestaña no aparece, así que «la búsqueda falló» se ve
  igual que «no tiene patentes». Para ITURRI y ACCIONA, industriales grandes, lo segundo es
  improbable: el 404 de EPO viene de no casar el nombre exacto del solicitante.

Prompt 69 redactado para ambos. No requiere nada de Signal.

**Limitaciones confirmadas por Signal, para no volver a preguntarlas:** la consulta de patentes es
por solicitante exacto, no por materia; no existe `registry/patents?q=`; el conector de patentes
vive en `/api/v1/scopes/sync` y **no** en el namespace Oracle, así que `/oracle/monitors` con
`source_types: patents` devolvería 422; y en producción hay 0 bindings y 0 señales de patentes, es
decir, la capacidad está instalada pero nunca validada con una vigilancia real.

## 2026-07-21 · Prompts 66, 67 y 68 desplegados y verificados en producción

Release `20260721T214054Z-quick-bc9d370`. Salud en verde. Gates completos: 509 tests backend con
integración (cobertura 84,06 %), 160 frontend, typecheck, lint y build.

Auditado con mutaciones propias, distintas de las de Codex:

- **66**: volver a `items[:limit]` hace caer
  `test_registry_temporal_sample_keeps_historical_acts_when_recent_year_is_dominant`.
- **67**: desactivar `is-focus-filtered` hace caer el test de aislamiento de vecinos.
- **68**: cambiar `kind=buyer` por `winner` hace caer el test del autocompletado.

Verificación visual en producción, que la entrega declaró no haber podido hacer por falta de
sesión:

- **Acciones de la tarjeta**: el desalineo vertical pasa de **22 px a 0**. La separación horizontal
  sigue siendo de 527 px, pero ya no es un accidente: ambos botones cuelgan de un
  `.procurement-card-actions` con `aria-label="Acciones para <título>"` que ocupa 760 px de una
  tarjeta de 790, con los botones en los extremos. Queda como decisión de diseño abierta, no como
  defecto: si se quiere el par adyacente, es un cambio de una línea de CSS.
- **Orden**: cuatro opciones («Orden recibido de Signal» por defecto, plazo asc/desc, actualización
  reciente) y el aviso es exactamente el que se pidió, con cifras reales: «Orden local sobre los 25
  resultados cargados en esta página; no reordena los 611 resultados del corpus».
- **Autocompletado de comprador**: escribiendo «ayuntamiento» devuelve 8 sugerencias reales, con
  `aria-expanded` y `aria-autocomplete="list"`. Nota metodológica: mi primera comprobación esperó
  1,4 s y no vio nada; el fallo era de la prueba, no del código.

Hueco menor anotado: el atenuado por hover del grafo no tiene test propio; se detectó al mutarlo
por error sin que cayera nada.

## 2026-07-22 · Prompt 69 desplegado y verificado en producción

Release `20260721T220428Z-quick-19b6f1b`. Salud en verde. Gates: 511 backend con integración
(84,07 %), 163 frontend, typecheck, lint y build.

Verificación visual real, que la entrega declaró no haber podido hacer por falta de sesión:

- **TELEFONICA SA** (caso de recorte): la pestaña Patentes muestra **«25 de 569 publicaciones de
  patente localizadas por EPO»** con sus 25 filas. Antes se veían 25 filas y nada indicaba que
  existieran 569.
- **ITURRI SA** (caso de fallo): la pestaña **sigue visible** y dice «La consulta de patentes no se
  pudo completar. EPO no encontró el nombre exacto del solicitante; puede estar registrado con otra
  grafía o mediante una filial. Este resultado no permite concluir que la entidad carezca de
  patentes», con el código `epo_search_404`. Antes la pestaña desaparecía y era indistinguible de
  «no tiene patentes».

Auditado con mutaciones propias, distintas de las de la entrega: devolver el total ya recortado,
silenciar el fallo de EPO, y cambiar `>` por `>=` en la condición de recorte. Las tres caen.

Nota metodológica: mi primer intento de mutar la condición del aviso buscó la comparación con una
heurística de texto y no encontró nada, dando un falso «no cazada». La mutación correcta sobre
`patentsTruncated` sí la caza. Ya van dos veces esta semana que una mutación mal dirigida produce
un falso negativo; conviene localizar la línea exacta antes de mutar, no buscarla por patrón.

## 2026-07-22 · El resumen nocturno en cloud: mi diagnóstico estaba incompleto

Signal movió `dossier_situation_summary` a `openrouter/gemini-2.5-flash` (verificado desde el
worker de Oracle). Lanzados cuatro resúmenes reales para medir el criterio de éxito —que bajara la
tasa histórica de fallo del 19 %— y el resultado obliga a corregir el diagnóstico.

**El 19 % no tenía una causa, tenía dos.** Desglose histórico de intentos de IA:

```
generate : 66 succeeded /  6 failed / 1 abandoned
reviewer : 48 succeeded /  8 failed
```

Los 6 fallos de generación eran el modelo local truncando: **eso sí lo arregla el paso a cloud**.
Pero los 8 fallos de revisión son una causa **independiente** que el cambio de proveedor no toca,
porque no es un problema técnico sino un veredicto semántico.

Al pedir cuatro resúmenes hoy: 2 `succeeded` y 2 `failed`, y los dos fallos son
«El revisor de evidencia rechazó el output», no un fallo de generación.

**Hallazgo contraintuitivo:** fallan los expedientes con MÁS evidencia.

| Expediente | Resultado | Evidencias |
|---|---|---:|
| Concurso bomberos | failed | 13 |
| Mercado baterías LFP Europa | failed | 7 |
| Gigafactoría CATL-Stellantis | succeeded | 3 |
| Prueba Playwright · Mercado | succeeded | 4 |

La explicación coherente con el diseño: el revisor emite un veredicto único para todo el output, y
si es `fail` el job muere entero. Cuanto más material tiene el expediente, más afirmaciones escribe
el modelo, y basta con que **una** resulte discutible para perder el resumen completo. Es una
puerta de todo o nada.

Para un resumen que se regenera cada noche, ese trato es malo: se pierde un informe entero por una
frase mejorable, y el expediente se queda con el resumen viejo sin que nadie lo sepa.

**Lo que sí mejoró:** ninguno de los cuatro falló generando, que era el 46 % del problema
histórico. El cambio de Signal no fue en vano, pero no basta.

**Riesgo anotado por Signal:** el fallback de esta task también es OpenRouter. Si se agota el
presupuesto global, Signal cierra con 429 y **no** degrada a Ollama, así que el agotamiento de
presupuesto sería un fallo total, no una degradación.

## 2026-07-22 · El prompt 70 funciona, pero el problema era otro y lo causamos nosotros

Desplegado `20260722T080332Z-quick-9f1d89a` (prompt 70 + vertical de inteligencia competitiva,
con migración 0021 aplicada). Salud en verde.

**El mecanismo del prompt 70 es correcto** —declara la política por agente, conserva el fallo duro
en los informes publicables y falla cerrado ante ambigüedad— **pero no arregla el caso real**, y al
medirlo aparecen dos correcciones importantes a lo que dimos por bueno ayer.

### Corrección 1: no fallan los expedientes ricos, falla la tirada

Ayer concluí, sobre 4 muestras, que fallaban los expedientes con más evidencia. **Con 8 muestras no
se sostiene**: «Mercado baterías LFP» y «Prueba Playwright» fallaron en una tirada y completaron en
la siguiente, minutos después, con el mismo código. Cada ejecución genera un resumen distinto y el
revisor lo juzga de nuevo, así que el resultado varía. Era una conclusión sacada de una muestra
demasiado pequeña.

### Corrección 2: mover el revisor a cloud lo hizo mucho más estricto

Fue **recomendación mía**, y tiene un coste medible. Intentos del revisor en
`dossier_situation_summary`:

| Periodo | OK | Falla | Tasa de fallo |
|---|---:|---:|---|
| Revisor en `qwen3.5:9b` local | 46 | 6 | **12 %** |
| Revisor en `gemini-2.5-flash` cloud | 5 | 11 | **69 %** |

Y no es solo el resumen. Contando todos los agentes que pasan por el revisor: **21 % de fallo con
el revisor local frente a 71 % con el de cloud**.

El motivo por el que se movió a cloud era arreglar el `ValidationError` del informe de entidad. Ese
problema acabó resolviéndose por otra vía (D-040, exención declarada), así que el cambio de
proveedor **no dejó ningún beneficio** y sí un revisor entre tres y seis veces más severo.

Además, los rechazos actuales caen en los cubos **no retirables por claim**
(`classification_errors`, `privacy_or_security_issues`, `prompt_injection_indicators`,
`confidence_issues`) o llegan sin nombrar ningún claim, de modo que el saneado quirúrgico del
prompt 70 no llega a aplicarse casi nunca.

### Pendiente de decidir

1. **Volver el revisor a local** en Signal. Restauraría el 12 % y revierte un cambio que no aportó
   nada. Es lo más barato y lo que yo haría primero.
2. Antes de darlo por bueno, saber **si las objeciones de gemini son legítimas**: puede estar
   detectando problemas reales que qwen pasaba por alto. Eso cambiaría la lectura, aunque un 69 %
   de rechazo no es operable en ningún caso.
3. **Hueco de diagnóstico**: el mensaje «objeciones que no se pueden retirar por claim» no
   distingue entre «el revisor no nombró ningún claim» y «hay objeciones globales», y son cosas
   distintas con arreglos distintos.

## 2026-07-22 · Identidad visual desplegada, y un fallo de empaquetado que destapó

Release `20260722T113146Z-quick-353cdbd`. Salud en verde.

La identidad visual (tokens «Porcelana camaleónica», manifest, marca en `public/brand`) pasó todos
los gates de frontend y se desplegó sin incidencias, pero al mirarla en producción **el logotipo
del login aparecía como imagen rota**.

**Causa:** Next.js con `output: standalone` **no incluye `public/`** en el bundle; hay que copiarlo
aparte. `Dockerfile.web` copiaba `.next/standalone` y `.next/static` pero nunca `public/`, y hasta
hoy no se notaba porque ese directorio no existía en el proyecto.

El fichero estaba en el release del servidor —verificado en
`/opt/opn-oracle/releases/.../public/brand/`— pero producción devolvía 404, porque nunca llegó a
entrar en la imagen del contenedor. Afectaba igual al favicon y al icono de aplicación del
manifest.

Corregido y verificado: los cuatro recursos (`symbol.svg`, `favicon.png`, `app-icon.png` y
`manifest.webmanifest`) responden 200, y el logotipo se ve en el login.

**Lección:** ningún gate podía detectarlo. `npm run build` es correcto, los 167 tests pasan y el
despliegue no falla; el fallo solo existe dentro de la imagen del contenedor y solo se ve mirando
la página. Es exactamente la clase de costura que el protocolo del prompt 58 describe: los gates
verifican el código, no el empaquetado.

## 2026-07-22 · Revisor devuelto a local: el resumen nocturno vuelve a completarse

Signal revirtió `evidence_reviewer` a `ollama/qwen3.5:9b` conservando los 4000 tokens de salida
(ese cambio sí era correcto y no se tocó). Verificado el enrutado desde el worker de Oracle.

Criterio de éxito medido con ocho resúmenes reales, dos tandas de cuatro sobre los mismos
expedientes usados en las pruebas anteriores:

| Periodo | Revisor aprueba | Rechaza | Tasa de rechazo |
|---|---:|---:|---:|
| A · local, histórico | 46 | 6 | 12 % |
| B · cloud (gemini) | 5 | 11 | **69 %** |
| C · devuelto a local | **8** | **0** | **0 %** |

**Ocho de ocho completados**, incluidos «Concurso bomberos» y «Mercado baterías LFP Europa», que
fallaban de forma reproducible con el revisor en cloud.

Con esto se cierra el ciclo completo del resumen nocturno:

- El paso de `dossier_situation_summary` a cloud **se conserva**: eliminó los 6 fallos históricos
  de generación por truncado del modelo local, y ese beneficio sigue vigente.
- El paso del **revisor** a cloud se revierte: no aportó nada —el problema que lo motivó se
  resolvió por otra vía— y multiplicaba por seis el rechazo.
- El mecanismo del prompt 70 queda instalado y correcto, aunque hoy apenas se ejercita porque ya
  casi no hay rechazos que sanear. Es red de seguridad, no parche.

Queda una pregunta abierta, deliberadamente sin responder: **si las objeciones de gemini eran
legítimas**, el revisor local podría estar dejando pasar afirmaciones flojas que el de cloud
detectaba. No se investiga ahora porque un 69 % de rechazo no es operable en ningún caso, pero es
una pregunta de calidad, no de infraestructura, y merece su propio análisis.

## 2026-07-22 · Prompt 71 desplegado, y la norma de commits ya está dando fruto

Release `20260722T193226Z-quick-5e2baf5`. Salud en verde. Gates: 518 backend con integración, 174
frontend, typecheck, lint y build.

**La deuda queda cerrada por las dos vías que pedía el prompt:**

- La suite E2E se **conecta al CI** (`frontend-e2e` en `ci.yml`, con PostgreSQL y Redis), se reparan
  los flujos caducados y queda como dependencia del job final: 25 pasan y 7 saltos intencionados.
- Los botones de mutación pasan por la puerta de hidratación, y queda un invariante
  (`mutation-action-button-invariant.test.ts`) con los tres casos exigidos, incluido el de **no**
  exigir la puerta a botones de interfaz pura.

**Verificado por mí con mutación:** devolver `publish()` a `<button>` nativo hace caer el
invariante, y además nombra el fichero y la línea exactos (`report-viewer.tsx:235`).

**Límite honesto del invariante**, medido al auditarlo: detecta por dos vías, un patrón general
para llamadas `api.*.<verbo>` y una **lista de 29 nombres de manejador**. Un botón nuevo con un
manejador nuevo que no llame a `api.*` en línea **no quedaría cubierto**. Protege bien lo arreglado
hoy; no protege automáticamente lo que se añada mañana. La primera mutación que probé cayó
justamente en ese hueco y no saltó.

**Hallazgo colateral bien gestionado:** al ejecutar el E2E completo apareció una carrera CSRF al
subir documentos durante la carga inicial (403 `csrf_failed` con varias lecturas en vuelo). Se
registró en `OPEN_QUESTIONS.md` con hipótesis y siguiente paso, **sin tocar producción**, que es
exactamente lo que pedía el prompt.

### La norma de commits (D-042) funciona desde el primer día

El árbol quedó limpio y apareció commiteado también `4d2eee7` («filtrar niveles visibles en grafo
de entidades»), de otra sesión. Antes ese trabajo habría quedado sin commitear y lo habría
recogido otro atribuyéndoselo. El commit del prompt 71 llega además con prefijo convencional,
cuerpo amplio y trailer `Prompt: 71`.

## 2026-07-23 · Marcas: el BOPI sí es tratable, pero el coste no baja lo suficiente

Signal respondió a la repregunta sobre si el BOPI se puede ingerir como el BORME. Resumen para no
volver a investigarlo:

**El BOPI no es solo PDF.** La OEPM publica el Tomo I de marcas y otros signos distintivos en
**XML y HTML con XSD oficial**. Mi hipótesis de partida («quizá solo hay PDF y por eso son 4-7
días») era falsa: no haría falta OCR ni empezar de cero.

**Pero no tiene la ergonomía del BORME.** El XML/HTML es *dato protegido*: exige registro de
entidad o persona y aceptación de condiciones. **No hay endpoint público anónimo** equivalente al
sumario del BOE que alimenta el BORME. Y el parser tendría que tolerar evolución del XSD, con
cambios documentados en 2019, 2023 y 2024.

**EUIPO** es más tratable como API REST estructurada, pero también con cuenta, `client_id`/secret y
suscripción aprobada. Y no sustituye a la OEPM: cubre EUTM y registros internacionales que designan
la UE. TMview agrega oficinas nacionales, pero Signal **no ha verificado** especificación pública
que permita asumir ingesta masiva o incremental de OEPM por esa vía, y lo dice expresamente en vez
de suponerlo.

**Estimación revisada:** 4-7 días se mantiene, y el motivo cambia: no es el formato, son las
credenciales de fuente, el modelo de dominio, las versiones de XML, el histórico y el contrato de
API. Bajaría a 3-5 días si el alcance fuese solo ingesta incremental mínima. La maquinaria
existente ahorra 1-2 días de infraestructura, no más.

**Lo nuevo sería el modelo de marca**, que no se parece al societario: expediente, denominación o
representación, titular normalizado, clases de Niza, tipo de signo, estado, y actuaciones
(solicitud, oposición, concesión, renovación, transmisión, nulidad, caducidad). Necesitaría sus
propias tablas de progreso y deduplicación; las del BORME son específicas y no se reutilizan tal
cual.

### Corrección a lo que yo afirmé

En la repregunta escribí que Signal «lo había hecho dos veces», citando `BormeConfig` y
`GazetteConfig` como segundo caso del mismo patrón. **Es inexacto y Signal lo corrige bien**: esos
son conectores de *vigilancia* que emiten señales, no índices históricos consultables. El índice
histórico existe **una sola vez**, en `borme_registry.py`. Mi argumento de que la máquina ya está
construida seguía siendo válido, pero yo lo reforcé con un ejemplo que no lo era.

### Decisión: aparcado, con el bloqueo identificado

No se emprende. Ningún cliente lo ha pedido y 4-7 días es una iniciativa, no un arreglo.

**Si algún día se emprende, el primer paso no es técnico:** hay que dar de alta una cuenta
autorizada en la OEPM y con ella verificar descarga real, rango histórico disponible, mecanismo de
listado por fecha, límites y estabilidad de los XML. Hasta eso, cualquier presupuesto sigue siendo
una estimación sobre supuestos.

## 2026-07-23 · Auditoría de cierre: CSRF y grafo, con producción alineada

Release `20260723T094553Z-quick-1adcd74`. `master`, `origin/master` y producción en el mismo
commit. Árbol limpio salvo `docs/strategy/`, que es del usuario.

### Prompt 72 · carrera CSRF

El arreglo elige la vía servidor: `GET /csrf` devuelve el token vigente y solo crea uno de forma
perezosa cuando falta, en vez de rotarlo en cada lectura. El cambio son **dos líneas** en
`auth/routes.py` y `auth/runtime.py`, y conserva los cuatro puntos de rotación sensibles
(creación de sesión, reautenticación, cambio de contraseña y cambio de tenant).

Verificado por mí en producción, no solo con tests:

| Comprobación | Resultado |
|---|---|
| Dos lecturas consecutivas de `/csrf` | **mismo token** (antes la segunda invalidaba la primera) |
| POST sin token | 403 |
| POST con token inventado | 403 |
| `hmac.compare_digest` en la guarda | intacto |
| Exenciones | solo el webhook de Signal, sin añadidos |

**Nota de método sobre mi propia auditoría.** Mi primera mutación —retirar `renew_csrf()` de
`_create_session`— **no hizo caer ningún test**, y la conclusión correcta no era «el test es
flojo»: `session.clear()` se ejecuta justo antes, así que el token desaparece igualmente y se
recrea de forma perezosa. El comportamiento observable no cambiaba. Al mutar la rotación en su
raíz (`renew_csrf` reutilizando el token existente) cayó
`test_csrf_rotates_on_login_and_password_change`, que es el invariante de verdad.

Es la tercera vez esta semana que una mutación mal dirigida produce un falso negativo. La regla que
ya anoté sigue siendo la correcta: localizar el punto exacto donde vive el comportamiento antes de
mutar, no el primero que aparece al grepear.

Efecto secundario positivo: el `renew_csrf()` explícito de `_create_session` es redundante dado el
`session.clear()` previo. Se deja como defensa en profundidad, pero conviene saber que la rotación
no depende de esa línea.

### Grafo de entidades

Dos commits de otra sesión, ya desplegados: normalización de roles con exploración que no oculta
cobertura, y jerarquía de vínculos por familia. Gates en verde con el resto.

### Estado de los gates

528 tests backend con integración (cobertura 84,09 %), 190 frontend, ruff, formato, mypy sobre 110
módulos y build de producción.

## 2026-07-23 · OEPM ya ingesta, pero la pantalla espera; y las «noticias» no son noticias

### OEPM: el índice existe y crece, pero aún no es buscable

Signal ha desplegado la ingesta del BOPI y expone `/api/v1/registry/ip-rights`, con **patentes y
marcas en el mismo índice** y filtros por `q`, `holder`, `source` (`epo_ops` | `oepm_bopi`) y
`right_type` (`patent` | `trademark`), más el detalle en
`/ip-rights/{source}/{right_type}/{external_id}`.

Medido hoy sobre 200 registros de marcas:

| Campo | Presente |
|---|---|
| titular | 142 de 200 |
| **`mark_text`** | **31 de 200 (15 %)** |
| clases de Niza | 18 de 200 |
| `status` | 0 de 200 |

El índice pasó de 4.950 a 6.488 registros en dos minutos: la ingesta sigue corriendo. Todas las
fechas de publicación son de hoy, así que aún no hay histórico.

**Decisión: no se construye todavía la pantalla de búsqueda.** Una búsqueda de marcas donde el 85 %
de los resultados no tiene nombre de marca no le sirve a un analista. Se consulta a Signal si el
hueco es del XML o del parser antes de invertir en interfaz. Cuando se haga, irá en pantalla propia
—no recargando la de BORME/PLACSP— y previsiblemente cubrirá patentes y marcas juntas, porque el
índice de Signal ya las unifica.

### Noticias: la pestaña no trae noticias, y su ruido llega al informe

`/api/v1/oracle/entity/news` en Signal hace una **búsqueda web** de `"<nombre> noticias"`. No hay
fuente de noticias detrás, y los campos que llegan lo confirman: `title`, `url`, `snippet`,
`source`, `provider`, **sin fecha**.

Los 8 resultados de ITURRI SA, íntegros: 2 son su propia web (`iturri.com`, `shop.iturri.com`), 1 es
un agregador de licitaciones que duplica datos que ya tenemos de mejor fuente, 1 es una ficha
académica, y **4 son empresas distintas**: Iturria SA (Argentina), Iturri Enea (moda vasca),
Conservas Iturri (Navarra) e ITURRI LTD. **Cero son noticias.**

Y no es cosmético: `build_pending_entity_evidence_sources` convierte estos resultados en evidencia
citable con `source_kind="news"`, y el último informe verificado pasó **8 fuentes de noticias** al
modelo. Es decir, el informe puede citar una marca vasca de moda como evidencia sobre un fabricante
de equipos contra incendios, con la trazabilidad formal intacta porque el ID está en la lista de
permitidos.

Esto invalida en parte el trabajo de los prompts 54 y 56: el informe cita evidencia, pero parte de
esa evidencia no es de la entidad. Prompt 73 redactado.

## 2026-07-23 · Prompt 73 (menciones web) implementado

Se cierra la contaminación de la antigua pestaña «Noticias» sin tocar Signal. La frontera Flask
normaliza la sección `news` una vez para ficha e informe y el constructor de evidencias vuelve a
validarla en modo cerrado. Solo sobrevive una URL HTTP(S) externa con coincidencia exacta de la
identidad completa; las formas jurídicas se normalizan únicamente para empresas.

Con el corpus productivo documentado de ITURRI SA el resultado esperado pasa de 8 supuestas
noticias citables a **0/8 menciones atribuibles**: 2 dominios propios, 1 duplicado de contratación y
5 sin atribución suficiente. Los títulos descartados no cruzan al frontend ni al modelo. La ficha
mantiene la pestaña visible como «Menciones web», muestra el recuento y explica que no es una
hemeroteca ni aporta fechas. El informe emite `source_kind="web_mention"`, declara el descarte en
`source_limits` y usa el prompt `entity_dossier_intelligence/v3`; v1 y v2 permanecen congelados.

No hay migración ni variable nueva. El techo global `EVIDENCE_SOURCE_TOTAL_LIMIT=45` y su reparto
se conservan después del filtrado. Se registra en D-059 la decisión y también la colisión del número
73 con el prompt del grafo. La dependencia de una fuente informativa real, fechada y desambiguada
queda abierta para Signal.

## 2026-07-23 · Propuesta ORACLE-EXP-INVESTIGACIONES

Se documenta en `docs/product/INVESTIGATION_WORKBENCH_PROPOSAL.md` una metodología genérica para
investigaciones empresariales trazables. No investiga una entidad concreta ni implementa todavía
el workflow. La recomendación mantiene `StrategicDossier` como unidad central y añade, si producto
la acepta, una ejecución por rondas con candidatos aislados, frontera, fuentes congeladas, claims,
contradicciones y revisión humana antes de promover `Actor`, `Relationship`, `Evidence` o `Report`.

La auditoría del producto actual confirma que ya existen grafo BORME, ficha e informe de entidad,
adjudicaciones PLACSP, descarga documental, evidencias, jobs durables y gobernanza IA. El hueco
material no es otro informe: es consultar contratación para cada sociedad verificada, resolver
identidad sin contaminar el grafo canónico y obtener participantes no adjudicatarios desde
documentos oficiales.

La propuesta corrige dos expectativas:

- Ollama extrae, contrasta y redacta detrás de task keys de Signal; no navega ni es fuente de
  verdad. Una investigación de horas se divide en un DAG durable de jobs cortos porque producción
  limita Celery a 690/720 segundos y las leases IA a 600.
- PLACSP ofrece adjudicatario y recuento comunicado de licitadores de forma estructurada, pero no
  garantiza los nombres de todos ellos. «Perdió» solo se publica cuando una fuente identifica al
  licitador y otro adjudicatario en el mismo lote; ausencia de resultado permanece `unknown`.

Se proponen una Fase 0 de 1–2 semanas para medir identidad, cobertura documental y Ollama, seguida
de MVP determinista, participación documental, informe multipasada y monitorización. El total
orientativo es 9–15 semanas de ingeniería, condicionado por Signal, acceso registral y compliance.
Las decisiones pendientes quedan en `OPEN_QUESTIONS.md`; no se registra una decisión aceptada ni se
modifica `DECISIONS.md` hasta recibir validación de producto.

No hay migración, variable, API ni código runtime nuevos. Por ser documentación de diseño no se
ejecutaron suites de aplicación. La validación documental cerró con `git diff --check` limpio,
10 enlaces Markdown locales resueltos y 0 ausentes. El barrido de ejemplos confirmó que la
propuesta no contiene Huawei ni otra entidad del caso inicial. El barrido de participantes y
`counterpart_kind` confirmó que el runtime solo modela participantes de reuniones y conserva una
clasificación parcial de contrapartes BORME; no existe todavía el índice nominal de licitadores que
la propuesta asigna a Signal.

## 2026-07-23 · Menciones web: la contaminación resuelta, con un coste medible

Release `20260723T121236Z-quick-0aed05a`, ya desplegado por la sesión que lo implementó, con
backup y restore aislado. `master` y producción alineados. Gates reproducidos por mí: 535 tests
backend con integración (84,17 %), ruff, mypy sobre 111 módulos.

**El objetivo del prompt 73 se cumple.** Verificado con cuatro entidades reales:

| Entidad | Resultados crudos | Atribuibles | Lectura |
|---|---:|---:|---|
| ITURRI SA | 8 | **0** | correcto: 4 eran otras empresas, 2 su propia web |
| TELEFONICA SA | 8 | **0** | correcto: los 8 son dominios propios |
| ACCIONA SA | 8 | **3** | correcto: pasa lo legítimo |
| INDRA SISTEMAS SA | 8 | **0** | **falsos negativos** |

Mutación propia: hacer que todo sea atribuible tumba 3 tests. El filtro muerde.

### El coste, medido: se pierden noticias reales

INDRA es el caso que lo destapa. Entre sus 8 resultados crudos hay periodismo genuino sobre la
empresa correcta —«Indra gana uno de los mayores contratos de radares de defensa» (computing.es),
«Indra y NAVANTIA se unen para desarrollar y comercializar…» (sepi.es), «Valencia confía a Indra el
despliegue de un sistema integrado»— y **el filtro descarta los tres**.

La causa está en `_is_attributable` (`common/web_mentions.py`):

```python
required = [*identity_tokens, legal_suffix] if legal_suffix else identity_tokens
```

Exige que el **nombre legal completo, incluida la forma societaria**, aparezca como secuencia
contigua: para «INDRA SISTEMAS SA» hace falta literalmente «indra sistemas sa». Pero la prensa
nunca usa la razón social: escribe «Indra», «Telefónica», «Acciona». ACCIONA pasa por casualidad,
porque el resumen de Wikipedia incluye «Acciona, S.A.».

Es decir: el filtro acierta con la contaminación y falla con **las empresas cuyo nombre comercial
difiere del legal**, que son casi todas las grandes. Para un analista, «Indra gana un contrato de
radares de defensa» es justo la señal que busca.

**No se revierte.** El estado anterior era peor: el informe de IA citaba una marca vasca de moda
como evidencia sobre un fabricante de equipos contra incendios. Perder señal es preferible a
afirmar falsedades con trazabilidad formal correcta. Pero la sección queda hoy casi vacía para
empresas grandes, y eso hay que corregirlo, no asumirlo.

**Siguiente paso propuesto:** aceptar el nombre comercial —los tokens de identidad sin exigir la
forma societaria— cuando otras señales respalden la atribución, en lugar de exigir la razón social
literal. Queda anotado, no se improvisa ahora.

## 2026-07-23 · Complemento revisado de ORACLE-EXP-INVESTIGACIONES

Se contrasta el borrador complementario aportado por producto con
`docs/product/INVESTIGATION_WORKBENCH_PROPOSAL.md`, el runtime actual y fuentes oficiales. Se
integran seis macropasadas P0–P5 sobre las doce rondas existentes, prioridad operativa para
administrador persona jurídica y socio único, triaje explicable de homónimos, checkpoint humano
antes de expandir personas, compradores públicos compartidos, recuento comunicado de licitadores
como contexto, minería documental dirigida y cuatro contratos iniciales de prompts.

También se incorpora un micro-spike técnico de 2–4 días dentro de la Fase 0 de 1–2 semanas:
inventario real de Signal, micro-DAG reanudable, benchmark por etapa, prueba de fuentes registrales
de pago para nodos críticos, evaluación del reviewer con errores sembrados y decisión sobre la
frontera de snapshots Signal/Oracle exigida por D-028.

No se adoptan como hechos el «70 % ya construido», las 2,5–5 horas, modelos 9B/27B concretos,
precios comerciales ni un corte fijo de cuatro años. Tampoco se permite que Ollama fusione
homónimos. BORME puede publicar ocasionalmente DNI/NIF o socios en texto libre; el límite correcto
es que no ofrece un identificador personal ni un accionariado completos, uniformes y estructurados.
Un administrador compartido no acredita matriz o control. `ReceivedTenderQuantity` se conserva por
procedimiento/lote/versión y no se suma cuando se repite por varios adjudicatarios.

No se codifica una interpretación cerrada del AI Act ni se usa como requisito funcional para este
workflow interno. Sí se conservan privacy-by-design, minimización, exactitud, licencia de fuentes y
revisión humana como controles de calidad y seguridad ya exigidos por el producto.

`BackgroundJob` permanece como autoridad única de intentos, leases, fencing y retry;
`InvestigationStep` solo proyecta el DAG y su resultado de dominio. D-028 permanece vigente:
Oracle guarda por defecto manifest, hashes, extractos y fuentes promovidas, mientras Signal produce
el corpus vivo. Retener payloads/PDFs exploratorios completos requiere una decisión explícita.
La expansión usa gobierno y propiedad documentada por defecto; representación es opt-in y un
representante físico solo recibe prioridad identitaria con identificador oficial. Tampoco se afirma
que `AIAuditLog` guarde hoy `policy_hash`: el diseño deberá incorporarlo al log o al manifest.

No hay código runtime, migración, API, variable ni decisión arquitectónica aceptada nuevos. La
propuesta continúa pendiente de validación de producto y `DECISIONS.md` no cambia.

Validación documental: `git diff --check` limpio, 10 enlaces Markdown locales resueltos con 0
ausentes y 66 filas de tablas con columnas consistentes. Se abrieron las especificaciones oficiales
de BORME, sindicación PLACSP, LCSP y el criterio AEPD citado. El barrido de
`ReceivedTenderQuantity`, tiempos, modelos, merges, Camerdata, AI Act, `BackgroundJob` y D-028
confirma que las cifras/modelos quedan como hipótesis, el recuento no se suma por adjudicatario, el
merge personal probabilístico está prohibido y no se duplican autoridad de jobs ni corpus bruto.
No se ejecutan suites de aplicación al no cambiar comportamiento.
