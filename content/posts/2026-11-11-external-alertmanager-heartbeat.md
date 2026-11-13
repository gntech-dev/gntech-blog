---
title: "Detect a Silent Alertmanager With an External Heartbeat"
description: "Send a continuous Prometheus alert through Alertmanager to Healthchecks.io and test the warning you get when those check-ins stop."
date: 2026-11-11T18:00:00-04:00
draft: false
ShowToc: true
tags: [prometheus, alertmanager, observability, monitoring, homelab]
keywords: [Alertmanager watchdog, Prometheus heartbeat, Healthchecks.io, dead man's switch]
summary: "Use an outside observer to detect a broken alert path even when your monitoring host cannot send its own warning."
cover:
  image: "/images/posts/external-alertmanager-heartbeat/featured.webp"
  alt: "A lit communications mast on a distant ridge seen from a dark server room."
  caption: "AI-generated editorial artwork."
  relative: false
---

When Alertmanager stops sending notifications, the same failure can prevent it from telling you what happened. A heartbeat reverses that dependency. Prometheus keeps a synthetic alert firing, Alertmanager sends regular webhooks, and an external monitor tells you when those webhooks stop arriving.

![Prometheus sends a synthetic alert to Alertmanager on the monitored host. Alertmanager checks in with Healthchecks.io, which alerts through a separate channel when check-ins stop.](/images/posts/external-alertmanager-heartbeat/flow.svg)

The heartbeat covers one route from rule evaluation through webhook delivery. It can detect a dead evaluator, an unavailable Alertmanager, a suppressed watchdog route, or loss of outbound connectivity, but the absence alone cannot distinguish among them. Test your regular paging routes separately.

## 1. Create a disposable external check

Use a Linux test host with Prometheus, Alertmanager, and their matching validation tools, `promtool` and `amtool`. Run the processes as your ordinary user. This lab uses ports 19090 and 19093 on loopback, outbound HTTPS to Healthchecks.io, and a test notification channel you can read without the monitored host. Ensure the ports are free before starting.

In Healthchecks.io, create a check with a **Simple** schedule, a **1 minute period**, and a **2 minute grace time**. Assign a test integration such as email that delivers independently of your own Alertmanager. Copy the UUID-style HTTPS success URL for the new check. Keep it secret because anyone with it can send false check-ins.

The sample sends a repeat every minute under normal conditions. The additional grace time allows for scheduling and delivery jitter. If the last accepted ping was at 18:00, the check becomes late at about 18:01 and down around 18:03 if nothing else arrives. Notification delivery can add time beyond the down transition.

## 2. Start Alertmanager

In a Bash terminal, create a private working directory. Paste the success URL at the hidden prompt, without any suffix. Copy the printed directory path for the second terminal. The receiver reads the URL from a file. Keep that file out of version control, screenshots, and diagnostics you share.

```bash
umask 077
lab="$(mktemp -d /tmp/gntech-watchdog.XXXXXX)"
cd "$lab" || exit 1
pwd

read -r -s -p 'Healthchecks.io success URL: ' ping_url
printf '\n'
if [[ "$ping_url" =~ ^https://hc-ping\.com/[[:xdigit:]-]{36}$ ]]; then
  printf '%s\n' "$ping_url" > ping-url
else
  unset ping_url
  printf 'Enter the UUID-style HTTPS success URL.\n' >&2
  exit 1
fi
unset ping_url

cat > alertmanager.yml <<YAML
route:
  receiver: discard
  routes:
    - receiver: watchdog
      matchers:
        - 'alertname="GntechWatchdogLab"'
      group_by: [alertname]
      group_wait: 5s
      group_interval: 15s
      repeat_interval: 1m
receivers:
  - name: discard
  - name: watchdog
    webhook_configs:
      - url_file: "$lab/ping-url"
        send_resolved: false
YAML

amtool check-config alertmanager.yml &&
alertmanager --config.file=alertmanager.yml --storage.path=alertmanager-data \
  --web.listen-address=127.0.0.1:19093 --cluster.listen-address=
```

The repeat interval is a multiple of the group interval. Resolved notifications are disabled because a webhook to this URL counts as a successful ping regardless of the alert status in its JSON body. Healthchecks.io can store that body with the ping event. Keep this receiver dedicated to the synthetic alert, with no sensitive annotations or labels.

## 3. Start Prometheus

Open a second Bash terminal and replace the example directory with the printed path.

```bash
cd /tmp/gntech-watchdog.REPLACE || exit 1
cat > watchdog.rules.yml <<'YAML'
groups:
  - name: watchdog-lab
    rules:
      - alert: GntechWatchdogLab
        expr: vector(1)
YAML

cat > prometheus.yml <<'YAML'
global:
  evaluation_interval: 15s
rule_files:
  - watchdog.rules.yml
alerting:
  alertmanagers:
    - static_configs:
        - targets: ['127.0.0.1:19093']
scrape_configs: []
YAML

promtool check config prometheus.yml &&
prometheus --config.file=prometheus.yml --storage.tsdb.path=prometheus-data \
  --web.listen-address=127.0.0.1:19090
```

The expression produces one sample on every evaluation, so the alert fires without depending on a scrape target. Open the Prometheus Alerts page at `http://127.0.0.1:19090/alerts` on the test host, then check Healthchecks.io's Events tab for at least two distinct success pings roughly one minute apart. Use the external event timestamps as evidence of delivery. An HTTP 200 alone is insufficient because the ping API can also return 200 for an ignored request.

## 4. Prove that silence produces an outside warning

1. After the second accepted ping, stop **Alertmanager only** with Ctrl+C in its terminal. Leave Prometheus running and the external check unpaused. Record the last accepted ping time.
2. Expect the check to go Late and then Down. Record the Down time and confirm the test channel actually received the warning. If the dashboard shows Down but the message is missing, investigate the external notification integration.
3. Restart Alertmanager from the same directory with the previous command. Wait for a fresh ping in Events and verify the check goes Up. A restart can retain recent notification state, so allow for the repeat interval.
4. After the drill, pause or delete the disposable check to avoid a false page. Stop both processes. Remove the ping URL file with `rm -- /tmp/gntech-watchdog.REPLACE/ping-url` after substituting the actual directory. Keep only the timing evidence you need.

| Observation | Where to look |
| --- | --- |
| The alert never fires | Rule file loading and evaluation in Prometheus. |
| The rule fires but Alertmanager has no alert | The configured target and connectivity from Prometheus. |
| Alertmanager sees the alert but external Events stop | Matchers, silences, inhibition, outbound DNS and TLS, and the receiver URL. |
| The check goes Down but the warning never arrives | The external check's assigned integration and delivery history. |

For a permanent check, keep the observer and its escalation channel outside the network, power, and credentials that the monitored system relies on. Give each site or independently monitored alert path its own check. Two senders that share a check can hide each other's failures. Size the period and grace from observed delivery gaps and the outage window you can tolerate. The [Infrastructure Series monitoring guide](/posts/2026-11-05-gntech-infrastructure-part-11-monitoring/) covers how to test missing data at the source.

## Official references

- [Prometheus alerting rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
- [Alertmanager routes and webhook configuration](https://prometheus.io/docs/alerting/latest/configuration/)
- [Healthchecks.io schedules](https://healthchecks.io/docs/configuring_checks/)
- [Healthchecks.io ping API](https://healthchecks.io/docs/http_api/)
- [Healthchecks.io notification integrations](https://healthchecks.io/docs/configuring_notifications/)
