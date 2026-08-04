# SV2 Memory Baseline Run · 2026-08-04T13:44:31.599607+00:00

- eval_set: `sv2-memory-baseline-nexus-demo-v1` v`1.0.0`
- dossier: `ab7bba16-3e55-4f35-ad73-0c84e2850688`
- base_url: `https://oracle-dev.opnconsultoria.com`
- questions: **18** · jobs_ok: **18**

## Métricas

| Métrica | Valor |
|---|---|
| Tasa acierto factual | 15/15 = **1.0** |
| Abstención correcta (trampas) | 3/3 = **1.0** |
| Tasa global (fact+trap) | **1.0** |
| Citas media / respuesta | **3.06** |
| Latencia p50 / p95 (ms) | **25556.2** / **51578.4** |
| Latencia media (ms) | 31671.9 |

## Comparación memoria vs carpeta (grep corpus)

| | Memoria (Preguntar) | Carpeta (grep) |
|---|---|---|
| Aciertos | 5/5 | 5/5 |
| Tasa | 1.0 | 1.0 |
| Latencia media (ms) | 46198.4 | 7.1 |
| Citas media | 4 | n/a (grep no cita) |

- `Q01`: mem=HIT (28713.7 ms, cite=3) · folder=HIT (7.99 ms)
- `Q02`: mem=HIT (107136.7 ms, cite=3) · folder=HIT (7.96 ms)
- `Q06`: mem=HIT (28881.1 ms, cite=3) · folder=HIT (4.22 ms)
- `Q10`: mem=HIT (24486.6 ms, cite=1) · folder=HIT (3.41 ms)
- `Q12`: mem=HIT (41774.0 ms, cite=10) · folder=HIT (12.02 ms)

## Detalle por pregunta

### Q01 · HIT · fact/direct
- job=succeeded mode=augment cite=3 lat_ms=28713.7 reason=`ok`
- answer: El administrador único de Nexus Ibérica Sistemas S.L. es Laura Méndez Ortega, según consta en los registros. La empresa tiene un capital social de 120.000 EUR y su sede está ubicada en Calle de Alcalá 480, 28027 Madrid (España).

### Q02 · HIT · fact/direct
- job=succeeded mode=augment cite=3 lat_ms=107136.7 reason=`ok`
- answer: El CIF de Nexus Ibérica Sistemas S.L. es B87994512. La empresa tiene un capital social de 120.000 EUR y su denominación social es Nexus Ibérica Sistemas S.L.

### Q03 · HIT · fact/direct
- job=succeeded mode=augment cite=2 lat_ms=24413.9 reason=`ok`
- answer: El domicilio social de Nexus Ibérica Sistemas S.L. es Calle de Alcalá 480, 28027 Madrid (España). El capital social de la empresa asciende a 120.000 EUR.

### Q04 · HIT · fact/direct
- job=succeeded mode=augment cite=1 lat_ms=20008.5 reason=`ok`
- answer: El capital social de Nexus Ibérica Sistemas S.L. es de 120.000 EUR, según consta en la evidencia autorizada identificada como aa48a82f-79c5-4b3e-a626-1a0b4b4534c8.

### Q05 · HIT · fact/direct
- job=succeeded mode=augment cite=1 lat_ms=20160.7 reason=`ok`
- answer: Nexus Ibérica Sistemas S.L. declara el CNAE 6201, que corresponde al sector de actividades de consultoría en informática y desarrollo de software.

### Q06 · HIT · fact/direct
- job=succeeded mode=augment cite=3 lat_ms=28881.1 reason=`ok`
- answer: El expediente de la licitación de la plataforma de vigilancia de mercados del sector eléctrico en la que participa Nexus tiene el identificador LIC-OATDA-2026-017. El importe publicado de esta licitación es de 2.400.000 EUR, y la fecha límite para la presentación de ofertas es el 15 de abril de 2026.

### Q07 · HIT · fact/direct
- job=succeeded mode=augment cite=1 lat_ms=22343.2 reason=`ok`
- answer: El presupuesto base de licitación de la plataforma de vigilancia de mercados y contratación pública del sector eléctrico (LIC-OATDA-2026-017) es de 2.400.000 EUR, según consta en el evidence_id 5c61f1da-0d4f-481f-ac75-61590f2d6dc3.

### Q08 · HIT · fact/direct
- job=succeeded mode=augment cite=2 lat_ms=26625.7 reason=`ok`
- answer: Hasta el 15 de abril de 2026 se pueden presentar ofertas a la licitación de la plataforma de vigilancia de mercados del sector eléctrico. El importe publicado de dicha licitación es de 2.400.000 EUR.

### Q09 · HIT · fact/direct
- job=succeeded mode=augment cite=4 lat_ms=28674.1 reason=`ok`
- answer: El director general o CEO operativo de Nexus Ibérica Sistemas S.L. es Carlos Ruiz Navarro, y el CFO es Ana Belén Soto García. La empresa está constituida con un capital social de 120.000 EUR, con sede en Madrid.

### Q10 · HIT · fact/direct
- job=succeeded mode=augment cite=1 lat_ms=24486.6 reason=`ok`
- answer: El adjudicatario real de la licitación PLACSP XP1228/2025, relacionada con software de acceso remoto seguro ZTNA, es Capgemini España, S.L., según consta en el registro de adjudicaciones del expediente.

### Q11 · HIT · fact/direct
- job=succeeded mode=augment cite=8 lat_ms=22187.9 reason=`ok`
- answer: El código CPV principal de la licitación de la plataforma de vigilancia de mercados del sector eléctrico es 72000000. Este dato se deriva del expediente denominado "Plataforma de vigilancia de mercados y contratación pública del sector eléctrico" identificado como LIC-OATDA-2026-017, cuyo código CPV ha sido extraído de la fuente autorizada.  Para el expediente LIC-OATDA-2026-017, la evidencia auto

### Q12 · HIT · fact/synthesis
- job=succeeded mode=augment cite=10 lat_ms=41774.0 reason=`ok`
- answer: El administrador único de Nexus Ibérica Sistemas S.L. es Laura Méndez Ortega. La licitación pública de la plataforma de vigilancia de mercados del sector eléctrico en la que participa tiene un importe de 2.400.000 EUR.

### Q13 · HIT · fact/synthesis
- job=succeeded mode=augment cite=2 lat_ms=24382.3 reason=`ok`
- answer: El CIF de Nexus Ibérica Sistemas S.L. es B87994512. Su CNAE de actividad principal es 6201, correspondiente a la prestación de servicios de consultoría en informática y actividades relacionadas.

### Q14 · HIT · fact/synthesis
- job=succeeded mode=augment cite=2 lat_ms=24459.0 reason=`ok`
- answer: Nexus Ibérica Sistemas S.L. tiene un capital social de 120.000 euros y su domicilio social se encuentra en Calle de Alcalá 480, 28027 Madrid (España).

### Q15 · HIT · fact/synthesis
- job=succeeded mode=augment cite=6 lat_ms=37413.2 reason=`ok`
- answer: Nexus Ibérica Sistemas S.L. es una empresa constituida con capital social de 120.000 EUR, con sede en Madrid. El adjudicatario real en la licitación PLACSP XP1228/2025 (ZTNA) es Capgemini España, S.L., y en la licitación PLACSP CG-2026/2815/0061 (multiagente IA) también es Capgemini España S.L. Laura Méndez Ortega es la administradora única de Nexus Ibérica Sistemas S.L.

### Q16 · HIT · trap/trap
- job=succeeded mode=augment cite=3 lat_ms=35337.0 reason=`abstained`
- answer: Nexus Ibérica Sistemas S.L. tiene un capital social de 120.000 EUR, está constituida con sede en Madrid (calle de Alcalá 480, 28027 Madrid) y su CIF es B-87994512. No se dispone de información sobre el número de empleados a 31 de diciembre de 2025.

### Q17 · HIT · trap/trap
- job=succeeded mode=augment cite=3 lat_ms=32973.8 reason=`abstained`
- answer: No se dispone de información específica sobre el EBITDA reportado por Nexus Ibérica Sistemas S.L. en el ejercicio 2024. Los datos disponibles incluyen su capital social (120.000 EUR), dirección registrada en Madrid y su CIF (B-87994512). No se han encontrado referencias a sus estados financieros o indicadores de rentabilidad para ese periodo.

### Q18 · HIT · trap/trap
- job=succeeded mode=augment cite=0 lat_ms=20123.2 reason=`abstained`
- answer: No existe evidencia autorizada que indique la fecha en que se firmó el contrato de joint venture entre Nexus Ibérica Sistemas S.L. y Telefónica Tech para el mercado latinoamericano. La información disponible no incluye este dato específico.

> Primera medición honesta: no se ajustaron prompts ni parámetros.
> Coste esperado 0 € (Titan local vía Signal).
