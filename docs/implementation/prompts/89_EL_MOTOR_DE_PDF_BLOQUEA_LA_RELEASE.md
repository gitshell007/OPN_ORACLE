# 89 — El motor de PDF bloquea la release (P0 · seguridad + informes)

> Prompt de producto para Codex, **backend**. El gate `pip-audit` del CI está en rojo por dos
> avisos de WeasyPrint publicados el 24-07-2026, y con el CI rojo **no hay release posible**:
> `release.yml` falla cerrado si no existe una ejecución `success` para el SHA exacto
> ([RELEASE.md](../../operations/RELEASE.md)). Ahora mismo hay trabajo verificado esperando en
> `master` que no puede llegar a producción por esto.
>
> No es un ejercicio de subir un número: hay que decidir con criterio si se actualiza el motor
> de PDF, si se acepta el riesgo con justificación, o si el gate necesita otra forma. Las tres
> salidas son legítimas; elegir en silencio no.

## 1 — El bloqueo, medido

Ejecución fallida: [run 30128952131](https://github.com/gitshell007/OPN_ORACLE/actions/runs/30128952131),
paso `[2/5] Python dependency audit from the frozen lock`:

```
weasyprint 66.0   PYSEC-2026-2034   Fix Versions: 68.0
weasyprint 66.0   PYSEC-2026-3412   Fix Versions: (vacío)
```

Restricción actual: `"weasyprint>=63,<67"` (`apps/api/pyproject.toml:26`), resuelta a 66.0. La
última publicada en PyPI es **69.0**.

El escaneo es `uvx --from pip-audit==2.9.0 pip-audit --requirement ...`
(`scripts/run-quality-scans.sh:19`), **sin ningún mecanismo de exención**. Dato que condiciona
todo el prompt: si `PYSEC-2026-3412` realmente no tiene versión de arreglo, **ninguna versión
de WeasyPrint pasa el gate** y actualizar no desbloquea nada. Confírmalo antes que nada
consultando el aviso real (rango afectado, versión corregida si existe); la columna vacía puede
ser una laguna del dato o la verdad.

## 2 — La exposición real, antes de decidir

Cualquier decisión sobre riesgo aceptado necesita saber qué superficie hay de verdad, y aquí
el renderer está deliberadamente encerrado (`apps/api/src/opn_oracle/reporting/rendering.py:45`):

- **Sin red**: `url_fetcher=_forbid_external_fetch` convierte cualquier petición en error duro
  (línea 34). No hay descarga de imágenes, fuentes ni hojas de estilo remotas.
- **Entrada propia y saneada**: solo recibe el HTML estricto de `render_report_html`, con el
  texto del modelo escapado y las referencias externas rechazadas antes de llegar aquí.
- **Apagable**: `REPORT_PDF_MODE` admite `disabled` o `weasyprint` (`config.py:606`).

Contrasta cada aviso con eso: si el vector requiere HTML/CSS/SVG hostil o carga remota, la
exposición práctica puede ser nula. **Documenta la conclusión por aviso, con el vector citado**
— no un «no nos afecta» genérico. Y ojo: «no nos afecta hoy» no es lo mismo que «no nos
afectará», porque el HTML lo compone una plantilla que evoluciona.

## 3 — Las tres salidas

Elige una y justifícala con lo medido en 1 y 2:

- **Actualizar a 68/69.** Es un salto de dos o tres mayores en el motor que renderiza vuestros
  informes, recién estrenado (`c418d70`). Solo vale si va con comparación real de PDFs (ver
  sección 4). Recuerda que el runtime nativo está fijado en la imagen —pango, pangoft2,
  harfbuzz, fontconfig, fuentes DejaVu y Liberation (`apps/api/Dockerfile:26-35`)— y que hubo
  que resolver la caché de fontconfig en rootfs de solo lectura (`aae7ed4`, `Dockerfile:17`).
  Una versión nueva puede pedir otras librerías nativas o comportarse distinto ahí: verifícalo
  **dentro de la imagen**, no solo en tu máquina.
- **Aceptar el riesgo con exención explícita.** Si 2 demuestra exposición nula y 1 confirma que
  no hay versión que limpie ambos avisos, añade la exención al escaneo **con identificador,
  motivo, fecha y caducidad**, y una decisión registrada en `DECISIONS.md`. Una exención sin
  fecha de revisión se convierte en deuda invisible; el patrón de honestidad del proyecto exige
  que se vea.
- **Apagar el PDF temporalmente** (`REPORT_PDF_MODE=disabled`) si el riesgo no es descartable y
  no hay versión segura. Es la salida más incómoda y la que hay que declarar más alto: los
  informes dejarían de exportar a PDF, así que solo si las otras dos no sirven.

Lo que no vale: subir el pin a ciegas para poner el CI verde, ni relajar el gate a
`--audit-level` más laxo, ni quitar el paso del escaneo.

## 4 — Si actualizas: los PDF se comparan mirándolos

Un test que comprueba que el resultado empieza por `%PDF-` (`rendering.py:67`) no detecta que
la maquetación se haya roto. Antes y después del salto:

- Genera el mismo informe real con ambas versiones y compara los PDF: número de páginas,
  saltos, tablas que no se partan a mitad, tipografías resueltas (con las fuentes de la imagen,
  no las del Mac), tildes y eñes, y las secciones largas que motivaron el trabajo de
  `c418d70`.
- Ejecuta la comparación **en la imagen de producción**, donde están pango y las fuentes
  declaradas. Un PDF que se ve bien en local y mal en el contenedor es el fallo clásico aquí.
- Adjunta al informe de cierre qué informes comparaste y qué cambió. Si nada cambia, dilo con
  esa misma claridad.

## 5 — Coordinación

Hay trabajo sin commitear en esta misma zona (`reporting/service.py`, `jobs/tasks.py`,
`ai/registry.py` y sus tests) de otra sesión. **No lo arrastres ni lo pises**: commitea solo lo
tuyo por rutas explícitas. Si el cambio de versión entra en conflicto con ese trabajo, dilo en
vez de resolverlo por tu cuenta.

## Verificación exigida

- La consulta real de ambos avisos, citada, con rango afectado y versión corregida.
- La tabla de exposición por aviso contra las tres barreras de la sección 2.
- Suite backend completa con integración, `ruff check`, `ruff format --check`, `mypy src`,
  nombrados por separado.
- `bash scripts/run-quality-scans.sh` en verde localmente, y el CI verde para el SHA publicado
  — que es el objetivo de todo el prompt.
- Si actualizas: la comparación de PDF de la sección 4, ejecutada en la imagen.
- Si eximes: la entrada en `DECISIONS.md` con identificador, motivo, fecha y caducidad.

## Qué NO hacer

- No pongas el CI verde debilitando el escaneo: ni bajar el umbral, ni saltar el paso, ni
  exenciones sin caducidad ni motivo.
- No subas el pin sin comparar PDF: el motor de maquetación no se valida con un `startswith`.
- No toques `url_fetcher` ni la sanitización de `render_report_html` «de paso»: son las
  barreras que hacen defendible cualquier decisión de riesgo.
- No commitees el trabajo ajeno del árbol.
- No cambies de motor de PDF en este prompt: si 68/69 no sirve y la exención tampoco, eso es
  otra decisión con su propio análisis.
