# ADR 0001 — Backend autoritativo Flask

- **Estado:** accepted
- **Fecha:** 2026-07-10

## Contexto

El repositorio real es un prototipo Next.js sin backend. `main.py` es un ejemplo de PyCharm, no una aplicación. La documentación antigua menciona FastAPI como integración futura, pero no existe código ni dependencia que obligue a conservar esa elección. El producto requiere identidad, aislamiento multi-tenant, persistencia, auditoría, integraciones y trabajos asíncronos autoritativos.

## Decisión

Construir el backend de producto en Python con Flask, application factory y blueprints bajo `apps/api/src/opn_oracle`. Toda API productiva se publicará bajo `/api/v1` y se servirá con Gunicorn. PostgreSQL será la fuente de verdad.

Next.js seguirá siendo frontend y motor de renderizado; no albergará lógica de dominio autoritativa.

## Alternativas consideradas

- **FastAPI:** descartado por decisión técnica vinculante, aunque aparezca en el README de la demo.
- **Route Handlers/Server Actions de Next.js:** descartados como backend de negocio por crear un segundo plano autoritativo.
- **Aplicación Flask monolítica en `main.py`:** descartada por impedir modularidad, tests y configuración segura.

## Consecuencias y riesgos

- Se añade un runtime Python y una cadena de calidad independiente.
- OpenAPI deberá generarse desde Flask y será el contrato con el frontend.
- La documentación de la demo que menciona FastAPI debe actualizarse al integrar la API.
- Hay que elegir y fijar una versión Python soportada; la 3.9.6 observada localmente no se adopta automáticamente como versión objetivo.

## Cuestiones pendientes

- Elegir herramienta de dependencias/lock de Python y versión mínima en la fase de fundación.
- Elegir librería de schemas/OpenAPI compatible con Flask.
- Definir política de compatibilidad y deprecación de `/api/v1`.
