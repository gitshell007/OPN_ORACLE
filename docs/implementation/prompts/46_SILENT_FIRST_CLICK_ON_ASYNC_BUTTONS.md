# 46 — El primer clic en los botones de acción se pierde tras navegar (P1 · UX)

> Prompt de corrección para Codex. Síntoma observado y reproducido **cuatro veces** en producción a
> lo largo del 2026-07-17, en botones distintos. No es anecdótico: afecta a todas las acciones
> principales de las páginas pesadas. **El diagnóstico NO está cerrado**: hay dos causas plausibles y
> el primer trabajo es confirmar cuál, no arreglar a ciegas.

## El síntoma, verificado

Al entrar en una página pesada y pulsar un botón de acción primario, **el primer clic no hace
nada** —ni petición de red, ni cambio visible, ni error— y el **segundo clic idéntico funciona**.
Observado con:

- «Informe documental» (sección de contratación del expediente).
- «Inteligencia competitiva» (misma sección).
- «Informe de la entidad» (ficha 360º de entidad).
- «Incorporar a expediente» y «Desfijar» tras navegar a la sección.

En todos, el botón **se ve habilitado** (azul primario, no atenuado) en ambos clics, y no hay
mensaje de carga. El usuario percibe que pulsó y no pasó nada.

## Dos causas candidatas — confírmalas antes de tocar nada

No sé cuál es sin instrumentar, y no quiero que la adivines. Las dos encajan con el síntoma:

**A) Hidratación tardía de Next (App Router).** El HTML server-rendered muestra el botón como
clicable antes de que React hidrate y ate el `onClick`. Un clic en esa ventana no dispara nada. Las
páginas afectadas son justo las más pesadas (grafo Cytoscape de 295 nodos, secciones múltiples), que
tardan más en hidratar. Encaja con «se ve habilitado pero está inerte».

**B) `disabled` durante la carga de datos, sin feedback.** Varios de estos botones están gated por
datos que llegan tras el montaje:
- `dossier-procurement-section.tsx`: `disabled={generatingCompetitive || !effectiveCompany}`, y
  `effectiveCompany` deriva de `items` que se cargan en un `useEffect`.
- El de informe documental: `disabled={generating || !items.some(i => i.kind === "award")}`.
- `entity-dossier.tsx:717`: `disabled={loading || generating || Boolean(activeJobId)}`.

Si el botón sigue `disabled` cuando se pulsa (datos aún cargando), el clic se traga en silencio y el
estilo primario oculta que está deshabilitado.

**Tu primer entregable es determinar cuál de las dos ocurre** (o si son ambas según el botón).
Instrumenta: registra en la consola el estado `disabled` y el momento de hidratación al montar, y
reproduce en el navegador con una página pesada. Reporta la causa **con evidencia**, no por
deducción. Es exactamente el tipo de fallo que este proyecto ha aprendido a no dar por diagnosticado
sin observarlo (ver los bugs de dispatch HTTP del 2026-07-17).

## Lo que se pide, según la causa confirmada

- **Si es (B), disabled sin feedback:** un botón deshabilitado **debe parecerlo** —estado visual de
  deshabilitado/cargando, con `aria-disabled` y `aria-busy`— para que el usuario sepa esperar. Y
  revisa si el gating es correcto: si el botón depende de datos que casi siempre llegan, plantéate
  mostrar «Cargando…» en vez de un botón muerto de aspecto activo.
- **Si es (A), hidratación:** el patrón correcto no es un hack de `setTimeout`. Considera deshabilitar
  explícitamente la acción hasta que el componente esté montado/hidratado (`useEffect` que marca
  `ready`), mostrando ese estado, de modo que nunca haya un botón que *parezca* clicable pero no lo
  sea. Documenta por qué la solución elegida no reintroduce el problema en otra página pesada.

En ambos casos, el principio es el mismo y **no negociable**: **ningún botón de acción puede
aparentar estar listo cuando no lo está.** Un clic sobre un control primario, o hace la acción, o
comunica por qué todavía no.

## Alcance

Arréglalo de forma **sistémica**, no botón a botón. Si el patrón se repite en cuatro sitios, la
solución debería vivir en un sitio (un componente de botón de acción, un hook `useHydrated`/estado
compartido, o el patrón que decidas) y aplicarse a todos. Enuméralos y confirma que quedan cubiertos:
los cuatro citados más cualquier otro botón de acción async que encuentres en el barrido.

## Criterios de aceptación

- [ ] Causa real confirmada con evidencia de instrumentación, no deducida.
- [ ] El primer clic tras navegar dispara la acción, o el botón comunica visiblemente que aún no
      está listo (nunca un primario de aspecto activo e inerte).
- [ ] Solución sistémica reutilizada en los cuatro botones citados y en los que aparezcan al barrer.
- [ ] `npm run lint`, `npm run typecheck`, `npx vitest run`, `npm run build` verdes.
- [ ] **Verificado en el navegador con datos reales** en al menos dos páginas pesadas (expediente con
      contratación y ficha de entidad con grafo). Si no tienes sesión, decláralo como no verificado
      y no lo des por hecho.

## No hacer

- No arregles a ciegas eligiendo una de las dos causas sin confirmarla.
- No parchees con `setTimeout` arbitrarios: enmascara el problema y reaparece en la siguiente página
  pesada.
- No lo resuelvas botón a botón si la causa es común: sería deuda repetida cuatro veces.
- No des por bueno el arreglo sin reproducir el síntoma original y comprobar que desaparece.
