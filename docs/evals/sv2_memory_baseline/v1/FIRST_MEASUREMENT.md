# Primera medición · 2026-08-04 · SV2-BASELINE-MEMORIA

Run: `v1/runs/run_20260804T065126Z.json` (= `LATEST.json`)

## Números crudos (automáticos, sin retocar)

| Métrica | Valor |
|---|---|
| Jobs OK | 18/18 |
| Acierto factual | **8/15 = 53,33 %** |
| Abstención trampa (scorer) | **2/3 = 66,67 %** |
| Global | **10/18 = 55,56 %** |
| Citas media | **2,11** (rango 0–6) |
| Latencia p50 / p95 | **24,4 s / 37,7 s** |
| Carpeta (grep) en 5 Q | **5/5 aciertos · ~8 ms** |
| Memoria en esas 5 Q | **3/5 aciertos · ~26 s · 2 citas media** |
| Coste | **0,00 €** |

## Lectura honesta

1. **Algo recupera, pero a medias.** 53 % factual no es vendible como «memoria que responde al expediente». El arnés binario (4 marcadores) ocultaba esto.
2. **Huecos de retrieval, no de extracción total.** CIF `B-87994512`, importe `2.400.000`, deadline `15-abr-2026` y CEO están **en el corpus/chunks**; el camino Preguntar dijo «no se dispone» o devolvió otro dato. El CIF ni siquiera está materializado como `memory_fact` (solo en texto).
3. **Error factual real (Q11):** respondió CPV `72230000` en vez de `72000000` (contaminación con otra licitación del corpus PLACSP). Peor que abstenerse.
4. **Trampas:** Q16/Q17 se abstuvieron bien. Q18 (scorer MISS) en lectura humana **sí se abstuvo** («No existe evidencia…»); el scorer v1 no tenía ese marcador — gap de evaluación, no alucinación. Tras ampliar marcadores, futuras corridas lo capturan; **la primera medición se deja con el número automático 2/3**.
5. **¿Mejor que buscar en la carpeta?** En tokens exactos, **no**: grep 5/5 vs memoria 3/5 y ~3000× más lento. Lo que aporta la memoria es **síntesis en lenguaje natural + citas + abstención** (cuando funciona). Hoy no gana al grep en recall de hechos sueltos; gana en presentación y en no inventar (parcialmente).

## No se maquilló

Cero cambios de prompts/parámetros de Preguntar. Se mide lo desplegado en oracle-dev (release `c64c5b2`).
