# 73 — La pestaña «Noticias» no trae noticias, y su ruido llega al informe de IA (P1)

> Prompt para Codex. **No es un problema estético.** Ese contenido se pasa al informe de IA como
> evidencia citable, así que hoy el informe puede citar a **otra empresa distinta** como respaldo de
> una afirmación.
>
> Todo lo que sigue está medido hoy contra producción. No hay que investigar la causa.

## Qué hay detrás de la pestaña

En Signal, `/api/v1/oracle/entity/news` no consulta ninguna fuente de noticias. Hace literalmente
esto (`app/services/oracle_entity.py`):

```python
connector.search(query=f"{query} noticias", max_results=8, language="es")
```

Es una **búsqueda web** del texto `"<nombre> noticias"`. De ahí salen todas las consecuencias: sin
fecha de publicación, sin distinguir la entidad consultada de otra que se llame parecido, y con el
posicionamiento web decidiendo qué aparece.

Los campos que llegan lo confirman: `title`, `url`, `snippet`, `source`, `provider`. **No hay
fecha.** Una noticia sin fecha no es una noticia.

## Lo que ve hoy un analista en ITURRI SA

Los 8 resultados reales, íntegros:

| # | Fuente | Resultado | Qué es |
|---|---|---|---|
| 1 | iturri.com | «ITURRI \| Your safety matters» | su propia web |
| 2 | el-vinculo.com | «ITURRI S.A. — Licitaciones y contratos públicos» | agregador de licitaciones |
| 3 | shop.iturri.com | «Ropa, vestuario, accesorios…» | su propia tienda |
| 4 | guiaindustrial.com.ar | «**Iturria SA** — Guía Industrial Argentina» | **otra empresa** |
| 5 | catedraempresafamiliar | «Grupo Iturri: empresa familiar andaluza…» | ficha académica |
| 6 | orain.eus | «**Iturri Enea**, la marca vasca que viste a las celebrities» | **otra empresa** |
| 7 | conservasiturri.es | «**Conservas Iturri** — Productos Navarra» | **otra empresa** |
| 8 | netetrade.com | «**ITURRI LTD**» | **probablemente otra** |

**Cero de ocho son noticias.** Cuatro son empresas distintas, dos son webs de la propia empresa y
una es un agregador que además duplica datos de contratación que ya tenemos de mejor fuente.

## Por qué esto es de corrección y no de estética

`build_pending_entity_evidence_sources` en `oracle/entity_dossier_report.py` convierte estos
resultados en **evidencia citable** con `source_kind="news"`. En el último informe verificado de
ITURRI se pasaron **8 fuentes de noticias** al modelo dentro de las 45 permitidas.

Es decir: el informe de IA puede citar «Conservas Iturri, productos de Navarra» o «Iturri Enea, la
marca vasca que viste a las celebrities» como **evidencia sobre un fabricante de equipos contra
incendios**. Y lo haría con toda la trazabilidad formal en orden, porque el ID está en la lista de
permitidos.

Esto invalida en parte el trabajo de los prompts 54 y 56: conseguimos que el informe cite evidencia,
pero parte de esa evidencia no es de la entidad.

## Qué hay que conseguir

Que Oracle no presente como noticia de la entidad algo que no lo es, y **sobre todo** que no lo
ofrezca al modelo como evidencia citable sin filtrar.

Decide y justifica. Algunas direcciones:

- **El nombre de la pestaña.** «Noticias» promete lo que no hay. Piensa qué la describe con
  honestidad —búsqueda web, menciones en la web, referencias externas— y declara su naturaleza como
  ya hacemos con BORME y patentes.
- **Descartar lo que objetivamente no aporta**: el dominio propio de la entidad (`iturri.com`,
  `shop.iturri.com`) no es una mención externa, es su web.
- **Homónimos.** Es lo más difícil y lo más valioso. Un resultado cuyo título nombra a otra
  sociedad («Iturria SA», «Conservas Iturri», «Iturri Enea») no debería presentarse al mismo nivel.
  No busques certeza: **si no puedes confirmar que el resultado trata de la entidad consultada,
  dilo en la interfaz y no lo pases como evidencia citable.** Es preferible una lista más corta y
  fiable que una larga y contaminada.
- **La evidencia citable es la decisión más importante de este prompt.** Si no puedes garantizar
  que un resultado es de la entidad, no debe llegar al informe. Y si con eso se queda sin fuentes
  de noticias, es un resultado correcto: mejor un informe sin noticias que uno que cita a otra
  empresa.

## Invariantes

- **No toques Signal.** El origen es suyo, pero el filtrado y la presentación son nuestros. Si
  concluyes que hace falta una fuente de noticias de verdad —con fecha y desambiguación—, **anótalo
  como dependencia externa** en `OPEN_QUESTIONS.md`; no lo inventes ni lo simules.
- **No inventes fechas.** Los resultados no las traen; no las deduzcas del texto ni del dominio.
- **No rompas el techo global de fuentes citables** (`EVIDENCE_SOURCE_TOTAL_LIMIT`) ni el reparto
  por tipos: si dejan de entrar noticias, el hueco lo ocupan otros tipos, que es lo correcto.
- **Declara el recorte** en `source_limits`, como con los actos BORME y las patentes: si se
  descartaron N de M resultados por no poder atribuirlos, el informe debe decirlo.

## Verificación exigida

- Con el corpus real de ITURRI (los 8 de la tabla), la ficha **no** presenta como noticias de la
  entidad los de la propia web ni los de otras sociedades, y lo explica.
- **Ningún resultado no atribuible llega a `pending_evidence_sources`.** Test explícito.
- Test del caso limpio: una entidad cuyos resultados sí son suyos no pierde nada ni muestra avisos
  innecesarios.
- **Cada test nuevo verificado por mutación**, localizando la línea exacta antes de mutar. Esta
  semana han fallado tres mutaciones por apuntar al sitio equivocado.
- `ruff check`, `ruff format --check`, `mypy src` y la suite con integración. Frontend completo si
  tocas la ficha.
- Verificación en navegador sobre **ITURRI SA** describiendo el antes y el después. Si no tienes
  sesión, decláralo y la hago yo.

## Qué NO hacer

- No borres la sección entera sin más: alguna mención externa sí es útil, y el usuario perdería una
  señal que hoy usa. El objetivo es separar lo atribuible de lo que no lo es.
- No uses IA para decidir si un resultado es de la entidad. Es una llamada más, más coste y más
  superficie de fallo para algo que en buena medida se resuelve comparando dominios y nombres.
- No amplíes el alcance a la sección de patentes o al grafo: si ves algo, anótalo.
