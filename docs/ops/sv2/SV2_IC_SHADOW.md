# SV2-IC · Oracle→signal-dev memory connection (shadow) + RT-08 model fix

- **Prompt:** `SV2-IC` / `PROMPT_000033`
- **Executor:** Grok Build
- **When (Europe/Madrid):** 2026-08-02 ~12:53–13:10
- **Hosts:** oracle-dev `159.195.216.33` · signal-dev `159.195.216.184`
- **Production:** not touched

## Objective

1. Issue CTC (consumer **64**) for demo tenant; wire Oracle Integration Connection + `MEMORY_CONTEXT_MODE=http` (shadow only).
2. Validate DMP shadow retrieve against signal-dev (items may be 0 until 034).
3. Fix RT-08 primary model to OpenRouter instruct; re-run custom brief plan.
4. Do **not** activate augment.

## Identifiers

| Item | Value |
| --- | --- |
| Oracle tenant | `sv2-demo` / `a6edb3c8-0611-4d7a-a6e1-e882c7460539` |
| dossier | `ab7bba16-3e55-4f35-ad73-0c84e2850688` |
| Signal consumer | **64** `opn-oracle-dev` (memory CTC) · **61** (AI tasks) |
| CTC id | **3** |
| CTC fingerprint | `I_3JPOzBK3K2` (prefix; raw never in git/answer) |
| CTC fp_sha16 | `407bee28d2e1c4bd` |
| `tenant_key` | `c:64\|t:a6edb3c8-0611-4d7a-a6e1-e882c7460539` |
| external_tenant_id | `a6edb3c8-0611-4d7a-a6e1-e882c7460539` (Oracle tenant UUID; same pattern as canary `c:64\|t:…`) |
| IC id | `c1986b88-bdee-4aee-983f-c51027fed0ff` |
| IC name / status | `signal-dev-sv2-demo` / **active** · http · `https://signal-dev.opnconsultoria.com` |
| DMP id | `8aa77899-4002-4a0d-baa8-015cff2180eb` · mode **shadow** · connection linked · last_test **ok** |
| Snapshot id | `e37ce334-639a-4897-aac1-48eef599a869` · watermark **`wm_6c017a7e28f4ae38`** |
| Ask conv / msg / job | `c963407b-…` / `8dab2574-…` / **`68ed06ae-…` succeeded** |
| Report (best) | `f9c530f0-…` plan job `dccc443e-…` **failed** (schema 422) |

## 1. CTC on signal-dev (c:64)

- Policy A insert into `consumer_tenant_credentials` (scopes `memory:read|write|stats|health`).
- Grant dossier `ab7bba16-…` for product `oracle`.
- CMS c:64: `enabled=true`, `kill_switch=false`, `allowed_external_tenant_ids=[]` (empty = all tenants).
- Verify:
  - `GET /api/v1/memory/v1/health` → **200** (`engine_enabled=true`)
  - `GET /api/v1/memory/v1/effective-config` with CTC + `X-OPN-External-Tenant-ID` → **200**
- Raw: sealed into Oracle keyring AES-GCM; temporary host files shredded (`/root/sv2_ic_ctc.raw`, signal backup raw).

## 2. IC + env on oracle-dev

### Env (only oracle-dev)

```text
MEMORY_CONTEXT_MODE=http
MEMORY_CONTEXT_BASE_URL=https://signal-dev.opnconsultoria.com
MEMORY_CONTEXT_TIMEOUT_SECONDS=15
```

Services restarted: api/web/worker/beat + nginx **active**.

### Integration connection

- Created via app `create_app` + `store_credential` (keyring) under RLS `app.tenant_id`.
- Metadata: `external_tenant_id` = tenant UUID, `mode=shadow`, `allowlist_host=signal-dev.opnconsultoria.com`, `ctc_id=3`.
- Credential fingerprint (Oracle side): `275c14e4f713a127e58dfe1d8d687786` v1.

### Host operational patches (no repo product change)

Required for real HTTP to signal-dev on release `native-4b454e1`:

1. `memory_http_client.DEFAULT_ALLOWED_HOSTS` += `signal-dev.opnconsultoria.com` (SSRF allowlist; prod host was sole default).
2. `HttpMemoryContextAdapter._resolve_client`: if scope lacks `external_tenant_id`, fall back to IC metadata / `connection.tenant_id` (Ask path only passed `tenant_id`).

Backups on host: `*.py.bak-sv2-ic`. Env backup: `oracle.env.bak-sv2-ic-*`.

## 3. Shadow validation

| Check | Result |
| --- | --- |
| test-connection | **ok**, synthetic=false, engine_enabled=true |
| direct retrieve | HTTP **200**, items=**0**, watermark=`wm_6c017a7e28f4ae38`, coverage present (`legitimate_empty_no_matching_memory`) |
| adapter retrieve | `HttpMemoryContextAdapter` · `effective_mode=shadow` · `items_for_prompt=[]` |
| snapshot | id `e37ce334-…` persisted with coverage + watermark |
| Ask re-run | job **succeeded** ~3–4 s · `memory_mode=**shadow**` · coverage_manifest consulted Signal stores · citations `[]` (expected pre-034) |

`capability.effective_mode` on GET effective remains `disabled` because `capability_payload` hardcodes `tenant_mode="disabled"`; **host_mode=`http`** and Ask **`memory_mode=shadow`** are the authoritative runtime signals.

## 4. RT-08 model fix (signal-dev c:61)

### Before → after (`report_custom_brief_plan` only)

| Field | Before (032) | After (033 primary) |
| --- | --- | --- |
| provider | `ollama_titan` | **`openrouter`** |
| model | `qwen3-coder:30b` | **`qwen/qwen-2.5-72b-instruct`** |
| fallback_provider | `openrouter` | **`ollama_titan`** |
| fallback_model | `qwen/qwen-2.5-7b-instruct` | **`qwen3-coder:30b`** |
| fallback_on_status | `[404,429,500,502,503]` | unchanged |

- Price ref OpenRouter Qwen 2.5 72B: **~$0.36 / Mtok in**, **~$0.40 / Mtok out**.
- Audits: **81** (initial), **82** (llama retry), **83** (restore qwen72 as residual primary).
- Intermediate retry model `meta-llama/llama-3.3-70b-instruct` (audit 82) — same schema class failure; primary left on Qwen 72B.

### Plan re-runs

| usage id | model | status LLM | in/out | cost_usd | result to Oracle |
| ---: | --- | --- | ---: | ---: | --- |
| 4486 | qwen/qwen-2.5-72b-instruct | ok | 1807/690 | **0.00092652** | HTTP **422** schema (missing required empty arrays facts/claims/…) |
| 4487 | qwen/qwen-2.5-72b-instruct | ok | 1828/649 | **0.00091768** | 422 same class |
| 4488 | meta-llama/llama-3.3-70b-instruct | ok | 1692/659 | **0.00048356** | 422 same class |

Progress vs 032: outputs are **flat JSON** (no `{"id":"RT-08","plan":…}` wrapper). Residual: required schema fields `facts|claims|conflicts|inferences|recommendations` often omitted when empty → post-LLM **422**, no status failover (SV2-FINDING-RT08-VALIDATION-NO-FAILOVER).

### Cost

| Scope | USD | EUR approx |
| --- | ---: | ---: |
| This turn OpenRouter c:61 | **≈ 0.00233** | ≪ €0.01 |
| Campaign OpenRouter (≤10 €) | ≈ 0.00233 + prior ~0 | **well under 10 €** |

## 5. Final health

| Surface | State |
| --- | --- |
| oracle-dev services | active |
| signal-dev services | active |
| augment | **OFF** |
| hung jobs this turn | **none** (pre-existing July queued/running left untouched) |
| production | intact |

## 6. Host evidence

- Oracle: `/var/backups/opn-oracle-dev/sv2-ic-20260802/`
- Signal: `/var/backups/opn_signal_dev/sv2-ic-20260802/`

## 7. Residual / next

1. **034** document→memory under dossier (fill Signal memory so retrieve items > 0).
2. **035** augment canary + citations.
3. RT-08 schema compliance residual (required empty arrays / schema repair) — product/runtime, not env.
4. Optional: promote host allowlist + external_tenant fallback into release packaging.

Prompt: SV2-IC
