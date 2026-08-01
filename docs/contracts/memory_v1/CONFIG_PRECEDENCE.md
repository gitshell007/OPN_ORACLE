# Precedencia de configuración efectiva (MDEV-01)

## Signal

```
host master switches (settings.env; restart)
  > consumer kill_switch / ConsumerMemorySettings.enabled (DB)
    > ConsumerMemorySettings.stages + limits + allowed_external_tenant_ids
      > dossier limits (si se modelan server-side)
        > task policy ConsumerAISettings (solo LLM stages)
          > catálogo código fallback
```

UI admin muestra valor efectivo y procedencia. Si el host apaga ENGINE, los toggles consumer
quedan sin efecto y se explica en español.

## Oracle

```
MEMORY_CONTEXT_MODE host (disabled|http)   # mock solo test
  > IntegrationConnection signal activa + healthy por tenant
    > tenant memory mode (disabled|shadow|augment)
      > DossierMemoryProfile.mode override opcional
```

## Local-only

Contenido tenant no sale a cloud salvo `APPROVED_EXTERNAL_SPEND` + `APPROVED_CLOUD_DATA_POLICY`.
En MDEV-01 ambos permanecen vacíos.
