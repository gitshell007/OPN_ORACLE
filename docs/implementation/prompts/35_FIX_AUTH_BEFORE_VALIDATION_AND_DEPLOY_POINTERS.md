# 35 — Autorización antes que validación en entity-intel + coherencia de punteros tras deploy fallido (P1)

> Prompt de corrección para Codex **con acceso al repo y al host de producción**. Son dos defectos
> distintos que se manifestaron juntos en el despliegue de `2ed3edb` (2026-07-16): el smoke de
> producción falla, y el activador reacciona a ese fallo dejando el host en un estado incoherente
> que hubo que arreglar a mano **dos veces**. El segundo es más grave que el primero.

## Contexto: qué pasó exactamente

El despliegue de `2ed3edb` terminó con `DEPLOY_FALLIDO` y «pointers restaurados», pero producción
**estaba sirviendo el release nuevo**. Los punteros se corrigieron manualmente (forward-fix). El
mismo patrón ya se había visto en el despliegue anterior. Diagnóstico verificado en vivo el
2026-07-17 contra `https://oracle.opnconsultoria.com`:

| Petición anónima | Código | |
|---|---|---|
| `/api/v1/entity-intel/suggest?q=iturri&kind=company` | `401` | correcto |
| `/api/v1/entity-intel/graph?name=iturri` | `401` | correcto |
| `/api/v1/entity-intel/suggest?q=ib&kind=company` | `422` | **el fallo** |
| `/api/v1/procurement/suggest?q=ib` | `401` | referencia correcta |

**Cadena causal completa, confirmada con `git log -L`:**

1. `scripts/smoke-production.sh:114` afirma que `entity-intel/suggest?q=ib&kind=company` debe
   devolver **401** a un anónimo. Es una aserción de seguridad: *«sin sesión no se entra, pase lo
   que pase»*.
2. F2 (`5d60847`) subió el mínimo de `q` de `min=2` a `min=3` en `EntitySuggestQuerySchema`
   (`entity_intel_routes.py:43`), porque el trigram necesita 3 caracteres. **El cambio es correcto.**
3. `q=ib` son exactamente **2 caracteres**: válido antes de F2, inválido después.
4. En `entity_intel_routes.py`, las cuatro rutas tienen `@bp.input` **por encima** de
   `@require_permission`, así que la validación de esquema corre **antes** que el permiso. Un
   anónimo con query inválida recibe `422` en vez de `401`.
5. El smoke ve `422 ≠ 401` → falla → el activador marca `DEPLOY_FALLIDO`.

Nadie lo relacionó porque el smoke solo comprueba el código de estado, no el motivo. El cuerpo del
422 lo decía literalmente: `"Length must be between 3 and 200."`.

**Este es el mismo defecto que ya se corrigió en `64eda7e` para procurement y que nunca se propagó a
entity-intel.** El patrón correcto está al lado, en `procurement_routes.py:238`.

## Fuentes de verdad (léelas antes de tocar nada)

`AGENTS.md` (§14 auditoría read-only previa, §16 testing, §18 flujo, §20 definición de terminado),
`OPN_Oracle_Codex_Memory.md`, `docs/implementation/STATUS.md`, `docs/operations/RELEASE.md`,
`DEPLOYMENT.md`, `CONTROL_CENTER.md`, `ROLLBACK.md` y `BACKUP_RESTORE.md`. Estado de partida:
`master` = `2ed3edb`, árbol limpio, sincronizado con `origin`. Release activo en producción:
`20260716T223027Z-quick-2ed3edb` (raíz de despliegue: `/opt/opn-oracle`, **no** `/opt/oracle`).

---

## Alcance A — Autorización antes que validación (código)

> **Corrección del 2026-07-17 (amplía el alcance original).** La primera versión de este prompt
> decía «réplica exacta del orden de `procurement_routes.py:238`» y te pedía NO arreglar el patrón
> fuera de entity-intel. **Ambas cosas eran erróneas y quedan anuladas.** Un barrido de todo el API
> demuestra que `64eda7e` arregló procurement solo a medias: las líneas 238/256/273 están bien, pero
> el mismo fichero conserva **seis rutas con el defecto**. No uses ese fichero como modelo: arréglalo.

Mueve `@require_permission(...)` para que quede **inmediatamente debajo del decorador de ruta** y
**por encima de `@bp.input`**. Es el orden que ya tiene `procurement_routes.py:238`, pero verifica
cada caso en vez de fiarte del fichero.

**Inventario completo del defecto** (barrido de `apps/api/src/opn_oracle`, 2026-07-17):

- `integrations/entity_intel_routes.py`: `/suggest` (:148), `/graph` (:168), `/registry` (:191),
  `/dossier` (:212) — 4 rutas.
- `integrations/procurement_routes.py`: `/tenders/<path:folder_id>/summary` (:301),
  `/tender-searches` POST (:328), `/tender-searches/<search_id>` GET (:337), PATCH (:348),
  DELETE (:366), y `/tender-searches/<search_id>/run` (:377) — 6 rutas.

Arregla **las diez**. Repite el barrido tú mismo al terminar (`@bp.input` antes de
`@require_permission` en cualquier blueprint) y declara en el resumen que el resultado es cero; si
aparece algún caso nuevo fuera de estos dos ficheros, arréglalo también e indícalo.

No cambies los límites de rate ni los esquemas: el `min=3` de F2 es correcto y se queda.

**No toques `scripts/smoke-production.sh`.** Con el orden corregido, `q=ib` devuelve `401` y el smoke
pasa **sin modificarse** — y pasa a comprobar exactamente lo que siempre quiso comprobar: que la
autorización precede a la validación. Cambiar el smoke a una query válida enmascararía el defecto en
lugar de arreglarlo.

**Tests obligatorios** (el defecto existía porque nadie comprobaba esto). En
`apps/api/tests/test_entity_intel.py` y, en el equivalente de procurement, para **las diez rutas**
(parametriza; no dupliques diez veces el mismo test). Sin sesión:

- [ ] query **inválida** (p. ej. `q=ib`, o `name` ausente) → **401**, nunca 422.
- [ ] el cuerpo de esa respuesta **no** contiene `errors`, ni nombres de campos, ni mensajes de
      validación: un anónimo no debe aprender el esquema.
- [ ] query **válida** sin sesión → **401** (no regresión).
- [ ] con sesión y permiso `actor.read`, query inválida → **422** con su detalle (la validación sigue
      funcionando para quien sí está autenticado).

Añade además una **prueba contractual que recorra el mapa de rutas de la app** (`app.url_map`) y
falle si cualquier vista protegida valida antes de autorizar. Un test que enumere diez rutas a mano
volverá a quedarse corto en cuanto alguien añada la undécima — que es exactamente cómo `64eda7e`
dejó seis rutas sin arreglar y nadie se enteró durante semanas.

## Alcance B — Coherencia de punteros tras deploy fallido (tooling)

Es el defecto grave, y es de diseño. En `scripts/oracle-control.sh`, `update_release()` (~:637-663):

1. mueve los punteros al release nuevo (`current`, `CURRENT_RELEASE`, env);
2. **luego** ejecuta `deploy-production.sh`, que levanta los contenedores nuevos y **al final** corre
   el smoke;
3. si algo falla —incluido el smoke, que corre **después** de haber cambiado los contenedores—
   restaura los punteros al release viejo… **pero no revierte los contenedores**.

Resultado: punteros diciendo `viejo`, contenedores sirviendo `nuevo`. Producción incoherente y una
bomba de relojería: al reiniciar el stack, revierte a un release que nadie decidió revertir. Es
justo lo que pasó dos veces y hubo que arreglar a mano.

El fallo de fondo es que la ruta de error **no distingue si el fallo ocurrió antes o después del
cambio de contenedores**, y aplica la misma reacción (restaurar punteros) a dos situaciones opuestas.

**No impongo la solución: es una decisión de diseño y quiero tu criterio razonado.** Las opciones que
veo, y lo que hay que exigir a cualquiera de ellas:

- **Rollback completo:** si el fallo es posterior al swap, revertir también los contenedores, no solo
  los punteros. Coherente, pero un smoke inestable puede tirar abajo un release sano.
- **Fail-forward explícito:** si el swap ya ocurrió, **dejar los punteros en el release nuevo**
  (coherentes con la realidad) y fallar ruidosamente pidiendo diagnóstico. Es lo que un humano tuvo
  que hacer a mano las dos veces.
- **Separar los gates:** distinguir «fallo de despliegue» (revertir) de «fallo de verificación
  posterior» (no revertir a ciegas, avisar).

Requisitos innegociables de la solución que elijas:

- [ ] `update_release()` **nunca** puede terminar con punteros y contenedores discrepando. Si no
      puede garantizar coherencia, debe decirlo explícitamente y no afirmar «pointers restaurados».
- [ ] El mensaje final debe reflejar el **estado real** del host, no la intención del script.
- [ ] Añade una verificación de coherencia (`current` ↔ `CURRENT_RELEASE` ↔ env ↔ imagen de los
      contenedores en ejecución) reutilizable desde `oracle-control health`, que falle si divergen.
      Hoy ese chequeo no existe, y por eso la incoherencia pasó dos veces desapercibida al script.
- [ ] Nunca revertir esquema: sigue valiendo la regla de rollback solo de aplicación.
- [ ] Registra la decisión y su porqué en `docs/implementation/DECISIONS.md`.

Si el diseño elegido cambia el runbook, actualiza `RELEASE.md` y `ROLLBACK.md`.

---

## Criterios de aceptación

- [ ] Las **diez** rutas (4 de entity-intel + 6 de procurement) devuelven `401` a un anónimo con
      entrada inválida, sin filtrar detalles de esquema; con sesión, la validación sigue dando `422`
      con detalle.
- [ ] Tests parametrizados cubren los tres casos por ruta y fallan si se vuelve a invertir el orden.
- [ ] Existe una prueba contractual sobre `url_map` que detecta el patrón en rutas futuras.
- [ ] El barrido final del patrón da cero, y así se declara en el resumen.
- [ ] `scripts/smoke-production.sh` pasa **sin haber sido modificado**.
- [ ] `update_release()` no puede dejar punteros y contenedores discrepando; `oracle-control health`
      detecta la divergencia si ocurre.
- [ ] Ruff, mypy y pytest verdes; lint/typecheck/test del frontend si lo tocas (no debería).
- [ ] `STATUS.md` actualizado con el estado real, y `DECISIONS.md` con la decisión del Alcance B.

## Despliegue y verificación (obligatorio)

Sigue el runbook (§14 de `AGENTS.md`): auditoría read-only, backup + restore-test, preparar release
inmutable, `compose config --quiet`, `sudo oracle-control update <release-id>`, smoke y health. **No
hay migración** en este cambio → upgrade solo de aplicación.

La verificación que de verdad importa, en producción y con `curl` real:

```bash
# Debe ser 401, no 422 — es el gate que hoy falla
curl -s -o /dev/null -w "%{http_code}\n" \
  "https://oracle.opnconsultoria.com/api/v1/entity-intel/suggest?q=ib&kind=company"
```

Y el despliegue debe terminar **verde por sí solo, sin arreglar punteros a mano**. Si vuelve a hacer
falta un forward-fix manual, el Alcance B no está resuelto: dilo claramente en el resumen en lugar de
darlo por bueno.

## No hacer

- No modifiques el smoke para que use una query válida: enmascara el defecto en vez de arreglarlo.
- No bajes el `min=3` de F2: es correcto, el trigram lo necesita.
- No toques Nginx, UFW, SSH ni TLS. No ejecutes migraciones ni downgrades.
- No hagas `git pull`, `docker compose down/-v`, `DROP DATABASE` ni `pg_restore` contra producción.
- No uses `procurement_routes.py` como fichero modelo: tiene seis rutas con el mismo defecto.
- No afirmes que una prueba pasó sin incluir el comando y su salida (`AGENTS.md` §16 y §21).

## Siguiente fase (no en este prompt)

Queda pendiente la prueba end-to-end del informe documental, bloqueada hasta ahora por el bug de las
barras (ya resuelto en ambos lados). Candidata verificada: adjudicación de **Iturri** con
`folder_id` = `EMERGENCIACR2026/671` — lleva barra, así que ejercita de paso la ruta `:path`. El
flujo a probar: fijar la adjudicación al expediente → generar informe → descarga real de PDF,
antivirus, extracción de texto y análisis con Ollama.
