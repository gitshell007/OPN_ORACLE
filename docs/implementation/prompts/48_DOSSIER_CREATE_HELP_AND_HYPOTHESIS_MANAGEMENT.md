# 48 — Crear expediente: ayuda de tipos y base de trabajo; y gestión de hipótesis (P2 · UX + feature)

> Prompt de producto para Codex. Tres mejoras del flujo de expedientes, diagnóstico ya hecho.
> Verifica en el navegador con datos reales; si no tienes sesión, decláralo como no verificado.

## 3 — El diálogo de «Nuevo expediente» no explica para qué sirve cada tipo

En `src/components/navigation/create-product-dossier-dialog.tsx`, el tipo es un `<select>` con siete
opciones (Proyecto, Mercado, Cuenta estratégica, Licitación o convocatoria, Alianza, Asunto
regulatorio, Otro) y **solo un `<small>` de una línea** con `starterProfileFor(type).description`. El
usuario no sabe cuándo elegir uno u otro.

**Se pide:** una ayuda clara de qué es cada tipo y para qué caso sirve. Decide el mecanismo —un icono
de ayuda con tooltip/popover accesible por tipo, o un texto descriptivo más extenso que se actualice
al elegir, o tarjetas de tipo en vez de un `select`— pero que el usuario entienda la diferencia sin
salir del diálogo. Reutiliza lo que `starterProfileFor(type)` ya sabe de cada tipo (focus, base) y
amplíalo si hace falta. Accesible (WCAG 2.2 AA): la ayuda debe alcanzarse por teclado y anunciarse.

## 3.1 — La «base de trabajo» sale desalineada porque `.checkbox-row` no tiene estilos

**Causa raíz, confirmada:** el bloque «Base de trabajo» usa `<span className="checkbox-row">` con un
checkbox y el texto «Crear una base inicial editable» (líneas ~123-134), pero **`.checkbox-row` no
existe en `concept-a.css`** (grep: cero coincidencias). Sin estilos, el checkbox y su texto no se
alinean, el conjunto «cae en medio» y da la impresión de que «falta un checklist al lado de cada
texto» —porque el label «Base de trabajo» y el texto del checkbox parecen dos textos sueltos sin sus
casillas.

**Se pide:** rediseñar ese bloque para que se lea sin ambigüedad. Como mínimo, dar estilo a
`.checkbox-row` (flex, `align-items:center`, gap, tamaño de fuente coherente con el resto del
formulario) para que la casilla quede pegada a su etiqueta. Revisa que el label del campo («Base de
trabajo») y la opción no se confundan visualmente: deben leerse como «título del campo» + «una opción
marcable», no como dos etiquetas huérfanas. Comprueba también el estado marcado/desmarcado y que el
texto de ayuda de debajo siga teniendo sentido en ambos.

## 4 — Las hipótesis se pueden añadir pero no gestionar: faltan listado, edición y borrado

Tras crear un expediente, la tarjeta «Marco de trabajo» del Resumen
(`src/components/dossiers/dossier-context-panel.tsx`) permite **añadir** hipótesis, pero no hay forma
de **verlas listadas, editarlas ni borrarlas**, ni una explicación de para qué sirven. No hay pestaña
ni datatable para ellas.

**Hallazgo:** el backend **ya soporta el CRUD completo**. `Hypothesis` está en los mapas de recursos
de `apps/api/src/opn_oracle/oracle/routes.py` con permisos `dossier.read`/`dossier.write` (crear,
editar, borrar). Igual que pasó con los actores en el prompt 44: el backend está, la UI no expone la
gestión. **Reúsalo; no dupliques lógica de dominio.**

**Se pide:**

1. **Explicar qué son.** Una hipótesis es una suposición de trabajo del expediente que se contrasta
   con evidencia (tiene estado y confianza). Un texto breve o ayuda en la propia sección que deje
   claro su propósito y cómo se usan.
2. **Listado gestionable.** Un datatable de hipótesis (patrón TanStack Table ya usado en el proyecto,
   como en el prompt 44 para órganos/cargos), con estado y confianza, ordenable y filtrable.
3. **Ver / editar / borrar** cada hipótesis, con un modal accesible para el detalle y la edición, y
   confirmación antes de borrar. Todo contra los endpoints existentes, respetando tenant scoping y
   permisos (`dossier.write` para mutar). Si borrar una hipótesis con evidencia vinculada
   (`HypothesisEvidence`) tiene reglas, respétalas y explícalas en la interfaz en vez de fallar con
   un error crudo.
4. **Dónde vive.** Decide y justifica: una pestaña propia en el expediente, o una sección expandida
   dentro del Resumen. Que sea descubrible —hoy el usuario no encuentra dónde gestionarlas—.

## Criterios de aceptación

- [ ] El diálogo de nuevo expediente explica cada tipo de forma comprensible y accesible.
- [ ] La «base de trabajo» se ve alineada y sin ambigüedad; `.checkbox-row` con estilos.
- [ ] Las hipótesis se listan en un datatable ordenable/filtrable, con ver/editar/borrar y su
      propósito explicado, reutilizando el CRUD de backend existente.
- [ ] Borrar pide confirmación y respeta las reglas de evidencia vinculada.
- [ ] `npm run lint`, `npm run typecheck`, `npx vitest run`, `npm run build` verdes; y
      `scripts/api-test.sh --unit` si tocas backend (`uv` en `~/.local/bin/uv`).
- [ ] Verificado en el navegador: crear un expediente, y gestionar (crear/editar/borrar) una
      hipótesis de verdad.

## No hacer

- No dupliques el CRUD de hipótesis: el backend ya lo tiene, expón la UI contra él.
- No borres hipótesis con evidencia vinculada saltándote las reglas del dominio.
- No dejes la gestión escondida donde el usuario no la encuentre: el problema es justo ese.
- Nada de `bash -n`/typecheck como sustituto de abrir la app y probar el flujo.
