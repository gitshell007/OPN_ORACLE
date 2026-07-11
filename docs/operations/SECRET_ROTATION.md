# Rotación de secretos

## Objetivo y procedimiento

Rotar sin Git, argumentos ni logs. Materializar el secreto por canal seguro en
`/etc/opn-oracle/secrets`, owner numérico y `0400`; validar el consumidor, recrear solo servicios
afectados y revocar el anterior tras el smoke. Rotar `SECRET_KEY` implica reautenticación global.

## Fallo

Restaurar el valor anterior desde custodia segura. Una exposición sigue siendo incidente aunque la
rotación funcione.

