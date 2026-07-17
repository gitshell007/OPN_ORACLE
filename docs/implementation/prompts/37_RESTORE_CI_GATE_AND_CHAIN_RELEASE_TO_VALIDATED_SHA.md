# 37 — Restaurar el gate de CI y encadenar el release al SHA validado (P0 de proceso)

> Prompt de proceso para Codex. No arregla un bug de producto: arregla **por qué los bugs llegan a
> producción**. Es la causa raíz de todo lo apagado en los prompts 26, 33, 35 y 36. Requiere una
> decisión de producto previa (ver «Gate de decisión»), así que **no empieces sin confirmación**.

## Contexto: hoy nada impide desplegar código roto

`ci.yml` solo se dispara con `workflow_dispatch`, y lo dice explícitamente en un comentario:

```yaml
# UAT fast-lane: keep the full CI available, but do not run it automatically on
# every push while the product is still moving quickly. Re-enable push/PR
# triggers when master becomes release-gated again.
workflow_dispatch:
```

No es un descuido: **fue una decisión consciente** para ir rápido durante UAT. Y `release.yml`
(también `workflow_dispatch`) publica imágenes sin exigir que el CI del **mismo SHA** esté verde.
Resultado: `master` acepta cualquier cosa y se puede publicar y desplegar sin lint, tipos,
migraciones ni tests.

**Prueba en vivo del 2026-07-17, no es teórico.** La entrega del prompt 35 llegó con:

- **12 tests en rojo** (4 + 6 de autorización/validación con arnés incorrecto, 1 falso positivo en
  el test de fuga de esquema, 1 regresión real en el texto de evidencia);
- **1 error de Ruff** (`I001`, imports sin ordenar);

y nada de eso habría sido detectado por ningún automatismo. Se descubrió porque un humano ejecutó
la suite a mano antes de desplegar. Con el gate actual, ese código se habría publicado en verde.

**Agravante que multiplica el riesgo:** el entorno donde se escribe el código **no puede ejecutar la
suite**: no hay `uv` ni `pytest` instalados, y el propio informe del prompt 35 lo declara («No he
podido ejecutar pytest/Ruff/mypy backend porque este entorno no tiene `uv` ni `pytest`»). Si quien
escribe no puede probar y CI no se dispara solo, **no existe ninguna red**. Es exactamente cómo se
desplegaron el bug de las barras, el 422 del smoke y la Idempotency-Key.

## Gate de decisión (obligatorio antes de tocar nada)

Restaurar el CI automático tiene un coste real: cada push ejecutará la suite completa con
PostgreSQL, Redis, Celery, migraciones y scans, y eso frena el ritmo de UAT. **Esa es la decisión
que el comentario de `ci.yml` aplazó, y toca tomarla ahora, no asumirla.**

Presenta al responsable las opciones y espera respuesta explícita:

1. **UAT ha terminado** → CI obligatorio en push y PR sobre `master`, rama protegida, release
   encadenado a SHA verde. Máxima seguridad, menor velocidad.
2. **UAT sigue, pero con red mínima** → CI automático solo en PR (no en cada push), y release
   encadenado a SHA verde de forma innegociable. Compromiso razonable: se puede iterar rápido en
   ramas, pero nada llega a producción sin validar.
3. **Mantener el fast-lane** → entonces el gate debe moverse al despliegue: `oracle-control update`
   rechaza cualquier release cuyo SHA no tenga un CI verde registrado. Menos ideal, pero cierra la
   puerta que de verdad importa.

Mi recomendación es la **2**, seguida de la 1 cuando se cierre UAT: preserva la velocidad donde no
hace daño y bloquea donde sí.

---

## Alcance A — Encadenar el release al SHA validado (innegociable en las tres opciones)

`release.yml` no debe poder publicar imágenes de un SHA sin CI verde de **ese mismo SHA** (no de la
rama, no del último run). Implementa la comprobación de forma que no se pueda saltar por descuido:
consulta la GitHub API por el conclusion del workflow CI para el SHA exacto, y falla el job si no
existe o no es `success`. Documenta el procedimiento de excepción (si lo hay) y hazlo ruidoso.

## Alcance B — Restaurar el disparo automático (según la opción elegida)

Aplica lo decidido en el gate: `push`/`pull_request` sobre `master`, o solo `pull_request`. Retira
el comentario del fast-lane, que dejará de ser cierto. Si la opción elegida exige **rama
protegida**, eso se configura en GitHub y no desde el repo: no puedes hacerlo tú — deja
instrucciones exactas (qué checks marcar como requeridos, con sus nombres de job) en
`docs/operations/` y anótalo como cambio manual pendiente en tu resumen.

## Alcance C — Que quien escribe pueda probar

Un comando único y reproducible que instale y ejecute la suite backend, de modo que ningún agente
vuelva a entregar código sin haberlo probado. Hoy `apps/api` usa `uv` pero no hay ni Makefile ni
script de arranque, y AGENTS.md §19 espera equivalentes de `make api-test`. Añade la entrada que
falte (Makefile o script en `scripts/`), documenta el prerrequisito de `uv` en el README y verifica
que desde un clon limpio funciona.

Relacionado y **solo para documentar, no arregles ahora**: las pruebas `integration` requieren
PostgreSQL real vía Docker; un entorno sin Docker no puede ejecutarlas ni en local ni en el agente.
Anótalo en `OPEN_QUESTIONS.md`: hoy esas pruebas solo se ejecutan de verdad en CI, lo que refuerza
que CI no puede ser opcional.

---

## Criterios de aceptación

- [ ] Decisión del gate registrada en `DECISIONS.md` con su porqué y quién la tomó.
- [ ] `release.yml` no publica si el CI del SHA exacto no está verde; probado con un SHA sin CI.
- [ ] Los disparos de `ci.yml` reflejan la opción elegida; el comentario del fast-lane, retirado.
- [ ] Instrucciones de rama protegida documentadas y marcadas como cambio manual pendiente.
- [ ] Existe un comando único que ejecuta la suite backend desde un clon limpio; documentado.
- [ ] `STATUS.md` corregido: hoy declara CI en PR/push cuando en realidad es manual (contradicción
      detectada en la auditoría del 17-07). Que el documento diga la verdad.

## No hacer

- No empieces sin la respuesta al gate de decisión: elegir por tu cuenta entre velocidad y seguridad
  no te corresponde.
- No relajes los checks existentes para que pasen antes (ni `--no-cov`, ni saltar mypy, ni excluir
  tests lentos).
- No toques la lógica de despliegue del prompt 35: ya está resuelta y desplegada aparte.
- No inventes tokens ni secretos nuevos para la consulta a la API de GitHub: usa el `GITHUB_TOKEN`
  del propio workflow con los permisos mínimos.
