# 47 — Dashboard: procesos con fecha y reubicados en Auditoría, y lista de atención con tipos e iconos (P2 · UX)

> Prompt de producto para Codex. Dos mejoras del Inicio (`product-home.tsx`), cada una con su
> diagnóstico ya hecho en el código. Verifica en el navegador con datos reales; si no tienes sesión,
> decláralo como no verificado.

## 1 — «Trabajos recientes» sin fecha, y debería vivir en Administración → Auditoría

**Falta la fecha/hora.** En `src/components/navigation/product-home.tsx:174`, cada fila de trabajo
muestra solo `{productStatusLabel(job.status)} · {job.progress}%` — nada de cuándo se ejecutó. El
modelo `background_jobs` tiene `created_at`/`updated_at`; el objeto `job` del cliente debería
exponerlos (verifícalo; si el endpoint no los devuelve, añádelos al serializador y regenera OpenAPI/
cliente). Muestra la fecha y hora de forma legible (formato español, como el resto del panel).

**Reubicación en Administración.** Este panel «Procesos / Trabajos recientes» encaja mejor en la
sección de auditoría que en el Inicio. Ya existe la zona: `src/app/app/admin/audit/` y las pestañas
de `tenant-admin.tsx` (members / audit / signal). Lo que se pide:

- Dentro de Administración → **Auditoría**, dos pestañas (o dos sub-vistas claras):
  1. **Registro de auditoría** — los `AuditEvent` (lo que ya haya allí).
  2. **Procesos** — la lista de trabajos en segundo plano, ahora **con fecha y hora**, estado,
     progreso y tipo, y con los fallidos destacados.
- Decide y documenta qué queda en el Inicio: o un vistazo compacto de «actividad reciente» que
  enlace a Administración → Auditoría → Procesos, o se retira del Inicio y vive solo allí. No
  dupliques la lógica: una fuente, reutilizada.

> Nota sobre el enunciado original («dos pestañas, una para auditoría y otra para Auditoría»): es una
> errata; se entiende **una para el registro de auditoría y otra para los procesos**. Si crees que la
> intención era otra, pregúntalo en `OPEN_QUESTIONS.md` en vez de adivinar.

## 2 — «Trabajo que requiere atención»: tipo en negrita y un icono por tipo

En la lista de «Priorización operativa» (`product-home.tsx:147-149`), hoy solo el **título** va en
negrita; el tipo (`productLinkedResourceLabel(item.kind)`: señal, oportunidad, elemento del
expediente, riesgo…) va en un `<small>` plano y sin distintivo. Cuesta distinguir de un vistazo qué
clase de trabajo es cada fila.

**Se pide:** por cada fila, un **icono propio del tipo** (`item.kind`) y el **nombre del tipo
resaltado**, para diferenciar señal / oportunidad / elemento / riesgo / etc. de un golpe de vista.
Reutiliza los iconos que ya usa la navegación lateral para esos mismos conceptos (coherencia visual;
Lucide, no metas librerías nuevas). Mapea todos los `kind` que `productLinkedResourceLabel` conoce, y
deja un icono por defecto para cualquiera no mapeado. No uses el color como única señal (AGENTS.md
§13, WCAG): icono + texto.

## Criterios de aceptación

- [ ] Cada trabajo muestra su fecha y hora legibles.
- [ ] Administración → Auditoría tiene las dos vistas (registro y procesos); los procesos con fecha.
- [ ] El Inicio no duplica la lógica de procesos; su relación con la vista de Auditoría es clara.
- [ ] Cada fila de «requiere atención» lleva icono por tipo y el tipo resaltado, con todos los kind
      cubiertos y un fallback.
- [ ] `npm run lint`, `npm run typecheck`, `npx vitest run`, `npm run build` verdes; y
      `scripts/api-test.sh --unit` si tocas el serializador del job (`uv` en `~/.local/bin/uv`).
- [ ] Verificado en el navegador (Inicio y Administración → Auditoría) con datos reales.

## No hacer

- No metas iconos por color solamente; icono + texto.
- No dupliques la consulta de trabajos entre Inicio y Auditoría.
- No inventes campos de fecha en el cliente: si el endpoint no los da, añádelos en el backend y
  regenera el contrato.
- Nada de dar por bueno sin abrir la app.
