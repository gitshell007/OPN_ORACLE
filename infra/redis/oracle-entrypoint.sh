#!/bin/sh
set -eu

secret_file=${REDIS_PASSWORD_FILE:-/run/secrets/redis_password}
if [ ! -f "$secret_file" ] || [ ! -r "$secret_file" ]; then
  printf '%s\n' 'REDIS_PASSWORD_FILE must reference a readable regular file' >&2
  exit 1
fi

password=$(sed -e 's/[[:space:]]*$//' "$secret_file")
case "$password" in
  *[!A-Za-z0-9_-]*|'')
    printf '%s\n' 'Redis password must be non-empty and URL-safe (A-Z, a-z, 0-9, _ or -)' >&2
    exit 1
    ;;
esac
if [ "${#password}" -lt 43 ]; then
  printf '%s\n' 'Redis password must contain at least 43 URL-safe characters' >&2
  exit 1
fi

install -d -m 0700 -o redis -g redis /run/oracle-redis
umask 077
{
  # Keep the default user disabled but password-protected so Redis protected mode does not treat
  # the instance as an unauthenticated deployment before the named user runs AUTH.
  printf 'user default off >%s ~* &* -@all\n' "$password"
  printf 'user oracle on >%s ~* &* +@all -ACL -CONFIG -DEBUG -MODULE -SHUTDOWN -FLUSHALL -FLUSHDB\n' "$password"
} > /run/oracle-redis/users.acl
chown redis:redis /run/oracle-redis/users.acl
unset password

exec /usr/local/bin/docker-entrypoint.sh \
  redis-server /usr/local/etc/redis/redis.conf \
  --aclfile /run/oracle-redis/users.acl
