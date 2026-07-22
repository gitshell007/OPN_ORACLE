# 71 — Dos protecciones que existen pero nadie hace cumplir (P2 · deuda)

> Prompt para Codex. Son dos deudas pequeñas con la **misma raíz**: en ambos casos la protección
> está construida y funciona, pero nada obliga a usarla, así que se erosiona sola y nadie se entera
> hasta que rompe algo.
>
> Ninguna urge. Las dos empeoran solas si se dejan.

## 1 — La suite E2E no se ejecuta en ninguna parte

`tests/e2e/` tiene **662 líneas** en tres specs (`smoke`, `accessibility-security`, `phase12`) y
`package.json` expone `test:e2e`. Pero **no aparece en `.github/workflows/ci.yml`**: no la corre el
CI, y en la práctica no la corre nadie.

El resultado previsible: se ha podrido. `phase12.spec.ts` busca un diálogo **«Promover señal»** que
se eliminó del producto en el commit `2e6f390`, hace tiempo. Su selector
`getByRole("button", { name: "Promover" })` es además ambiguo desde que existen «Promover a
oportunidad» y «Promover a riesgo». Al ejecutarla ahora: **20 pasan, 6 se saltan, 4 fallan**.

Es el mismo patrón que ya sufrimos con los tests de integración: un gate que no se enciende no
protege, solo da falsa sensación de cobertura. Allí, al encenderlo, aparecieron tres fallos
latentes de días distintos, incluida una regresión de seguridad.

**Qué hay que decidir, y quiero que lo decidas tú con criterio:**

- Si la suite aporta, **conéctala al CI** y arregla lo que esté caducado para que quede en verde.
- Si no aporta lo suficiente para el coste que tiene, **bórrala y dilo**. Una suite muerta en el
  repositorio es peor que no tenerla: aparenta cobertura que no existe.

Lo que no vale es dejarla como está. Si eliges conectarla, ten en cuenta que necesita la aplicación
levantada; mira cómo lo resuelven los otros jobs del CI antes de inventar nada.

## 2 — Los botones de mutación protegidos por accidente

Existe `AsyncActionButton` / `HydratedActionButton` (`src/components/ui/async-action-button.tsx`),
que marca la acción como no disponible hasta que React hidrata y expone `aria-busy`,
`aria-disabled` y `data-action-ready`. Se creó precisamente para que un clic prematuro no se
perdiera. **Lo usan 14 ficheros.**

Pero quedan **21 botones que ejecutan mutaciones** —crear, borrar, generar, incorporar, promover,
guardar, rotar secretos, lanzar backups— **sin esa puerta**. Entre otros:

```
src/components/admin/signal-admin.tsx:326
src/components/concept-a/vector-documents.tsx:115, 116
src/components/dossiers/dossier-actor-candidates.tsx:143, 153
src/components/dossiers/dossier-context-panel.tsx:354, 359
src/components/dossiers/dossier-documents-section.tsx:176, 183
src/components/dossiers/dossier-inventory.tsx:435
```

**Lo importante no es cuántos son, sino por qué hoy casi ninguno falla.** La mayoría está a salvo
por accidente: un `useState(true)` de carga, sin relación con la hidratación, los deja
deshabilitados el tiempo justo. El día que alguien refactorice ese estado, precargue datos desde el
servidor o cambie el arranque a estático, el bug vuelve **en silencio y sin que ningún test lo
cace**.

**Qué hay que conseguir:**

- Que los botones que ejecutan mutaciones usen la puerta explícita.
- Y, más importante que el arreglo puntual, **que exista un invariante que lo mantenga**: un test
  que falle si aparece un botón de mutación sin protección. Sigue el patrón de
  `tests/test_verification_protocol.py` del backend, que hace exactamente esto para otras reglas y
  ya nos ha cazado cosas.

Cuidado al definirlo: no todo botón necesita la puerta. Ordenar una tabla, paginar, plegar un panel
o abrir un diálogo son acciones de interfaz sin efecto en el servidor. Si el invariante los exige
también, será ruidoso y alguien acabará desactivándolo. Define el criterio de «mutación» de forma
que se pueda comprobar, y documenta en el propio test por qué queda fuera lo que quede fuera.

## Invariantes

- **No cambies el comportamiento visible** de los botones más allá de la protección: mismo texto,
  misma posición, mismo resultado al pulsarlos una vez hidratada la página.
- No toques `AsyncActionButton`: funciona y lo usan 14 ficheros.
- Si al conectar el E2E aparecen fallos ajenos a estas dos deudas, **repórtalos, no los arregles
  aquí**. Ya nos pasó con la integración: mezclar el arreglo del gate con los fallos que destapa
  hace ilegible la entrega.

## Verificación exigida

- El invariante de botones **falla** si se quita la puerta de uno de los arreglados. Demuéstralo
  mutando y di cuál.
- El invariante **no salta** con un botón de interfaz pura (ordenar, paginar). Un invariante que
  obliga a excepciones constantes acaba desactivado.
- Si conectas el E2E: verde en CI, y di qué arreglaste de lo caducado. Si lo borras: dilo
  explícitamente en el resumen y en `DECISIONS.md`, con el motivo.
- `npm run typecheck`, `npm run lint`, `npx vitest run` y `npm run build`, nombrados por separado.

## Qué NO hacer

- No añadas la puerta a botones que no mutan nada solo para que pase el invariante: eso es adaptar
  el producto al test.
- No dejes la suite E2E como está. Cualquiera de las dos salidas es válida; la indecisión no.
- No amplíes el alcance a otros arreglos de UI que veas de paso: anótalos y sigue.
