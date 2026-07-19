# 51 — Asistente de mejora del expediente: botón IA y wizard por rondas (P1 · UX + feature)

> Prompt de producto para Codex, frontend. **Depende del prompt 50** (API y contrato de salida). El
> E2E con IA real depende además del 52 (alta de la task en Signal): verifica con `AI_MODE=mock` u
> Ollama local y declara lo no verificado. Verifica en el navegador con datos reales; si no tienes
> sesión, decláralo como no verificado.

## 1 — Botón de entrada: que se note que es IA sin romper Vector

Hoy la única marca visual de IA es el icono `Sparkles` de Lucide sobre botones estándar
(`vector-primary`). Se pide un **único** estilo nuevo reutilizable — p. ej. `.vector-ai` en
`src/styles/concept-a.css`, junto a `.vector-primary` (~1168) — sobre la base del sistema Vector
con un acento distintivo sutil (gradiente o borde discreto), icono `Sparkles` y etiqueta clara
(«Mejorar con Oracle» o similar). Sin romper la paleta; contraste AA; estados
hover/focus/disabled/`aria-busy` como el resto (el patrón ya está en `concept-a.css:1189-1216`).
No lo apliques en masa a otros CTAs IA existentes en este prompt: solo el wizard.

Colocación: visible desde **todas** las pestañas del expediente — en la cabecera del detalle o
junto a `DossierNavigation` (`src/app/app/dossiers/[id]/layout.tsx` +
`src/components/navigation/product-navigation.tsx`). Decide el sitio exacto y justifícalo.

## 2 — El wizard

Modal Radix (`@radix-ui/react-dialog`, patrón de los formularios existentes) con flujo por rondas
contra la API del prompt 50:

1. **Lanzar ronda** → job en cola `ai`: reutiliza `JobProgress`
   (`src/components/reporting/job-progress.tsx`) y el patrón de polling a 5 s del panel Oráculo
   (`src/components/dossiers/dossier-oracle-summary-panel.tsx`). Nada de streaming.
2. **Diagnóstico:** estado por sección (`ok` / `incomplete` / `empty`) con la explicación del
   agente en bloques escaneables: el usuario debe entender qué falta y por qué importa para su
   objetivo.
3. **Preguntas:** formulario con las `questions[]` de la ronda; se puede responder solo algunas y
   relanzar la ronda con `answers`.
4. **Acciones recomendadas:** cada `recommended_action` se pinta con su `kind` y un CTA que lleva
   al formulario real **prefijado** con `prefill`:
   - `create_signal_monitor` → Configuración del expediente con el formulario de monitor
     precargado (keywords, idiomas, fuentes).
   - `pin_procurement` → Contratación pública (`/app/procurement`) con la búsqueda precargada.
   - `create_opportunity` / `create_risk` → el modal de la pestaña correspondiente precargado
     (título, descripción, siguiente acción / mitigación).
   - `create_actor` → el modal de actor precargado (nombre, tipo, etiquetas, roles).
   - `refine_goal` / `other` → texto explicativo y enlace a donde corresponda.
   Decide el mecanismo de prefill (query params, store compartida...) y justifícalo; obligar al
   usuario a copiar a mano no vale.
5. **Estados:** cargando, error recuperable (retriable de Signal, como el informe de entidad), sin
   permisos, sesión expirada, y ronda anterior recuperable tras recargar la página.

Microcopy en español de España, tono de guía y honesto: es un análisis asistido, no una decisión
humana; no muestres pensamiento interno del modelo. WCAG 2.2 AA, manejo completo por teclado, sin
color como única señal.

## Criterios de aceptación

- [ ] Botón IA visible desde todas las pestañas del expediente, con el estilo nuevo único,
      accesible y coherente con Vector.
- [ ] Ronda completa en mock: lanzar → diagnóstico → responder preguntas → nueva ronda que refleja
      las respuestas.
- [ ] Cada acción recomendada abre su formulario real prefijado y crear desde ahí funciona.
- [ ] Estados de carga/error/permiso/recarga cubiertos; polling reutilizado; cero streaming.
- [ ] `npm run lint`, `npm run typecheck`, `npx vitest run`, `npm run build` verdes.
- [ ] Verificado en el navegador con el caso «Coches de Bomberos» (expediente `market` vacío): el
      flujo guía de verdad a monitor + licitaciones + actores.

## No hacer

- No inventes un chat libre: el flujo es por rondas estructuradas contra el contrato del 50.
- No dupliques formularios para el prefill: abre y precarga los existentes.
- No añadas librerías de UI nuevas; Radix + Lucide + Vector bastan.
- No hagas pasar el análisis IA por hechos: microcopy de asistencia, como el panel Oráculo.
- Nada de dar por bueno sin abrir la app.
