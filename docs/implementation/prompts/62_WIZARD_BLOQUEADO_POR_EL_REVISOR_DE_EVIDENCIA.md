> **Diagnóstico ya hecho contra producción. La causa no está en el wizard.** No empieces
> depurando su prompt ni su esquema: el generador funciona. Lee esto entero antes de tocar nada.

# 62 — El asistente de expediente no ha funcionado nunca: le aplicamos un control que no le toca (P1)

## Qué pasa, medido

Ejecutado el wizard en producción con sesión real, expediente «Coches de Bomberos»
(`d6be4657-4d08-41ff-9ca6-4615ef9a2792`), job `894d9379-e2c5-427d-9545-ecb8e13e3937`:

```
POST /api/v1/ai/dossiers/{id}/completion-wizard/runs  ->  202, encola bien
job -> failed | progress 10
        "El job no pudo completarse. Causa: El revisor de evidencia rechazó el output."
```

Y en los intentos de esa ejecución:

```
generate  | succeeded     <- el wizard produjo su salida sin problema
reviewer  | failed        <- lo tumba el revisor de evidencia
```

Histórico de `ai_audit_logs` por agente: **`dossier_completion_wizard` acumula 1 fallo y 0 éxitos.
Nunca ha completado una ejecución.** El track se dio por entregado sin E2E, y esto es lo que había
debajo.

## Por qué: un control universal sobre un contrato que no lo admite

`ai/service.py` ejecuta el revisor de evidencia **después de todo agente** que no sea el propio
revisor (`if agent != "evidence_reviewer" and not result.safe_fallback_used`), y si el veredicto es
`fail` el job muere (`ai/service.py:773-774`).

Ese control existe para informes: comprueba que las afirmaciones citan evidencia permitida. Pero el
contrato del wizard **no tiene evidencia por ninguna parte**. Verificado campo a campo en
`ai/schemas.py`:

- `DossierCompletionWizardOutput`: `summary`, `confidence`, `warnings`, `section_diagnostics`,
  `questions`, `recommended_actions`. Ningún `evidence_ids`.
- `DossierWizardSectionDiagnostic`: `section`, `status`, `explanation`.
- `DossierWizardQuestion`: `id`, `question`, `why_it_matters`, `expected_input`.
- `DossierWizardRecommendedAction`: `kind`, `title`, `rationale`, `prefill`.

Y es correcto que no la tenga, porque **el wizard afirma ausencias**: «te falta definir el objetivo»,
«no hay actores registrados». No se puede citar evidencia de algo que no existe. Pedirle citas sería
pedirle que documente lo que no está.

Por eso el resto de agentes pasan y este no: `dossier_situation_summary` (50 éxitos),
`signal_triage` (18) y los agentes de informe llevan todos `evidence_ids` en su esquema. **El wizard
es el primer agente cuya salida no cita nada por diseño, y la revisión universal no contempla ese
caso.**

## Qué hay que decidir (y es una decisión de diseño, no un parche)

La pregunta es: **¿qué significa "revisar" para un agente que no cita evidencia?**

Hay dos salidas legítimas y quiero que elijas con criterio, no la más rápida:

**A. Declarar qué agentes están sujetos a revisión de evidencia.** Una propiedad explícita del
agente o del contrato —no una lista suelta en un `if`— que diga si su salida es de las que citan.
Los que no lo son, se saltan ese control. Es honesto y simple, pero deja al wizard **sin ningún
control de salida**, y eso hay que asumirlo conscientemente: es un agente que propone acciones
ejecutables al usuario.

**B. Que el revisor entienda contratos sin evidencia.** Que en vez de fallar por ausencia de citas,
verifique lo que sí tiene sentido verificar en un diagnóstico: que no inventa secciones fuera del
enum, que las preguntas se refieren a huecos reales del expediente, que no afirma hechos sobre el
negocio del cliente que no puede saber. Es más trabajo y más valioso.

**Mi recomendación es A ahora y B como mejora posterior**, para desbloquear el wizard sin construir
un revisor nuevo a medias. Pero si al mirarlo ves que B es barato, dilo: prefiero un control real a
ninguno.

Lo que **no** vale: ablandar el revisor para todos, ni convertir su veredicto en aviso. Ese control
es lo que sostiene la fiabilidad de los informes, y ya está midiendo bien —de hecho acaba de hacer
su trabajo: detectó una salida que no cumplía lo que se le exigía—. El problema es que se le exige
lo que no toca.

## Invariantes que no puedes romper

- **La revisión sigue siendo obligatoria para los agentes que producen informes**
  (`report_writer`, `competitive_procurement_intelligence`, `entity_dossier_intelligence`). Si tu
  cambio los deja sin revisar, es un fallo grave: un informe publicado sin revisar es peor que uno
  que falla.
- **No toques el paquete compacto del revisor** (prompt 60): acaba de arreglarse y funciona.
- La exención, si la implementas, debe ser **explícita y visible en el contrato del agente**, no un
  `if agent == "dossier_completion_wizard"` escondido en el servicio. El próximo agente sin
  evidencia debe encontrar el camino hecho, no repetir este fallo.

## Verificación exigida

El E2E de este track nunca se ha hecho. No lo declares hecho sin esto:

1. El wizard completa una ejecución real (`succeeded`) sobre un expediente con datos.
2. Una **segunda ronda** con respuestas del usuario (`answers`) también completa. El wizard es por
   rondas y esa es su razón de ser; una sola ronda no prueba el flujo.
3. `GET /completion-wizard/latest` devuelve el resultado.
4. Un agente de informe sigue fallando si su salida no cita bien: demuéstralo mutando y di qué test
   cayó. Es la garantía de que no has desactivado el control donde sí importa.

Y en el resumen final, dos cosas concretas: **qué opción elegiste y por qué**, y **qué control de
salida tiene el wizard después de tu cambio** — aunque la respuesta honesta sea «ninguno, y aquí
está la deuda anotada».

## Qué NO hacer

- No empieces por el prompt ni el esquema del wizard: el generador funciona, `generate` sale
  `succeeded`.
- No desactives el revisor globalmente ni lo degrades a aviso.
- No cambies el flujo de informes.
- No des el track por verificado sin las dos rondas.
