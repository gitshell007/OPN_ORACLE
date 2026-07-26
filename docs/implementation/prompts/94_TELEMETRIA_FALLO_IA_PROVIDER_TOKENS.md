# 94 — Telemetría de fallo IA: provider upstream y tokens (P1 · IA)

> Con `AI_MODE=signal`, un generate Ollama vía Signal que luego falla en el revisor dejaba
> audit.provider=signal y usage 0. Eso confunde el diagnóstico ollama vs signal.

## Alcance

- Persistir provider/model del LLMResult al completar generate.
- En fail(), liquidar tokens de intentos hermanos y settled si hubo uso.

## Fuera de alcance

Cambiar AI_MODE de producción; SSO; PDF.
