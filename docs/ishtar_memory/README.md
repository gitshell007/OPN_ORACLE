# Ishtar Memory

Sistema vivo y editable de planificación del desarrollo. Convierte ideas en un árbol de tareas con
identificador propio, permite cambiar estados a mano, guarda los prompts asociados a cada tarea y
genera un dashboard HTML autónomo que no se desincroniza de los datos.

No está acoplado a ningún producto: toda la identidad del proyecto vive en `project-config.json`.

## Qué archivo manda

`roadmap.json` es la **fuente única de verdad**. `dashboard.html` es siempre un artefacto generado
y nunca debe editarse a mano. `activity.jsonl` es el registro cronológico de lo que ha ocurrido.

```text
docs/ishtar_memory/
├── project-config.json   Identidad del proyecto (lo único que cambia entre repositorios)
├── roadmap.json          ← fuente de verdad
├── roadmap.schema.json   Contrato del roadmap
├── activity.jsonl        Historial de cambios, una línea JSON por evento
├── decisions.md          Decisiones relevantes
├── progress.md           Avance legible por sesiones
├── architecture.md       Cómo funciona este sistema
├── README.md             Este manual
└── dashboard.html        Generado. No editar.
```

## Configurar el sistema para otro proyecto

Edita `project-config.json`. No hay que tocar el código del generador.

```json
{
  "project": { "id": "OPN-NEXUS", "name": "OPN Nexus", "slug": "opn-nexus", "task_prefix": "NEX" }
}
```

Prefijos previstos: `ORC` Oracle, `NEX` Nexus, `RSK` Risk Advisor, `SEN` Event Sentinel,
`COR` Core, `GEN` proyecto genérico. En un repositorio nuevo:

```bash
python scripts/ishtar_memory.py init --project-id OPN-NEXUS --task-prefix NEX
```

## Los dos modos

### Modo consulta

Abre `docs/ishtar_memory/dashboard.html` directamente en el navegador. Funciona sin servidor y sin
conexión, con los datos de la última generación. Puedes buscar, filtrar, expandir, navegar el grafo
y leer o copiar prompts. Los controles de edición aparecen desactivados y no se escribe nada.

### Modo edición

```bash
python scripts/ishtar_memory.py serve
```

Abre `http://127.0.0.1:8765`. El dashboard detecta la API local y activa los controles. Para
cambiar el puerto:

```bash
python scripts/ishtar_memory.py serve --port 9000
```

El servidor escucha solo en `127.0.0.1`, exige token CSRF y valida `Host` y `Origin`.

## Crear tareas

La creación y la modificación estructural se hacen desde el repositorio, no desde el navegador.
Pídeselo al asistente en lenguaje natural:

```text
Añade una tarea raíz para el sistema de alertas.

Añade una subtarea debajo de ORC-ALT-001.

Vamos a trabajar en ORC-ALT-002.

Registra este prompt en ORC-ALT-002 y ejecútalo.

Marca ORC-ALT-002 como en progreso.

Marca ORC-ALT-002 como realizada.

Añade un comentario a ORC-ALT-002.

Actualiza la memoria y regenera el dashboard.
```

O directamente por línea de comandos:

```bash
python scripts/ishtar_memory.py add-task "Sistema de alertas" --group ALT --priority high
```

```bash
python scripts/ishtar_memory.py add-task "Modelo de datos" --group ALT --parent ORC-ALT-001
```

### Cómo se obtiene una ID

El identificador es `PREFIJO-GRUPO-NNN`, por ejemplo `ORC-ALT-001`. El grupo lo eliges con
`--group`; el número es el siguiente libre dentro de ese grupo. Cada tarea y cada subtarea tiene su
propia ID: la posición en el árbol nunca se usa como identificador y mover una tarea la conserva.

```bash
python scripts/ishtar_memory.py move-task ORC-ALT-003 --parent ORC-ALT-002
```

## Cambiar estados

Estados: `pending` (Pendiente), `in_progress` (En progreso), `blocked` (Bloqueada),
`done` (Realizada).

Desde el dashboard en modo edición, cada fila tiene botones para Pendiente, En progreso y Realizada,
y un menú `⋯` para Bloqueada. Desde la línea de comandos:

```bash
python scripts/ishtar_memory.py set-status ORC-ALT-002 in_progress
```

Bloquear exige motivo:

```bash
python scripts/ishtar_memory.py set-status ORC-ALT-002 blocked --blocked-reason "Falta la migración"
```

La decisión final siempre es tuya. Si marcas como realizada una tarea con subtareas pendientes,
criterios sin cumplir, pruebas sin superar, bloqueos activos o sin evidencias, el sistema avisa y
pide un motivo, pero no lo impide:

```bash
python scripts/ishtar_memory.py set-status ORC-ALT-002 done --override-reason "Cerrada por decisión del usuario"
```

Después la tarea muestra el distintivo «Realizada manualmente con elementos pendientes».

El estado de una tarea padre **no** se calcula: se muestra el progreso de sus hijos, pero marcarla
sigue siendo una acción manual.

## Prompts por tarea

Cada tarea guarda sus prompts en `prompt_records`, con ID propio (`ORC-ALT-002-P001`), texto
literal, metadatos e historial de revisiones.

### Añadir

En el dashboard, pulsa `Prompts · N` en la tarea, ve a **Añadir prompt**, rellena título y texto y
guarda. El textarea conserva saltos de línea, Markdown, bloques de código y tabulaciones, muestra
contador de caracteres y avisa antes de cerrar si hay cambios sin guardar.

Desde la línea de comandos:

```bash
python scripts/ishtar_memory.py add-prompt ORC-ALT-002 --title "Implementación inicial" --file prompt.txt
```

También puedes pedírselo al asistente: «Guarda este prompt en ORC-ALT-002».

### Revisar

Al editar un prompt existente, el contenido anterior se guarda en `revision_history` con su motivo
de cambio. Nunca se sobrescribe una versión sin conservarla.

### Archivar

Los prompts no se eliminan desde la interfaz: se archivan. Siguen en el roadmap con `archived_at` y
se pueden mostrar con el filtro «Mostrar prompts archivados». Sus IDs no se reutilizan.

### Consultar

La pestaña **Prompts** reúne los prompts de todas las tareas, con filtros por tarea, texto,
etiqueta, modelo, fecha y archivado. Desde ahí se abre el mismo modal de detalle, con copia al
portapapeles y versiones anteriores.

## Comandos

```bash
python scripts/ishtar_memory.py validate    # valida configuración, árbol, prompts y actividad
python scripts/ishtar_memory.py generate    # regenera dashboard.html
python scripts/ishtar_memory.py check       # valida y comprueba consistencia sin reemplazar
python scripts/ishtar_memory.py serve       # modo edición local
```

Auxiliares: `init`, `add-task`, `move-task`, `set-status`, `add-prompt`, `migrate`.

Pruebas:

```bash
python3 tests/test_ishtar_memory.py
```

## Qué ocurre si abro el HTML directamente

Se abre en modo consulta con los datos incrustados en la última generación. Es correcto y no
requiere servidor, pero si alguien ha cambiado el roadmap desde entonces sin regenerar, verás datos
antiguos. `check` detecta esa desincronización.

No se usa `localStorage` como fuente de verdad: lo que ves proviene siempre de los archivos.

## Conflictos de revisión

Cada escritura envía `expected_revision`. Si el proyecto ha cambiado entretanto, la API responde
`REVISION_CONFLICT` y el dashboard recarga los datos sin sobrescribir el cambio más reciente. Repite
tu acción sobre el estado actualizado.

## Recuperación de errores

- La escritura es atómica: si algo falla, se conserva el último `roadmap.json` válido.
- Si la validación no pasa, `generate` **no** sobrescribe el HTML anterior.
- Ante un roadmap corrupto, restaura la última versión con `git checkout` solo si no tienes cambios
  sin confirmar; en caso contrario, corrige el JSON a mano y ejecuta `validate`.
- `migrate --apply` deja copia de seguridad en `docs/ishtar_memory/migration-backup/`.

## Migración desde la versión anterior

Si el repositorio contiene `docs/development/oracle-roadmap.json`, puedes importarlo:

```bash
python scripts/ishtar_memory.py migrate
```

Simula la conversión y comunica cuántos módulos y funcionalidades se convertirían. Para aplicarla:

```bash
python scripts/ishtar_memory.py migrate --apply
```

Los módulos pasan a tareas raíz y las funcionalidades a subtareas, conservando IDs, comentarios,
evidencias, dependencias y fechas. Los estados antiguos se convierten así:

```text
idea, proposed, needs_definition, approved, ready, deferred, rejected → pending
in_progress, under_review                                             → in_progress
blocked                                                               → blocked
implemented, validated, deployed                                      → done
```

Los archivos anteriores no se borran ni se sobrescriben.

## Qué no debe guardarse

Nunca registres en el roadmap, en los prompts ni en la actividad: contraseñas, tokens, claves
privadas, credenciales, secretos ni datos personales innecesarios. El dashboard se genera dentro del
repositorio y puede acabar en un commit.
