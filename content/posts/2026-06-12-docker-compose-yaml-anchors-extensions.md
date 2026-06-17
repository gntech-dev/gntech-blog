---
title: "Docker Compose YAML Anchors & Extensions — DRY Multi-Service Deployments"
description: "Stop repeating config across docker-compose services. Learn YAML anchors, x-blocks, and extension patterns to write clean, maintainable Compose files for your homelab."
date: 2026-06-12T18:00:00-04:00
tags:
  - docker
  - compose
  - yaml
  - homelab
  - automation
keywords:
  - Docker Compose YAML anchors reusable configuration blocks
  - Docker Compose x-extension blocks homelab deployment
  - Docker Compose DRY multi-service compose file patterns
  - Docker Compose YAML merge fragment logging configuration
  - Docker Compose anchor alias logging restart resource pattern
  - Docker Compose compose profiles YAML fragments homelab
  - docker compose dry config cleanup reusable deploy config
summary: "Stop copying config between services. Use YAML anchors, x-blocks, and fragment merging to write clean, DRY docker-compose files for your homelab. Practical patterns with real examples."
canonical: "https://blog.gntech.me/posts/docker-compose-yaml-anchors-extensions/"
---

Si tu `docker-compose.yml` tiene más de 15 servicios —como cualquier homelab que lleve un par de años creciendo— probablemente te duele mantenerlo. Cada nuevo servicio copia los mismos bloques de logging, restart policy, redes, y recursos. Cuando decides cambiar el driver de logging de json-file a local, toca editar 12 servicios uno por uno. Y en algún momento alguien se olvida de uno y los logs no rotan.

YAML anchors, aliases, y extension blocks (`x-`) resuelven esto. Son una característica del lenguaje YAML que Docker Compose entiende nativamente, sin plugins, sin herramientas externas, sin nada más que sintaxis YAML estándar. Esta guía cubre cómo usarlos en tu homelab con ejemplos reales que puedes copiar y adaptar.

## YAML Anchors and Aliases — The Foundation for Reusable Compose Config

YAML tiene un mecanismo nativo para definir un bloque de configuración una vez y reutilizarlo en varios lugares: los anchors (marcados con `&nombre`) y los aliases (marcados con `*nombre`).

```yaml
# anchor definition
x-logging: &logging
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"

services:
  app:
    image: nginx:alpine
    logging: *logging   # <-- alias

  db:
    image: postgres:16-alpine
    logging: *logging   # <-- same config, no repetition
```

El anchor `&logging` marca un bloque YAML completo. El alias `*logging` lo inserta en el lugar donde se usa. Docker Compose lo resuelve antes de validar el archivo, así que es como si hubieras escrito el bloque completo en cada servicio.

La regla de oro: mira tu compose file actual. Cualquier bloque que aparezca igual en tres o más servicios es candidato a ser un anchor.

## x- Extension Blocks for Structured Reusable Compose Fragments

Docker Compose ignora silenciosamente cualquier llave de nivel superior que comience con `x-`. Esto las convierte en el vehículo ideal para agrupar anchors de forma legible y predecible.

En lugar de esparcir definiciones `&logging`, `&restart` y `&resource` por todo el archivo, las agrupas en una sección `x-` al inicio:

```yaml
x-restart: &restart
  restart: unless-stopped

x-logging: &logging
  logging:
    driver: "json-file"
    options:
      max-size: "10m"
      max-file: "3"

x-healthcheck: &health
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost/health"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 40s

x-resource-limits: &limits
  deploy:
    resources:
      limits:
        memory: 512M
        cpus: "0.5"
      reservations:
        memory: 128M
```

Beneficio inmediato: todas las configuraciones reutilizables están en un mismo lugar, al inicio del archivo. Cambias el driver de logging una vez y se propaga a todos los servicios que usan `*logging`.

## Anchors and Merge Key (<<) for Service Composition

Los aliases simples (`*logging`) funcionan para bloques individuales, pero cuando cada servicio necesita combinar logging + restart + resources + redes, escribir `*logging`, `*restart`, `*limits` dentro de cada servicio sigue siendo verboso. Aquí entra el merge key de YAML (`<<`).

El merge key fusiona uno o varios anchors en un mapa, permitiendo sobreescribir campos específicos por servicio:

```yaml
x-defaults: &defaults
  <<: [*restart, *logging, *limits]
  networks:
    - internal
  security_opt:
    - "no-new-privileges:true"

services:
  api:
    <<: *defaults
    image: myapp/api:latest
    environment:
      DB_HOST: postgres
    ports:
      - "8080:8080"

  worker:
    <<: *defaults
    image: myapp/worker:latest
    environment:
      QUEUE: default
    deploy:
      resources:
        limits:
          memory: 1G
```

El orden importa: los campos definidos después del merge key sobreescriben los que vienen del anchor. En el ejemplo, `worker` hereda `*limits` del defaults (512M) pero lo sobreescribe con 1G.

## Real-World Homelab Example — DRY Monitoring Stack with Compose Anchors

Veamos un ejemplo completo. Un stack de monitoreo con Grafana, Prometheus, Loki, y Alloy, usando los patrones anteriores:

```yaml
x-restart: &restart
  restart: unless-stopped

x-logging: &logging
  logging:
    driver: "local"
    options:
      max-size: "10m"

x-resources: &limits
  deploy:
    resources:
      limits:
        memory: 512M
        cpus: "0.5"

x-defaults: &defaults
  <<: [*restart, *logging, *limits]
  networks:
    - monitoring

services:
  grafana:
    <<: *defaults
    image: grafana/grafana:latest
    container_name: grafana
    ports:
      - "3000:3000"
    volumes:
      - grafana-data:/var/lib/grafana
    environment:
      GF_SECURITY_ADMIN_PASSWORD: "${GF_ADMIN_PASSWORD}"
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: "1.0"

  prometheus:
    <<: *defaults
    image: prom/prometheus:latest
    container_name: prometheus
    ports:
      - "9090:9090"
    volumes:
      - prometheus-data:/prometheus
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.retention.time=30d"

  loki:
    <<: *defaults
    image: grafana/loki:latest
    container_name: loki
    ports:
      - "3100:3100"
    volumes:
      - loki-data:/loki
      - ./loki-config.yml:/etc/loki/config.yml:ro
    command:
      - "-config.file=/etc/loki/config.yml"

  alloy:
    <<: *defaults
    image: grafana/alloy:latest
    container_name: alloy
    ports:
      - "12345:12345"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./alloy/config.alloy:/etc/alloy/config.alloy:ro
    environment:
      LOKI_URL: "http://loki:3100/loki/api/v1/push"
      PROMETHEUS_URL: "http://prometheus:9090/api/v1/write"

volumes:
  grafana-data:
  prometheus-data:
  loki-data:

networks:
  monitoring:
    driver: bridge
```

Sin anchors, este mismo archivo tendría cuatro bloques de `logging:`, cuatro bloques de `restart:`, cuatro bloques de `deploy:resources:`, y cuatro bloques de `networks:`. Con los anchors, la sección `x-` centraliza todo y cada servicio declara solo lo que le es específico: image, container_name, ports, volumes, environment, y command.

Para iniciar el stack:

```bash
# variables de entorno
export GF_ADMIN_PASSWORD=secure_password_here

# levantar todo
docker compose up -d

# verificar que todos usan el logging correcto
docker compose logs grafana | head -5
```

## Common Docker Compose YAML Pitfalls and Limitations

Los anchors son poderosos, pero tienen limitaciones que debes conocer para evitar bugs difíciles de depurar.

### Anchors No Pueden Mergear Secuencias (Listas)

El merge key `<<` solo funciona con mapas (YAML mappings/dictionaries). No puedes mergear listas. Esto es relevante porque en Compose hay campos como `depends_on`, `ports`, `volumes`, y `networks` que son listas.

```yaml
# ESTO NO FUNCIONA
x-ports: &ports
  - "80:80"
  - "443:443"

services:
  web:
    ports: *ports    # alias OK, pero no puedes mergear con <<
```

Solución: usa el alias directamente (`*ports`), no el merge key. Si necesitas combinar puertos de un anchor con puertos específicos del servicio, tendrás que escribirlos todos en el servicio o usar un anchor que ya contenga todo.

### Anchors Son Referencias, No Copias

Un anchor YAML es una referencia, no una copia. Si defines un anchor de environment y un servicio lo modifica después del alias, el anchor original NO se modifica —pero ten cuidado con objetos mutables compartidos.

En la práctica, para Compose esto no es problema porque los values son escalares (strings, números) o mapas planos. Nunca estamos mutando objetos después de creados.

### Orden de Resolución del Merge Key

Cuando usas `<<: *defaults` seguido de campos propios del servicio, el orden es:

1. Se aplica el merge key primero (todo lo que viene de `*defaults`)
2. Se aplican los campos explícitos del servicio después

Esto significa que puedes sobreescribir cualquier campo del defaults:

```yaml
services:
  heavy-worker:
    <<: *defaults
    image: myapp/worker:latest
    # sobreescribe el deploy del defaults
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: "2.0"
```

### No Puedes Usar << Dentro de Bloques Anidados

El merge key solo funciona en el nivel donde lo colocas. Si `*defaults` contiene `deploy:` con recursos dentro, no puedes hacer un `<<:` dentro de `deploy` para mezclar recursos del defaults con recursos extra. El merge es plano.

Solución: si necesitas combinar, define el bloque completo en el servicio y omite el anchor correspondiente, o crea variantes del anchor (por ejemplo, `*limits-default` y `*limits-large`).

## Resumen: Docker Compose DRY Patterns for Your Homelab

Tres patrones para aplicar hoy mismo:

1. **x-blocks**: Define `x-logging`, `x-restart`, `x-resources` al inicio de tu compose file. Agrupa toda la configuración reusable en un solo lugar visible.

2. **Defaults composition**: Crea un `x-defaults` con `<<: [*restart, *logging, *limits]` y reutiliza `*defaults` en todos los servicios. Sobreescribe por servicio cuando sea necesario.

3. **Override on demand**: Los anchors no son rígidos — cada servicio puede heredar defaults y cambiar cualquier campo. Usa esto para servicios con requisitos especiales de memoria o redes.

El patrón más impactante con el que puedes empezar hoy: agrega un bloque `x-logging: &logging` con `driver: "local"` y `max-size: "10m"`, luego úsalo en todos tus servicios con `logging: *logging`. Es un cambio de una línea por archivo que evita que los logs de tus contenedores se coman el disco del host.

```bash
# Verifica que tu compose file es válido con anchors
docker compose config > /dev/null && echo "✅ Compose file is valid"
```

El comando `docker compose config` resuelve todos los anchors y muestra el archivo final expandido — útil para depurar si algo no se aplica como esperas.
