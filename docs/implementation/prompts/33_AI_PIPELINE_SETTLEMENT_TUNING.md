# 33 — Estabilizar el pipeline IA de informes/briefings/digest (asentamiento, reintentos y tuning) (P1)

> Lee `18_UX_REMEDIATION_OVERVIEW.md` (reglas comunes). Requiere **acceso al host de Oracle** para
> leer auditoría IA de producción. Al terminar, **despliega** (D-022) y **verifica en vivo**.

## Contexto: el prompt 31 funcionó, pero el pipeline sigue cayendo en Oracle

Tras habilitar en Signal las tasks `report_writer`/`meeting_briefing`/`weekly_change` (release
Signal `1fae7cf`), la verificación en vivo del 2026-07-14 muestra que **Signal ya sirve las
inferencias** y aun así **el job de Oracle falla**:

- Informe `oracle.report.generate` (job `8f9b716e-7718-4b03-a1e1-ac6ae108d4f6`, 06:30–06:34 UTC):
  el intento 1 ejecutó **dos llamadas a Signal con 200 OK** (writer 06:31:42, reviewer 06:34:27 —
  confirmado en los logs de uvicorn de Signal) y **falló ~9 s después del reviewer**; los intentos
  2 y 3 murieron al instante sin llegar a Signal, y el job terminó `retry_exhausted`. El informe
  quedó «Fallido · Código seguro: AIPolicyDenied».
- Briefing `oracle.meeting_briefing.refresh` (job `be3839d6-f5d8-4f79-8e2d-c15f10a2e2f4`,
  2026-07-13 18:16 UTC): `permanent_failure` con 2 intentos.
- Histórico relevante: `dossier_situation_summary` pasó por **exactamente esta clase de fallos**
  hasta su tuning de producción (prompt v1→v5, presupuesto 2.600 tokens, timeout 210 s, reparación
  JSON compacta — ver STATUS «El E2E real sobre el expediente de mercado…»). Los otros tres agentes
  **no han recibido ese tuning**.

## Diagnóstico preliminar (código)

1. **Los reintentos Celery son inútiles por diseño actual:** `execute_agent`
   (`apps/api/src/opn_oracle/ai/service.py` ~línea 195) levanta
   `AIPolicyDenied("La ejecución IA de este job ya fue reclamada.")` si existe un `AIAuditLog` del
   mismo (job, agent) en estado no-`succeeded`. Un fallo transitorio en el intento 1 condena los
   intentos 2 y 3 a fallar al instante → `retry_exhausted` + el código visible `AIPolicyDenied`
   enmascara la causa raíz.
2. **La causa raíz del intento 1 está en el tramo post-reviewer** (asentamiento): candidatos —
   veredicto del reviewer `rejected`/inválido, `validate_evidence` sobre el output del reviewer,
   expiración de lease (`lease_seconds = min(CELERY_TASK_TIME_LIMIT, 600)`), o validación de schema
   del writer con salida larga de `qwen3.5:9b`. El error exacto está en
   `AIAuditLog.error_code`/`AIAttempt.error_code` de producción.

## Objetivo

Que informes, briefings y digest **publiquen de forma fiable** en producción con los modelos
locales gobernados, y que un fallo transitorio **no queme los reintentos** ni enmascare la causa.

## Alcance

1. **Diagnóstico primero (obligatorio, en el host de Oracle):** consulta en PostgreSQL los
   `AIAuditLog`/`AIAttempt` de los jobs citados (error_code, kind generate/reviewer, latencias,
   tokens) y determina la causa raíz real del intento 1 del informe y del briefing. Regístrala en
   STATUS antes de tocar código.
2. **Arreglar la semántica de reintentos:** un intento Celery nuevo debe poder crear un intento IA
   nuevo (o el fallo debe marcar el job como no reintentable de inmediato). Elimina el patrón
   «intento 1 falla → 2 y 3 mueren en el fencing»: conserva la garantía de no-duplicación (un solo
   audit activo), pero permite reintentos reales tras fallo terminalizado, con el error raíz
   propagado al `BackgroundJob.error_*` (no `AIPolicyDenied` genérico).
3. **Tuning de producción de los tres agentes** (siguiendo el precedente del Oráculo v5):
   presupuesto de tokens y timeout coherentes con lo gobernado en Signal (report_writer 300 s/6500;
   meeting_briefing 180 s/3500; weekly_change 240 s/4200), prompts compactos si hace falta
   (versionados vN, sin tocar versiones aplicadas), reparación JSON si aplica, y lease/tiempos
   Celery (`CELERY_TASK_TIME_LIMIT`, renovación del reviewer) que cubran el peor caso
   writer+reviewer local. Si el veredicto del reviewer resulta demasiado estricto para outputs
   largos locales, ajusta el prompt/criterios del reviewer con la misma disciplina (evidencia
   obligatoria, sin publicar outputs inválidos).
4. **Sin aflojar la seguridad:** nada de publicar outputs que no validen schema/evidencia; los
   intentos inválidos siguen quedando en auditoría.

## Criterios de aceptación

- [ ] Causa raíz del intento 1 (informe y briefing) identificada y registrada con evidencia de
      auditoría en STATUS.
- [ ] Un informe «Plan de acción» del expediente CATL se genera y **publica** en producción con
      contenido citado (estado Listo/válido, no Fallido).
- [ ] «Preparar reunión» publica un briefing real; el digest de «Qué ha cambiado» publica contenido.
- [ ] Un fallo transitorio inyectado (o simulado en test) permite reintento real: el job no muere en
      «ya fue reclamada» y el error raíz llega a `BackgroundJob.error_message`.
- [ ] Tests backend de la nueva semántica de reintentos y del asentamiento; suite completa verde
      (recuerda `ruff format --check .` sobre todo el árbol).
- [ ] Sin migración salvo necesidad justificada; contrato regenerado si cambia.

## Despliegue y verificación (obligatorio)

1. **CI completo manual** (`workflow_dispatch`, D-024) verde — esto toca el núcleo IA.
2. Modo rápido UAT (D-022): backup local + restore aislado, release inmutable,
   `sudo oracle-control update`, smoke + health.
3. Verificación funcional en producción (expediente CATL `292d85e5-…`): generar informe, briefing
   y digest de punta a punta hasta verlos **publicados** con fuentes; sin errores de consola.
   Reintentar el informe fallido `c20355ff-2642-4693-89e5-19c44034d9ef` («Reintentar») y confirmar
   que ahora completa.
4. Actualiza `STATUS.md` (causa raíz + release + comandos + resultados) y `DECISIONS.md` si cambia
   la semántica de reintentos.

## No hacer

- No activar cloud ni cambiar la política de proveedores (Ollama/Titan gobernados por Signal).
- No publicar outputs sin validación de schema/evidencia.
- No borrar auditoría existente; los fallos históricos son evidencia.
