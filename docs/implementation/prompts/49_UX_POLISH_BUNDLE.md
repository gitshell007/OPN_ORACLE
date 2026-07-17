# 49 — Pulido de UX: clic silencioso en diálogos, tipo pegado al título, toast y prefetch 503 (P2)

> Prompt de pulido para Codex. Cuatro fricciones sueltas observadas a lo largo del 2026-07-17, cada
> una con su causa ya localizada. Son pequeñas; agrúpalas. Verifica en el navegador; si no tienes
> sesión, decláralo.

## 1 — El clic silencioso vuelve en los botones que abren diálogos

El prompt 46 arregló el primer-clic-perdido en los **botones de acción async** con `AsyncActionButton`
(gating por hidratación). Pero **«Nuevo expediente»** sigue fallando: es un botón que **abre un
diálogo**, no lanza una acción async, y no pasó por ese arreglo.

Causa, en `src/components/navigation/product-home.tsx:114` y `:131`:
```jsx
<button className="vector-primary" onClick={() => setCreateOpen(true)}>
```
Botón plano, sin gating de hidratación: durante la ventana de hidratación el `onClick` no está atado
y el primer clic se pierde, igual que el bug del 46.

**Se pide:** extender la protección de hidratación a los botones que abren diálogos, de forma
reutilizable. `AsyncActionButton` ya expone el mecanismo (`useHydrated`); haz que sirva también para
triggers de diálogo (una variante sin estado de «cargando…» de acción, pero que deshabilite hasta
hidratar), o extrae el hook y aplícalo. Barre los demás botones que abren diálogos o navegan a
acciones (no solo «Nuevo expediente») y cúbrelos todos. Mismo principio del 46: ningún botón puede
parecer listo cuando no lo está.

## 2 — En «Trabajo que requiere atención» el tipo va pegado al título

En `product-home.tsx:163`:
```jsx
<span><strong>{item.title}</strong><small><b>{productLinkedResourceLabel(item.kind)}</b> · ...</small></span>
```
El `</strong>` del título va seguido del `<small>` sin separación, así que en pantalla se lee
«…BESS**señal**» — el tipo pegado al título sin espacio. Añade separación clara (un espacio/separador
o que el tipo caiga a una segunda línea/columna), de modo que título y tipo se distingan. Comprueba
que sigue leyéndose bien en las filas con títulos largos.

## 3 — El toast de proceso fallido se queda y no refleja el reintento

En `src/components/reporting/job-progress.tsx:56`, un job en estado `failed` dispara
`toast.error("El proceso necesita atención")`. Observado: ese toast permanece en pantalla mientras el
usuario **reintenta** el mismo proceso y este termina bien — queda un error visible de algo ya
resuelto.

**Se pide:** revisar el ciclo de vida del toast. Al reintentar o al superar un job, el error previo
debe **retirarse o sustituirse** por el estado nuevo (usa un `id` de toast por job para que
`success` reemplace al `error` del mismo, en vez de acumularse). El error tampoco debería quedar
indefinidamente: una duración razonable y descartable. No rompas el aviso legítimo de un fallo real.

## 4 — 503 en los prefetch `_rsc` tras cada despliegue (investigar, no parchear a ciegas)

Tras cada despliegue se ven en la red **503** en peticiones `...?_rsc=...` (prefetches RSC de Next),
aunque la app funciona. Probablemente es **desajuste de build ID**: clientes con el build anterior
piden payloads RSC que el servidor nuevo ya no sirve, y Next debería recuperarse con una recarga por
version-skew.

**Se pide:** confirmar la causa antes de tocar nada (¿es version-skew que Next auto-recupera, o Nginx
devolviendo 503 durante el swap de contenedores?). Si es lo primero y se recupera solo, **documenta
que es esperado** y ciérralo; si Nginx corta con 503 real durante el despliegue, ajústalo (upstream/
reintento) para que el prefetch degrade sin 503 visible. No metas reintentos en el cliente sin saber
cuál de las dos es.

## Criterios de aceptación

- [ ] «Nuevo expediente» y demás triggers de diálogo abren al primer clic; ninguno inerte de aspecto
      activo. Solución reutilizable, no botón a botón.
- [ ] En «requiere atención», título y tipo se distinguen visualmente; sin texto pegado.
- [ ] Un job reintentado con éxito no deja el toast de error anterior; los errores son descartables.
- [ ] La causa del 503 `_rsc` confirmada y, o bien documentada como esperada, o corregida.
- [ ] `npm run lint`, `npm run typecheck`, `npx vitest run`, `npm run build` verdes.
- [ ] Verificado en el navegador reproduciendo los síntomas 1-3 hasta verlos desaparecer.

## No hacer

- No arregles el clic silencioso solo en «Nuevo expediente»: es la misma clase de bug, hazlo común.
- No metas reintentos de cliente para el 503 sin confirmar antes que no es version-skew esperado.
- No silencies el toast de fallo real: el objetivo es que refleje el estado actual, no ocultarlo.
