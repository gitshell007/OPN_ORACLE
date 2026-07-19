# 58 — Protocolo de verificación y entrega: por qué se nos escapan los fallos (P0, transversal)

> Este prompt no pide una funcionalidad. Pide cambiar **cómo trabajamos**, a partir de la
> evidencia de todos los fallos que han llegado a producción en las últimas semanas.
> Léelo entero antes de tocar nada. El entregable incluye modificar `AGENTS.md`, así que
> afecta a todas las tareas futuras.
>
> Aviso honesto y necesario: **una parte de estos fallos no es culpa de quien implementa,
> sino de prompts mal especificados**. Eso también se corrige aquí, y se dice explícitamente
> quién falló en cada caso. No es un documento de reproche: es un documento de bordes.

---

## 1. El hallazgo central

Se han revisado uno por uno los fallos que alcanzaron producción. **Ninguno fue un error de
lógica de negocio.** Todos vivían en una costura que quien implementa no puede observar desde
el editor:

| Costura | Fallo real |
|---|---|
| test ↔ despacho HTTP real | `json_data` vs `payload`: la vista revienta con `TypeError` solo por HTTP |
| código ↔ contenedor | `DOCUMENT_ALLOW_OFFICIAL_UNSCANNED` en el fichero de entorno, ausente en `compose.prod.yml` |
| Oracle ↔ Signal | `_signal_output` solo entendía la forma de respuesta de Ollama; OpenRouter devuelve `choices[0].message.content` |
| código ↔ base de datos | UUID guardados con `model_dump(mode="json")` vuelven como cadenas y `model_validate` estricto los rechaza |
| código ↔ runtime de librería | `httpx.RemoteProtocolError` **no** es subclase de `TimeoutException` ni de `NetworkError` |
| entrada ↔ presupuesto del modelo | el informe truncaba porque el número de fuentes citables fija el suelo de longitud de la salida |

La conclusión operativa es dura pero útil: **la «definición de terminado» actual (`AGENTS.md`
§20) se puede cumplir íntegra sin cruzar ni una sola de esas costuras.** Por eso los fallos no
los caza el gate: los caza producción.

---

## 2. Taxonomía de nuestros fallos reales

Cada patrón, con su evidencia. Estos son los que hay que dejar de repetir.

### 2.1 Ceguera de frontera: tests a la altura equivocada

`create_entity_report` recibía `payload` en vez de `json_data`. APIFlask inyecta el cuerpo como
`json_data`, así que la vista solo revienta bajo despacho HTTP real; invocarla directamente
funciona. Hubo además 10 tests que usaban `test_request_context` llamando al endpoint a mano,
saltándose la conversión a 422 de APIFlask: **verificaban una ruta que no existe en producción**.

**Regla:** todo endpoint se prueba con `client.post(...)`/`client.get(...)` sobre la app real.
Nunca invocando la función de vista. Si el test no pasa por el router, no prueba la ruta.

### 2.2 Afirmaciones sobre el entorno sin comprobarlas

Se reportó «no hay `uv` ni `pytest`» y se entregaron 12 tests en rojo. Era falso: `uv 0.11.29`
estaba en `~/.local/bin`, que solo entra en el `PATH` vía `.zshrc`, y los shells no interactivos
no lo leen. Faltaba un `export PATH`.

Más reciente: se reportó «Ruff: correcto» cuando `ruff format --check` **fallaba** en el fichero
de tests entregado. Se ejecutó `ruff check` y se reportó como si fuera todo Ruff.

**Regla:** una afirmación sobre el entorno («no está instalado», «no se puede ejecutar») exige
el comando y su salida. Y el nombre de un gate solo se puede dar por cumplido si se ejecutaron
**todos** sus comandos, no uno de ellos.

### 2.3 Configuración declarada pero no cableada

Una variable nueva necesita **cuatro** sitios, y saltarse uno la deja muerta:

1. campo en el dataclass `Settings` (`config.py`),
2. parseo con su valor por defecto,
3. entrada en `compose.prod.yml` (si no, no llega al contenedor),
4. entrada en `infra/production/oracle.env.example`.

Ocurrió con `DOCUMENT_ALLOW_OFFICIAL_UNSCANNED`. Y **volvió a ocurrir con
`ENTITY_INTEL_MAX_EVIDENCE_SOURCES`, cometido por quien audita, no por quien implementa**: el
defecto funcionaba, pero sin la variable en compose no había palanca de runtime y recortar
habría exigido desplegar código.

**Regla:** al añadir configuración, recorrer los cuatro puntos y **demostrarlo** con
`docker compose config` o `printenv` dentro del contenedor.

### 2.4 Arreglar la instancia e ignorar la clase

Tres casos, uno de ellos cometido por quien audita:

- `json_data`: se arregló una ruta y **no se barrió el fichero**; la segunda ruta tenía el
  mismo fallo y volvió a romper en producción.
- `model_validate` sobre payload ya serializado: se arregló en la incorporación; el mismo
  patrón estaba en `_strip_unauthorized_evidence_blocks`, **la red de seguridad que elimina
  citas no autorizadas**, que habría reventado justo cuando actúa.
- `except (httpx.TimeoutException, httpx.NetworkError)`: el mismo patrón en **cinco** ficheros.

**Regla:** todo arreglo va seguido de un `grep` del patrón en el repo, y el resumen final
declara qué se buscó y qué apareció. Si aparecen más instancias, se arreglan o se justifica por
qué no.

### 2.5 No consultar la memoria institucional

El caso más caro y el más evitable. `entity_dossier_report.py` contenía este comentario, escrito
tras medirlo en producción:

```
#   25 actos -> informe completo y más rico, 0 citas inventadas
#   65 actos -> vuelve a truncar ("Invalid JSON: EOF", línea 585)
```

Justo debajo se añadieron tres topes nuevos (patentes 20, CNMV 20, adjudicaciones 15) que, con
los ya existentes, elevaban el techo de fuentes citables **de 55 a 110**: el doble del punto de
rotura medido. El conocimiento estaba a cinco líneas del cambio.

**Regla:** cuando toques un módulo, lee sus comentarios de medición y `docs/implementation/DECISIONS.md`.
Un número acompañado de una medición en producción es **carga estructural**, no decoración. Si
tu cambio lo afecta, dilo en el resumen y explica por qué sigue siendo seguro.

### 2.6 Tratar el síntoma en vez de la causa

El informe truncaba. Se subió el techo de salida de 5000 → 8000 → 16000. El corte se movió de la
línea 225 a la 281 y a la 615, pero **nunca cerró el JSON**. La causa no era el techo de salida:
era la entrada sin acotar, porque cada fuente citable se enumera en el índice de fuentes.
Acotando la entrada, el informe se completó a la primera.

**Regla:** si un límite hay que subirlo dos veces, deja de subirlo. Es una señal de que la causa
está en otro sitio.

### 2.7 Cambiar un contrato sin medir el radio de impacto

Las secciones de la plantilla `entity_intelligence` se cambiaron in situ, sin subir de versión.
`_validate_report_output` exige que **todas** las secciones de la plantilla estén presentes, así
que los informes ya incorporados dejaron de poder revisarse. El daño real fue nulo (2 informes,
ambos de prueba) **porque se midió antes de desplegar**, no porque el cambio fuera seguro.

**Regla:** al cambiar un contrato (secciones de plantilla, esquema, constraint, forma de
respuesta), consulta cuántas filas existentes quedan afectadas y dilo. Un `SELECT count(*)` vale
más que una intuición.

### 2.8 Pérdida silenciosa de datos

`_year_distribution` descartaba sin avisar las adjudicaciones sin fecha válida, así que la suma
por años no cuadraba con el total y el lector no tenía forma de saber por qué.

**Regla:** ningún dato se cae en silencio. Si se descarta o se recorta algo, el resultado lo
declara. Esto vale igual para los recortes que hace Oracle antes de llamar al modelo: un informe
que analiza 25 actos de 65 **debe decirlo**, y no puede concluir ausencia de nada a partir de lo
que no vio.

### 2.9 Los gates que no se ejecutan pudren en silencio

Los 107 tests de integración llevaban tiempo sin correrse. Al ejecutarlos aparecieron **tres
fallos latentes de días distintos**:

- una regresión de sanitización introducida el 17 de julio, **con su test ya escrito**, que
  filtraba el texto de la excepción en el `error_message` de cualquier job;
- dos aserciones obsoletas desde el prompt 45 (afirmaban 9 plantillas; son 10);
- un test que solo pasaba si la integración no se ejecutaba antes.

Ninguno se introdujo esa mañana. El gate no estaba en rojo: **no estaba encendido**.

**Regla:** la integración se ejecuta. Hay receta sin Docker en el prompt 57 y en §19 de
`AGENTS.md` tras este cambio. Si no puedes ejecutarla, dilo en el resumen como riesgo abierto,
no como nota al pie.

### 2.10 Tests que afirman sobre el texto, no sobre el comportamiento

Cometido por quien audita. Un test comprobaba con `inspect.getsource` que cierto `except`
contenía `httpx.RequestError`. Al mutar el código quitando esa captura, **el test siguió
pasando**: lo satisfacía un comentario que mencionaba la excepción. Un test que no falla al
romper lo que cubre es peor que no tener test, porque da falsa confianza.

**Regla:** nada de `inspect.getsource`, ni de afirmar sobre docstrings o nombres. Comportamiento
observable: valores devueltos, estado en base de datos, códigos HTTP, efectos.
**Y cada test nuevo se verifica mutando** el comportamiento que cubre; si no falla, el test no
sirve. Declara en el resumen qué mutaste y qué falló.

### 2.11 El éxito destapa bugs latentes

El fallo de los UUID llevaba ahí desde el principio, invisible mientras los informes salían sin
citar evidencia: sin `evidence_ids` no hay UUID que validar. Lo destapó **conseguir que el
informe citara**, que era justo el objetivo del cambio.

**Regla:** cuando una funcionalidad empieza a producir datos que antes no producía, revisa
específicamente los caminos que ahora se recorren por primera vez (serialización, validación de
vuelta, constraints, límites). Que algo llevara meses «funcionando» no prueba que estuviera
probado: prueba que no se estaba usando.

---

## 3. Lo que falló en la especificación, no en la implementación

Para que el reparto sea justo, dos fallos fueron de los prompts:

- **Prompt 35** señalaba `procurement_routes.py` como fichero modelo a imitar. Ese fichero tenía
  seis rutas con el mismo defecto que se pedía corregir. La corrección se hizo sobre un modelo
  roto.
- **Prompt 56** pedía acotar las adjudicaciones citables, pero **nunca exigió mantener acotado el
  total de fuentes**, pese a que el techo se había medido el día anterior y estaba escrito en un
  comentario del mismo fichero. La regresión de 110 fuentes es imputable al prompt.

**Regla para quien escribe prompts (no para Codex):** todo invariante conocido que el cambio
pueda romper se enuncia como obligación explícita, no como contexto. Si el prompt dice «acota X»
sin decir «y el total sigue acotado», la implementación correcta puede romper el sistema.

**Regla para quien implementa:** si detectas que el prompt contradice una medición registrada en
el código o en `DECISIONS.md`, **para y dilo**. No lo implementes en silencio. Ese aviso vale
más que la entrega.

---

## 4. Qué hay que cambiar (entregable)

### 4.1 Reescribir `AGENTS.md` §20 «Definición de terminado»

La lista actual es cierta pero insuficiente: se cumple sin cruzar ninguna costura. Añade estos
puntos, con este nivel de concreción:

- Los endpoints nuevos o modificados tienen test **por despacho HTTP real**, no por invocación
  directa de la vista.
- Cada test nuevo se ha **verificado mutando** el comportamiento que cubre, y el resumen dice
  qué mutación se aplicó y qué test falló.
- Ningún test afirma sobre el código fuente, docstrings ni nombres de símbolo.
- Si el cambio introduce configuración, se ha recorrido el cuadrante completo (dataclass, parseo,
  `compose.prod.yml`, `oracle.env.example`) y se ha comprobado que la variable **llega al
  contenedor**.
- Si el cambio corrige un fallo, se ha barrido el repo buscando el mismo patrón y el resumen
  declara qué se buscó y qué apareció.
- Si el cambio toca un valor con medición registrada (comentario o `DECISIONS.md`), el resumen
  explica por qué sigue siendo seguro.
- Si el cambio altera un contrato con datos existentes, el resumen incluye el recuento de filas
  afectadas.
- La suite de integración se ha ejecutado, o su ausencia figura como **riesgo abierto** con el
  motivo.

### 4.2 Ampliar `AGENTS.md` §21 «Formato del resumen final»

Añade tres apartados obligatorios:

- **Mutaciones aplicadas y resultado.** Sin esto, «tiene tests» no es información.
- **Barrido del patrón.** Qué se buscó, dónde y qué apareció.
- **Invariantes tocados.** Qué mediciones o decisiones registradas afecta el cambio.

Y refuerza lo que ya dice: «Evita "todo funciona" sin evidencias concretas» debe aplicarse
también a los nombres de los gates. «Ruff: correcto» solo es válido si se ejecutaron `ruff check`
**y** `ruff format --check`.

### 4.3 Documentar en §19 la receta de integración sin Docker

Está en el prompt 57. Llévala a `AGENTS.md` para que no se pierda, incluidos los dos escollos de
aislamiento ya conocidos: Celery reconfigura el logging con `disable_existing_loggers` al
arrancar el worker real, y `configure_logging` hace `root.handlers.clear()` al construir la app,
lo que se lleva por delante el handler de `caplog`.

### 4.4 Convertir en tests los invariantes que hoy son prosa

Esto es lo más valioso del prompt. Un invariante escrito en un comentario no protege nada; uno
escrito en un test, sí. Añade al menos estos, todos verificados por mutación:

1. **Cuadrante de configuración.** Test que recorre los campos de `Settings` relacionados con
   despliegue y comprueba que cada uno aparece en `compose.prod.yml`. Hoy es la tercera vez que
   se nos olvida cablear una variable.
2. **Contrato de APIFlask.** Ya existe un barrido textual para `entity_intel_routes.py`.
   Generalízalo a **todos** los blueprints: cualquier vista con `@bp.input(location="json")` debe
   recibir `json_data`.
3. **Excepciones de red.** Test que afirme que los clientes HTTP capturan `httpx.RequestError`
   (no un subconjunto), porque `RemoteProtocolError` y otras cinco quedan fuera si se listan a
   mano.
4. **Techo de fuentes citables.** Ya existe. Amplíalo para que falle si se añade un tipo de
   fuente nuevo sin contarlo en el techo global.
5. **Revalidación de payloads guardados.** Test genérico: todo modelo `StrictModel` que se
   guarde con `model_dump(mode="json")` debe poder releerse con `model_validate_json`.

---

## 5. Criterios de aceptación

- `AGENTS.md` §19, §20 y §21 actualizados con lo anterior, en el estilo del documento (conciso,
  imperativo, sin relleno).
- Los cinco tests de invariantes implementados, cada uno verificado por mutación, y el resumen
  final declara qué mutación se aplicó a cada uno y qué falló.
- Suite completa en verde con integración: `uv run pytest` con `ORACLE_RUN_INTEGRATION=1`,
  cobertura por encima del umbral.
- `ruff check`, `ruff format --check` y `mypy` limpios. Los tres nombrados por separado en el
  resumen, con su salida.
- Una entrada nueva en `docs/implementation/DECISIONS.md` que registre este protocolo, para que
  la próxima sesión lo encuentre sin depender de este prompt.

## 6. Qué NO hacer

- No cambies comportamiento de producción en este prompt. Es proceso, tests e invariantes.
  Si al escribir un test de invariante descubres un fallo real, **repórtalo y no lo arregles
  aquí**: merece su propio cambio con su propia verificación.
- No relajes ningún umbral ni ninguna regla para que el gate pase.
- No añadas tests que solo ejecuten líneas. Un test que no falla al mutar el comportamiento que
  dice cubrir es ruido con coste de mantenimiento.
- No conviertas `AGENTS.md` en un documento largo. Si un punto nuevo hace redundante a otro
  existente, fusiónalos. Un protocolo que no se lee no se cumple.
