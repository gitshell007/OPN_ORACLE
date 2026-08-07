# Primera medición · 2026-08-04 · SV2-BASELINE-MEMORIA

Esta nota documenta la **primera** corrida del baseline (histórica). **No** es
la corrida vigente.

| Qué | Dónde |
|-----|--------|
| Primera medición (53 % factual) | `v1/runs/run_20260804T065126Z.json` |
| Corrida 15/15 + 3/3 (2026-08-04 tarde) | `v1/runs/run_20260804T134431Z.json` |
| Corrida vigente | el `run_*.json` con **mayor marca de tiempo** en `v1/runs/` |

## Política LATEST (desde MEDIR-SHA)

`LATEST.json` / `LATEST.md` **ya no se versionan** como ficheros de contenido.
El corredor crea **enlaces simbólicos locales** (gitignored) al último `run_*`.
Un commit de otro tema no puede volver a pisar una cifra: la verdad inmutable
es siempre `run_<timestamp>.json`.

## Números crudos de la primera corrida (automáticos, sin retocar)

| Métrica | Valor |
|---|---|
| Jobs OK | 18/18 |
| Acierto factual | **8/15 = 53,33 %** |
| Abstención trampa (scorer de entonces) | **2/3 = 66,67 %** |
| Global | **10/18 = 55,56 %** |
| Citas media | **2,11** (rango 0–6) |
| Latencia p50 / p95 | **24,4 s / 37,7 s** |
| Carpeta (grep) en 5 Q | **5/5 aciertos · ~8 ms** |
| Memoria en esas 5 Q | **3/5 aciertos · ~26 s · 2 citas media** |
| Coste | **0,00 €** |

## Lectura honesta (de aquella primera pasada)

1. **Algo recupera, pero a medias.** 53 % factual no es vendible como «memoria que responde al expediente». El arnés binario (4 marcadores) ocultaba esto.
2. **Huecos de retrieval, no de extracción total.** CIF `B-87994512`, importe `2.400.000`, deadline `15-abr-2026` y CEO están **en el corpus/chunks**; el camino Preguntar dijo «no se dispone» o devolvió otro dato. El CIF ni siquiera está materializado como `memory_fact` (solo en texto).
3. **Error factual real (Q11):** respondió CPV `72230000` en vez de `72000000` (contaminación con otra licitación del corpus PLACSP). Peor que abstenerse.
4. **Trampas:** Q16/Q17 se abstuvieron bien en lectura humana. Q18 (scorer MISS) decía «No existe evidencia…»; el scorer v1 no tenía ese marcador — gap de evaluación, no alucinación. La primera medición se deja con el número automático **2/3**.
5. **¿Mejor que buscar en la carpeta?** En tokens exactos, **no**: grep 5/5 vs memoria 3/5 y ~3000× más lento. Lo que aporta la memoria es **síntesis + citas + abstención**.

## No se maquilló (primera pasada)

Cero cambios de prompts/parámetros de Preguntar. Se midió lo desplegado en
oracle-dev de entonces (release corto `c64c5b2`). **Esa corrida no registró
`release_sha` / `release_id` en el JSON** — deuda cerrada en el tramo MEDIR-SHA:
toda corrida nueva falla de forma visible si `/api/v1/meta` no da release.
