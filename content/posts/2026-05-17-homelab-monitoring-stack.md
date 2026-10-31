---
title: "Homelab Monitoring with Docker Compose — Prometheus and Grafana Foundations"
description: "Build and verify a small Prometheus and Grafana stack, then add exporters, logs and notifications with clear boundaries."
date: 2026-05-17T14:30:00-04:00
lastmod: 2026-10-31
draft: false
aliases:
  - /posts/2026-05-09-homelab-monitoring-stack/
tags:
  - docker
  - monitoring
  - homelab
  - prometheus
  - grafana
summary: "A small monitoring foundation you can verify before adding host exporters, Loki, Alloy and notification routing. Includes Compose, datasource provisioning and a troubleshooting checklist."
---

A dashboard is useful only when you know what its data represents. Start by proving that Prometheus can scrape a target and Grafana can query Prometheus. Add host metrics, container metrics, logs and notifications after that path works.

This guide consolidates the two earlier monitoring-stack posts. It replaces their overlapping all-in-one examples with a smaller foundation and explains the prerequisites for extending it. The commands are examples, not evidence of a deployment tested during this update.

## Verification status

| Scope | Evidence and limits |
| --- | --- |
| Environment | Docker host or VM with the Compose plugin; Prometheus and Grafana images must be selected and recorded by the reader. |
| Previously reported lab observations | The consolidated two-service example is proposed configuration; no runtime result is claimed for it. |
| Preparation checks | 6 Bash blocks passed syntax checks and 3 generated YAML files parsed during preparation. |
| Still to verify | Run Compose and promtool validation, start the selected releases, and confirm the self-scrape query succeeds from Grafana. Test backups separately. |

*This table summarizes the evidence recorded for this article. It is not a new hardware test or a certification for other versions.*

## Know which component does what

![Connection path from the browser through host loopback port 3000 to Grafana, then over the Compose network to Prometheus; Prometheus scrapes its own metrics endpoint.](/images/diagrams/monitoring-path.svg)

*The initial two-service deployment. Arrows show requests; replies return along those connections. On a remote host, use an SSH tunnel for browser access. Container-local localhost and the host's loopback address are different endpoints.*

| Component | Responsibility |
| --- | --- |
| Prometheus | Scrape metrics, store time series and evaluate alert rules |
| Grafana | Query configured data sources and display results |
| Node Exporter | Expose operating-system metrics for the environment it can observe |
| cAdvisor or another suitable exporter | Expose container metrics, subject to runtime and permission requirements |
| Loki | Store and query logs |
| Alloy | Collect and forward telemetry; not a replacement for a queryable metrics database |
| Alertmanager | Route Prometheus alerts to configured receivers |

The initial deployment below includes **Prometheus and Grafana only**. It scrapes Prometheus itself. A successful self-scrape is a pipeline check, not proof that your Proxmox hosts or application containers are monitored.

## Prerequisites and image selection

Use a dedicated Docker host or VM with Docker Engine and the Docker Compose plugin, persistent storage, and a backup plan. This example creates a new directory under your home folder. Do not overwrite an existing monitoring deployment with it.

```bash
docker compose version
mkdir -p "$HOME/homelab-monitoring-foundation"
cd "$HOME/homelab-monitoring-foundation"
mkdir -p prometheus grafana/provisioning/datasources
```

Select supported image releases from the official projects, including an explicit tag or digest. The old posts' image tags are historical examples, not current security recommendations. Enter your reviewed image references when prompted:

```bash
read -r -p 'Prometheus image, including reviewed tag/digest: ' PROMETHEUS_IMAGE
read -r -p 'Grafana image, including reviewed tag/digest: ' GRAFANA_IMAGE
read -r -s -p 'New Grafana admin password: ' GRAFANA_ADMIN_PASSWORD
printf '\n'
export PROMETHEUS_IMAGE GRAFANA_IMAGE GRAFANA_ADMIN_PASSWORD
```

For example, the repositories are `prom/prometheus` and `grafana/grafana`; append versions you have reviewed rather than using an unversioned reference. The exports apply to this shell. Retain the chosen references and password in your approved configuration/secret store so another session can manage the same deployment. Do not commit secrets to Git or share rendered Compose configuration containing the password.

## Create the configuration

Prometheus starts with one target and a seven-day time retention setting:

```bash
cat > prometheus/prometheus.yml <<'EOF'
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: prometheus
    static_configs:
      - targets: ['localhost:9090']
EOF
cat > grafana/provisioning/datasources/prometheus.yml <<'EOF'
apiVersion: 1
datasources:
  - name: Prometheus
    uid: prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false
EOF
cat > compose.yaml <<'EOF'
services:
  prometheus:
    image: ${PROMETHEUS_IMAGE:?Select a reviewed Prometheus image}
    restart: unless-stopped
    command:
      - --config.file=/etc/prometheus/prometheus.yml
      - --storage.tsdb.path=/prometheus
      - --storage.tsdb.retention.time=7d
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus_data:/prometheus
    ports:
      - "127.0.0.1:9090:9090"

  grafana:
    image: ${GRAFANA_IMAGE:?Select a reviewed Grafana image}
    restart: unless-stopped
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:?Set a Grafana admin password}
      GF_AUTH_ANONYMOUS_ENABLED: "false"
    volumes:
      - ./grafana/provisioning/datasources:/etc/grafana/provisioning/datasources:ro
      - grafana_data:/var/lib/grafana
    ports:
      - "127.0.0.1:3000:3000"

volumes:
  prometheus_data:
  grafana_data:
EOF
docker compose config --quiet
docker compose run --rm --no-deps --entrypoint /bin/promtool \
  prometheus check config /etc/prometheus/prometheus.yml
docker compose up -d
```

The two containers use the Compose project's default network. Grafana reaches Prometheus by its service name, not through Grafana's own `localhost`.

The host ports bind only to loopback. Use a local browser, an SSH tunnel, or a deliberately configured authenticated proxy. This example does not configure Traefik, public access, or TLS.

The Grafana password setting initializes a new database. Changing the environment value does not necessarily reset the administrator password in an existing persistent Grafana database; use the supported password-reset procedure for your installed release.

## Verify the whole initial path

```bash
docker compose ps
docker compose logs --tail=50 prometheus grafana
curl --fail http://127.0.0.1:9090/-/ready
curl --fail http://127.0.0.1:3000/api/health
curl --fail --get http://127.0.0.1:9090/api/v1/query \
  --data-urlencode 'query=up{job="prometheus"}'
```

Wait for a scrape interval after startup. The query should return a successful response containing a sample value of `1` for the Prometheus target. If the response is empty or reports `0`, inspect the target and logs before importing dashboards.

Open Grafana at `http://127.0.0.1:3000`, log in, and select the provisioned Prometheus source in Explore. Run `up{job="prometheus"}` there too. This checks Grafana's access to Prometheus, which separate readiness responses alone cannot prove.

For a remote Docker host, forward the two loopback ports with your existing SSH access. Run this on your client, replacing the example destination:

```bash
ssh -N -L 3000:127.0.0.1:3000 -L 9090:127.0.0.1:9090 user@monitoring-host
```

Choose different local ports if those are already occupied on your client.

## Add host and container metrics deliberately

Install a supported Node Exporter on the host you actually want to measure, or use its documented container deployment with the required namespaces and filesystem mounts. An exporter inside an LXC can observe a different environment from the Proxmox host. Docker NAT alone is not what determines metric accuracy.

Add its reachable management address to the existing `scrape_configs` list. The following is a fragment, not a replacement file:

```yaml
  - job_name: node
    static_configs:
      - targets: ['YOUR_NODE_MANAGEMENT_ADDRESS:9100']
```

Restrict exporter access to the intended scraper. Validate the configuration with `promtool`, restart Prometheus after saving it, and query `up{job="node"}`. Use host metrics in dashboards only after confirming the target and labels represent the expected machine.

For container metrics, follow the selected exporter's deployment instructions for your Docker version, cgroup configuration and storage driver. Do not add privileged mode or broad host mounts without understanding why the collector requires them. Dashboard IDs are not compatibility guarantees; check the metrics, labels and data source expected by an imported dashboard.

## Add logs as a separate pipeline

For log collection, see the [Alloy and Loki guide](/posts/2026-05-14-grafana-alloy-log-collection/), checking its versions and validation limits before adapting it. The pipeline is collector → Loki → Grafana. Configure Loki as a Loki data source; Alloy's metrics endpoint is not a Prometheus query API.

Before deploying, confirm whether the collector uses Docker discovery/API access, JSON files, or the system journal. The selected method needs matching mounts, permissions, labels and persistent collection state. A filesystem glob is not Docker API discovery, and mounting a Docker socket read-only does not turn its API into a read-only API.

Configure retention using the mechanism supported by the selected Loki schema and storage backend. A retention duration alone is not proof deletion is active. Never reclaim space by manually removing arbitrary chunk files from a live indexed store.

## Add alerts and test delivery

An alert rule, an Alertmanager route and an external notification are separate checks. Validate rule files with `promtool`, configure Prometheus to reach Alertmanager, validate Alertmanager configuration with its version's `amtool`, and send a controlled test through the full route.

Do not assume Alertmanager expands shell variables in a bind-mounted YAML file. Use the receiver's supported secret-file fields or a deliberate configuration-generation step. A value such as \`${TELEGRAM_CHAT_ID}\` in an ordinary file is not automatically replaced by Docker Compose.

Also distinguish a failing scrape from a target removed entirely from the configuration. An `up == 0` rule checks existing failed scrapes; it does not establish an inventory of every service that ought to exist. Container disappearance may remove a time series instead of leaving a durable failure value.

## Maintenance and rollback

Back up configuration and use a supported consistent backup method for persistent data, especially Grafana's database. Record the image references used for each working deployment. A time retention setting is not a disk-capacity guarantee; monitor growth and leave free space for normal operation.

Before an upgrade, review the release notes and data-format compatibility. Returning to an older image is not always safe after a database migration. Keep a tested restore path as well as the previous configuration.

To stop the example while retaining its named volumes:

```bash
docker compose down
```

Do not add `--volumes` unless you intend to delete the stored monitoring data. Restart using the same Compose project identity and the recorded image references. A fresh volume creates a fresh deployment, not a restoration of your historical data.

## Continue reading

- [Alloy and Loki log collection](/posts/2026-05-14-grafana-alloy-log-collection/) — Explore the separate log pipeline after verifying the metrics path.
- [Docker Compose health checks](/posts/2026-05-14-docker-compose-healthchecks/) — Understand why a running container and a ready service are different states.
- [Proxmox Backup Server](/posts/2026-05-08-proxmox-backup-server-setup/) — Plan guest recovery alongside monitoring; dashboards do not replace backups.

## Validation and references

The update consolidates the previous May 9 and May 17 articles. It removes unsupported claims of a fixed RAM footprint, complete ready-made dashboards, and confirmed incident outcomes. Bash syntax and configuration structure can be checked locally; this example has not been deployed or exercised against a live Docker host during preparation. Live upstream retrieval was unavailable.

- [Prometheus installation and Docker deployment](https://prometheus.io/docs/prometheus/latest/installation/)
- [Prometheus configuration](https://prometheus.io/docs/prometheus/latest/configuration/configuration/)
- [Node Exporter](https://github.com/prometheus/node_exporter)
- [Grafana Docker installation](https://grafana.com/docs/grafana/latest/setup-grafana/installation/docker/)
- [Grafana data source provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/)
- [Loki retention](https://grafana.com/docs/loki/latest/operations/storage/retention/)

Check the documentation for the exact releases selected before deploying. A useful first result is modest and observable: a real scrape, a successful query from Grafana, and a clear plan for the next target.
