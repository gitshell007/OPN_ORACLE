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

## Decisión ya tomada (2026-07-17) — no la reabras

El responsable del producto ha elegido, entre las tres opciones planteadas:

> **CI automático en cada Pull Request (no en cada push) + `release.yml` encadenado al SHA verde.**

Razón: preserva la velocidad de iteración en ramas, donde equivocarse es barato, y bloquea la
puerta que de verdad importa, que es la publicación de imágenes. La rama protegida con CI en push
queda para cuando se cierre UAT formalmente; anótalo como fase futura, no lo implementes ahora.

Implementa exactamente eso. Si al hacerlo descubres que la opción elegida no es viable por una
razón técnica concreta, **para y explícalo** en vez de sustituirla por tu criterio.

---

## Alcance A — Encadenar el release al SHA validado (innegociable en las tres opciones)

`release.yml` no debe poder publicar imágenes de un SHA sin CI verde de **ese mismo SHA** (no de la
rama, no del último run). Implementa la comprobación de forma que no se pueda saltar por descuido:
consulta la GitHub API por el conclusion del workflow CI para el SHA exacto, y falla el job si no
existe o no es `success`. Documenta el procedimiento de excepción (si lo hay) y hazlo ruidoso.

## Alcance B — Restaurar el disparo automático en Pull Request

Añade el disparo `pull_request` sobre `master` a `ci.yml`, conservando `workflow_dispatch` para
validaciones manuales puntuales. **No añadas `push`**: es lo decidido. Retira el comentario del
fast-lane, que dejará de ser cierto.

Deja documentado en `docs/operations/` cómo marcar los checks como requeridos en la configuración
de rama protegida de GitHub (nombres exactos de los jobs), para cuando se cierre UAT. Eso no se
puede hacer desde el repo: anótalo como cambio manual pendiente, no como hecho.

## Alcance C — Que quien escribe pueda probar

> **Corrección del 2026-07-17: `uv` SÍ está instalado.** El informe del prompt 35 concluyó «no hay
> `uv` ni `pytest`» y era falso: `uv 0.11.29` está en `~/.local/bin/uv` desde el 15 de julio, y el
> entorno `apps/api/.venv` ya contiene `pytest`, `ruff` y `mypy`. Lo que falla es el PATH:
> `~/.local/bin` se añade desde `.zshrc` (`. "$HOME/.local/bin/env"`), y un shell **no interactivo**
> —como el de un agente— no lo lee. De ahí que `command -v uv` no devuelva nada. Basta con:
>
> ```bash
> export PATH="$HOME/.local/bin:$PATH"
> cd apps/api && uv run pytest -q --no-cov
> ```
>
> Doce tests en rojo se entregaron como «no pude probarlo» por un `export` que faltaba. Esa es la
> deuda real: no la ausencia de la herramienta, sino que encontrarla dependa de un shell interactivo.

Añade un comando único y reproducible que ejecute la suite backend **sin depender del PATH del
shell** (resolviendo `uv` por ruta absoluta o comprobando y avisando si falta). Hoy `apps/api` usa
`uv` pero no hay ni Makefile ni script de arranque, y AGENTS.md §19 espera equivalentes de
`make api-test`. Añade la entrada que falte (Makefile o script en `scripts/`), documenta el
prerrequisito en el README, y verifica que funciona desde un shell no interactivo:
`zsh -c 'scripts/…'` sin sourcear nada.

Relacionado y **solo para documentar, no arregles ahora**: las pruebas `integration` requieren
PostgreSQL real vía Docker; un entorno sin Docker no puede ejecutarlas ni en local ni en el agente.
Anótalo en `OPEN_QUESTIONS.md`: hoy esas pruebas solo se ejecutan de verdad en CI, lo que refuerza
que CI no puede ser opcional.

---

## Criterios de aceptación

- [ ] Decisión registrada en `DECISIONS.md`: CI en PR + release atado a SHA verde, con su porqué.
- [ ] `release.yml` no publica si el CI del SHA exacto no está verde; probado con un SHA sin CI.
- [ ] `ci.yml` se dispara en `pull_request` (no en `push`); comentario del fast-lane retirado.
- [ ] Instrucciones de rama protegida documentadas y marcadas como cambio manual pendiente.
- [ ] Existe un comando único que ejecuta la suite backend desde un shell **no interactivo**, sin
      depender de que `.zshrc` haya puesto `uv` en el PATH; documentado y probado.
- [ ] `STATUS.md` corregido: hoy declara CI en PR/push cuando en realidad es manual (contradicción
      detectada en la auditoría del 17-07). Que el documento diga la verdad.

## No hacer

- No añadas el disparo en `push` ni configures rama protegida: la decisión fue CI en PR.
- No relajes los checks existentes para que pasen antes (ni `--no-cov`, ni saltar mypy, ni excluir
  tests lentos).
- No toques la lógica de despliegue del prompt 35: ya está resuelta y desplegada aparte.
- No inventes tokens ni secretos nuevos para la consulta a la API de GitHub: usa el `GITHUB_TOKEN`
  del propio workflow con los permisos mínimos.
