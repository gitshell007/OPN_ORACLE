# Manifiesto de secretos de producción

Solo documenta nombres y formato. No guardes valores aquí. Los ficheros terminan como máximo en un
salto de línea y deben ser regulares, legibles únicamente por el proceso necesario.

| Archivo | Consumidor/propietario recomendado | Formato |
|---|---|---|
| `postgres_admin_password` | PostgreSQL init, `root:root 0400` | aleatorio fuerte URL-safe |
| `postgres_migrator_password` | PostgreSQL init, UID/GID `postgres` de la imagen, `0400` | aleatorio fuerte URL-safe |
| `postgres_app_password` | PostgreSQL init, UID/GID `postgres` de la imagen, `0400` | aleatorio fuerte URL-safe |
| `redis_password` | Redis init, `root:root 0400` | 43+ caracteres `[A-Za-z0-9_-]` |
| `oracle_secret_key` | app, `10001:10001 0400` | aleatorio, 32+ caracteres |
| `oracle_database_url` | app, `10001:10001 0400` | URL psycopg con `oracle_app` |
| `oracle_database_migration_url` | migrate, `10001:10001 0400` | URL psycopg con `oracle_migrator` |
| `oracle_redis_url` | app, `10001:10001 0400` | URL Redis ACL usuario `oracle`, DB 0 |
| `oracle_session_redis_url` | app, `10001:10001 0400` | misma credencial, DB 1 |
| `oracle_ratelimit_redis_url` | app, `10001:10001 0400` | misma credencial, DB 2 |
| `oracle_celery_broker_url` | app/workers, `10001:10001 0400` | misma credencial, DB 3 |
| `oracle_celery_result_url` | app/workers, `10001:10001 0400` | misma credencial, DB 4 |
| `oracle_graph_client_secret` | app/workers, `10001:10001 0400` | secreto de cliente de la app Entra; nunca el object ID |

Compose local usa mounts de archivos. No presupongas que `uid`, `gid` o `mode` declarados en YAML
se aplicarán a un bind mount: verifica ownership numérico en el host y lectura desde los
contenedores no-root antes de iniciar. No uses `docker compose config` sin `--quiet` en registros
compartidos, aunque el YAML solo referencia rutas.

En `postgres:17-bookworm` el usuario suele tener UID/GID `999`, pero no lo hardcodees sin verificar
la imagen realmente descargada. El entrypoint oficial lee `postgres_admin_password` antes de bajar
privilegios; los dos secrets de roles los lee después el init script como usuario `postgres`.

Las URLs contienen contraseñas y son secretos completos. Genéralas en una sesión interactiva
segura, con encoding correcto y sin argumentos de shell, historial, clipboard compartido o logs.
