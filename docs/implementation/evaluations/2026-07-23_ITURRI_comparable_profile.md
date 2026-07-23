# Evaluación del perfil comparable · ITURRI, S.A

- Ejecutada: `2026-07-23T16:02:14.801404+00:00`.
- Filas Signal: **1252**; analizadas: **1252**; truncado: **false**.
- Expedientes agregados: **769**; con fecha para el split: **769**.
- Entrenamiento: **615** (`2017-11-27` → `2025-08-26`).
- Holdout: **154** (`2025-08-27` → `2026-07-16`).
- Sin fecha excluidos del split: **0**; filas con fecha inválida: **0**.
- Filas fuente sin fecha: **5**; se conservan en el corpus agregado cuando su expediente tiene otra fila fechada.

## Recall sobre adjudicaciones conocidas del holdout

| Plan | Aciertos | Denominador | Recall |
|---|---:|---:|---:|
| Top-K CPV | 70 | 154 | 45.5 % |
| Top-K términos | 110 | 154 | 71.4 % |
| Combinado | 126 | 154 | 81.8 % |

## Plan aprendido solo del 80 % antiguo

- CPV (K=20): `18100000`, `18143000`, `18141000`, `34144210`, `18110000`, `35812000`, `34144212`, `44482100`, `35113000`, `35113400`, `18800000`, `39518000`, `35100000`, `35111200`, `50110000`, `18000000`, `18220000`, `34144200`, `35110000`, `34144213`
- Términos (K=20): `proteccion`, `personal`, `equipos`, `incendios`, `vehiculos`, `individual`, `vestuario`, `extincion`, `bomberos`, `uniformidad`, `mantenimiento`, `material`, `salvamento`, `contra`, `guantes`, `trabajo`, `forestales`, `prevencion`, `destino`, `intervencion`
- Stopwords/tokenización: `spanish-procurement-stopwords-v1`.

## Licitaciones actuales: comprobación informativa

Estos recuentos son consultas independientes con `scope=all`; se solapan, no se suman y no forman parte del recall histórico.

| Tipo | Consulta | Total actual |
|---|---|---:|
| cpv | `18100000` | 18 |
| cpv | `18143000` | 1 |
| cpv | `18141000` | 1 |
| cpv | `34144210` | 0 |
| cpv | `18110000` | 2 |
| term | `proteccion` | 6 |
| term | `personal` | 65 |
| term | `equipos` | 65 |
| term | `incendios` | 28 |
| term | `vehiculos` | 1 |

## Resultado reproducible

```json
{
  "company": "ITURRI, S.A",
  "current_tender_smoke": {
    "measured_at": "2026-07-23T16:02:14.801081+00:00",
    "probes": [
      {
        "kind": "cpv",
        "total": 18,
        "value": "18100000"
      },
      {
        "kind": "cpv",
        "total": 1,
        "value": "18143000"
      },
      {
        "kind": "cpv",
        "total": 1,
        "value": "18141000"
      },
      {
        "kind": "cpv",
        "total": 0,
        "value": "34144210"
      },
      {
        "kind": "cpv",
        "total": 2,
        "value": "18110000"
      },
      {
        "kind": "term",
        "total": 6,
        "value": "proteccion"
      },
      {
        "kind": "term",
        "total": 65,
        "value": "personal"
      },
      {
        "kind": "term",
        "total": 65,
        "value": "equipos"
      },
      {
        "kind": "term",
        "total": 28,
        "value": "incendios"
      },
      {
        "kind": "term",
        "total": 1,
        "value": "vehiculos"
      }
    ],
    "provider_contract": "active=false omite el predicado de actividad en Signal v1",
    "purpose": "informational-current-scope-all-not-recall",
    "warning": "Los recuentos se solapan y no se suman. Describen el índice actual de licitaciones, no la recuperación del holdout histórico de adjudicaciones."
  },
  "evaluation": {
    "company_normalized_by_signal": "ITURRI",
    "company_requested": "ITURRI, S.A",
    "corpus": {
      "aggregated_contracts": 769,
      "analyzed_rows": 1252,
      "dated_contracts": 769,
      "ignored_rows_without_folder_id": 0,
      "provider_total_rows": 1252,
      "rows_with_invalid_date": 0,
      "rows_without_date": 5,
      "truncated": false,
      "undated_contracts_excluded_from_split": 0
    },
    "holdout_observability": {
      "contracts_with_cpv": 154,
      "contracts_with_title_terms": 154
    },
    "plan": {
      "cpv_top_k": 20,
      "cpvs": [
        "18100000",
        "18143000",
        "18141000",
        "34144210",
        "18110000",
        "35812000",
        "34144212",
        "44482100",
        "35113000",
        "35113400",
        "18800000",
        "39518000",
        "35100000",
        "35111200",
        "50110000",
        "18000000",
        "18220000",
        "34144200",
        "35110000",
        "34144213"
      ],
      "term_top_k": 20,
      "terms": [
        "proteccion",
        "personal",
        "equipos",
        "incendios",
        "vehiculos",
        "individual",
        "vestuario",
        "extincion",
        "bomberos",
        "uniformidad",
        "mantenimiento",
        "material",
        "salvamento",
        "contra",
        "guantes",
        "trabajo",
        "forestales",
        "prevencion",
        "destino",
        "intervencion"
      ],
      "title_term_method_version": "spanish-procurement-stopwords-v1"
    },
    "recall": {
      "combined": {
        "denominator_holdout_contracts": 154,
        "hits": 126,
        "recall_percent": "81.8"
      },
      "cpv": {
        "denominator_holdout_contracts": 154,
        "hits": 70,
        "recall_percent": "45.5"
      },
      "terms": {
        "denominator_holdout_contracts": 154,
        "hits": 110,
        "recall_percent": "71.4"
      }
    },
    "schema": "procurement-comparable-evaluation-v1",
    "temporal_split": {
      "holdout_contracts": 154,
      "holdout_end": "2026-07-16",
      "holdout_start": "2025-08-27",
      "method": "80% más antiguo para entrenamiento; 20% más reciente para holdout",
      "training_contracts": 615,
      "training_end": "2025-08-26",
      "training_start": "2017-11-27"
    }
  },
  "generated_at": "2026-07-23T16:02:14.801404+00:00",
  "parameters": {
    "cpv_top_k": 20,
    "max_rows": 2000,
    "page_size": 100,
    "term_top_k": 20
  },
  "schema": "procurement-comparable-evaluation-report-v1"
}
```
