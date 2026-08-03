# Agregados de expediente (salud / oportunidad / riesgo)

## Problema (SV2-METRICAS)

Las columnas `health_score`, `opportunity_score` y `risk_score` del
`StrategicDossier` se inicializaban en **0** y solo se actualizaban al crear o
editar oportunidades/riesgos. Al crear un expediente vacío **nunca** se llamaba
a `_refresh_dossier_aggregates`, así que la portada mostraba **0 / 0 / 0**.

En una escala 0–100, un **0 de salud se lee como el peor caso**, cuando lo
correcto para un expediente sin ítems es el **neutro 50**.

Prueba de que el recálculo no había corrido: `score_explanation == {}`. Tras un
recálculo válido incluye `algorithm_version: oracle-scoring-v1`.

## Fórmula (`aggregate_dossier_scores`, `oracle-scoring-v1`)

Sea \(O_i\) el `overall_score` de cada oportunidad del expediente y \(R_j\) el
de cada riesgo:

\[
\begin{aligned}
\text{opportunity} &= \operatorname{mean}(O_i)\ \text{o}\ 0\ \text{si no hay oportunidades}\\
\text{risk} &= \operatorname{mean}(R_j)\ \text{o}\ 0\ \text{si no hay riesgos}\\
\text{health} &= \operatorname{clamp}\bigl(50 + 0{,}5\cdot\text{opportunity} - 0{,}5\cdot\text{risk},\ 0,\ 100\bigr)
\end{aligned}
\]

| Situación | Oportunidad | Riesgo | Salud |
|-----------|-------------|--------|-------|
| Sin oportunidades ni riesgos | 0 | 0 | **50** (neutro) |
| Solo oportunidad media 100 | 100 | 0 | 100 |
| Solo riesgo medio 100 | 0 | 100 | 0 |
| Opp 60, riesgo 20 | 60 | 20 | 70 |

## Cuándo se calcula

1. **Al crear el expediente** (`create_dossier` → `_refresh_dossier_aggregates`).
2. Al crear/actualizar oportunidades o riesgos, o al promover señales.
3. **Self-heal** en listado y detalle si `score_explanation.algorithm_version`
   no es `oracle-scoring-v1` (expedientes previos al fix).

## No incluye (deliberado)

Cobertura de evidencia, hechos confirmados u otras señales no entran en este
agregado v1. La fórmula se limita a medias de scores de oportunidades y riesgos
ya puntuados, para poder explicarla en demo sin inventar pesos nuevos.
