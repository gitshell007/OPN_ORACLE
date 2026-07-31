# Monitor diario de servidores

El monitor genera un informe diario para info@opnconsultoria.com con:

- espacio libre de /, memoria disponible y estado de los servicios;
- tamaño de todas las bases PostgreSQL visibles en cada instancia;
- ejecuciones de tareas de las últimas 24 horas, agrupadas por estado y tipo;
- porcentaje de variación frente a la captura diaria anterior;
- Oracle: docker system df, contenedores activos, snapshots de
  /var/backups/opn-oracle y copia off-host.
- OpenRouter: gasto de las últimas 24 horas, total, variación, solicitudes, tokens y desglose
  por consumidor, modelo, tarea, proyecto, coste y estado. Se obtiene de `ai_usage_logs` en
  Signal y se calcula con los tokens y el catálogo de precios registrado; se etiqueta como coste
  registrado y no como factura descargada del proveedor.

La ejecución es externa al backend Flask: un host monitor conecta por SSH, recibe un pequeño
recolector por stdin y no instala agentes ni modifica los servidores consultados. El histórico se
guarda en /var/lib/opn-server-monitor/state.json; si un servidor falla, conserva su última base
válida para no contaminar la comparación siguiente.

## Instalación en Oracle

El monitor se instala como un release separado en /opt/opn-server-monitor/releases/<id> y
/opt/opn-server-monitor/current. La configuración no secreta se copia a:

    /etc/opn-server-monitor/server-health-monitor.toml

Secretos y confianza SSH:

    /etc/opn-server-monitor/secrets/id_ed25519          # root:root 0600
    /etc/opn-oracle/secrets/oracle_graph_client_secret # root:root 0400
    /etc/opn-server-monitor/known_hosts                  # root:root 0644

El fichero TOML de ejemplo es
infra/monitoring/server-health-monitor.toml.example. Reutiliza el secreto Graph existente de Oracle;
el TOML contiene tenant_id, client_id y el buzón remitente, pero nunca el client_secret.

Después de publicar el release:

    sudo /opt/opn-server-monitor/current/scripts/install-server-health-monitor.sh --install
    sudo systemctl start opn-server-health-report.service
    sudo journalctl -u opn-server-health-report.service -n 100 --no-pager

El timer queda programado a las 08:00 de Europe/Madrid, con hasta diez minutos de dispersión.
Persistent=true permite recuperar una ejecución perdida tras reiniciar el host.

El correo se entrega como HTML responsive: cabecera ejecutiva, tarjetas de KPIs, control de coste
OpenRouter y una tarjeta por servidor. A 430 px de ancho (viewport aproximado de un iPhone 16 Pro
Max) las métricas se apilan en dos columnas y el único detalle tabular, el desglose OpenRouter,
se desplaza horizontalmente dentro de su propia caja sin ensanchar el correo completo.

## Seguridad y límites

- La clave de monitorización es dedicada; no se reutiliza una clave de aplicación.
- El servicio conserva únicamente `CAP_DAC_READ_SEARCH` para poder leer el secreto Graph existente
  cuando su propietario sea un UID de contenedor no resuelto en el host; no se conceden capacidades
  de administración, red o ejecución privilegiada adicionales.
- El recolector solo ejecuta consultas de lectura (df, /proc, systemctl is-active, psql SELECT,
  docker ps/system df, du).
- No se imprimen secretos ni payloads de negocio. La respuesta de errores de Graph se generaliza.
- La primera captura no muestra porcentajes porque no existe baseline; desde la segunda sí.
- “Tareas ejecutadas” significa trabajos persistidos por cada aplicación: background_jobs,
  connector_run_logs, ai_analysis_jobs y tablas de ejecución equivalentes. No se infieren
  ejecuciones desde logs cuando la aplicación no las persiste.
- Si Signal no conserva coste para una fila OpenRouter, el informe cuenta la solicitud y la marca
  como coste no calculable; no inventa un precio.
