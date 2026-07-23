# ORACLE-EXP-INV-01 · ERD propuesto, sin migración

**Estado:** diseño del spike; no existe todavía en PostgreSQL.

```mermaid
erDiagram
    STRATEGIC_DOSSIER ||--o{ INVESTIGATION_RUN : contiene
    INVESTIGATION_RUN ||--o{ INVESTIGATION_STEP : planifica
    BACKGROUND_JOB ||--o{ INVESTIGATION_STEP : ejecuta_intentos
    INVESTIGATION_RUN ||--o{ RESEARCH_ENTITY : descubre
    RESEARCH_ENTITY ||--o{ RESEARCH_ALIAS : identifica
    RESEARCH_ENTITY ||--o{ RESEARCH_IDENTIFIER : verifica
    INVESTIGATION_RUN ||--o{ RESEARCH_RELATION : observa
    RESEARCH_ENTITY ||--o{ RESEARCH_RELATION : sujeto
    RESEARCH_ENTITY ||--o{ RESEARCH_RELATION : objeto
    INVESTIGATION_RUN ||--o{ RESEARCH_SOURCE_SNAPSHOT : manifiesta
    RESEARCH_SOURCE_SNAPSHOT ||--o{ RESEARCH_EVIDENCE_LINK : localiza
    INVESTIGATION_RUN ||--o{ PROCUREMENT_LOT_OBSERVATION : contrasta
    PROCUREMENT_LOT_OBSERVATION ||--o{ PROCUREMENT_PARTICIPATION : agrupa
    RESEARCH_ENTITY ||--o{ PROCUREMENT_PARTICIPATION : participa
    INVESTIGATION_RUN ||--o{ RESEARCH_CLAIM : consolida
    RESEARCH_CLAIM ||--o{ RESEARCH_CLAIM_EVIDENCE : cita
    INVESTIGATION_RUN ||--o{ RESEARCH_CONTRADICTION : registra
    RESEARCH_CLAIM ||--o{ RESEARCH_CONTRADICTION : confronta
    INVESTIGATION_RUN ||--o{ RESEARCH_REVIEW : decide
    INVESTIGATION_RUN ||--o{ RESEARCH_PROMOTION : promueve
    AI_AUDIT_LOG o|--o{ INVESTIGATION_STEP : documenta
    AI_AUDIT_LOG o|--o{ RESEARCH_ENTITY : deriva
    AI_AUDIT_LOG o|--o{ RESEARCH_RELATION : deriva
    AI_AUDIT_LOG o|--o{ PROCUREMENT_PARTICIPATION : deriva
    AI_AUDIT_LOG o|--o{ RESEARCH_CLAIM : deriva

    INVESTIGATION_RUN {
        uuid id PK
        uuid tenant_id FK
        uuid dossier_id FK
        string status
        string stage
        timestamptz as_of
        jsonb scope
        jsonb budgets
        jsonb usage
        string protocol_version
        string source_policy_version
        string corpus_hash
        integer version
    }
    INVESTIGATION_STEP {
        uuid id PK
        uuid tenant_id FK
        uuid run_id FK
        uuid background_job_id FK
        string stage
        string subject_key
        string state
        string input_hash
        string result_hash
        jsonb result_ref
        uuid ai_audit_log_id FK
        string prompt_name
        string prompt_version
    }
    RESEARCH_ENTITY {
        uuid id PK
        uuid tenant_id FK
        uuid run_id FK
        string literal_name
        string normalized_name
        string entity_kind
        string resolution_status
        integer depth
        integer identity_confidence
        string discovery_path_hash
        uuid ai_audit_log_id FK
    }
    RESEARCH_ALIAS {
        uuid id PK
        uuid tenant_id FK
        uuid run_id FK
        uuid research_entity_id FK
        string literal_name
        string normalized_name
        uuid evidence_id FK
    }
    RESEARCH_IDENTIFIER {
        uuid id PK
        uuid tenant_id FK
        uuid run_id FK
        uuid research_entity_id FK
        string scheme
        string authority
        string jurisdiction
        string normalized_value_blind_index
        string blind_index_key_version
        string masked_value
        string verification_status
        uuid evidence_id FK
    }
    RESEARCH_RELATION {
        uuid id PK
        uuid tenant_id FK
        uuid run_id FK
        uuid subject_id FK
        uuid object_id FK
        string relation_type
        string source_label
        date valid_from
        date valid_to
        string status
        integer relation_confidence
        uuid ai_audit_log_id FK
    }
    RESEARCH_SOURCE_SNAPSHOT {
        uuid id PK
        uuid tenant_id FK
        uuid run_id FK
        string provider
        string source_class
        string external_key
        string content_sha256
        string content_ref
        jsonb coverage
        string parser_version
        string policy_version
    }
    PROCUREMENT_LOT_OBSERVATION {
        uuid id PK
        uuid tenant_id FK
        uuid run_id FK
        string folder_id
        string lot_id
        string source_revision
        integer received_tender_quantity
        string coverage_status
        uuid evidence_id FK
    }
    PROCUREMENT_PARTICIPATION {
        uuid id PK
        uuid tenant_id FK
        uuid run_id FK
        uuid research_entity_id FK
        uuid lot_observation_id FK
        string role
        string coverage_status
        uuid ai_audit_log_id FK
    }
    RESEARCH_CLAIM {
        uuid id PK
        uuid tenant_id FK
        uuid run_id FK
        string kind
        string subject
        string predicate
        string object
        jsonb period
        string status
        integer confidence
        uuid ai_audit_log_id FK
    }
```

## Invariantes

- Todas las tablas son tenant-scoped; `tenant_id` se deriva de sesión/run, nunca del navegador.
- `InvestigationStep` expresa el DAG funcional. `BackgroundJob` conserva la autoridad sobre lease,
  heartbeat, fencing, retry e intentos; no se crea una segunda máquina de ejecución.
- Las constraints de idempotencia usan al menos `tenant_id + run_id + stage + subject_key +
  input_hash`.
- `ResearchEntity` y `ResearchRelation` son candidatos aislados. No comparten IDs ni escritura
  implícita con `Actor`/`Relationship`.
- Identidad y relación tienen confianza separada. Solo coincide un identificador cuando `scheme`,
  `authority`, `jurisdiction` y valor normalizado son iguales. Para identificadores personales, el
  valor persistido usa índice ciego HMAC tenant-scoped con clave versionada/rotable y forma
  enmascarada; un SHA-256 simple no sirve por ser enumerable. Las personas sin prueba inequívoca
  requieren revisión humana.
- `ProcurementLotObservation` es única por run, expediente, lote y revisión y guarda el recuento
  una sola vez. `ProcurementParticipation` es única por run, entidad, observación y rol.
- Las fuentes conservan manifest, hash, localizador, parser y cobertura. El bruto completo queda en
  Signal o caché temporal salvo decisión explícita que modifique D-028.
- Cada claim factual tiene al menos una evidencia aceptada. Opinión y recomendación referencian
  claims; no introducen hechos nuevos.
- Todo candidato derivado por IA conserva `AIAuditLog`, prompt/version y evidencias de origen; los
  resultados deterministas dejan esos campos nulos y registran parser/policy en la fuente.
- `ResearchReview` es append-only. Una promoción a dominio canónico es otra acción idempotente,
  autorizada y auditada; nunca un side effect de la inferencia.
- La cancelación impide publicar dependencias nuevas, pero conserva los resultados ya asentados y
  permite auditoría.

## Índices y constraints a validar en Fase 1

- índices compuestos por `tenant_id, run_id, status/stage`;
- unicidad de source snapshot por `run_id, provider, external_key, content_sha256`;
- unicidad de alias/identificador normalizado dentro del candidato, sin imponer unicidad global a
  nombres de personas;
- unicidad de observación de contratación por `run_id, folder_id, lot_id, source_revision`;
- constraint de presupuesto/uso no negativa;
- optimistic concurrency mediante `version`;
- RLS como defensa en profundidad después del scoping de repositorio;
- conteo de filas existente antes de cualquier futura migración; este spike crea cero filas.
