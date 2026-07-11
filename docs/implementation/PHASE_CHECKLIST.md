# Checklist y dependencias de fases

```text
00 Orchestration
  -> 01 Audit
    -> 02 Flask foundation
      -> 03 Database + tenancy
        -> 04 Auth + sessions + RBAC
          -> 05 Frontend auth/admin
          -> 06 Oracle core
            -> 07 Celery + Redis
              -> 08 Signal adapter
              -> 09 AI runtime
              -> 10 Documents + evidence
                -> 11 Reports + notifications
                  -> 11A Information architecture
                    -> 12 Vector product completion
                      -> 13 Security/QA/readiness
                        -> 14 Production audit + approved changes
                          -> 15 CI/CD + backup/restore
                            -> 16 UAT + GO/NO-GO
```

## Gates

| Gate | Estado | Evidencia requerida |
|---|---|---|
| Interfaz canónica | resuelto | `CANONICAL_UI=vector`, decisión D-001 |
| Contrato Signal | abierto | Contrato v1, auth, monitor, cursor y webhook |
| Proveedor IA | abierto | Proveedor/modelos/región/redacción/coste |
| SMTP | abierto | Host/proveedor, remitente y credencial segura |
| Storage productivo | abierto | Backend, bucket/ruta, cifrado y retención |
| Acceso servidor | parcial | Credenciales recibidas; falta confirmar host/fingerprint mediante auditoría |
| Aplicar cambios servidor | bloqueado | Auditoría Etapa A revisada y autorización explícita posterior |
| Backup offsite | abierto | Destino, cifrado y retención |
| Release | bloqueado | Readiness sin critical/high, restore real y TLS renewal dry-run |

## Interfaz de comandos objetivo

Se propondrá un `Makefile` únicamente en la fase Flask si no aparece otra interfaz sólida:

```text
make api-install     make web-install
make api-lint        make web-lint
make api-typecheck   make web-typecheck
make api-test        make web-test
make api-migrate     make web-build
make api-run         make web-e2e
make dev-up          make dev-down
make logs            make smoke
make backup          make restore-test
```

## Regla de cierre

Cada fase requiere documentación actualizada, comandos con resultados reales y todos sus criterios de aceptación. Un gate abierto puede permitir mocks o trabajo local, pero nunca se presenta como integración productiva terminada.
