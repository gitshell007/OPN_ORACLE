# SV2-RT08 · Informe operativo (v1.0.2 + runtime=commit)

Fecha: 2026-08-02 · Prompt: SV2-RT08 · ANSWER_000035

## Resumen

Fix raíz del plan de informe: el JSON Schema RT-08 exigía como `required` arrays
semánticamente vacíos (`facts|claims|conflicts|inferences|recommendations`). En v1.0.2
pasan a **opcionales con default `[]`**. El parser Oracle
`normalize_brief_plan_output` rellena claves ausentes antes de persistir/aceptar.

Gate anti-intermitencia: **3/3** planes consecutivos `job=succeeded` +
`lifecycle_state=plan_proposed`.

## SHAs y releases

| Entorno | Branch | SHA tip | Release / runtime |
| --- | --- | --- | --- |
| Oracle | `sv2/bridge-dev` | `d9cf723fe68417e4ac8d5357d348769f6cae6bbc` | `20260802T114531Z-native-d9cf723` (current, limpia) |
| Signal | `sv2/dev-integration` | `28187492e38a9ac05034b8a72f407e14562b9aad` | `/opt/apps/opn_signal_dev` detached HEAD = tip, `git status` limpio |

PREVIOUS_RELEASE oracle: `20260802T111719Z-native-19903c1`.

Hotpatches post-034 (`tasks.py` / `memory_outbox.py`) quedan **dentro** del tip
(`a31240a`/`4ba68b5`/`6dd9726` + RT-08). Runtime ya no depende de ficheros sucios en host.

## Contrato RT-08 v1.0.2

| Campo | Valor |
| --- | --- |
| `prompt_version` | `1.0.2` |
| `schema_version` | `custom_brief_plan.v1` (mismo nombre; shape más laxo) |
| `prompt_sha256` | `3768e8828e623cf69608ed799f900f389b4e3e9d57b85fbcc189bb67bf4c92fe` |
| `schema_sha256` | `949a1b57b628246594ffc169d77a7cb676a11d90fa43a5910ab455920e7028f7` |
| required | `version`, `sections` |
| optional + default `[]` | `facts`, `claims`, `conflicts`, `inferences`, `recommendations` |

### Diff schema (Signal)

```diff
- "required": ["version", "sections", "facts", "claims", "conflicts", "inferences", "recommendations"],
+ "required": ["version", "sections"],
- "facts": {"type": "array"},
+ "facts": {"type": "array", "default": []},
  (igual claims/conflicts/inferences/recommendations)
```

### Parser Oracle

`opn_oracle.oracle.custom_reports.normalize_brief_plan_output` — usado en:

- `_plan_via_signal` / `process_custom_brief_plan`
- `accept_plan` / `edit_plan` (lifecycle)

## Tests

```text
uv run pytest tests/test_memory_sv2_bridge_outbox.py -q --no-cov
...........  11 passed
```

- Output sin arrays → normalize → `[]` en las 5 claves.
- Output con arrays → intacto.
- Mutación: sin normalize, required-check RED; con normalize GREEN.
- En host Signal: Draft202012Validator minimal sin arrays → 0 errores; mutación required antigua → RED.

## E2E planes (3 consecutivos)

Evidencia: `/var/backups/opn-oracle-dev/sv2-rt08-e2e-20260802T114904Z/`

| # | report_id | job_id | job | lifecycle | sections |
| ---: | --- | --- | --- | --- | ---: |
| 1 | `2e57a475-…` | `688ecfa5-…` | succeeded | plan_proposed | 7 |
| 2 | `d32f94e8-…` | `f8cbea34-…` | succeeded | plan_proposed | 5 |
| 3 | `aa23a336-…` | `bfab0151-…` | succeeded | plan_proposed | 7 |

Arrays normalizados en los 3: `facts|claims|conflicts|inferences|recommendations = []`.

### Usage RT-08 turn (Signal `ai_usage_logs`)

| id | model | in | out | cost USD | ms |
| ---: | --- | ---: | ---: | ---: | ---: |
| 4505 | qwen-2.5-72b-instruct | 1961 | 501 | 0.00090636 | 33863 |
| 4506 | qwen-2.5-72b-instruct | 1960 | 373 | 0.00085480 | 29641 |
| 4507 | qwen-2.5-72b-instruct | 1963 | 434 | 0.00088028 | 26666 |
| **suma 3 planes** | | | | **≈ 0.00264** | |

OpenRouter campaña día (id≥4486, date≥2026-08-02): **≈ $0.0124** (≪ 10 €).

## Lifecycle post-accept

| Paso | Resultado |
| --- | --- |
| accept plan report `2e57a475…` | HTTP 200 |
| lifecycle | **`accepted_degraded`** |
| error_code | `memory_not_durable` |
| motivo | `memory_mode != durable; generación productiva bloqueada (DUR-MDEV05-001)` |
| write/draft/ready | **no** (producto bloquea writer sin memoria durable) |
| download | HTTP 409 |
| citas en artefacto | N/A (sin writer) |
| `allowed_evidence_ids` | allowlist de snapshot degradada/vacía esperable en shadow → 036 con augment |

Esto **no** es fallo schema/modelo; es gate de producto sobre memoria durable.
En shadow (augment OFF) el plan se acepta y congela, pero no arranca RT-09/10.

## Estado final

- oracle-dev / signal-dev: services **active**
- runtimes = commits (sin hotpatches sucios)
- augment OFF
- jobs colgados 2h: **0**
- producción: no tocada
- Backups: `/var/backups/opn-oracle-dev/sv2-rt08-*`, `/var/backups/opn_signal_dev/sv2-rt08-*`

## Deuda residual → 036/037

1. Write/review/artefacto requieren memoria **durable** (o excepción auditada) — típico de
   augment canario (SV2-AUG).
2. Citas duales evidence/memoria dependen de allowlist + augment.
3. Bilateral ingest sigue soft (flags OFF en Signal).
