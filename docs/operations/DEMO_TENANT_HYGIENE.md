# Higiene del tenant de demo

Checklist operativa para dejar el tenant de demostración de **Oracle Dev** presentable.
El procedimiento es reversible: archiva expedientes y desactiva vigilancias, pero no borra filas.

## Qué hace

1. Archiva expedientes cuyo título contiene marcadores de prueba (`AUDIT-TEST`, `Playwright`,
   `prueba real`, `UAT P…`), sin tocar CATL, Coches de Bomberos ni Concurso bomberos.
2. Marca todas las notificaciones in-app como leídas (`POST /notifications/read-all`).
3. Opcionalmente encola informes «dorados» (ejecutivo CATL y actores de Concurso bomberos). Con
   WeasyPrint activo el backend añade el artefacto PDF aunque el cliente pida solo html/json.

## Ejecución segura en Oracle Dev

```bash
export ORACLE_BASE_URL=https://oracle-dev.opnconsultoria.com
export ORACLE_EMAIL='…'
export ORACLE_PASSWORD='…'   # no commitear ni pegar en tickets

# 1. Preflight obligatorio: solo muestra el plan.
python3 scripts/demo_tenant_hygiene.py --expected-tenant 'SV2 Demo Tenant'

# 2. Aplicar exactamente el mismo alcance tras revisar el dry-run.
python3 scripts/demo_tenant_hygiene.py --expected-tenant 'SV2 Demo Tenant' --apply

# 3. Opcional: regenerar además los informes dorados.
python3 scripts/demo_tenant_hygiene.py \
  --expected-tenant 'SV2 Demo Tenant' \
  --apply \
  --with-golden-reports
```

Requisitos: Python 3.11+, red a Oracle Dev y usuario con `dossier.archive`, `report.generate` y
`notifications.read` (p. ej. owner). El script exige que el nombre del tenant activo coincida
exactamente con `--expected-tenant`; si no coincide, aborta antes de mutar. No uses la URL de
producción para esta limpieza.

## Referencia histórica (2026-07-26)

Expedientes visibles de demo: Coches de Bomberos, Gigafactoría CATL-Stellantis, Concurso bomberos.
Informes ready con PDF de referencia:

- Actores · Ecosistema Iturri (`a60d618a-…`)
- Ejecutivo CATL (`14a0381e-…`)
- Actores · ITURRI SCIS Ciudad Real (`1c72df9d-…`)

Notificaciones: `unread_count=0` tras aquel pase. Esta referencia no acredita el estado actual;
cada ejecución debe conservar su propio dry-run y resumen posterior.

## No cubre

- Borrado físico de datos (solo archivo y lectura de notificaciones).
- Materializar PDF sobre informes *ready* antiguos sin regenerar.
- Documentos (módulo deshabilitado) ni patentes EPO.
