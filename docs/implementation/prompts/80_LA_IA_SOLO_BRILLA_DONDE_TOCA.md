# 80 — UI del wizard: la IA solo brilla donde toca (P1 · UX)

> Prompt de producto para Codex, **solo frontend** (el 79 es del carril de investigación).
> Construye la interfaz del wizard de búsqueda sobre el backend del prompt 78 (commit
> `232def3`, decisión D-063). Todo lo de abajo está medido en el código de `master`; el
> cliente TypeScript ya está regenerado en `packages/api-client`.
>
> Regla transversal que da nombre al prompt: el estilo IA (`vector-ai`, Sparkles) aparece
> **únicamente** en las acciones donde interviene el modelo — generar o regenerar el plan.
> Contadores, motivos, perfil de comparable, aceptación y guardado son deterministas y van
> con estilo neutro. Si todo brilla, el usuario no distingue «esto lo interpretó un modelo,
> revísalo» de «esto es un hecho medido», y esa distinción es el discurso del producto.

## 1 — Superficie API medida, con sus límites

| Endpoint | Límite | Nota |
|---|---|---|
| `POST /api/v1/ai/tender-search-wizard/runs` | — | encola la generación; job asíncrono |
| `GET /api/v1/ai/tender-search-wizard/latest` | — | último job + artifact, patrón del wizard de dossiers |
| `POST /api/v1/procurement/search-plans/preview` | **6/minuto** | sondea bloques de **4 términos + 4 CPV**; devuelve `{plan, preview}` con el plan repostvalidado |
| `GET /api/v1/procurement/comparable-profile` | **6/hora** | TTL de caché 6 h; incluye `measured_at` y descartes |
| `GET/POST /api/v1/procurement-search-profiles` | 60/min | memoria tenant-scoped |
| `POST .../{id}/acceptances` | 30/min | acepta el plan **editado**; re-valida en servidor (422 con campos) |
| `POST .../{id}/saved-search` | — | crea la vigilancia en Signal; **solo `scope=active`** (422 si no) |

Los rate limits bajos no son un estorbo a esquivar: son el contrato. La UI los presupuesta y
los comunica; nunca los quema en silencio ni los sortea con reintentos.

## 2 — Flujo: dos pasos, valor visible cuanto antes

CTA **«Buscar con Oracle»** en el `page-heading` de `/app/procurement` con `vector-ai`,
separado de la búsqueda manual, que no se toca: el wizard es un acelerador, no un reemplazo.
Abre como Dialog/sheet reutilizando el patrón de `dossier-completion-wizard.tsx` (job status
con texto honesto, `role="status"`, `AsyncActionButton`).

**Paso 1 — Cuéntanos qué haces.** Un textarea protagonista y, en disclosure colapsado, los
campos opcionales: empresa comparable (autocomplete con `suggest?kind=winner`, texto libre
siempre), geografías, importes. Si el usuario indica comparable, muestra de inmediato — es
determinista, sin esperar al modelo — el mini-perfil del endpoint `comparable-profile`: top
CPVs etiquetados, compradores, ventana temporal y `measured_at`. Con el límite de 6/hora:
si responde 429, muestra el último resultado en caché de sesión o un estado «perfil no
disponible ahora, reintenta más tarde» — jamás un bucle de reintentos.

**Paso 2 — Esto es lo que hemos entendido.** El `intent_summary` como titular editable y el
plan como **chips editables agrupados**: incluir, sinónimos, excluir, CPV, compradores,
geografía, ámbito temporal e importes. Badge discreto «Generado con IA — revísalo antes de
aceptar». Los descartes de la postvalidación (`discarded_count`/motivos que ya devuelve el
backend) se muestran, no se ocultan: «2 CPV propuestos no existen en la taxonomía y se
descartaron». `confidence` se presenta como etiqueta cualitativa con tooltip, nunca como
porcentaje crudo. `assumptions` y `questions` como notas inline, jamás como bloqueo.

## 3 — La lección de los −16,2 puntos: procedencia y unión

La evaluación del 78 midió que Ollama entregó un plan con **3 CPV** habiendo recibido 20
medidos en el grounding, y cayó a 65,6 % frente al 81,8 % determinista. La UI corrige ese
modo de fallo por diseño:

- Cada chip lleva **procedencia** visible: «medido en la comparable» (preconfirmado, estilo
  sólido), «propuesto por IA» (estado candidato, borde discontinuo) o «añadido por ti». La
  procedencia se calcula en cliente cruzando el plan con el `comparable-profile` — es
  determinista, sin backend nuevo.
- Si el plan del modelo omite candidatos top medidos en la comparable, la UI los ofrece como
  fila de sugerencias con acción de un clic **«Añadir los medidos que faltan»**. El modelo
  no puede eliminar en silencio lo que la aritmética midió; quitar chips es siempre un acto
  del usuario. Con esta unión, el plan aceptado nunca rinde menos que la línea base por culpa
  de un olvido del modelo.
- Regenerar el plan (única acción IA del paso 2) conserva los chips añadidos o confirmados
  por el usuario: la regeneración propone, no pisa.

## 4 — Preview con presupuesto honesto

Con 6/minuto y bloques de 4+4, el bucle «toco un chip → cambia el número» no puede ser por
pulsación. Diseña el preview como acción explícita:

- Botón «Actualizar recuentos» con debounce, deshabilitado con cuenta atrás visible cuando
  el presupuesto se agota (429 → `role="status"`, nunca un toast de error críptico).
- El resultado etiqueta **qué se sondeó y qué no**: los bloques de 4 términos y 4 CPV
  sondeados, y el resto marcado como «sin sondear todavía». Los recuentos «se solapan, no se
  suman»: prohibido presentar la suma de sondas como total global — es el mismo engaño que
  D-043 prohíbe con el orden y D-044 con los topes.
- Ámbito temporal con el control segmentado ya existente del prompt 74: `historical`
  deshabilitado con explicación honesta («no disponible en Signal v1»), `all` etiquetado
  como «todo el índice actual», no como archivo completo.

## 5 — Aceptar y vigilar: fronteras humanas con fricción proporcional

- **Aceptar** envía el plan editado a `acceptances`; los 422 de re-validación se pintan
  inline sobre el chip o campo culpable, no como error genérico. Tras aceptar, se muestra la
  versión del plan (v1, v2…) — el modelo del backend ya la incrementa.
- **Guardar vigilancia** es un segundo acto explícito: nombre prellenado con el
  `intent_summary`, explicación de qué implica (se ejecutará periódicamente, solo activas —
  el 422 de `historical`/`all` no debe poder ocurrir porque la UI no lo ofrece), y la
  búsqueda aparece en el aside «Vigilancia» existente con su chip de versión.
- Nada se acepta ni se guarda automáticamente, nunca, tampoco «por conveniencia» tras
  regenerar: D-063.

## 6 — Accesibilidad y móvil

- Chips con gestión de teclado: foco por chip, Supr/Retroceso para quitar, `role="group"`
  con `aria-label` por categoría. Recuentos anunciados con `role="status"` polite.
- El combobox de comparable replica el patrón accesible ya medido en
  `procurement-workspace.tsx` (roles, `aria-activedescendant`, sin petición por tecla).
- Móvil: wizard como sheet a pantalla completa, chips con wrap, resultados en tarjetas y
  detalle en drawer — datatable Vector solo en escritorio.

## Verificación exigida

- Vitest de: detección de candidatos medidos ausentes y acción de unión; procedencia de
  chips; presupuesto del preview (no hay llamada por toggle — múltiples toggles, una sonda);
  manejo del 429 con cuenta atrás; 422 de aceptación pintado en el campo culpable;
  `historical` no ofertable en guardado; regeneración que conserva chips del usuario.
- **Cada test nuevo verificado por mutación**: di qué mutaste y qué test cayó.
- `npm run typecheck`, `npm run lint`, `npx vitest run`, `npm run build`, por separado.
- Decide sobre Playwright: hay infraestructura (`playwright.config.ts`); o cubres el flujo
  feliz wizard→aceptar→vigilancia, o declaras por qué no y qué lo sustituye.
- Verificación visual con sesión real en escritorio y móvil: antes/después de
  `/app/procurement`, el paso 1 con comparable (perfil visible), el paso 2 con chips de las
  tres procedencias, un preview con bloques sondeados/no sondeados, y la vigilancia creada
  en el aside. Sin sesión: no verificado, declarado.

## Qué NO hacer

- Ninguna llamada IA desde el frontend fuera de `tender-search-wizard/runs`: preview,
  aceptación, guardado y perfil de comparable son deterministas.
- No aceptes ni guardes nada sin acción humana explícita; no re-dispares generación en
  silencio al abrir el wizard si ya hay un artifact reciente — ofrécelo.
- No sondees recuentos por pulsación ni evadas el 6/minuto con colas de reintento.
- No presentes sondas parciales como totales globales, ni «todo el índice actual» como
  archivo histórico completo.
- No apliques `vector-ai`/Sparkles a datos deterministas, ni escondas los CPV descartados.
- No toques el backend: si encuentras un hueco real del contrato (un dato que la UI necesita
  y no llega), documéntalo en el informe de cierre como dependencia — no lo rodees con
  hacks de cliente.
