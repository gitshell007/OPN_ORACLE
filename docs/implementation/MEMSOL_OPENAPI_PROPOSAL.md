# Propuesta OpenAPI aditiva · Memoria Sol (no generada aún en openapi.json)

Implementación en MEMSOL-03/04/06/07. Todos los errores: `application/problem+json`.
Mutaciones sensibles: `Idempotency-Key`. Drafts: `If-Match` / `version`.

## Intent

- `GET /api/v1/dossiers/{dossier_id}/intent` → IntentBundle
- `POST /api/v1/dossiers/{dossier_id}/intent/drafts` → 201 IntentRevision
- `PATCH /api/v1/dossiers/{dossier_id}/intent/drafts/{revision_id}` → 200
- `POST /api/v1/dossiers/{dossier_id}/intent/drafts/{revision_id}/accept` → 200 (no side-effect remoto)
- `POST /api/v1/dossiers/{dossier_id}/intent/drafts/{revision_id}/reject` → 200

## Requirements & offerings

- `GET|POST /api/v1/dossiers/{dossier_id}/requirements`
- `PATCH /api/v1/dossiers/{dossier_id}/requirements/{id}`
- `GET|POST /api/v1/dossiers/{dossier_id}/offerings`

## Activity (MEMSOL-04)

- `GET /api/v1/dossiers/{dossier_id}/activity`

## Questions (MEMSOL-06)

- `POST /api/v1/dossiers/{dossier_id}/conversations` → 201
- `POST /api/v1/dossiers/{dossier_id}/conversations/{id}/messages` → **202** `{job_id,message_id}`
- `GET .../messages/{id}`

## Custom reports (MEMSOL-07)

- `POST /api/v1/dossiers/{dossier_id}/reports/custom` → **202**
- `POST .../reports/{id}/plan/accept`

## Signal memory (MEMSOL-02/05)

- `POST /api/v1/memory/v1/retrieve` (propuesta) → MemoryRetrievalResponse
- Auth: consumer API key + external tenant; scope server-side
