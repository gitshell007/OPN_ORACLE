# ORACLE_DEV_SV2_ASK2 · SV2-ASK-2 (PROMPT_000032)

**Fecha:** 2026-08-02  
**Prompt:** `SV2-ASK` / fase `SV2-ASK-2`  
**Hosts:** signal-dev (`v2202607388167489649` / `159.195.216.184`) + oracle-dev (`v2202607388167489673` / `159.195.216.33`)  
**Release oracle-dev:** `20260802T040823Z-native-4b454e1` (`4b454e1c…`)  
**Prohibido:** producción, deploys, instalación de modelos VPS, código de repos.

---

## 1. Fix de configuración signal-dev (consumer 61) — auditado

**Consumer:** `61` / `opn-oracle-memsol-pilot`  
**Fila:** `consumer_ai_settings.id=33`

### Antes (por task)

| Campo | `dossier_question_answer` | `report_custom_brief_plan` |
| --- | --- | --- |
| provider | `ollama` | `ollama` |
| model | `qwen3.5:9b` | `qwen3.5:9b` |
| fallback_provider | `ollama_titan` | `ollama_titan` |
| fallback_model | `qwen3.6:27b` | `qwen3.6:27b` |
| fallback_on_status | `[429]` | `[429]` |

Defaults fila: `default_provider=ollama`, `default_model=qwen3.5:9b`, `fallback_provider=ollama_titan`, `fallback_model=qwen3.6:27b`, `allowed_providers=["ollama","ollama_titan"]`.

Conservados: `json_mode`, `structured_output`, `timeout_seconds=180`, `num_ctx=32768`, `keep_alive=30m`, `temperature=0.1`, `log_prompts/responses`, `openrouter_options`, `require_explicit_task`, `max_output_tokens` (2500 / 2000).

### Después

| Campo | Valor (ambas tasks) |
| --- | --- |
| provider | **`ollama_titan`** |
| model | **`qwen3-coder:30b`** |
| fallback_provider | **`openrouter`** |
| fallback_model | **`qwen/qwen-2.5-7b-instruct`** (~$0.04–0.10 / Mtok in+out; no ejercido) |
| fallback_on_status | **`[404, 429, 500, 502, 503]`** |

Defaults fila alineados: primary Titan coder, fallback OpenRouter instruct, `allowed_providers=["ollama","ollama_titan","openrouter"]`.

**NO** se usó `qwen3.6:27b` como primario. **NO** se instalaron modelos en el VPS.

### Audit

| Campo | Valor |
| --- | --- |
| `admin_audit_logs.id` | **79** |
| action | `consumer_ai_settings.sv2_ask2.provider_model_failover_fix` |
| entity_type / entity_id | `consumer_ai_settings` / `33` |
| created_at (UTC) | `2026-08-02 10:36:10.004712` |
| before_json / after_json | capturados en la fila de audit |

Servicios signal-dev post-cambio: api/worker/beat **active** (sin restart requerido; config leída de BD).

---

## 2. Re-validación oracle-dev (owner real)

**Login:** `owner.sv2.demo@oracle.invalid` (creds host `/root/sv2_demo_owner_credentials.txt`)  
**Dossier:** `ab7bba16-3e55-4f35-ad73-0c84e2850688`  
**Política AI:** `max_classification=internal` (persistente desde 031)  
**Evidencia host:** `/var/backups/opn-oracle-dev/sv2-ask2-20260802/`

### 2.1 Ask

| Campo | Valor |
| --- | --- |
| Pregunta | ¿Quién es el administrador único y qué licitación tiene en curso Nexus Ibérica? |
| conversation_id | `07b9fd8e-f410-4236-8d5c-fa12fd610d73` |
| message_id (user) | `88bb45af-400a-41f6-a2ed-bb6aa46b9318` |
| job_id | `6fecc4a9-c9bb-4476-96b8-891dbe6c097a` |
| job_type | `oracle.dossier_question.answer` |
| HTTP enqueue | **202** |
| Job status | **succeeded** (~4.26 s wall) |
| Signal HTTP | **200 OK** |

#### Respuesta completa (formato producto: `answer_payload` en mensaje user settled)

```text
No hay evidencia autorizada disponible para responder la pregunta sobre quién es el
administrador único y qué licitación tiene en curso Nexus Ibérica Sistemas S.L.
Los evidence_ids permitidos están vacíos, por lo que no se pueden citar fuentes
confiables. Se requiere información adicional o actualización de los datos autorizados.
```

#### Citas (formato real del producto)

```json
[]
```

Campos de producto relevantes:

| Campo | Valor |
| --- | --- |
| `provider_path` | `signal` |
| `task_key` | `dossier_question_answer` |
| `prompt_runtime_id` | `RT-07` |
| `memory_mode` | **`disabled`** |
| `allowed_evidence_ids` | **`[]`** |
| `citations` | **`[]`** |
| `confidence` | `0` |
| `coverage_manifest.requested` | `["memory.disabled"]` |
| `coverage_manifest.excluded` | `[{"source":"memory","reason":"policy"}]` |
| Oracle `ai_audit_logs` | `1e54ee00-…` status=**succeeded**, provider=**ollama_titan**, model=**qwen3-coder:30b**, cost_micros=**0**, latency_ms=**4175**, tokens 3543/219 |

**Contraste documento (no alcanzado en respuesta):** el fixture contiene admin **Laura Méndez Ortega** y licitación **LIC-OATDA-2026-017** (17 chunks `ready`), pero el allowlist de citas llegó vacío → el modelo (correctamente) no inventa.

### 2.2 Informe `custom_brief`

| Campo | Valor |
| --- | --- |
| report_id | `8036bf16-9186-41bc-8466-87a3b1bc9a23` |
| plan job | `4e492a68-9753-4f01-be54-e814dac104be` (`oracle.report.custom_brief.plan`) |
| create | **202** |
| lifecycle_state | quedó en **`brief_draft`** |
| plan_status | **`draft`** (no `proposed` / no `plan_proposed`) |
| job | **failed** `permanent_failure` (~6.3 s wall) |
| plan/accept | **no** (sin plan propuesto) |
| artefacto / JSONB citas | **no** |

Worker: Signal `/ai/run` → **HTTP 422** tras LLM Titan OK. Oracle → `AIUnavailable` / `permanent_failure`.

Signal `ai_usage_logs` **4484**: provider=ollama_titan, model=qwen3-coder:30b, status=**ok**, tokens 901/511, duration_ms=**6172**, fallback_used=false, estimated_cost_usd=null.

Causa del 422: salida del modelo con forma `{"id":"RT-08","plan":{...}}` vs schema RT-08 flat requerido (`version`, `sections`, `facts`, `claims`, `conflicts`, `inferences`, `recommendations`). Validación post-LLM en Signal; **no** es status de provider → **no** dispara `fallback_on_status`.

### 2.3 Usage / coste / latencia (signal-dev c:61)

| id | task_key | provider | model | status | in/out | cost_usd | duration_ms | fallback |
| ---: | --- | --- | --- | --- | ---: | ---: | ---: | --- |
| 4483 | dossier_question_answer | ollama_titan | qwen3-coder:30b | ok | 3543/219 | **0/null** | **4082** | false |
| 4484 | report_custom_brief_plan | ollama_titan | qwen3-coder:30b | ok | 901/511 | **0/null** | **6172** | false |

- OpenRouter c:61: **0** filas  
- Otros providers no ollama/titan/openrouter (2h): **0**  
- **0 llamadas a producción de pago**  
- Latencias interactivas **≪ 90 s** (4.1 s Ask, 6.2 s plan LLM) — **sin** riesgo demo por latencia Titan en este run

### 2.4 Riesgos residuales (nuevas RC / deudas)

1. **Evidence vacía / memory disabled (oracle-dev)**  
   - `MEMORY_CONTEXT_MODE` no configurado en host → default `disabled`  
   - Tabla `evidence` del tenant demo: **0** filas; documento con 17 chunks no materializado como Evidence citable  
   - Ask succeeded sin citas contrastables (Laura Méndez / LIC-OATDA-2026-017)  
   - **Fuera de alcance 032** (no es modelo inexistente / no-failover; no se tocó env host ni código)

2. **RT-08 schema non-compliance (Signal post-LLM 422)**  
   - Primario Titan genera JSON con wrapper `plan` en vez del schema flat  
   - Failover OpenRouter no se activa (provider 200; fallo es validación de task)  
   - Informe no avanza a `plan_proposed`  
   - **Fuera de alcance 032** salvo re-prompt/código o cambio de modelo no autorizado

3. Hallazgo previo producción (no tocar): `SV2-FINDING-AIRUN-FAILOVER` (031).

---

## 3. Estado final

| Superficie | Estado |
| --- | --- |
| signal-dev | Solo config BD c:61 auditada (audit **79**); servicios intactos |
| oracle-dev | Expediente + Ask **succeeded** (sin citas); informe en `brief_draft` (plan failed); sin jobs colgados |
| Producción | no tocada; 0 usage de pago |

### Branch / commit

| Artefacto | Valor |
| --- | --- |
| Branch | `sv2/ask-unblock` |
| Doc | `docs/ops/sv2/ORACLE_DEV_SV2_ASK2.md` |
| Trailer | `Prompt: SV2-ASK` |
| Host evidence | `/var/backups/opn-oracle-dev/sv2-ask2-20260802/` |
| Worktree | `/Users/gitshellmini/PycharmProjects/OPN_ORACLE/.worktrees/sv2-ask-unblock` |

