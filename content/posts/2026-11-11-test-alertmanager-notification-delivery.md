---
title: "Test Alertmanager Delivery When an Alert Never Reaches You"
description: "Send an isolated Alertmanager API test alert, capture its firing and resolved webhooks, and locate the failure between rule evaluation and notification delivery."
date: 2026-11-11T00:00:00-04:00
draft: false
ShowToc: true
tags: [prometheus, alertmanager, observability, troubleshooting, homelab]
keywords: [Alertmanager webhook test, Alertmanager API v2, missing notification, alert routing]
summary: "Use a loopback webhook to verify the delivery path without paging anyone, then trace a real alert from the evaluator to its receiver."
cover:
  image: "/images/posts/alertmanager-notification-test/featured.webp"
  alt: "Amber indicator on a dark operations bench beside a compact network rack."
  caption: "AI-generated editorial artwork."
  relative: false
---

A firing rule tells you the evaluator detected a condition. A received notification tells you that the event also reached Alertmanager, matched a route, survived any suppression rules, and reached the destination. When an alert goes missing, test these stages independently.

This lab uses an isolated Alertmanager instance and a Python webhook receiver on a Linux test host. Install Alertmanager and its matching amtool, plus Python 3, Bash, curl, and the usual Linux utilities. Use an ordinary account. Both listeners are on loopback and use disposable state. There is no production paging route or credential in the example.

## 1. Start a local webhook capture

Check that ports 19093 and 18084 are available. In a first terminal, create a temporary directory and note the path printed by `pwd`.

```bash
ss -ltn '( sport = :19093 or sport = :18084 )'
lab="$(mktemp -d /tmp/gntech-notify.XXXXXX)"
cd "$lab" || exit 1
pwd

cat > capture.py <<'PY'
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path

class Capture(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/alerts":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 65536:
                raise ValueError("invalid payload length")
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict) or "alerts" not in payload:
                raise ValueError("missing alert list")
        except (ValueError, TypeError):
            self.send_error(400)
            return
        with Path("received.jsonl").open("a", encoding="utf-8") as output:
            output.write(json.dumps(payload) + "\n")
        self.send_response(204)
        self.end_headers()

HTTPServer(("127.0.0.1", 18084), Capture).serve_forever()
PY

python3 capture.py
```

## 2. Start an isolated Alertmanager

In a second terminal, replace the placeholder with the printed directory. The child route sends only alerts labeled `purpose="notification-lab"` to the capture. The default receiver has no integrations.

```bash
cd /tmp/gntech-notify.REPLACE || exit 1
mkdir -p state

cat > alertmanager.yml <<'YAML'
route:
  receiver: discard
  group_by: [alertname]
  group_wait: 1s
  group_interval: 5s
  repeat_interval: 10m
  routes:
    - receiver: capture
      matchers:
        - 'purpose="notification-lab"'

receivers:
  - name: discard
  - name: capture
    webhook_configs:
      - url: http://127.0.0.1:18084/alerts
        send_resolved: true
YAML

amtool check-config alertmanager.yml &&
alertmanager --config.file=alertmanager.yml --storage.path=state \
  --web.listen-address=127.0.0.1:19093 --cluster.listen-address=
```

The short grouping intervals are for the lab. A production notification may arrive later because of grouping, delivery retries, or routing policy. An alert that resolves before the initial group wait can finish without a firing notification.

## 3. Test firing and resolution separately

In a third terminal, use the lab directory and check readiness. Create a sender that submits the same labels and start time for both states. A future end time gives the test alert an expiry if you leave the lab running.

```bash
cd /tmp/gntech-notify.REPLACE || exit 1
curl --fail --silent --show-error http://127.0.0.1:19093/-/ready
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
send_lab_alert() {
  python3 - "$started" "$1" <<'PY' |
import datetime
import json
import sys

start, state = sys.argv[1:]
now = datetime.datetime.now(datetime.timezone.utc)
end = now + datetime.timedelta(minutes=5) if state == "firing" else now
print(json.dumps([{
    "labels": {"alertname": "GntechDeliveryLab", "purpose": "notification-lab"},
    "annotations": {"summary": "Disposable notification test"},
    "startsAt": start,
    "endsAt": end.isoformat(timespec="seconds"),
}]))
PY
  curl --fail --silent --show-error --max-time 5 \
    -H 'Content-Type: application/json' --data-binary @- \
    http://127.0.0.1:19093/api/v2/alerts
}

send_lab_alert firing
```

Wait for the firing webhook to appear before sending resolution. Keep the same shell so `started` and the function are preserved.

```bash
python3 - <<'PY'
import json
from pathlib import Path
for line in Path("received.jsonl").read_text().splitlines():
    entry = json.loads(line)
    print(entry["receiver"], entry["status"], entry["groupLabels"])
PY
```

Look for receiver `capture`, status `firing`, and alert name `GntechDeliveryLab`. Then run `send_lab_alert resolved` and repeat the capture check after the next grouping interval. The expected evidence is a second notification with status `resolved`. A successful API request alone only confirms that Alertmanager accepted the alert.

## 4. Trace a missing production notification

| Evidence | Where to investigate next |
| --- | --- |
| Rule never fires | Inspect the query, evaluation errors, labels, and pending duration. |
| Rule fires but Alertmanager lacks the alert | Check the evaluator's Alertmanager target, connectivity, and alert relabeling. |
| Alertmanager has the alert but the destination sees nothing | Inspect matching routes, silences, inhibition, mute intervals, and delivery errors. |
| Webhook arrives but no one is notified | Check the integration downstream of the webhook, including its permissions and routing. |

The direct API test starts at Alertmanager. Use a real test rule and representative telemetry to check the full path from the evaluator. For a related test of data delivery, see the [log destination outage guide](/posts/2026-11-10-test-log-delivery-during-destination-outage/).

Stop Alertmanager and the capture with Ctrl+C in their own terminals. Keep the captured payloads if needed for review. Use a fresh temporary directory for another run so old notifications and state cannot affect your results.

## Official references

- [Alertmanager API clients](https://prometheus.io/docs/alerting/latest/clients/)
- [Alertmanager routing, timing, and webhook configuration](https://prometheus.io/docs/alerting/latest/configuration/)
- [Python HTTP server](https://docs.python.org/3/library/http.server.html)
