# Encargo de tratamiento (DPA) · borrador art. 28 RGPD

> **BORRADOR · requiere revisión jurídica y validación del despliegue antes de enviar o firmar**

| Campo | Valor |
|---|---|
| Versión | `0.1.0-g21` |
| Owner | OPN · cumplimiento comercial (borrador producto) |
| Estado | `borrador interno · no contractual · no firmable sin abogado` |
| Fecha | 2026-08-06 |
| Base de código inventariada | `d472aeb7ff62a1fb8fff69086c63752fc37e5b39` |

## Aviso importante

Este texto es una **plantilla de trabajo** para que legal de OPN y del cliente la revisen. No es
asesoramiento jurídico definitivo. Las citas al RGPD se usan como **checklist de revisión**, no
como transcripción normativa. Los campos `[POR CONFIRMAR]` deben rellenarse con datos del
despliegue y de la entidad contratante antes de cualquier envío formal o firma.

## 1. Partes

| Rol contractual propuesto | Parte | Identificación |
|---|---|---|
| **Responsable del tratamiento** | Cliente (organización usuaria de OPN Oracle) | `[POR CONFIRMAR: razón social, NIF, domicilio, contacto privacidad]` |
| **Encargado del tratamiento** | Prestador del servicio OPN Oracle | `[POR CONFIRMAR: razón social OPN, NIF, domicilio, contacto]` |
| **Contacto de privacidad del encargado** | `[POR CONFIRMAR]` | Puede ser DPO u otro contacto; **DPO formal no consta en el repositorio** |

En escenarios de **datos de terceros** obtenidos de fuentes públicas para inteligencia, la
calificación de roles puede ser más compleja (responsable autónomo / corresponsabilidad). Ver
[BASE_JURIDICA_INVESTIGACIONES.md](./BASE_JURIDICA_INVESTIGACIONES.md). Este DPA se centra en el
encargo clásico de datos del cliente en la plataforma SaaS/self-hosted gestionada.

## 2. Objeto y duración

1. **Objeto:** el Encargado trata datos personales por cuenta del Responsable para prestar el
   servicio de software OPN Oracle (inteligencia estratégica multi-tenant centrada en expedientes),
   incluyendo autenticación, administración de usuarios, almacenamiento de contenido del tenant,
   notificaciones, exportaciones, auditoría y, si se habilitan, documentos e IA.
2. **Duración:** desde la fecha de firma / inicio de servicio hasta la terminación del contrato
   principal + periodo de devolución/supresión acordado (`[POR CONFIRMAR: plazo]`).
3. **Naturaleza:** tratamiento automatizado en sistemas de aplicación, base de datos, colas y
   almacenamiento de objetos según configuración.
4. **Finalidad del encargo:** únicamente las necesarias para la prestación del servicio y las
   instrucciones documentadas del Responsable. **Prohibido** el uso de datos del cliente para
   entrenar modelos propios del Encargado salvo instrucción escrita y base legal aparte
   (`[POR CONFIRMAR política comercial]`).

## 3. Categorías de interesados y datos (orientativo)

Detalle ampliado en [REGISTRO_ACTIVIDADES_TRATAMIENTO.md](./REGISTRO_ACTIVIDADES_TRATAMIENTO.md).

| Interesados (típicos) | Datos (ejemplos verificables en modelo de producto) |
|---|---|
| Usuarios del Responsable | Email, nombre visible, hash de contraseña, estado, sesiones, IP/UA de sesión, roles |
| Personas de contacto / invitados | Email de invitación, tokens de invitación (hash) |
| Personas físicas referenciadas en investigaciones o fuentes públicas | Nombres, cargos, vínculos societarios u otros datos que el tenant incorpore o que lleguen vía fuentes configuradas |
| Firmantes/interlocutores en documentos subidos (si documentos habilitados) | Contenido de ficheros y metadatos |

**Datos especiales (art. 9):** el producto no está diseñado como sistema de categorías especiales.
El Responsable se compromete a no cargar deliberadamente datos del art. 9 salvo acuerdo escrito y
medidas adicionales (`[POR CONFIRMAR]`).

## 4. Instrucciones del Responsable

El Encargado solo tratará datos conforme a:

1. El contrato principal y este DPA.
2. La configuración del tenant y permisos que el Responsable administre en la aplicación.
3. Instrucciones escritas adicionales del Responsable (ticket/email formal `[canal POR CONFIRMAR]`).

El Encargado informará si una instrucción es, a su juicio, contraria al RGPD u otra norma
aplicable (checklist art. 28.3).

## 5. Confidencialidad

1. Personas autorizadas del Encargado sujetas a deber de confidencialidad.
2. Acceso operativo al tenant del cliente limitado a personal con necesidad legítima de soporte,
   con registro cuando el producto lo permita (p. ej. superadmin con motivo y auditoría — capacidad
   descrita en [../security/MULTITENANCY.md](../security/MULTITENANCY.md)).
3. Prohibición de usar datos del cliente para fines propios ajenos al servicio.

## 6. Medidas de seguridad (art. 32 — checklist, no certificación)

El Encargado aplicará medidas **técnicas y organizativas** acordes al riesgo. Estado honestamente
documentado en [MATRIZ_CONTROLES_Y_ALEGACIONES.md](./MATRIZ_CONTROLES_Y_ALEGACIONES.md).

**Implementadas como capacidad de producto (evidencia en repo), sin afirmar certificación:**

- Aislamiento multi-tenant (RLS + scoping).
- RBAC por tenant.
- Hash de contraseñas Argon2id.
- Sesión cookie HttpOnly + CSRF.
- Auditoría de eventos.
- Cifrado AES-256-GCM de credenciales de integración.
- Scripts de backup lógico y restore aislado; off-host opcional.

**No afirmables como presentes sin evidencia de despliegue o implementación:**

- MFA, SSO/SAML/OIDC.
- Cifrado en reposo del volumen del host.
- PITR.
- Residencia UE operativa.
- ISO/SOC/ENS.
- SLA de disponibilidad o de notificación de incidentes (salvo contrato).

## 7. Subencargados

1. Lista orientativa y estado de confirmación: [SUBENCARGADOS_Y_RESIDENCIA.md](./SUBENCARGADOS_Y_RESIDENCIA.md).
2. El Responsable autoriza con carácter general a los subencargados listados como **confirmados**
   en el anexo vigente; los marcados `por confirmar` o `configurable no activado` no se dan por
   autorizados hasta actualización del anexo.
3. **Notificación de cambios:** el Encargado notificará con antelación razonable
   (`[POR CONFIRMAR: p. ej. 15/30 días]`) la incorporación o sustitución de subencargados que
   traten datos del cliente, con derecho de oposición según se negocie.
4. El Encargado impondrá obligaciones equivalentes en lo esencial a los subencargados.

## 8. Asistencia al Responsable

El Encargado asistirá, en la medida de lo razonable y de las capacidades del producto, en:

| Derecho / obligación | Asistencia prevista (producto / proceso) | Limitación |
|---|---|---|
| Acceso / portabilidad | Exports CSV allowlisted; extracción operativa adicional si se acuerda | No hay export «todo el tenant» verificado como un solo artefacto |
| Rectificación | El Responsable edita en la app según permisos | Datos de fuentes públicas: ver política de investigaciones |
| Supresión / oposición | Procedimiento de soporte + capacidades de soft-delete/purge parciales | Erasure total de tenant no automatizado de punta a punta |
| Limitación | Legal hold en documentos (si módulo activo); otras medidas operativas | `[POR CONFIRMAR procedimiento]` |
| DPIA / consultas AEPD | Información razonable sobre el sistema | No sustituye la DPIA del Responsable |
| Brechas | Proceso de incidentes documentado en ops | Plazo contractual de aviso `[POR CONFIRMAR]`; no hay SLA genérico en repo |

## 9. Notificación de violaciones de seguridad

1. El Encargado notificará al Responsable, sin dilación indebida y en el canal
   `[POR CONFIRMAR]`, las violaciones de seguridad que afecten a datos del cliente de las que tenga
   conocimiento.
2. Contenido mínimo orientativo: naturaleza, categorías y número aproximado de interesados/registros
   afectados si se conocen, consecuencias probables, medidas adoptadas o propuestas, punto de
   contacto.
3. Runbooks internos de referencia (no contractuales por sí solos):
   [../operations/INCIDENT_RESPONSE.md](../operations/INCIDENT_RESPONSE.md).

## 10. Devolución y supresión al terminar

Al finalizar el encargo, a elección del Responsable y según lo pactado:

1. **Devolución:** exportación de datasets disponibles + entrega operativa de copias acordadas.
2. **Supresión:** borrado de datos del tenant en sistemas activos y, en la medida practicable,
   de backups según la política de retención de copias.
3. **Certificación de borrado:** `[POR CONFIRMAR formato y responsable]`.

**Brecha documentada con honestidad:** no existe en el repositorio un flujo único verificado de
«supresión total de tenant + purga de backups + certificación» como producto cerrado. Debe
acordarse operativamente. Detalle: [PRIVACIDAD_RETENCION_Y_SUPRESION.md](./PRIVACIDAD_RETENCION_Y_SUPRESION.md).

## 11. Auditorías

1. El Responsable podrá auditar el cumplimiento de este DPA con preaviso razonable
   (`[POR CONFIRMAR]`), en horario laboral, sin interrumpir indebidamente el servicio y bajo NDA.
2. Alternativas: cuestionarios, evidencias de configuración (sin secretos), revisión de este
   paquete y de la matriz de controles.
3. No se concede acceso a datos de otros clientes ni a secretos.

## 12. Transferencias internacionales

1. Si algún subencargado o componente implica transferencia fuera del EEE, se documentará en el
   anexo de subencargados con mecanismo (cláusulas tipo, decisión de adecuación, etc.)
   `[POR CONFIRMAR]`.
2. **Este turno no confirma** transferencias operativas activas: varios componentes son
   autoalojados o configurables.

## 13. Responsabilidad y prelación

1. Este DPA forma parte del contrato de servicio.
2. En caso de conflicto sobre protección de datos, prevalece este DPA salvo norma imperativa.
3. Limitaciones de responsabilidad: según contrato principal `[POR CONFIRMAR]`.

## 14. Derecho aplicable y fuero

`[POR CONFIRMAR: p. ej. legislación española y juzgados de …]`

## Anexos

| Anexo | Contenido | Documento |
|---|---|---|
| A | Descripción de tratamientos | [REGISTRO_ACTIVIDADES_TRATAMIENTO.md](./REGISTRO_ACTIVIDADES_TRATAMIENTO.md) |
| B | Subencargados y residencia | [SUBENCARGADOS_Y_RESIDENCIA.md](./SUBENCARGADOS_Y_RESIDENCIA.md) |
| C | Retención y supresión | [PRIVACIDAD_RETENCION_Y_SUPRESION.md](./PRIVACIDAD_RETENCION_Y_SUPRESION.md) |
| D | Controles y alegaciones | [MATRIZ_CONTROLES_Y_ALEGACIONES.md](./MATRIZ_CONTROLES_Y_ALEGACIONES.md) |
| E | Readiness / límites | [PRODUCTION_READINESS_STATEMENT.md](./PRODUCTION_READINESS_STATEMENT.md) |

## Firmas (no ejecutar sobre este borrador)

| | Responsable | Encargado |
|---|---|---|
| Nombre | | |
| Cargo | | |
| Fecha | | |
| Firma | **NO FIRMAR este borrador G-21** | **NO FIRMAR este borrador G-21** |
