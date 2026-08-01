# Modelo de credencial por tenant (MDEV-01)

1. Signal emite N API keys bajo el consumer de entorno (p. ej. `opn-oracle-dev`).
2. Cada key se liga server-side a **un** `external_tenant_id` en la política de memoria
   (`allowed_external_tenant_ids` y/o binding de credencial).
3. Oracle guarda la key cifrada en `IntegrationConnection` **del tenant** (nunca en el frontend
   tras el alta; nunca compartida entre tenants).
4. Rotación: nueva key → update connection del tenant → revoca la anterior en Signal.
5. Revocación de un tenant no invalida keys de otros.
6. Scopes de la key: `memory:read`, `memory:write`, más monitores/señales/ai según necesidad.
7. Un único secreto de conexión cubre memory + monitores + `/ai/run`; no se exige segundo secreto
   legacy obligatorio.
