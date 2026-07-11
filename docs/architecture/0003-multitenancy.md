# ADR 0003 — Multi-tenancy desde el modelo y los repositorios

- **Estado:** accepted
- **Fecha:** 2026-07-10

## Contexto

Los tipos y fixtures actuales son de una demo de un solo workspace y no incluyen `tenant_id`. El producto necesita servir a varias organizaciones y evitar lectura, modificación, enumeración o inferencia cruzada. Añadir aislamiento después de crear las tablas produciría migraciones y controles incompletos.

## Decisión

Todo recurso de negocio pertenecerá a un tenant salvo que esté clasificado explícitamente como global de plataforma. El `tenant_id` se derivará de la sesión y membership validadas, nunca de un valor confiado al cliente.

El aislamiento se aplicará centralmente en repositorios y servicios Flask, con UUIDs, constraints e índices por tenant. PostgreSQL RLS se incorporará como defensa en profundidad cuando el modelo y el contexto transaccional estén preparados. Cada módulo tendrá tests negativos de IDOR y aislamiento.

El acceso de `platform_super_admin` a datos privados requerirá tenant objetivo, permiso, motivo y evento de auditoría.

## Alternativas consideradas

- **Una base de datos por tenant:** no seleccionada inicialmente por coste operacional; podrá evaluarse para requisitos regulatorios concretos.
- **Un schema PostgreSQL por tenant:** no seleccionado por complejidad de migraciones y conexiones.
- **Filtrado ad hoc en rutas:** descartado por ser fácil de omitir y difícil de probar.
- **Confiar únicamente en RLS:** descartado; RLS complementa, no sustituye, la autorización de aplicación.

## Consecuencias y riesgos

- Todas las tablas, repositorios, cachés, jobs y claves de idempotencia deberán incluir contexto de tenant.
- Los DTO de demo no pueden trasladarse directamente a modelos ORM.
- Una sesión de superadmin necesita UX y auditoría diferenciadas.
- Una configuración incorrecta de RLS o del pool podría conservar contexto entre peticiones; habrá tests específicos.

## Cuestiones pendientes

- Definir si `Workspace` será obligatorio o permitirá un workspace inicial implícito.
- Diseñar el mecanismo seguro para establecer y limpiar contexto RLS por transacción.
- Definir requisitos de residencia/aislamiento reforzado para clientes regulados.
