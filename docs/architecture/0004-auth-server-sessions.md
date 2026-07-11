# ADR 0004 — Autenticación con sesiones de servidor

- **Estado:** accepted
- **Fecha:** 2026-07-10

## Contexto

La demo no tiene login. `localStorage` se usa solo para preferencias y estado sintético, pero no es adecuado para credenciales. El producto necesita revocación inmediata, sesiones visibles, CSRF, fresh login y auditoría multi-tenant.

## Decisión

Usar sesión opaca server-side en Flask, con identidad mediante Flask-Login y datos de sesión en Redis. La cookie será `HttpOnly`, `Secure` en producción y `SameSite=Lax` salvo excepción documentada. Las mutaciones requerirán CSRF. Las contraseñas usarán Argon2id.

Se mantendrá una entidad durable `UserSession` para listar y revocar sesiones. El ID de sesión rotará tras login, elevación y cambios sensibles. El frontend enviará cookies con `credentials: include` y el token CSRF por el canal definido por la API.

## Alternativas consideradas

- **JWT o tokens en `localStorage`:** descartados por exposición a XSS y revocación más compleja.
- **Cookies JWT stateless:** descartadas; no satisfacen por sí solas revocación y control de sesiones.
- **Sesiones de NextAuth/Auth.js:** descartadas como autoridad por situar identidad en Node.
- **Sesión solo en memoria de Flask:** descartada por no escalar ni sobrevivir reinicios.

## Consecuencias y riesgos

- Redis es dependencia de disponibilidad para sesiones, pero no fuente de datos de negocio.
- CSRF debe cubrir todos los métodos mutables y convivir con login anti-enumeración/rate limit.
- Se requieren timeouts inactivo y absoluto, logout actual/all y fresh login.
- XSS sigue siendo relevante aunque la cookie sea `HttpOnly`; se necesita CSP y sanitización.

## Cuestiones pendientes

- Concretar timeouts, límite de sesiones y política remember-me.
- Elegir mecanismo CSRF exacto y contrato de bootstrap/renovación para el cliente.
- Definir proveedor SMTP y flujos de invitación/reset antes de activarlos.
