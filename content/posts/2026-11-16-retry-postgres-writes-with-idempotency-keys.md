---
title: "Retry PostgreSQL Writes Safely After Losing the Response"
description: "Use an idempotency key to return the original result after an uncertain commit, and verify that the write happened once."
date: 2026-11-16T00:00:00-04:00
draft: false
ShowToc: true
tags: [postgresql, reliability, docker, homelab]
keywords: [PostgreSQL idempotency key, ambiguous commit, retry duplicate writes]
summary: "Simulate losing a successful response, replay the original key and check the database for duplicate writes."
cover:
  image: "/images/posts/postgres-idempotent-writes/featured.webp"
  alt: "A hand places a brass token into a slot on a warm-lit homelab workbench."
  caption: "AI-generated editorial artwork."
  relative: false
---

A caller times out while submitting a request. PostgreSQL may have committed the write just before the response disappeared. Opening a new connection restores communication, but the caller still needs to know what happened to the original request. If the caller retries with the same idempotency key, the database can return the original result without creating a second row.

This companion to the [PostgreSQL Docker deployment guide](/posts/2026-05-28-postgresql-docker-homelab-deployment/) uses a disposable PostgreSQL 16 instance. It discards a successful result on purpose to reproduce uncertainty at the caller. It does not inject a fault during PostgreSQL's wire-level commit. The expected observations below are for your lab.

## 1. Create the lab and its uniqueness constraint

Use Docker Compose v2 and OpenSSL. In a fresh directory, generate a disposable password.

```bash
mkdir postgres-retry-lab
cd postgres-retry-lab
(umask 077 && printf 'LAB_PASSWORD=%s\n' "$(openssl rand -hex 24)" > .env)
```

Save this as `compose.yaml`. PostgreSQL has no published port. All SQL runs through `docker compose exec`.

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: retrylab
      POSTGRES_USER: retrylab
      POSTGRES_PASSWORD: "${LAB_PASSWORD:?Generate a disposable lab password}"
```

Start the container, then repeat the readiness check until it accepts TCP connections.

```bash
docker compose -p postgres-retry-lab up -d
docker compose -p postgres-retry-lab exec -T db pg_isready -h 127.0.0.1 -U retrylab -d retrylab
```

Set up the schema in a fresh instance. Here, the business row itself stores the request key and the original result. The database enforces one row per caller and request key.

```bash
lab_sql() {
  docker compose -p postgres-retry-lab exec -T db \
    psql -X -U retrylab -d retrylab -v ON_ERROR_STOP=1 "$@"
}

lab_sql -f - <<'SQL'
CREATE TABLE lab_order (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    caller text NOT NULL,
    request_key text NOT NULL,
    item text NOT NULL,
    UNIQUE (caller, request_key)
);

CREATE FUNCTION submit_order(p_caller text, p_key text, p_item text)
RETURNS bigint LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    order_id bigint;
    saved_item text;
BEGIN
    INSERT INTO lab_order (caller, request_key, item)
    VALUES (p_caller, p_key, p_item)
    ON CONFLICT (caller, request_key) DO NOTHING
    RETURNING id INTO order_id;

    IF FOUND THEN
        RETURN order_id;
    END IF;

    SELECT id, item INTO STRICT order_id, saved_item
    FROM lab_order
    WHERE caller = p_caller AND request_key = p_key;

    IF saved_item IS DISTINCT FROM p_item THEN
        RAISE EXCEPTION 'request key already used with different input';
    END IF;

    RETURN order_id;
END;
$$;
SQL
```

Run this function at **Read Committed** isolation. A concurrent insert can win the unique-key conflict while its row is outside the first statement's snapshot. The separate lookup in this volatile function gets a fresh snapshot and can see the committed winner. A single-statement fallback lookup can miss that row. The example assumes these request records are retained and their inputs stay immutable throughout the retry window.

## 2. Lose the first result and retry

Keep the same key on the retry. The first command discards the returned ID after a successful execution. The unique constraint remains the authority when another session repeats the request.

```bash
lab_sql -c "SELECT submit_order('lab-client', 'lost-reply-1', 'sample-item');" >/dev/null
lab_sql -At -c "SELECT submit_order('lab-client', 'lost-reply-1', 'sample-item');"
lab_sql -At -c "SELECT id, item FROM lab_order
  WHERE caller = 'lab-client' AND request_key = 'lost-reply-1';"
```

The replay should return the ID from the sole stored row. Now try a changed request with the same key. This command should fail and leave the original row unchanged.

```bash
lab_sql -c "SELECT submit_order('lab-client', 'lost-reply-1', 'different-item');"
```

## 3. Rehearse two concurrent attempts

In the same Bash shell, run two requests with a fresh key. Both results should be equal and the stored count should be one. Use a new key on each repeat if you want to exercise insertion again.

```bash
results="$(mktemp -d)"
lab_sql -At -c "SELECT submit_order('lab-client', 'race-1', 'sample-item');" > "$results/a" &
left=$!
lab_sql -At -c "SELECT submit_order('lab-client', 'race-1', 'sample-item');" > "$results/b" &
right=$!
wait "$left" && wait "$right" && test -s "$results/a" && cmp "$results/a" "$results/b" &&
  lab_sql -At -c "SELECT count(*) FROM lab_order
    WHERE caller = 'lab-client' AND request_key = 'race-1';"
rm -f -- "$results/a" "$results/b"
rmdir "$results"
```

## 4. Carry the rule into your application

Generate the key once per logical operation before the first request, then preserve it across retries. Derive the caller scope from authenticated identity. If a request has several meaningful fields, compare all of them or store a digest of a canonical representation. For a multi-table write, commit the business changes and the stored result together. Keep the key for at least as long as callers may retry. A retry after key expiration may create a new operation.

An external action such as sending a notification needs its own delivery safeguards. If the transaction records a pending event for a separate worker, give that event a stable ID so delivery can also be deduplicated. Clean up the disposable lab with `docker compose -p postgres-retry-lab down --volumes`.

## References

- [PostgreSQL 16 INSERT and conflict handling](https://www.postgresql.org/docs/16/sql-insert.html)
- [PostgreSQL 16 transaction isolation](https://www.postgresql.org/docs/16/transaction-iso.html)
- [PostgreSQL 16 function volatility and snapshots](https://www.postgresql.org/docs/16/xfunc-volatility.html)
