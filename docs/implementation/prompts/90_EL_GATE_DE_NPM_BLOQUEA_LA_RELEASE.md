# 90 — El gate de npm bloquea la release (P0 · seguridad + entrega)

> Prompt de producto para Codex, **frontend/tooling**. El paso `[1/5]` de
> `scripts/run-quality-scans.sh` está en rojo con 11 vulnerabilidades altas, y con el CI rojo
> **no hay release posible**: `release.yml` falla cerrado si no existe una ejecución `success`
> para el SHA exacto ([RELEASE.md](../../operations/RELEASE.md)). El resto del pipeline ya está
> verde, así que este paso es lo único que separa a producción de trabajo verificado que arregla
> un P0 de informes.
>
> El caso anterior ([89](./89_EL_MOTOR_DE_PDF_BLOQUEA_LA_RELEASE.md)) se cerró actualizando,
> porque existía versión limpia. **Aquí no la hay**, y eso cambia la naturaleza de la decisión.
> Elegir con criterio es el trabajo; elegir en silencio no.

## 1 — El bloqueo, medido

Ejecución: [run 30132168354](https://github.com/gitshell007/OPN_ORACLE/actions/runs/30132168354)
(SHA `267b1ec`). Los otros tres jobs pasan —incluido *Backend, migrations and integration* con
las integradas reales sobre Postgres y Redis—; falla solo *Security, images and SBOM*, en su
primer paso:

```
npm audit --audit-level=high   →  11 high severity vulnerabilities  →  exit 1
```

Un único aviso raíz arrastra los diez restantes:

```
GHSA-mh99-v99m-4gvg — brace-expansion: DoS via unbounded expansion length (OOM crash)
OSV: { introduced: "0" }, { fixed: "5.0.8" }        ← un solo rango, sin backport por mayor
```

La cadena es `brace-expansion` → `minimatch` → núcleo de eslint (`@eslint/config-array`,
`@eslint/eslintrc`) y los tres plugins que arrastra `eslint-config-next`. Las tres puertas de
entrada son **devDependencies**: `eslint`, `eslint-config-next`, `openapi-typescript`.

## 2 — Lo que ya está descartado (no lo repitas)

Estas tres comprobaciones están hechas y verificadas el 25-07-2026. Confírmalas si quieres, pero
no las presentes como hallazgo nuevo:

- **El override global no sirve.** `"brace-expansion": "5.0.8"` en `overrides` —el patrón que el
  repo ya usa con `postcss`, `js-yaml` y `sharp` (`026cb7d`)— **rompe eslint**: los consumidores
  están anclados a la serie 1.x/2.x y revienta con un stack trace en
  `@eslint/config-array/dist/cjs/index.cjs`. Comprobado ejecutando `npm run lint`.
- **Actualizar el toolchain no pone el gate en verde.** `eslint@10.8.0` sí sale de la cadena
  (usa `minimatch ^10.2.5`, fuera del rango vulnerable `2.0.0 - 10.0.2`), pero las versiones
  **más recientes publicadas** de los plugins siguen dentro:

  ```
  eslint-plugin-import   @2.32.0 → minimatch ^3.1.2
  eslint-plugin-jsx-a11y @6.10.2 → minimatch ^3.1.2
  eslint-plugin-react    @7.37.5 → minimatch ^3.1.2
  ```

  No es cuestión de esfuerzo ni de saltar un mayor: no existe upstream limpio hoy.
- **La exposición en producción es nula, y está medida:**

  ```
  npm audit --audit-level=high --omit=dev  →  found 0 vulnerabilities
  ```

  Las 11 altas viven íntegramente en herramienta de lint y generación de cliente, que no entra
  en la imagen de runtime. El vector es un DoS por expansión no acotada de patrones glob que el
  propio repositorio escribe, procesados en tiempo de lint/build.

## 3 — Las salidas

Elige una y justifícala con lo de la sección 1 y 2:

- **Acotar el gate a lo que se envía.** Bloquear con `--omit=dev` y conservar el escaneo completo
  como paso informativo que no tumba la release. El gate pasaría a medir exposición real, seguiría
  fallando el día que una dependencia **enviada** se vuelva vulnerable, y no se pierde visibilidad
  de la cadena de build. Es la opción recomendada por quien redacta este prompt. Si la tomas,
  el paso informativo tiene que **verse** en el log, no desaparecer.
- **Exención explícita del aviso**, con identificador, motivo, fecha y **caducidad**, más entrada
  en `DECISIONS.md`. Ojo: `run-quality-scans.sh` no tiene hoy ningún mecanismo de exención para
  `npm audit`, así que esta salida implica inventarlo — y un mecanismo de exención mal hecho es
  peor que el problema. Una exención sin fecha de revisión es deuda invisible.
- **Congelar el toolchain fuera del árbol auditado** (por ejemplo, mover lint y generación de
  cliente a un manifiesto propio o a una herramienta que no comparta el lock de la aplicación).
  Es la más limpia conceptualmente y la más cara; solo si las otras dos no te convencen.

Lo que no vale: bajar `--audit-level` a `critical`, quitar el paso del escaneo, ejecutar
`npm audit fix --force` (propone lo que parece un *downgrade* de `eslint-config-next` a `0.2.4`),
ni dejar el gate verde sin que nadie pueda explicar por qué.

## 4 — Un hallazgo lateral que conviene cerrar

`package.json` fija `"next": "latest"` y `"eslint-config-next": "latest"`. Un spec flotante hace
que el árbol auditado cambie sin que cambie el repositorio: hoy el gate puede estar verde y
mañana rojo sin un solo commit, que es exactamente lo que pasó entre las ejecuciones de anoche.
Decide si se pinnan —y a qué— o argumenta por qué no. No lo arrastres en silencio.

## 5 — Coordinación

`master` tiene ya cuatro commits de otra sesión que **no debes tocar ni rehacer**:

```
315ac87  fix(reporting): que los informes de expediente dejen de salir vacíos
662b961  fix(security): subir WeasyPrint a 69 para desbloquear la release   (cierra el prompt 89)
267b1ec  feat(reporting): congelar la cartera del expediente para informes ejecutivos
bf55c1f  fix(reporting): que la cartera congelada no desplace a la evidencia citable
```

Tu cambio es de tooling: `package.json`, `package-lock.json`, `scripts/run-quality-scans.sh`,
`.github/workflows/ci.yml` y `docs/`. **No toques `apps/api/`.** Si crees que necesitas hacerlo,
dilo en vez de resolverlo por tu cuenta.

Dato operativo que ahorra una vuelta: **el CI no se dispara con `push`**. `ci.yml` solo escucha
`pull_request` hacia master y `workflow_dispatch`. Para validar tu SHA:

```bash
gh workflow run ci.yml --ref master -f reason="Gate de npm: <tu decisión>"
```

## Verificación exigida

- La consulta real del aviso, citada, con rango afectado y versión corregida.
- La justificación de la salida elegida contra lo medido en la sección 2, incluida la razón de
  descartar las otras dos.
- `npm ci` y `npm run lint` en verde: cualquier toque a `overrides` o al lock puede romper el
  linter, y ya pasó una vez.
- `npm run typecheck`, `npm run test -- --run`, `npm run api:client:check` y `npm run build`.
- `bash scripts/run-quality-scans.sh` completo en verde localmente, nombrando qué hace ahora
  cada uno de sus cinco pasos si has cambiado alguno.
- **CI verde para el SHA publicado**, disparado como se indica arriba. Es el objetivo del prompt:
  sin eso no hay release, y hay un P0 de informes esperando.
- Entrada en `DECISIONS.md` con el mismo criterio que D-077, que resolvió el prompt 89.

## Qué NO hacer

- No pongas el CI verde debilitando el escaneo sin declararlo: ni bajar el umbral, ni saltar el
  paso, ni exenciones sin motivo ni caducidad.
- No reintentes el override global de `brace-expansion` ni la subida de eslint como si fueran
  caminos abiertos: están medidos y cerrados en la sección 2.
- No ejecutes `npm audit fix --force`.
- No toques `apps/api/` ni rehagas los cuatro commits de la sección 5.
- No cambies el árbol de dependencias de la aplicación para arreglar un problema del árbol de
  build: hoy lo que se envía a producción está limpio y así debe seguir.
