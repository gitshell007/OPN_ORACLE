# Arquitectura de Ishtar Memory

Describe cómo funciona el propio sistema de planificación. No documenta la arquitectura de negocio
del proyecto, que vive en `docs/architecture/`. Se muestra en la pestaña **Arquitectura**.

## Piezas

```text
docs/ishtar_memory/
├── project-config.json   Identidad del proyecto. Único punto de acoplamiento.
├── roadmap.json          Fuente única de verdad: árbol de tareas y prompts.
├── roadmap.schema.json   Contrato del roadmap.
├── activity.jsonl        Registro cronológico, una línea JSON por evento.
├── decisions.md          Decisiones relevantes.
├── progress.md           Avance legible por sesiones.
├── architecture.md       Este documento.
├── README.md             Manual de uso.
└── dashboard.html        Artefacto generado. Nunca se edita a mano.

scripts/ishtar_memory.py  Validador, generador, servidor local y API.
tests/test_ishtar_memory.py  Pruebas del sistema.
```

## Flujo de datos

```text
roadmap.json ──▶ validación ──▶ métricas ──▶ dashboard.html
     ▲                                            │
     │                                            ▼
  API local ◀──── modo edición ◀──── navegador (127.0.0.1)
     │
     └──▶ activity.jsonl
```

El HTML nunca es la fuente de verdad. Cada escritura sigue el mismo orden: validar la petición,
comprobar la revisión esperada, modificar la estructura en memoria, escribir el JSON de forma
atómica, registrar la actividad, regenerar el HTML y devolver el nuevo estado al navegador.

## Dos modos

- **Consulta.** El HTML se abre directamente desde el sistema de archivos. Funciona sin servidor y
  sin conexión, con los datos incrustados en la última generación. Los controles de edición
  aparecen desactivados y no se escribe nada en el repositorio.
- **Edición.** `python scripts/ishtar_memory.py serve` levanta un servidor en `127.0.0.1` que sirve
  el dashboard y expone la API local. El navegador detecta la API en `/api/bootstrap` y activa los
  controles.

No se usa `localStorage` como fuente de verdad: el estado canónico permanece siempre en los
archivos del repositorio.

## Concurrencia y consistencia

- `state_revision` se incrementa tras cada escritura válida.
- Toda operación de escritura envía `expected_revision`; si no coincide, la API responde 409 con
  `REVISION_CONFLICT` y el navegador recarga los datos sin sobrescribir cambios más recientes.
- Un bloqueo de archivo serializa las escrituras entre el servidor y la línea de comandos.
- La escritura es atómica: archivo temporal, `fsync` y reemplazo. Ante cualquier error se conserva
  el último JSON y el último HTML válidos.

## Seguridad del servidor local

- Escucha únicamente en `127.0.0.1` y valida el encabezado `Host`.
- Valida `Origin` y `Referer`; no habilita CORS abierto.
- Exige un token CSRF generado al iniciar y entregado en `/api/bootstrap`.
- Limita el tamaño de las peticiones y valida tipos y longitudes.
- No sirve rutas arbitrarias del sistema de archivos: solo el dashboard generado.
- No ejecuta prompts ni comandos del sistema.
- Todo el contenido se pinta en el navegador con nodos de texto, nunca interpretando HTML.

## Modelo de tareas

Cada nodo es recursivo y tiene identificador propio. `parent_id` debe coincidir con el nodo que lo
contiene; si no coincide, la validación falla y el sistema no corrige la incoherencia en silencio.
Las dependencias son distintas de la relación padre-hijo. Mover una tarea conserva su ID y todos
sus descendientes. El estado de una tarea padre nunca se deriva automáticamente: se calcula y se
muestra el progreso de sus hijos, pero la decisión sigue siendo manual.
