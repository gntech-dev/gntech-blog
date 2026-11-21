---
title: "Measure Transaction Retry Amplification with Prometheus"
description: "Count logical requests, transaction attempts and final outcomes separately, then inspect retry amplification without unbounded labels."
date: 2026-11-21T18:00:00-04:00
draft: false
ShowToc: true
tags: [prometheus, python, monitoring, reliability]
keywords: [transaction retry metrics, retry amplification, Prometheus counters, bounded labels]
summary: "A loopback-only synthetic worker with counter assertions, scrape configuration and PromQL for attempts and exhaustion."
cover:
  image: "/images/posts/retry-amplification/featured.webp"
  alt: "A brass tally counter beside two rows of blue glass beads on a warmly lit homelab desk."
  caption: "AI-generated conceptual editorial artwork; not a monitoring dashboard."
  relative: false
---

A worker can finish most requests while quietly making several database attempts for each one. A success counter alone hides that extra work. Count logical requests, transaction attempts and final outcomes at separate boundaries so retry pressure remains visible.

This standalone companion to the [GNTECH monitoring chapter](/posts/2026-11-05-gntech-infrastructure-part-11-monitoring/) uses a synthetic Python worker and the Prometheus Python client. It needs Python 3.11+ and `curl`; a Prometheus server is needed only for the scrape/query portion. It does not contact PostgreSQL or reproduce database failures. The example measures event accounting, not database recovery or GNTECH production behavior.

Preparation status: five counter tests and a local HTTP scrape/shutdown check passed with prometheus-client 0.21.1. No live Prometheus server, database integration or notification route was exercised.

## 1. Define the counting boundaries

| Metric | Increment boundary |
| --- | --- |
| `gntech_tx_requests_started_total` | Once when a logical request enters this worker's retry controller. |
| `gntech_tx_attempts_total` | Immediately before every complete transaction attempt, including the first. |
| `gntech_tx_requests_finished_total{outcome="committed"}` | Once after the operation returns with commit confirmed. |
| `gntech_tx_requests_finished_total{outcome="exhausted"}` | Once when a retryable abort consumes the final allowed attempt. |
| `gntech_tx_requests_finished_total{outcome="error"}` | Once for an ordinary exception outside that retryable-abort path. |

The outcome label has exactly three allowed values. Request IDs, user IDs, SQL text, exception messages and arbitrary SQLSTATE strings belong in appropriate logs, not labels. Prometheus adds target labels such as `job` and `instance`; those also contribute to total series count.

An attempt's callback must own the whole transaction and return only after commit. A retryable exception must escape **after rollback/cleanup**, before the next attempt starts. The fixture below models that contract with a custom exception. Real Psycopg workers can catch `DeadlockDetected` and `SerializationFailure` at this same boundary, while preserving their existing retry limit and delay policy.

## 2. Run a small metrics fixture

Create a fresh directory and virtual environment:

```bash
mkdir retry-metrics-lab
cd retry-metrics-lab
python3 -m venv .venv
. .venv/bin/activate
python -m pip install 'prometheus-client==0.21.1'
```

Save this as `retry_metrics.py`. The synthetic abort class and immediate retries keep the counting demonstration self-contained; this is not a production database retry implementation.

```python
import time
from prometheus_client import CollectorRegistry, Counter, start_http_server


class RetryAbort(Exception):
    pass


class Metrics:
    def __init__(self):
        self.registry = CollectorRegistry()
        self.started = Counter(
            "gntech_tx_requests_started", "Logical requests started",
            registry=self.registry)
        self.attempts = Counter(
            "gntech_tx_attempts", "Complete transaction attempts started",
            registry=self.registry)
        self.finished = Counter(
            "gntech_tx_requests_finished", "Logical requests finished",
            ["outcome"], registry=self.registry)
        for outcome in ("committed", "exhausted", "error"):
            self.finished.labels(outcome)

    def run(self, operation):
        self.started.inc()
        for attempt in range(1, 4):
            self.attempts.inc()
            try:
                result = operation()
            except RetryAbort:
                if attempt == 3:
                    self.finished.labels("exhausted").inc()
                    raise
            except Exception:
                self.finished.labels("error").inc()
                raise
            else:
                self.finished.labels("committed").inc()
                return result


def operation(failures=0, permanent=False):
    calls = 0
    def invoke():
        nonlocal calls
        calls += 1
        if permanent:
            raise ValueError("synthetic permanent failure")
        if calls <= failures:
            raise RetryAbort("synthetic transaction abort")
        return "committed"
    return invoke


def exercise(metrics):
    metrics.run(operation())
    metrics.run(operation(failures=2))
    try:
        metrics.run(operation(failures=99))
    except RetryAbort:
        pass
    try:
        metrics.run(operation(permanent=True))
    except ValueError:
        pass


if __name__ == "__main__":
    metrics = Metrics()
    exercise(metrics)
    server, thread = start_http_server(
        9815, addr="127.0.0.1", registry=metrics.registry)
    try:
        while True:
            time.sleep(10)
            exercise(metrics)
    except KeyboardInterrupt:
        server.shutdown()
        server.server_close()
        thread.join()
```

Start `python retry_metrics.py` in Terminal A and leave it running. In Terminal B:

```bash
curl --fail --silent --show-error http://127.0.0.1:9815/metrics
```

Each completed batch adds four logical requests and eight attempts: one immediate success, one success after two aborts, one exhaustion and one permanent error. It adds two committed outcomes, one exhausted outcome and one error. Counter values grow every ten seconds; do not expect a later scrape to retain the first batch's absolute values.

The endpoint listens only on loopback. Keep this fixture and its scrape target separate from production dashboards. A remote Prometheus server cannot reach this address; use your approved private monitoring path when adapting the worker. This example uses a single process; several worker processes require an appropriate client-library deployment model rather than unrelated counters behind one load-balanced endpoint.

## 3. Assert the counters before trusting a graph

Save as `test_retry_metrics.py`:

```python
import unittest
from retry_metrics import Metrics, RetryAbort, operation, exercise


class MetricTests(unittest.TestCase):
    def value(self, metrics, name, labels=None):
        return metrics.registry.get_sample_value(name, labels or {})

    def check_case(self, callback, error, attempts, outcome):
        metrics = Metrics()
        if error:
            with self.assertRaises(error):
                metrics.run(callback)
        else:
            self.assertEqual(metrics.run(callback), "committed")
        self.assertEqual(self.value(metrics, "gntech_tx_requests_started_total"), 1)
        self.assertEqual(self.value(metrics, "gntech_tx_attempts_total"), attempts)
        for label in ("committed", "exhausted", "error"):
            self.assertEqual(self.value(
                metrics, "gntech_tx_requests_finished_total", {"outcome": label}),
                int(label == outcome))

    def test_first_attempt(self):
        self.check_case(operation(), None, 1, "committed")

    def test_recovery(self):
        self.check_case(operation(failures=2), None, 3, "committed")

    def test_exhaustion(self):
        self.check_case(operation(failures=99), RetryAbort, 3, "exhausted")

    def test_permanent_error(self):
        self.check_case(operation(permanent=True), ValueError, 1, "error")

    def test_batch_accounting(self):
        metrics = Metrics()
        exercise(metrics)
        self.assertEqual(self.value(metrics, "gntech_tx_requests_started_total"), 4)
        self.assertEqual(self.value(metrics, "gntech_tx_attempts_total"), 8)
        self.assertEqual(self.value(metrics, "gntech_tx_requests_finished_total",
                                    {"outcome": "committed"}), 2)


if __name__ == "__main__":
    unittest.main()
```

Run `python -m unittest -v test_retry_metrics`. Expect five passing cases. A process killed between start and finish can leave a request without an outcome; these tests cover completed callback paths, not abrupt termination. Cancellations derived from `BaseException` are also outside the ordinary `Exception` accounting path.

## 4. Scrape from Prometheus on the same host

Add this job under the existing `scrape_configs` list. Do not replace other jobs. The address assumes Prometheus runs in the same host network namespace; a container's loopback belongs to that container.

```yaml
- job_name: retry-metrics-lab
  scrape_interval: 5s
  static_configs:
    - targets: ['127.0.0.1:9815']
```

Validate your complete configuration with `promtool check config prometheus.yml`, then reload it through your established deployment process. Check the target in Prometheus and query:

```promql
up{job="retry-metrics-lab"}
```

Expect 1 while the endpoint can be scraped. A responding exporter does not itself prove the real application or database is healthy. Collect several scrapes before evaluating rates.

## 5. Read amplification and exhaustion separately

Attempts per started logical request over five minutes:

```promql
(
  sum(rate(gntech_tx_attempts_total{job="retry-metrics-lab"}[5m]))
  /
  sum(rate(gntech_tx_requests_started_total{job="retry-metrics-lab"}[5m]))
)
and on()
(
  sum(rate(gntech_tx_requests_started_total{job="retry-metrics-lab"}[5m])) > 0
)
```

The positive-denominator condition suppresses an idle window rather than displaying a misleading zero or dividing by zero. This fixture should tend toward 2 attempts per request over a stable window. It is a windowed workload ratio, not an exact per-request distribution: attempts and starts can cross window boundaries, and scrapes can occur mid-request. A ratio above 1 reveals extra work even when eventual success remains common.

Use rates before summing so counter resets are handled per series. Counters reset on process restart. Increments between the last scrape and a crash may be lost; these metrics are operational signals, not a durable audit ledger.

Exhausted requests over ten minutes:

```promql
sum(increase(gntech_tx_requests_finished_total{
  job="retry-metrics-lab",outcome="exhausted"
}[10m]))
```

`increase` extrapolates across the range, so its result can be fractional. An alert expression of the form `sum(increase(...[10m])) > 0` detects observed exhaustion; choose the window, traffic floor and notification policy for the real workload. This synthetic fixture exhausts one request every batch, so do not route it to production paging.

Check scrape health separately:

```promql
up{job="retry-metrics-lab"} == 0
```

A removed target may have no `up` series, and missing application metrics do not mean zero failures. Use the expected target inventory and a separate missing-target check. The three outcome series are initialized at startup, making a zero distinct from an outcome label that was never created.

## 6. Adapt the event boundaries and clean up

Put one request-start increment outside the real retry loop, one attempt increment immediately before each complete transaction callback, and exactly one final outcome at the controller's exit. Do not increment the committed outcome at the last SQL statement if commit has not completed. Keep request identities in logs so operators can investigate exhaustion without creating a time series per request.

Stop the fixture with Ctrl+C in Terminal A, remove its scrape job, validate/reload the configuration, and remove any lab-only dashboard panels or alert expressions. The local tests and HTTP scrape can validate exposition; a live Prometheus scrape, query window and notification delivery remain separate checks.

## References

Official documentation reviewed November 21, 2026:

- [Prometheus instrumentation and metric types](https://prometheus.io/docs/practices/instrumentation/)
- [Metric naming and label cardinality](https://prometheus.io/docs/practices/naming/)
- [Python client counters and initialized labels](https://prometheus.github.io/client_python/instrumenting/labels/)
- [Python client HTTP exporter lifecycle](https://prometheus.github.io/client_python/exporting/http/)
- [PromQL rate and increase behavior](https://prometheus.io/docs/prometheus/latest/querying/functions/)
