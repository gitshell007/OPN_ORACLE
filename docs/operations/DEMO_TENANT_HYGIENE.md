# Higiene del tenant de demo

Checklist operativa para dejar el tenant de demostración presentable (Vector).

## Qué hace

1. Archiva expedientes cuyo título contiene marcadores de prueba (`AUDIT-TEST`, `Playwright`,
   `prueba real`, `UAT P…`), sin tocar CATL, Coches de Bomberos ni Concurso bomberos.
2. Marca todas las notificaciones in-app como leídas (`POST /notifications/read-all`).
3. Opcionalmente encola informes «dorados» (ejecutivo CATL y actores de Concurso bomberos). Con
   WeasyPrint activo el backend añade el artefacto PDF aunque el cliente pida solo html/json.

## Ejecución

```bash
export ORACLE_BASE_URL=https://oracle.opnconsultoria.com
export ORACLE_EMAIL='…'
export ORACLE_PASSWORD='…'   # no commitear ni pegar en tickets

python3 scripts/demo_tenant_hygiene.py
python3 scripts/demo_tenant_hygiene.py --with-golden-reports
```

Requisitos: Python 3.11+, red a producción, usuario con `dossier.archive`, `report.generate` y
`notifications.read` (p. ej. owner).

## Tras la higiene (2026-07-26)

Expedientes visibles de demo: Coches de Bomberos, Gigafactoría CATL-Stellantis, Concurso bomberos.
Informes ready con PDF de referencia:

- Actores · Ecosistema Iturri (`a60d618a-…`)
- Ejecutivo CATL (`14a0381e-…`)
- Actores · ITURRI SCIS Ciudad Real (`1c72df9d-…`)

Notificaciones: `unread_count=0` tras el pase.

## No cubre

- Borrado físico de datos (solo archivo y lectura de notificaciones).
- Materializar PDF sobre informes *ready* antiguos sin regenerar.
- Documentos (módulo deshabilitado) ni patentes EPO.
