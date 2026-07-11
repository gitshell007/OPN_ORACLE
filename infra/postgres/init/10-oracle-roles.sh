#!/bin/sh
set -eu

read_secret() {
  variable_name="$1"
  file_variable_name="${variable_name}_FILE"
  eval "direct_value=\${$variable_name:-}"
  eval "secret_file=\${$file_variable_name:-}"

  if [ -n "$direct_value" ] && [ -n "$secret_file" ]; then
    printf '%s\n' "$variable_name and $file_variable_name are mutually exclusive" >&2
    exit 1
  fi
  if [ -n "$secret_file" ]; then
    if [ ! -f "$secret_file" ] || [ ! -r "$secret_file" ]; then
      printf '%s\n' "$file_variable_name must reference a readable regular file" >&2
      exit 1
    fi
    direct_value=$(sed -e 's/[[:space:]]*$//' "$secret_file")
  fi
  if [ -z "$direct_value" ]; then
    printf '%s\n' "$variable_name or $file_variable_name is required" >&2
    exit 1
  fi
  printf '%s' "$direct_value"
}

ORACLE_MIGRATOR_PASSWORD=$(read_secret ORACLE_MIGRATOR_PASSWORD)
ORACLE_APP_PASSWORD=$(read_secret ORACLE_APP_PASSWORD)
export ORACLE_MIGRATOR_PASSWORD ORACLE_APP_PASSWORD

psql --set=ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=database_name="$POSTGRES_DB" \
  --set=migrator_password="$ORACLE_MIGRATOR_PASSWORD" \
  --set=app_password="$ORACLE_APP_PASSWORD" <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'oracle_migrator') THEN
    CREATE ROLE oracle_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
      NOREPLICATION BYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'oracle_app') THEN
    CREATE ROLE oracle_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
      NOREPLICATION NOBYPASSRLS;
  END IF;
END
$$;

ALTER ROLE oracle_migrator WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT NOREPLICATION BYPASSRLS;
ALTER ROLE oracle_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT NOREPLICATION NOBYPASSRLS;

DO $$
DECLARE inherited_role record;
BEGIN
  FOR inherited_role IN
    SELECT granted.rolname
    FROM pg_auth_members membership
    JOIN pg_roles granted ON granted.oid = membership.roleid
    JOIN pg_roles member ON member.oid = membership.member
    WHERE member.rolname = 'oracle_app'
  LOOP
    EXECUTE format('REVOKE %I FROM oracle_app', inherited_role.rolname);
  END LOOP;
END
$$;

ALTER ROLE oracle_migrator PASSWORD :'migrator_password';
ALTER ROLE oracle_app PASSWORD :'app_password';
ALTER DATABASE :"database_name" OWNER TO oracle_migrator;
ALTER SCHEMA public OWNER TO oracle_migrator;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE :"database_name" TO oracle_app;
SQL
