# Decisiones

Registro de decisiones relevantes tomadas durante el desarrollo. Una entrada por decisión,
en orden cronológico inverso. Este archivo se muestra en la pestaña **Decisiones** del dashboard.

Formato sugerido:

```text
## AAAA-MM-DD · Título corto

- Contexto: qué problema obligaba a decidir.
- Decisión: qué se eligió.
- Alternativas descartadas: qué se valoró y por qué no.
- Consecuencias: qué queda condicionado.
- Tareas afectadas: IDs de Ishtar Memory.
```

## 2026-08-01 · Ishtar Memory como sistema de planificación del repositorio

- Contexto: el estado del desarrollo no debe depender del historial conversacional ni de un HTML
  editado a mano, y el mismo mecanismo debe servir para otros proyectos de OPN.
- Decisión: la fuente única de verdad es `roadmap.json`; el dashboard es siempre un artefacto
  generado; la identidad del proyecto vive en `project-config.json` y no en el código.
- Alternativas descartadas: mantener el estado dentro del HTML (se desincroniza) y usar
  `localStorage` como almacén (no es compartible ni versionable).
- Consecuencias: toda escritura pasa por validación, control de revisión y registro de actividad.
- Tareas afectadas: ninguna todavía. El árbol se construye a partir de las instrucciones del usuario.

## 2026-08-01 · El roadmap arranca vacío y la migración es explícita

- Contexto: el repositorio ya contenía un roadmap heredado en `docs/development/oracle-roadmap.json`.
- Decisión: Ishtar Memory se implanta con cero tareas de negocio y la importación del roadmap
  anterior se ejecuta bajo demanda con `migrate --apply`, que crea copia de seguridad y no borra
  los archivos previos.
- Alternativas descartadas: importar automáticamente durante la instalación, que habría creado
  tareas sin instrucción expresa del usuario.
- Consecuencias: los datos heredados siguen intactos y disponibles hasta que se decida migrarlos.
- Tareas afectadas: ninguna.
