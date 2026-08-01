# MDEV-00 · Baseline bilateral Oracle Dev ↔ Signal Dev (rework)

**Rework Codex:** 2026-08-01 Europe/Madrid
**Pack:** `memoria_dev_v2` `2026-08-01.4` · content_set `687505b4…ada164`
**Evidencia:** `docs/implementation/evidence/mdev-00/`
**Producción:** OUT_OF_SCOPE

## Pack integrity

| Paso | Resultado | Evidencia |
|---|---|---|
| Canónico 27/27 + content_set | MATCH | `03_pack_integrity_mutation.txt` |
| Copia temporal: alterar `README.md` | MATCH False → **BLOCKED_PACK_INTEGRITY** | idem |
| Descartar solo copia; revalidar canónico | MATCH 27/27 | idem |

## Git census

| Hecho | Valor | Evidencia |
|---|---|---|
| Oracle master | `402fc29` | `01_git_census.txt` |
| Oracle oracle-dev | `81475d0` | idem |
| Oracle only-dev count | **8** (incl. merge `d3804ba`) | idem |
| Signal main | `8973a09` | idem |
| Signal signal-dev | `db9fd37` | idem |
| Signal only-dev count | **9** | idem |
| PRs históricos | Oracle #1–#5 merged; Signal #1–#5 merged | `02_pr_ci_historical.txt` |
| CI MDEV-00 | solo el del PR de esta rama (se anota al integrar) | no confundir con CI histórico |

### `d3804ba`

Merge commit `6a2b103` + `e896f50` → integra master MEMSOL en canal oracle-dev para smoke.
**Clasificación: descartar** como delta a traer a master (master ya es la fuente; no cherry-pick merges).

## Hosts RO

### Oracle Dev (`159.195.216.33`)

- Release `20260731T192559Z-native-96250a4` / `96250a4`
- Services active; listeners 8010/3010/nginx/pg/redis
- Health ready OK; AI_MODE=signal → signal-dev only
- MEMORY_CONTEXT absent → disabled; Http stub raises not-enabled
- Alembic `20260731_0028`
- Celery: 51 tasks, queues default/signals/ai/documents/notifications/maintenance; beat 12 entries
- Deploy: build-release + activate-release + CURRENT/PREVIOUS

Evidencia: `04_oracle_dev_host.txt`, `04b_celery_tasks.txt`

### Signal Dev (`159.195.216.184`)

- Tree `/opt/apps/opn_signal_dev` @ `db9fd37`
- API/worker active; beat **active** + unit **disabled** (drift)
- healthz 200; `/api/v1/memory/v1/*` **404** (NO_MEMORY_API)
- Memory flags all functional OFF; probe ON
- Memory schema counts: 11857/48955/15925 … 100% `c:pilot|t:phase2`
- Memory alembic `20260731_mem_areq` (no lifecycle)
- Consumers: includes `opn-oracle` (14), pilot 61; **no** `opn-oracle-dev`
- Task policies: `05b_consumers_policies.txt`
- Update script restarts **api+worker only**, not beat; **no** CURRENT/PREVIOUS; **NO_ROLLBACK**

Evidencia: `05_signal_dev_host.txt`, `05b_consumers_policies.txt`

## Stubs

| Stub | Demostración | Evidencia |
|---|---|---|
| Signal Dev HTTP memory | 404 | `05_*`, `07_public_http.txt` |
| Signal main retrieve | `items=[]` | `08_code_stubs.txt` |
| Oracle disabled/http adapters | runtime raises | `04_oracle_dev_host.txt` |
| Unit tests adapter | 9 passed | `06_tests_focal.txt` |

## Tests

- Focal Oracle/Signal: **ejecutados** (9 + 31 passed)
- Suites completas: **NO ejecutadas** en esta fase (histórico documentado en ledger)

## Bases y worktrees

- Implementación futura desde **master/main limpios**, no merge ciego Dev
- Rework en `.worktrees/mdev00-rework`; roots compartidos no tocados
- Histórico `mdev/00-baseline-ledger` conservado

## Roadmap

- `ORC-MEM-001` approved + edges MEM-001..003 + módulo ORC-MOD-005
- progress project/module alineados al generador (74% / 56%)
- diff roadmap mínimo (sin reserialización global)
