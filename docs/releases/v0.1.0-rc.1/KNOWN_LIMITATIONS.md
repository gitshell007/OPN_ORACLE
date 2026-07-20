# Known limitations · v0.1.0-rc.1

> ℹ️ **Documento histórico.** Refleja el estado de la release candidate v0.1.0-rc.1 (2026-07-11) y no
> se mantiene al día. Varias limitaciones de abajo ya no aplican: la IA está operativa gobernada por
> Signal (Ollama `qwen3.5:9b`) y el adapter HTTP de Signal Avanza está habilitado. Para el estado
> actual del producto, consulta [`docs/implementation/STATUS.md`](../../implementation/STATUS.md).

- Signal Avanza usa mock/fail-closed; el adapter HTTP no está habilitado.
- IA está deshabilitada; no se hacen llamadas a modelos externos.
- Documentos y PDF productivos están deshabilitados hasta storage, antivirus y sandbox.
- Host de 3,7 GiB: worker consolidado con concurrencia 1; no representa capacidad de carga alta.
- CSP permanece report-only y necesita nonce/enforcement posterior.
- Métricas in-process no agregan todavía todos los workers.
- Backup local diario funciona; la automatización off-host y el restore desde descarga siguen
  pendientes.
- El primer tenant existe, pero aún no tiene owner aceptado.

