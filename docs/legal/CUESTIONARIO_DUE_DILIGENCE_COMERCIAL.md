# Cuestionario de due diligence comercial · respuestas reutilizables

> **BORRADOR · requiere revisión jurídica y validación del despliegue antes de enviar o firmar**

| Campo | Valor |
|---|---|
| Versión | `0.1.0-g21` |
| Owner | OPN · cumplimiento comercial (borrador producto) |
| Estado | `borrador interno · no contractual` |
| Fecha | 2026-08-06 |
| Base de código | `d472aeb7ff62a1fb8fff69086c63752fc37e5b39` |

## Cómo usar este cuestionario

- Respuestas cortas: **sí / no / parcial / por confirmar**.
- Cada respuesta enlaza evidencia de este paquete o del repo.
- Las preguntas marcadas ⚙️ **requieren datos del despliegue** (no inventar).

---

## A. Producto y roles

| # | Pregunta | Respuesta | Evidencia | Notas |
|---|---|---|---|---|
| A1 | ¿Es multi-tenant? | **sí** | [../security/MULTITENANCY.md](../security/MULTITENANCY.md) | Aislamiento por tenant en app + RLS |
| A2 | ¿Hay RBAC? | **sí** | `platform/rbac.py` | Roles de sistema por tenant |
| A3 | ¿Existe superadmin de plataforma? | **sí** (capacidad) | MULTITENANCY | Acceso excepcional con motivo/auditoría; no «ver todos los tenants a la vez» por RLS abierta |
| A4 | ¿SSO/SAML/OIDC? | **no** | Matriz C07 | Roadmap gated por contrato |
| A5 | ¿MFA? | **no** | Matriz C06 | No implementar en este turno |

## B. Datos tratados

| # | Pregunta | Respuesta | Evidencia | Notas |
|---|---|---|---|---|
| B1 | ¿Qué datos de usuarios tratáis? | **sí** (describible) | [REGISTRO_ACTIVIDADES_TRATAMIENTO.md](./REGISTRO_ACTIVIDADES_TRATAMIENTO.md) T1 | Email, nombre, hash contraseña, sesión, IP/UA |
| B2 | ¿Tratáis datos de negocio del cliente (expedientes)? | **sí** | RAT T3 | Contenido del tenant |
| B3 | ¿Tratáis datos de personas en investigaciones? | **parcial** | [BASE_JURIDICA_INVESTIGACIONES.md](./BASE_JURIDICA_INVESTIGACIONES.md) | Depende del uso del cliente y fuentes |
| B4 | ¿Categorías especiales art. 9 por diseño? | **no** | DPA borrador | Cliente no debe cargarlas sin acuerdo |
| B5 | ¿Dónde está el inventario de tratamientos? | **sí** | RAT | Borrador orientativo |

## C. Finalidades y base jurídica

| # | Pregunta | Respuesta | Evidencia | Notas |
|---|---|---|---|---|
| C1 | ¿Finalidad del servicio? | **sí** | README del paquete / DPA | Prestación de software de inteligencia estratégica |
| C2 | ¿Base jurídica cerrada y única para todos los clientes? | **no** | BASE_JURIDICA | Cada responsable debe formalizar la suya |
| C3 | ¿Usáis datos del cliente para entrenar modelos propios? | **por confirmar** (política comercial) | DPA §2 | Diseño: no sin instrucción; confirmar contrato |
| C4 | ¿IA activa por defecto? | **no** | [../operations/AI_RUNTIME.md](../operations/AI_RUNTIME.md) | Fail-closed |

## D. Accesos y seguridad

| # | Pregunta | Respuesta | Evidencia | Notas |
|---|---|---|---|---|
| D1 | ¿Cifrado en tránsito? | **por confirmar** ⚙️ | Matriz C08; TLS runbook | Diseñado; activo = despliegue |
| D2 | ¿Cifrado en reposo del disco? | **por confirmar** ⚙️ | Matriz C09 | No afirmar como activo de producto |
| D3 | ¿Credenciales de integración cifradas en BD? | **sí** | Matriz C10 | AES-256-GCM |
| D4 | ¿RLS? | **sí** | MULTITENANCY | Capacidad de producto |
| D5 | ¿Logs de auditoría? | **sí** | Matriz C03 | Append-oriented |
| D6 | ¿Penetration test / certificación ISO? | **no** (cert) / **parcial** (controles) | Matriz C20; readiness | Sin ISO/SOC/ENS en repo |
| D7 | ¿Plan de incidentes? | **sí** (documentado) | [../operations/INCIDENT_RESPONSE.md](../operations/INCIDENT_RESPONSE.md) | SLA contractual ⚙️ |

## E. Hosting, residencia y terceros

| # | Pregunta | Respuesta | Evidencia | Notas |
|---|---|---|---|---|
| E1 | ¿Residencia UE garantizada por el código? | **no** | [SUBENCARGADOS_Y_RESIDENCIA.md](./SUBENCARGADOS_Y_RESIDENCIA.md) | Confirmar despliegue ⚙️ |
| E2 | ¿Lista de subencargados? | **parcial** | SUBENCARGADOS | Muchos `por confirmar` |
| E3 | ¿Correo vía Microsoft Graph? | **por confirmar** ⚙️ | config `MAIL_BACKEND` | Soportado, no afirmar activo |
| E4 | ¿Subprocesador de IA cloud? | **por confirmar** ⚙️ | AI_RUNTIME | Primario documentado local vía Signal/Ollama |
| E5 | ¿Signal Avanza interviene? | **parcial** | contrato Signal en docs | Integración real según modo/config |

## F. Retención, export y borrado

| # | Pregunta | Respuesta | Evidencia | Notas |
|---|---|---|---|---|
| F1 | ¿Podéis exportar datos? | **parcial** | exports.py | CSV allowlisted + procedimiento |
| F2 | ¿TTL de exports? | **sí** | default 24 h config | Configurable |
| F3 | ¿Retención de documentos? | **parcial** | documents models | Si feature on |
| F4 | ¿Borrado total al fin de contrato automatizado? | **no** | [PRIVACIDAD_RETENCION_Y_SUPRESION.md](./PRIVACIDAD_RETENCION_Y_SUPRESION.md) | Procedimiento a pactar |
| F5 | ¿Backups? | **parcial** | BACKUP_RESTORE | Scripts sí; off-host ⚙️ |
| F6 | ¿PITR? | **no** | Matriz C14 | |

## G. Readiness y alcance comercial

| # | Pregunta | Respuesta | Evidencia | Notas |
|---|---|---|---|---|
| G1 | ¿Declaráis production-ready global? | **no** | [PRODUCTION_READINESS_STATEMENT.md](./PRODUCTION_READINESS_STATEMENT.md) | Veredicto por alcance |
| G2 | ¿Hay DPA firmable en este paquete? | **no** (solo borrador) | [DPA_BORRADOR.md](./DPA_BORRADOR.md) | Requiere abogado |
| G3 | ¿ENS / ISO / SOC? | **no** | Matriz C20 | |
| G4 | ¿Piloto con datos no críticos posible? | **parcial** | PRODUCTION_READINESS | Condicionado a límites y contrato |

---

## Respuestas en una frase (elevator due diligence)

1. **Qué datos:** cuentas de usuario, contenido del tenant (expedientes) y, si el cliente investiga personas, datos de fuentes/manuales; detalle en el RAT.
2. **Por qué:** prestar el software de inteligencia estratégica y operar seguridad/auditoría del servicio.
3. **Quién accede:** usuarios del tenant según RBAC; operadores del prestador con necesidad; superadmin excepcional auditado.
4. **Dónde están:** **por confirmar en el despliegue del servicio ofrecido**; no se afirma residencia UE genérica aquí.
5. **Cuánto se conservan:** sesiones y exports con plazos de producto; documentos con política si el módulo está activo; negocio/auditoría/backups **a pactar / confirmar**.
6. **Cómo se devuelven/borran:** exports CSV + procedimiento de fin de contrato; **no** hay erasure total automatizado verificado.
7. **Qué terceros:** hosting, PostgreSQL/Redis autoalojados en diseño, Signal, correo (SMTP/Graph), storage/IA opcionales — ver tabla de subencargados.
8. **Qué falta confirmar:** región, subencargados activos, TLS/off-host reales, DPO, plazos contractuales de incidentes y borrado, activación de documentos/IA/Signal HTTP.

## Preguntas que el comercial debe devolver al prospecto / a ops (⚙️)

1. ¿Región y proveedor de hosting del entorno propuesto?
2. ¿Correo Graph o SMTP y contrato del proveedor?
3. ¿Documentos e IA habilitados en el alcance del piloto?
4. ¿Destino de backup off-host y retención real?
5. ¿Contacto de privacidad/DPO de ambas partes?
6. ¿Plazo de preaviso de subencargados y de notificación de brechas deseado por el cliente?

## Enlaces del paquete

- [README.md](./README.md)
- [MATRIZ_CONTROLES_Y_ALEGACIONES.md](./MATRIZ_CONTROLES_Y_ALEGACIONES.md)
- [PRODUCTION_READINESS_STATEMENT.md](./PRODUCTION_READINESS_STATEMENT.md)
