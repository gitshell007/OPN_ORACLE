# OPN Oracle — Revisión UX orientada a venta y uso

Base: auditoría de código del frontend (rutas, navegación, componentes) y docs de producto. Etiquetas: HECHO / INFERENCIA / RECOMENDACIÓN.

---

## 1. ¿La experiencia responde a las ocho preguntas?

| Pregunta | ¿Responde hoy? | Dónde |
|---|---|---|
| ¿Qué cambió? | **Sí** | `/app/changes` + badge de no leídos + digest (HECHO) |
| ¿Qué importa? | **Sí** | Triaje con score y filtros; dashboard "trabajo que requiere atención" (HECHO) |
| ¿Por qué importa? | **Sí** | Explicación del triaje y "por qué importa" en el detalle de señal (HECHO) |
| ¿Qué evidencia existe? | **Sí, punto fuerte** | Drawer de señal, visor de informes con citas legibles (HECHO) |
| ¿Qué debemos hacer? | **Parcial** | Acción recomendada en señal/wizard; no hay "siguiente mejor acción" agregada por expediente (INFERENCIA) |
| ¿Quién debe actuar? | **Parcial** | Tareas con asignación; sin vista "mis pendientes" transversal destacada |
| ¿Cuándo? | **Parcial** | Deadlines en oportunidades/tareas; sin línea temporal de expediente |
| ¿Qué ocurrió después? | **Sí** | Decisiones + historial de estados + auditoría (HECHO) |

Veredicto: la arquitectura de información es sólida y honesta (estados vacíos explicativos, errores claros, concurrencia manejada). Las brechas son de agregación ("qué hago yo hoy"), no de estructura.

## 2. Las dos interfaces: decisión ya tomada, cerrarla

- HECHO: Vector Command Center es canónica y productiva; Horizon Decision Canvas quedó como prototipo mock (4 páginas, `localStorage`), redirigido en producción, con guard que rompe el build si se intenta habilitar.
- RECOMENDACIÓN: **no hay decisión pendiente que reabrir ni tercera síntesis que hacer.** Ejecutar la retirada documentada de Horizon (ya prevista en AGENTS.md) y dejar de mantener el escaparate A/B — es coste de atención sin retorno. Lo único que merece heredarse de Horizon es la idea de "carriles de decisión" como *informe* (vista de siguiente acción), no como layout.
- Riesgo de adopción de Vector: densidad alta puede intimidar al directivo. Mitigación: el directivo no navega — recibe el digest y el informe; el analista vive en las tablas. Encaja con los roles reales.

## 3. Experiencia por rol

- HECHO: no hay vistas por persona; hay una UI única con RBAC (34 permisos) que oculta acciones.
- RECOMENDACIÓN: no construir "dashboard ejecutivo" separado ahora. Sustitutos de bajo coste: (1) digest semanal por email (el "dashboard" del directivo es su bandeja), (2) el informe ejecutivo en PDF, (3) una vista "Mis pendientes" para el analista (P1). Un dashboard ejecutivo dedicado es P2, cuando haya 10+ clientes pidiéndolo.

## 4. Menú definitivo (validación)

El menú actual (HECHO: Trabajo estratégico / Inteligencia / Ejecución / Administración) es correcto y no necesita rediseño. Ajustes menores recomendados:
1. Renombrar la entrada "Señales" con contador ya existente — mantener.
2. Elevar "Licitaciones" un puesto (encima de Oportunidades) para el ICP B2G — cosmético, alineado con la venta.
3. "Qué ha cambiado" como landing por defecto del usuario recurrente (hoy Inicio) — evaluar con los pilotos antes de cambiar.

## 5. Flujos clave: estado y huecos

| Flujo | Estado | Hueco comercial |
|---|---|---|
| Crear expediente (diálogo + perfiles por tipo + wizard) | HECHO, bueno | Falta plantilla explícita "Concurso/licitación" prefijada con el flujo PLACSP como onboarding de venta |
| Revisión de señales → promoción | HECHO, excelente (ETag, transiciones, evidencia) | Ninguno relevante |
| Scoring explicado | HECHO (explicación + confianza + feedback) | Exponer "cómo puntuamos" en un tooltip/página corta para la demo |
| Informes | HECHO | **PDF** (P0 comercial); plantilla go/no-go de licitación (P1, vendible) |
| Informe de entidad | Roto en producción (p63) | **P0: estabilizar antes de cualquier demo** |
| Qué ha cambiado | HECHO | "Marcar revisado" pendiente (menor); digest por email (P0 retención) |
| Móvil / accesibilidad | HECHO: listas móviles, ARIA, foco, teclado | Suficiente; no invertir más ahora |

## 6. Idioma y tono

HECHO: todo en español de España, con dos auditorías lingüísticas que eliminaron jerga técnica (tenant, job, score → lenguaje de negocio). Es un activo de venta en el ICP elegido — mantener como criterio de calidad.

## 7. Lo que puede perjudicar la adopción

1. **Cold start** (INFERENCIA, riesgo nº1): tenant nuevo = señales vacías. Mitigar con onboarding que precarga PLACSP/BORME del cliente el día 1 y un monitor semilla por expediente.
2. Generación asíncrona sin expectativas: informes tardan ~1-2 min (HECHO: ~80 s el de entidad); la UI ya usa JobProgress — en demo, pregenerar.
3. Densidad para el patrocinador directivo: resuelto vía digest/PDF, no vía rediseño.

## 8. Qué es "premium sin sacrificar claridad"

Ya lo tiene: sobriedad, evidencia visible, estados honestos. No añadir decoración. La percepción premium para el comprador vendrá de: PDF bien maquetado, digest por email cuidado, y demo sin errores — no de más UI.
