# 49 — Expediente guiado: ayuda en formularios y empty states accionables (P1 · UX)

> Prompt de producto para Codex. Cuatro mejoras de orientación al usuario en el detalle de
> expediente, diagnóstico ya hecho. Sin IA: es microcopy, enlaces y ejemplos; el asistente IA llega
> en los prompts 50–52 y no es requisito de este. Verifica en el navegador con datos reales; si no
> tienes sesión, decláralo como no verificado.
>
> Contexto real: un usuario creó un expediente tipo Mercado («Coches de Bomberos», objetivo: conocer
> las licitaciones de vehículos de emergencia y su competencia) y se perdió en cada pestaña: no supo
> qué poner en los formularios ni por qué Señales estaba vacía.

## 1 — Empty state de Licitaciones sin enlaces

`src/components/dossiers/dossier-procurement-section.tsx:446-448` dice «No hay licitaciones o
adjudicaciones fijadas. Puedes fijarlas desde Contratación pública o desde el panel de Actores»,
pero no enlaza a ninguno de los dos sitios: el usuario tiene que adivinar dónde están.

**Se pide:** convertir ambas menciones en enlaces reales: Contratación pública (`/app/procurement`,
ya definido en `src/lib/app-routes.ts:139-141`) y la pestaña Actores del propio expediente
(`/app/dossiers/<id>/actors`, segmento en `app-routes.ts:247`). Respeta los permisos que
`app-routes.ts` declara para cada destino: sin permiso, no muestres un enlace muerto.

## 2 — El modal de oportunidad/riesgo no explica qué poner ni para qué sirve

Modal compartido en `src/components/dossiers/dossier-intelligence-section.tsx` (formulario
~731-750): Título, Descripción, tres sliders («Encaje estratégico»/«Urgencia» o
«Impacto»/«Probabilidad», más «Confianza inicial») y un campo final cuyo label es un ternario en la
línea 744: «Siguiente acción» (oportunidades → `next_action`) o «Mitigación inicial» (riesgos →
`mitigation`). Ningún campo tiene ayuda ni placeholder. La pregunta literal del usuario fue: «¿qué
tengo que poner en cada apartado y para qué me va a servir o en qué va a influir en la IA?».

**Se pide:** ayuda contextual por campo reutilizando el patrón ya existente en
`src/components/navigation/create-product-dossier-dialog.tsx` (~108-134): `<small>` con la
explicación vinculado por `aria-describedby`, y `<details>` si hace falta extenderse. **Antes de
redactar la microcopy, verifica en el backend qué influye cada campo de verdad**
(`apps/api/src/opn_oracle/oracle/models.py`: ejes de `Opportunity`/`RiskItem` y
`ScoredResourceMixin`; dónde y cómo se calcula/usa `overall_score`; qué llega al contexto IA en
`apps/api/src/opn_oracle/ai/context.py`) y escribe la verdad, no una promesa. Sentido esperado de
cada campo (contrástalo con el código):

- **Encaje estratégico** — cuánto acerca esta oportunidad al objetivo del expediente.
- **Urgencia** — ventana temporal; si la ocasión caduca pronto, sube.
- **Impacto / Probabilidad** — ejes clásicos del riesgo: daño si ocurre y opciones de que ocurra.
- **Confianza inicial** — cuán seguro estás de tu juicio; con poca información, baja.
- **Siguiente acción** — el próximo paso concreto y verificable. El diálogo de promoción de señal ya
  lo hace bien (span en la línea 945, placeholder «Ej.: Preparar contacto con compras y validar
  encaje» y checkbox «Crear tarea con esta acción»): iguala el modal manual a ese nivel.
- **Mitigación inicial** — qué harías para reducir la probabilidad o el impacto del riesgo.

Añade placeholders con ejemplo a Descripción, Siguiente acción y Mitigación inicial, coherentes con
los del diálogo de promoción. Y que la ayuda diga en qué influye puntuar: ordena y prioriza las
listas y alimenta lo que la IA lee del expediente (solo si lo verificas en el código).

## 3 — «Nuevo actor»: Roles sin ejemplos ni orientación

En `src/components/dossiers/dossier-work-section.tsx:682` las Etiquetas ya tienen placeholder
(«fabricante, socio industrial»), pero en la línea 687 «Roles (separados por comas)» es un textarea
sin placeholder ni ayuda. En backend los roles son texto libre (`DossierActor.roles`, JSONB sin
allowlist, normalizado con `clean_labels`): el usuario no sabe qué es un «rol» aquí ni qué valores
tienen sentido.

**Se pide:** placeholder con ejemplos de roles relativos al expediente («competidor, cliente
potencial, adjudicatario habitual, decisor, prescriptor, socio, proveedor») y una línea de ayuda que
explique la diferencia: la etiqueta describe qué es el actor en general; el rol, qué papel juega en
este expediente. Opcional: sugerencias con `<datalist>` sin restringir el texto libre.

## 4 — Empty state de Señales: no dice cómo hacer que entren señales

`dossier-intelligence-section.tsx:656` muestra «El expediente todavía no contiene señales.» y nada
más (ojo: es una plantilla compartida con oportunidades y riesgos; acota el cambio a señales). El
mecanismo real, verificado: las señales solo entran si hay (a) una conexión Signal Avanza activa del
tenant y (b) un monitor del expediente con sus criterios; la watchlist «Vigilancia inicial» sembrada
al crear el expediente no trae señales por sí sola (los starter profiles no crean monitores,
`apps/api/src/opn_oracle/oracle/starter_profiles.py`). La UI de monitores ya existe en la pestaña
Configuración del expediente (`src/components/dossiers/dossier-settings-section.tsx`: formulario de
creación y acciones pausar/reanudar/sincronizar).

**Se pide:** que el empty state de señales explique el porqué y lleve a la solución:

- Sin monitores activos: explicar que las señales llegan mediante monitores de vigilancia y enlazar
  a Configuración (`/app/dossiers/<id>/settings`) con un CTA claro.
- Con monitor activo pero sin señales aún: decir que la vigilancia está activa y que las señales
  aparecerán con las próximas sincronizaciones.
- Los monitores ya se cargan vía `api.signalAvanza.monitors(dossierId)` (lo usa Configuración):
  reutiliza el cliente, no dupliques lógica ni machaques el presupuesto de requests de la pestaña.

## Criterios de aceptación

- [ ] El empty state de Licitaciones enlaza de verdad a Contratación pública y a Actores,
      respetando permisos.
- [ ] Todos los campos del modal oportunidad/riesgo tienen ayuda y ejemplos honestos con lo que el
      backend hace con ellos.
- [ ] Roles de actor con placeholder, ayuda y ejemplos; siguen siendo texto libre.
- [ ] El empty state de Señales distingue «sin monitor» de «monitor activo sin señales aún» y enlaza
      a Configuración; oportunidades y riesgos no cambian.
- [ ] Ayuda accesible (WCAG 2.2 AA): `aria-describedby`, alcanzable por teclado, sin color como
      única señal.
- [ ] `npm run lint`, `npm run typecheck`, `npx vitest run`, `npm run build` verdes.
- [ ] Verificado en el navegador: un expediente sin monitores y otro con datos reales.

## No hacer

- No inventes microcopy sobre qué hace la IA o el scoring con cada campo sin verificarlo en el
  código: ayuda falsa es peor que ninguna.
- No metas librerías nuevas de tooltips: reutiliza el patrón `<small>` + `<details>` existente.
- No conviertas roles ni etiquetas en enums: el backend los trata como texto libre a propósito.
- No dupliques la carga de monitores entre Señales y Configuración.
- Nada de dar por bueno sin abrir la app.
