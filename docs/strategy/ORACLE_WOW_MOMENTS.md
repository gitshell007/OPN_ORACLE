# OPN Oracle — Momentos wow

> **REVISIÓN 2026-08-07:** inventario interno de hipótesis de demostración, no
> guion autorizado. Las etiquetas históricas «HECHO» significaban presencia en
> código, no disponibilidad, cobertura, latencia ni funcionamiento universal en
> un despliegue. Prevalecen el [guion canónico](ORACLE_DEMO_SCRIPT.md) y el
> [one-pager honesto](ORACLE_ONE_PAGER_HONESTO.md).

Criterio de inclusión: mejora venta, adopción, retención o margen; cada momento
requiere humo específico y límites expresos.

---

## Aperturas posibles de una demo alternativa de entidad

**W1 — "Esta es tu competencia, por dentro."**
- Usuario: director/a de desarrollo de negocio (prospecto en demo).
- Problema: due diligence manual de competidores/socios.
- Entrada: nombre de un competidor real del prospecto (preparado antes de la reunión).
- Acción de Oracle: ficha de entidad con los actos, vínculos y contratación que las fuentes y el despliegue devuelvan para esa identidad.
- Salida: pantalla con cobertura y vacíos visibles; no se promete ficha completa.
- Tiempo hasta valor: medir en el entorno ensayado; no existe SLA universal. Revisar las fuentes mostradas.
- KPI: reuniones que piden segunda cita tras ver W1.
- Dificultad técnica histórica: existe base de código; requiere humo, resolución de identidad y p63 si se genera informe.
- Impacto comercial: **el abridor de la demo**. Máximo.

**W2 — "Esto es lo que se adjudicó en tu sector el último trimestre."**
- Usuario: mismo. Entrada: CPV/sector del prospecto.
- Acción: workspace de contratación — adjudicaciones recientes, importes, adjudicatarios, UTEs, licitaciones abiertas.
- Salida: muestra de contratación pública según filtros y cobertura. Tiempo: medir; no prometer exhaustividad.
- Dificultad: requiere datos y filtros ensayados. Impacto hipotético: alto.

## Wow en la demo de 15 minutos (secuencia completa en [ORACLE_DEMO_SCRIPT.md](ORACLE_DEMO_SCRIPT.md))

**W3 — Señal → oportunidad con evidencia y explicación.**
- Entrada: señal triada en un expediente demo. Acción: abrir el detalle — score con explicación, evidencia, "por qué importa", acción recomendada; promoverla a oportunidad con tarea en un clic.
- Salida: oportunidad con procedencia completa. Tiempo: 2 min.
- KPI demo: el prospecto pregunta "¿y esto lo hace con mis proyectos?". Dificultad: 0 (HECHO). Impacto: alto — es el corazón del producto.

**W4 — Informe para revisión con evidencia disponible.**
- Entrada: expediente con señales/oportunidades. Acción: generar informe ejecutivo; abrir el visor y clicar 2-3 citas hasta su fuente.
- Salida: borrador de informe revisable; no llamarlo «listo para comité» sin aprobación humana. Tiempo y estabilidad se miden por release.
- KPI: el revisor puede seguir las citas presentes y detectar vacíos. p63 bloquea esta demo de entidad; la muestra histórica de citas no es garantía universal.

**W5 — "Qué ha cambiado" + digest semanal.**
- Entrada: expediente con actividad. Acción: vista de cambios priorizados (5-10, no lista infinita) + digest estratégico.
- Salida: el ritual del lunes del equipo. Tiempo: 1 min.
- KPI (post-venta): usuarios que vuelven ≥1 vez/semana. Dificultad: envío por email pendiente (pequeña). Impacto: el que sostiene la renovación.

**W6 — Asistente "Mejorar con Oracle" (wizard).**
- Entrada: expediente recién creado en la demo con el caso del prospecto. Acción: diagnóstico por rondas — qué falta, preguntas, acciones con formularios prefijados (crear vigilancia, licitación, actor).
- Salida: expediente operativo en minutos, no en una consultoría. Tiempo: 3 min.
- KPI: time-to-first-value en pilotos. Dificultad: 0 (HECHO). Impacto: alto — desactiva "no tengo equipo para configurar esto".

## Wow a los 30 días (renovación y expansión)

**W7 — Briefing de reunión con memoria.**
- Entrada: reunión creada con actores del expediente. Acción: briefing IA — contexto, intereses, preguntas, objeciones.
- Salida: nadie llega a esa reunión sin contexto. KPI: briefings generados/mes. Dificultad: 0 (HECHO). Impacto: medio-alto en retención.

**W8 — Memoria de decisiones auditable.**
- A los 30 días, enseñar el registro: qué se decidió, cuándo, con qué evidencia, qué hipótesis se descartaron.
- KPI: decisiones registradas/mes. Impacto: switching cost creciente — el argumento anti-churn.

**W9 — Informe competitivo de contratación por adjudicatario.**
- "En 8 semanas, esto es lo que tus 3 competidores han ganado, dónde y con quién." KPI: informes competitivos/piloto. Dificultad: 0 (HECHO, plantilla v2). Impacto: alto en conversión piloto→anual.

## Evaluación de los candidatos restantes del prompt maestro

| Candidato | Veredicto |
|---|---|
| Crear expediente desde documentos/URL/transcripción | **Posponer** (P1): el intake agent existe como agente pero el flujo UI no está montado; el wizard cubre la activación hoy |
| Escenarios ideal/probable/adverso | **Descartar por ahora**: no implementado, alto esfuerzo, valor de demo dudoso frente a W1-W4 |
| Contradicciones entre fuentes | **Descartar por ahora**: prometedor pero sin soporte técnico actual; no prometer |
| Comparativa entre expedientes | **Posponer**: valor real en cartera madura (mes 6+), no en venta |
| Cambio que invalida una hipótesis | **Posponer a P1**: las hipótesis existen en el modelo; la detección automática no. Sería un wow diferencial de renovación cuando exista |
| Mapa vivo de actores interno | Ya cubierto parcialmente (candidatos desde señales + grafo BORME); no sobreinvertir en visualización |

## Regla de oro

La demo autorizable inicial es el recorrido de contratación del guion canónico. Los demás momentos quedan como candidatos hasta superar humo, cobertura y aprobación comercial propios; p63 bloquea únicamente los que incluyan informe de entidad.
