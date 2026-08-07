# Declaración de readiness de producción · OPN Oracle

> **BORRADOR · requiere revisión jurídica y validación del despliegue antes de enviar o firmar**

| Campo | Valor |
|---|---|
| Versión | `0.1.0-g21` |
| Owner | OPN · cumplimiento comercial (borrador producto) |
| Estado | `borrador interno · no contractual` |
| Fecha de esta declaración | 2026-08-06 |
| Base de código | `044e35a8ef696faf53d3d108387d0cbed06a99dc` |

## 1. Propósito

Este documento **encuadra** los veredictos técnicos previos de «no production ready» / `NO-GO`
con fecha, alcance y evidencia. No los oculta ni los convierte en un sello de aptitud global.

## 2. Veredictos previos vigentes (no retirados)

| Fuente | Fecha | Veredicto | Alcance | ¿Sigue vigente en su ámbito? |
|---|---|---|---|---|
| [../security/READINESS_REPORT.md](../security/READINESS_REPORT.md) | 2026-07-11 | **NO production ready**; apto para iniciar auditoría read-only de infra | App local full-stack hasta fase 13; no audita servidor remoto de entonces | **Sí** como referencia de gates de release e infra pendientes, salvo evidencia de cierre documentada en despliegue |
| [../releases/v0.1.0-rc.1/GO_NO_GO.md](../releases/v0.1.0-rc.1/GO_NO_GO.md) | release `v0.1.0-rc.1` | **`NO-GO`** | UAT incompleto, CI/imágenes, off-host, gates documentos/Signal/IA | **Sí** para ese release; un release posterior solo cambia el veredicto con evidencia propia |

Gates de release explícitos del informe de readiness (no rebajados por estar fuera del entorno local):

- F13-11: sandbox parser, S3 y ClamAV productivos no verificados (bloquea documentos/release).
- F13-12: backup/restore productivo medido incompleto en el momento del informe.
- F13-13: Trivy/SBOM, ZAP staging, TLS/cert/puertos y carga representativa no ejecutados entonces.

El repositorio **sí** contiene después scripts y runbooks de backup local, restore aislado y
pipeline off-host opcional ([../operations/BACKUP_RESTORE.md](../operations/BACKUP_RESTORE.md),
[../operations/P2_OPS_READINESS.md](../operations/P2_OPS_READINESS.md)). Eso demuestra **capacidad
de producto/ops en código**, no un RPO/RTO contractual medido en un despliegue concreto sin
validación de despliegue.

## 3. Veredicto por alcance (2026-08-06)

| Alcance | Veredicto | Justificación honesta |
|---|---|---|
| **Desarrollo / demo / piloto controlado** con datos no críticos y fail-closed de features | **Condicionalmente viable** si el operador acepta límites y no promete controles no verificados | Producto multi-tenant con auth, RLS, auditoría y exports implementados; varios módulos gated |
| **Uso productivo estable con datos reales de cliente y obligaciones contractuales fuertes** | **No declarado apto de forma global** en este paquete | Faltan confirmaciones de despliegue (residencia, off-host, TLS activo, subencargados activos), UAT/release gates y paquete contractual firmado |
| **Enterprise con SSO/ENS/SLA formal** | **No disponible como presente** | SSO/SAML/OIDC y ENS no implementados; roadmap gated por contrato (ver matriz) |
| **Documentos productivos (`DOCUMENTS_ENABLED`)** | **Parcial / gated** | Código y retención existen; producción estable exige S3+ClamAV y gates de release |
| **IA real** | **Parcial / configurable** | Por defecto deshabilitada; modo gobernado `signal` documentado; cloud secundario no forzado desde Oracle |
| **Cumplimiento documental comercial** | **Borrador disponible (este paquete)** | Suficiente para iniciar due diligence; insuficiente para firmar sin abogado y sin datos de despliegue |

### Frase autorizada (ventas / pre-sales)

> «OPN Oracle dispone de controles de producto verificables en repositorio (aislamiento multi-tenant,
> RBAC, auditoría, autenticación con hash Argon2id y política mínima de longitud —MFA no disponible—,
> exports con caducidad). La aptitud para un entorno
> productivo concreto depende del despliegue, de los features habilitados y del contrato. No
> afirmamos certificación ISO/SOC/ENS ni readiness global de producción sin evidencia de ese
> entorno.»

### Frases prohibidas

- «Estamos listos para producción» / «production ready» sin calificar alcance y fecha.
- «Cumplimos plenamente el RGPD / ENS / ISO».
- «Todos los datos residen en la UE» sin evidencia de despliegue.
- «MFA disponible», «SSO disponible», «PITR activo», «cifrado en reposo activo» como hechos
  generales del producto sin el estado de la matriz.

## 4. Limitaciones de este turno (G-21)

- No se ha consultado producción, secretos, hostnames privados ni datos de clientes.
- No se ha implementado seguridad técnica nueva (MFA, SSO, cifrado de disco, etc.).
- No se ha firmado ni negociado ningún DPA real.
- Coste de este trabajo documental: **0 €** (sin LLM de pago, sin red de producción, sin deploy).

## 5. Condiciones para reconsiderar un veredicto de alcance

1. Release con GO documentado y SHA reproducible.
2. Evidencia de despliegue: región/hosting, TLS, backup off-host con restore, subencargados activos.
3. Features habilitados alineados con el contrato (documentos, Signal HTTP, IA).
4. Revisión jurídica del DPA y del RAT.
5. Cierre o aceptación formal de gates abiertos del informe de readiness aplicables al alcance.

## 6. Relación con el resto del paquete

- Controles y lenguaje: [MATRIZ_CONTROLES_Y_ALEGACIONES.md](./MATRIZ_CONTROLES_Y_ALEGACIONES.md)
- Q&A corto: [CUESTIONARIO_DUE_DILIGENCE_COMERCIAL.md](./CUESTIONARIO_DUE_DILIGENCE_COMERCIAL.md)
- Índice: [README.md](./README.md)
