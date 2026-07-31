# Decisiones de desarrollo vivo de OPN Oracle

Este registro contiene las decisiones que gobiernan el sistema vivo de planificación. Las
decisiones de producto y arquitectura históricas siguen en `docs/implementation/DECISIONS.md` y
en `docs/architecture/`; este archivo reúne solo las que afectan directamente a este mecanismo.

## ORC-ADR-0001 — El roadmap JSON es la fuente estructurada de verdad

- Fecha: 2026-07-31
- Estado: aceptada
- Contexto: El proyecto tiene memoria de producto, estado de implementación, prompts y código que evolucionan entre sesiones.
- Decisión: `docs/development/oracle-roadmap.json` es la fuente principal para estados, IDs, dependencias, criterios, evidencias y próximos trabajos. El HTML es un artefacto generado.
- Motivo: Evitar divergencia entre un dashboard editado a mano y la realidad auditable del repositorio.
- Alternativas consideradas: Mantener una checklist HTML manual; usar únicamente `STATUS.md`; guardar el estado en el historial de chat.
- Consecuencias: Cada cambio relevante requiere actualizar JSON y regenerar el dashboard; el HTML puede desecharse y reconstruirse.
- Funcionalidades afectadas: ORC-GOV-001, todas las funcionalidades de módulos.
- Archivos afectados: `docs/development/oracle-roadmap.json`, `scripts/generate-development-dashboard.py`, `docs/development/oracle-development-dashboard.html`.

## ORC-ADR-0002 — El generador valida antes de reemplazar el dashboard

- Fecha: 2026-07-31
- Estado: aceptada
- Contexto: Un JSON corrupto, una dependencia inexistente o un estado falso no debe destruir el último dashboard útil.
- Decisión: El generador valida estructura, IDs, estados, dependencias, evidencias, pruebas y rutas locales antes de escribir un archivo temporal y reemplazar el HTML atómicamente.
- Motivo: Fallar cerrado y conservar el último artefacto válido.
- Alternativas consideradas: Escribir directamente; generar un HTML parcial con warnings; delegar validación a revisión manual.
- Consecuencias: Una entrada inválida detiene la generación y devuelve errores accionables.
- Funcionalidades afectadas: ORC-GOV-001.
- Archivos afectados: `scripts/generate-development-dashboard.py`.

## ORC-ADR-0003 — El grafo se renderiza localmente sin CDN

- Fecha: 2026-07-31
- Estado: aceptada
- Contexto: El dashboard debe abrirse como archivo local sin servidor ni dependencia externa.
- Decisión: El generador crea un grafo SVG inline con enlaces a las tarjetas del checklist y estilos por estado.
- Motivo: Mantener el artefacto autónomo y hacer seleccionable cada nodo incluso sin red.
- Alternativas consideradas: Mermaid desde CDN; un iframe; una imagen estática sin navegación.
- Consecuencias: El layout inicial se calcula durante la generación; cambios de layout se implementan en el generador.
- Funcionalidades afectadas: ORC-GOV-001.
- Archivos afectados: `scripts/generate-development-dashboard.py`, `docs/development/oracle-development-dashboard.html`.

## ORC-ADR-0004 — La auditoría inicial expresa confianza y discrepancias

- Fecha: 2026-07-31
- Estado: aceptada
- Contexto: Existe código amplio y documentación histórica, pero algunos estados de despliegue o integración no se pueden comprobar desde una sola lectura local.
- Decisión: Cada conclusión del snapshot se clasifica como comprobada, parcialmente comprobada, propuesta o desconocida y enlaza evidencia. No se eleva una implementación a validada por la mera existencia de una ruta.
- Motivo: Reducir afirmaciones ficticias y conservar deuda real.
- Alternativas consideradas: Marcar por presencia de archivo; copiar el estado histórico sin reconciliarlo; dejar todos los puntos como pendientes.
- Consecuencias: El roadmap puede mostrar `implemented` o `under_review` aunque exista mucho código; los gates faltantes quedan visibles.
- Funcionalidades afectadas: ORC-SEC-001, ORC-SIG-001, ORC-SIG-003, ORC-EVID-001, ORC-AI-001, ORC-INV-001, ORC-ACT-002, ORC-REP-001, ORC-UX-002, ORC-UX-003, ORC-QA-001.
- Archivos afectados: `docs/development/oracle-roadmap.json`, `docs/development/oracle-architecture.md`, `docs/development/oracle-progress.md`.

## ORC-ADR-0005 — Los estados de implementación, validación y despliegue no se colapsan

- Fecha: 2026-07-31
- Estado: aceptada
- Contexto: El producto mezcla código local, pruebas, UAT y despliegues nativos.
- Decisión: `implemented` significa código realizado; `validated` significa criterios y pruebas superados; `deployed` requiere evidencia de un entorno concreto.
- Motivo: Evitar que una feature desplegada parcialmente o probada solo en unit tests se presente como terminada.
- Alternativas consideradas: Un único estado done; interpretar deployed como implemented; inferir validación desde CI histórico.
- Consecuencias: El dashboard muestra estados distintos para capacidades cercanas y obliga a documentar la evidencia del entorno.
- Funcionalidades afectadas: Todas.
- Archivos afectados: `docs/development/oracle-roadmap.json`, `scripts/generate-development-dashboard.py`.

## ORC-ADR-0006 — El historial de progreso es append-only a nivel documental

- Fecha: 2026-07-31
- Estado: aceptada
- Contexto: El roadmap necesita conservar estado anterior, nuevo, trabajo, archivos, pruebas y pendientes sin reescribir la memoria.
- Decisión: Cada feature conserva `history` y `oracle-progress.md` recibe entradas nuevas; no se borran entradas históricas para limpiar el dashboard.
- Motivo: Poder reconstruir por qué se cambió un estado.
- Alternativas consideradas: Sobrescribir un campo last_updated; guardar solo commits; mantener un changelog separado sin IDs.
- Consecuencias: El JSON crece, pero la trazabilidad queda junto al elemento y el dashboard puede mostrar la última actividad.
- Funcionalidades afectadas: ORC-GOV-001 y todas las features evolucionadas.
- Archivos afectados: `docs/development/oracle-roadmap.json`, `docs/development/oracle-progress.md`.

## ORC-ADR-0007 — Las integraciones externas se auditan como dependencias, no como hechos locales

- Fecha: 2026-07-31
- Estado: aceptada
- Contexto: Signal, proveedores IA, SMTP/Graph y fuentes oficiales pueden estar configurados de forma diferente por entorno.
- Decisión: La auditoría puede usar contratos, adapters, tests y runbooks locales, pero solo marca operación externa como desplegada cuando existe evidencia de entorno, release y configuración sin secretos.
- Motivo: Separar capacidad implementada de integración habilitada.
- Alternativas consideradas: Marcar deployed por existir un adapter; asumir que un runbook equivale a credenciales activas; ocultar la deuda externa.
- Consecuencias: Signal/IA/documentos pueden permanecer under_review o implemented con blockers explícitos.
- Funcionalidades afectadas: ORC-OPS-001, ORC-SIG-001, ORC-SIG-003, ORC-EVID-001, ORC-AI-001, ORC-PROC-001, ORC-PROC-002.
- Archivos afectados: `docs/development/oracle-roadmap.json`, `docs/implementation/OPEN_QUESTIONS.md`.

## ORC-ADR-0008 — La cobertura nominal de participantes no se infiere

- Fecha: 2026-07-31
- Estado: aceptada
- Contexto: `ReceivedTenderQuantity` informa un contador, no necesariamente nombres, roles o lista reconciliable de participantes.
- Decisión: ORC-PROC-004 permanece bloqueada hasta medir cobertura representativa y disponer de fuente/contrato con rol, fragmento y estado de localización.
- Motivo: No convertir «no localizado» en «no se presentó» ni prometer exhaustividad.
- Alternativas consideradas: Inferir participantes desde contadores o nombres; sumar resultados; presentar el conjunto visible como completo.
- Consecuencias: La UX y los informes deben comunicar límites y conservar el diagnóstico de cobertura.
- Funcionalidades afectadas: ORC-PROC-004, ORC-INV-001, ORC-PROC-003.
- Archivos afectados: `docs/development/oracle-roadmap.json`, `docs/implementation/STATUS.md`, `docs/implementation/spikes/77_investigation_protocol_v1_1.md`.
