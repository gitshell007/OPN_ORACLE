# 40 — El 46% de la suite no se ejecuta, y el cerrojo de oracle-control se queda colgado (P0 · integridad)

> Prompt de corrección para Codex. Dos hallazgos de la verificación del 2026-07-17, ninguno
> introducido por los prompts 35-39: son deuda preexistente que llevaba semanas invisible.
> **Ninguno oculta bugs en CI**, pero los dos hacen que «los tests pasan» y «el despliegue funciona»
> signifiquen bastante menos de lo que parece. Va **antes que cualquier funcionalidad nueva**.

## Hallazgo 1 — 129 tests unitarios se saltan en silencio (P0)

Medido en local, sin `ORACLE_RUN_INTEGRATION=1`:

```
uv run pytest --no-cov -m "not integration"
  → 155 passed, 129 skipped, 107 deselected

uv run pytest --no-cov -m "not integration" --ignore=tests/test_integration_*.py
  → 284 passed, 0 skipped
```

**155 + 129 = 284.** Los 129 «saltados» pasan todos. El simple hecho de *recolectar* los ficheros de
integración desactiva casi la mitad de la suite unitaria.

**Ficheros que no se ejecutan enteros** (0 pasan, todos saltados):

| Fichero | Tests |
|---|---|
| `test_procurement.py` | 46 |
| `test_reporting_routes_extra.py` | 15 |
| `test_signal_avanza.py` | 15 |
| `test_multitenancy_unit.py` | **13** |
| `test_jobs.py` | 11 |
| `test_reporting.py` | 9 |
| `test_signal_ai_provider.py` | 7 |
| `test_oracle_scoring.py` | 3 |
| `test_procurement_document_report.py` | 3 |
| `test_security_surface.py` | **2** |

Entre ellos, el aislamiento multi-tenant (AGENTS.md §7, «regla absoluta») y la superficie de
seguridad.

**Causa raíz, aislada por bisección** (`--ignore` fichero a fichero: solo
`test_integration_alerts.py` cambia el resultado):

1. `tests/test_integration_alerts.py:37` declara:
   ```python
   pytest_plugins = ("tests.test_integration_reporting_extra",)
   ```
   Eso registra ese módulo como **plugin global de pytest**, no como una importación local.
2. `tests/test_integration_reporting_extra.py:208` define:
   ```python
   @pytest.fixture(autouse=True)
   def clean_reporting_sessions(reporting_stack) -> None: ...
   ```
   Al venir de un plugin global, su `autouse` deja de estar acotado a su módulo.
3. `reporting_stack` (línea ~60) hace `pytest.skip("define ORACLE_RUN_INTEGRATION=1")` si la
   variable no está.
4. Resultado: todo test recolectado **después** pide la autouse → pide `reporting_stack` → se salta.

**El detalle que lo delata:** los afectados son exactamente los ficheros **alfabéticamente
posteriores** a `test_integration_*`. `test_contract.py` y `test_entity_intel.py` se salvan por
empezar por letra anterior. **El orden alfabético del nombre del fichero decide si tu test se
ejecuta o no.** Un `test_zzz.py` nuevo nacería muerto y nadie se enteraría.

### Qué se pide

Arregla la causa, no el síntoma. `pytest_plugins` en un módulo de test es la raíz: los fixtures
compartidos entre módulos de integración deben vivir donde corresponde (un `conftest.py` acotado a
integración, o un módulo de fixtures importado explícitamente), no registrarse como plugin global.
Razona tu solución y documenta por qué la elegida no puede volver a filtrar una `autouse` fuera de
su ámbito.

**Innegociable, y es la parte importante:**

- [ ] Un test o comprobación en CI que **falle si el número de tests recolectados y ejecutados cae
      sin que nadie lo declare**. Un salto masivo y silencioso no puede volver a pasar
      desapercibido. Hoy la suite dice «155 passed» en verde mientras oculta 129: eso es
      exactamente el falso verde que este proyecto lleva semanas persiguiendo.
- [ ] `uv run pytest -m "not integration"` ejecuta los 284 sin saltar ninguno.
- [ ] Los saltos que queden deben ser **declarados y visibles**, no un efecto colateral de un
      plugin.

Comprueba además si esto afecta a CI (que sí define `ORACLE_RUN_INTEGRATION=1` y por tanto no
saltaba nada): si en CI se ejecutaba todo, dilo explícitamente para que quede claro que no se han
ocultado fallos allí.

## Hallazgo 2 — `oracle-control` se cuelga reteniendo el cerrojo (P1)

`create_backup` termina llamando a `pause()`, que espera un Intro. Con `ssh -tt` —lo único que
funciona, porque `confirm()` exige `[[ -t 0 ]]`— el proceso queda vivo esperando esa tecla y
**retiene `/run/lock/opn-oracle-control.lock` indefinidamente**, bloqueando cualquier operación
posterior.

Ocurrió hoy en producción durante el despliegue de `479f416`: el backup terminó correctamente
(manifiesto, `database.dump` y checksums verificados), pero el `restore-test` siguiente falló con
«Otra operación de control está en curso» y hubo que localizar el PID y hacer `kill -9` a mano.

El problema de fondo: **el mismo binario sirve para un humano en una terminal y para una
automatización, y solo está pensado para el primero.** Decide cómo resolverlo y razónalo:

- un modo no interactivo explícito (`--yes`/`--non-interactive`) que salte `confirm`/`pause`
  conservando los gates reales (manifiesto, evidencia, frase de confirmación);
- o que `pause()` no se ejecute cuando la sesión no es realmente interactiva;
- o un cerrojo con dueño y caducidad que no sobreviva a un proceso zombi.

Requisitos:

- [ ] Automatizar `backup`, `restore-test` y `update` no puede dejar el cerrojo retenido.
- [ ] No relajes los gates de seguridad para conseguirlo: la frase de confirmación de `update` y la
      exigencia de manifiesto y evidencia se quedan.
- [ ] Documenta en `CONTROL_CENTER.md` cómo se invoca desde una automatización.

## Fleco menor

`.codex-screenshots/` aparece como untracked tras el prompt 39. Decide si va al `.gitignore` o si
se borra, pero que no se quede ahí ensuciando `git status`.

---

## Criterios de aceptación

- [ ] `uv run pytest -m "not integration"` ejecuta 284 tests sin saltos silenciosos.
- [ ] Existe una protección que falla si la recolección cae sin declararlo.
- [ ] `scripts/api-test.sh --unit` refleja la realidad: si dice 284, son 284.
- [ ] Automatizar oracle-control no deja cerrojos huérfanos.
- [ ] Decisiones registradas en `DECISIONS.md`; `STATUS.md` dice la verdad.
- [ ] **Ejecuta los checks**: `scripts/api-test.sh --unit` y, si tocas frontend, `npm run lint`,
      `npm run typecheck` y `npx vitest run`. `uv` está en `~/.local/bin/uv`.

## No hacer

- No arregles esto marcando los tests afectados como `integration`: se ejecutan perfectamente sin
  PostgreSQL ni Redis (284 pasan al ignorar los ficheros de integración). Serían falsos saltos.
- No añadas `ORACLE_RUN_INTEGRATION=1` al entorno local para «arreglarlo»: eso haría que los
  fixtures de integración intenten conectar a servicios inexistentes.
- No relajes los gates de `oracle-control` para facilitar la automatización.
- No des por bueno el arreglo sin ejecutar la suite y comparar el recuento antes/después. Este
  prompt existe precisamente porque nadie miraba el recuento.
