# Memory API v1 · contrato MDEV-01

Bundle bilateral idéntico en Oracle (`docs/contracts/memory_v1/`).

- `CONTRACT_MANIFEST.json` congela SHA-256 de schemas/fixtures/error_catalog.
- Implementación runtime: `app/services/memory_host/memory_contract_v1.py` + `scope_for_dossier`.
- Retrieve productivos exigen tenant allowlist + `memory:read` + dossier UUID.
- Engine host OFF → 503; stub items=[] con coverage honesta cuando engine ON.

No activar flags en Dev en MDEV-01.
