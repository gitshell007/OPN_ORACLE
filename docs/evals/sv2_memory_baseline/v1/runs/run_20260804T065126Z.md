# SV2 Memory Baseline Run · 2026-08-04T06:51:26.461273+00:00

- eval_set: `sv2-memory-baseline-nexus-demo-v1` v`1.0.0`
- dossier: `ab7bba16-3e55-4f35-ad73-0c84e2850688`
- base_url: `https://oracle-dev.opnconsultoria.com`
- questions: **18** · jobs_ok: **18**

## Métricas

| Métrica | Valor |
|---|---|
| Tasa acierto factual | 8/15 = **0.5333** |
| Abstención correcta (trampas) | 2/3 = **0.6667** |
| Tasa global (fact+trap) | **0.5556** |
| Citas media / respuesta | **2.11** |
| Latencia p50 / p95 (ms) | **24350.9** / **37668.4** |
| Latencia media (ms) | 24746.8 |

## Comparación memoria vs carpeta (grep corpus)

| | Memoria (Preguntar) | Carpeta (grep) |
|---|---|---|
| Aciertos | 3/5 | 5/5 |
| Tasa | 0.6 | 1.0 |
| Latencia media (ms) | 26124.3 | 7.9 |
| Citas media | 2 | n/a (grep no cita) |

- `Q01`: mem=HIT (26621.8 ms, cite=3) · folder=HIT (8.76 ms)
- `Q02`: mem=MISS (30870.1 ms, cite=3) · folder=HIT (9.86 ms)
- `Q06`: mem=HIT (24358.4 ms, cite=1) · folder=HIT (4.32 ms)
- `Q10`: mem=HIT (26471.8 ms, cite=1) · folder=HIT (4.22 ms)
- `Q12`: mem=MISS (22299.5 ms, cite=2) · folder=HIT (12.54 ms)

## Detalle por pregunta

### Q01 · HIT · fact/direct
- job=succeeded mode=augment cite=3 lat_ms=26621.8 reason=`ok`
- answer: El administrador único de Nexus Ibérica Sistemas S.L. es Laura Mendez, según consta en los registros de la empresa. La compañía tiene un capital social de 120.000 EUR y su sede está ubicada en Calle de Alcalá 480, 28027 Madrid.

### Q02 · MISS · fact/direct
- job=succeeded mode=augment cite=3 lat_ms=30870.1 reason=`missing:B-87994512`
- answer: Nexus Ibérica Sistemas S.L. tiene un capital social de 120.000 EUR y su sede está en Calle de Alcalá 480, 28027 Madrid. No se ha proporcionado el CIF en los datos autorizados.

### Q03 · HIT · fact/direct
- job=succeeded mode=augment cite=1 lat_ms=17882.1 reason=`ok`
- answer: El domicilio social de Nexus Ibérica Sistemas S.L. es Calle de Alcalá 480, 28027 Madrid, según consta en los registros comerciales.

### Q04 · HIT · fact/direct
- job=succeeded mode=augment cite=1 lat_ms=17939.6 reason=`ok`
- answer: El capital social de Nexus Ibérica Sistemas S.L. es de 120.000 EUR, según consta en los registros de la empresa.

### Q05 · HIT · fact/direct
- job=succeeded mode=augment cite=1 lat_ms=17820.0 reason=`ok`
- answer: El CNAE principal declarado por Nexus Ibérica Sistemas S.L. es 6201, según consta en los registros autorizados.

### Q06 · HIT · fact/direct
- job=succeeded mode=augment cite=1 lat_ms=24358.4 reason=`ok`
- answer: El identificador de expediente de la licitación de la plataforma de vigilancia de mercados del sector eléctrico en la que participa Nexus es LIC-OATDA-2026-017. Esta licitación se refiere a un servicio relacionado con el sector eléctrico y está registrada bajo este número identificativo externo.

### Q07 · MISS · fact/direct
- job=succeeded mode=augment cite=1 lat_ms=24415.5 reason=`must_any_groups_failed`
- answer: La licitación PLACSP identificada como LIC-OATDA-2026-017 corresponde a la plataforma de vigilancia de mercados y contratación pública del sector eléctrico. No obstante, no se dispone de información sobre el importe base de dicha licitación en los datos autorizados proporcionados.

### Q08 · MISS · fact/direct
- job=succeeded mode=augment cite=1 lat_ms=24306.4 reason=`must_any_groups_failed`
- answer: La licitación de la plataforma de vigilancia de mercados y contratación pública del sector eléctrico tiene el identificador externo 'LIC-OATDA-2026-017'. No obstante, no se dispone de información sobre la fecha límite para presentar ofertas en los datos autorizados.

### Q09 · MISS · fact/direct
- job=succeeded mode=augment cite=3 lat_ms=24383.2 reason=`missing:Carlos`
- answer: Según la información disponible, Nexus Ibérica Sistemas S.L. tiene un capital social de 120.000 EUR y su sede está ubicada en Calle de Alcalá 480, 28027 Madrid. Laura Mendez es identificada como la administradora de la empresa. No se dispone de información sobre el director general o CEO operativo de la compañía.

### Q10 · HIT · fact/direct
- job=succeeded mode=augment cite=1 lat_ms=26471.8 reason=`ok`
- answer: El adjudicatario real en la licitación PLACSP XP1228/2025, que corresponde al suministro de software de acceso remoto seguro ZTNA, es Capgemini España S.L.

### Q11 · MISS · fact/direct
- job=succeeded mode=augment cite=1 lat_ms=20086.2 reason=`missing:72000000`
- answer: El código CPV principal de la licitación de la plataforma de vigilancia de mercados y contratación pública del sector eléctrico es 72230000. Este dato se deriva del título de la licitación identificada como 'Plataforma de vigilancia de mercados y contratación pública del sector eléctrico' (evidence_id: 9a7353ac-41e1-45af-a7ee-003eecc08f27).

### Q12 · MISS · fact/synthesis
- job=succeeded mode=augment cite=2 lat_ms=22299.5 reason=`must_any_groups_failed`
- answer: El administrador único de Nexus Ibérica Sistemas S.L. es Laura Mendez. La licitación pública de la plataforma de vigilancia de mercados del sector eléctrico en la que participa se titula 'Plataforma de vigilancia de mercados y contratación pública del sector eléctrico'. No se dispone de información sobre el importe de dicha licitación en los datos proporcionados.

### Q13 · MISS · fact/synthesis
- job=succeeded mode=augment cite=2 lat_ms=24343.4 reason=`must_any_groups_failed`
- answer: El CIF de Nexus Ibérica Sistemas S.L. no se proporciona explícitamente en los datos autorizados. Sin embargo, se indica que el capital social de la empresa es de 120.000 EUR (evidence_id: aa48a82f-79c5-4b3e-a626-1a0b4b4534c8) y su actividad principal está clasificada con el CNAE 6201 (evidence_id: e38615d3-881c-4584-8349-156a3e269c35).

### Q14 · HIT · fact/synthesis
- job=succeeded mode=augment cite=2 lat_ms=22295.4 reason=`ok`
- answer: Nexus Ibérica Sistemas S.L. tiene un capital social de 120.000 EUR y su domicilio social se encuentra en Calle de Alcalá 480, 28027 Madrid.

### Q15 · HIT · fact/synthesis
- job=succeeded mode=augment cite=6 lat_ms=37339.8 reason=`ok`
- answer: Nexus Ibérica Sistemas S.L. es una empresa con capital social de 120.000 EUR, con sede en Madrid (Calle de Alcalá 480, 28027 Madrid). Un adjudicatario real identificado es Capgemini España S.L., que ha obtenido licitaciones como XP1228/2025 (ZTNA) y CG-2026/2815/0061 (plataforma IA). El administrador único de Nexus Ibérica Sistemas S.L. es Laura Mendez.

### Q16 · HIT · trap/trap
- job=succeeded mode=augment cite=4 lat_ms=30956.2 reason=`abstained`
- answer: No se dispone de información específica sobre el número de empleados de Nexus Ibérica Sistemas S.L. a 31 de diciembre de 2025. Se conocen datos como su capital social (120.000 EUR), sede social en Madrid, CNAE (6201) y la administradora (Laura Mendez). No se han registrado cambios materiales recientes ni decisiones urgentes pendientes relacionadas con el número de empleados.

### Q17 · HIT · trap/trap
- job=succeeded mode=augment cite=5 lat_ms=39530.8 reason=`abstained`
- answer: Nexus Ibérica Sistemas S.L. tiene un capital social de 120.000 EUR, con sede en Madrid (Calle de Alcalá 480, 28027 Madrid). Se enfoca en sectores de software y energía. El expediente SV2 Demo · Nexus Ibérica Sistemas tiene como objetivo vigilar la competencia y oportunidades de esta empresa para demo SV2. No se dispone de información sobre el EBITDA reportado por Nexus Ibérica en el ejercicio 2024

### Q18 · MISS · trap/trap
- job=succeeded mode=augment cite=0 lat_ms=13522.9 reason=`no_abstention`
- answer: No existe evidencia disponible en los registros autorizados que indique la fecha en que se firmó el contrato de joint venture entre Nexus Ibérica Sistemas S.L. y Telefónica Tech para el mercado latinoamericano. La información requerida no está incluida en los datos proporcionados ni en las fuentes consultadas.

> Primera medición honesta: no se ajustaron prompts ni parámetros.
> Coste esperado 0 € (Titan local vía Signal).
