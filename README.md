# Containerized Observability App

This project is a small production-style demo platform built to show how an application can be deployed behind a reverse proxy, scaled horizontally, observed with metrics and logs, and exercised with synthetic traffic.

The stack includes:

- A Flask API with Prometheus instrumentation and structured JSON logging
- Three application replicas behind NGINX
- PostgreSQL for persistent storage
- Prometheus for metrics collection
- Grafana for dashboards
- Loki + Promtail for centralized container logs
- An optional load generator for demos and testing
- A PostgreSQL backup script

The goal is not just to run a web app, but to demonstrate the full operational flow around it: routing, persistence, health checks, observability, rate limiting, and repeatable local deployment with Docker Compose.

## What the Project Does

The application exposes a small HTTP API that:

- returns service metadata from the root endpoint
- reports health and readiness
- records visit events in PostgreSQL
- stores and lists short messages
- exports Prometheus metrics

Every request goes through NGINX, which forwards traffic to one of three Flask replicas. Each replica:

- writes structured logs to stdout
- exports HTTP and custom business metrics on `/metrics`
- adds `X-Request-ID` and `X-App-Instance` headers to responses
- persists data into PostgreSQL through a connection pool

The observability stack collects both metrics and logs:

- Prometheus scrapes all three Flask instances and the NGINX exporter
- Grafana is pre-provisioned with Prometheus and Loki data sources
- Promtail discovers Docker containers through the Docker socket
- Loki stores container logs for log exploration in Grafana

## Architecture

```text
Client
  |
  v
NGINX (:80)
  |
  +--> app1 (:8000)
  +--> app2 (:8000)
  +--> app3 (:8000)
           |
           v
      PostgreSQL (:5432, internal)

Metrics flow:
Flask /metrics ----------> Prometheus (:9090) ----------> Grafana (:3000)
NGINX stub_status -> exporter (:9113) --/

Logs flow:
Docker container logs -> Promtail -> Loki (:3100) -> Grafana
```

## Main Components

### Application

The Flask app lives in [`app/`](./app) and is started with Gunicorn inside a Python 3.12 container.

It includes:

- automatic database connection retries on startup
- on-start schema safety through `CREATE TABLE IF NOT EXISTS`
- Prometheus HTTP metrics via `prometheus-flask-exporter`
- custom counters:
  - `app_visit_events_total`
  - `app_messages_created_total`
- structured JSON logs via `python-json-logger`

### Database

PostgreSQL stores two tables:

- `visit_events`
- `messages`

The schema is initialized in two ways:

- `database/init/01-init.sql` creates tables and inserts a seed message
- the Flask app also runs `ensure_schema()` on startup for extra safety

### Reverse Proxy

NGINX provides:

- a single public entrypoint on port `80`
- load balancing across `app1`, `app2`, and `app3`
- forwarded client headers
- request rate limiting
- a `stub_status` endpoint on port `8080` for exporter scraping

Two balancing modes are supported:

- round robin by default
- least connections through an override Compose file

### Monitoring and Logging

The `monitoring/` directory provisions the full observability layer:

- Prometheus scrape configuration
- Grafana data sources
- Grafana dashboard provisioning
- Loki configuration
- Promtail configuration

The prebuilt Grafana dashboard shows:

- request rate
- p95 request duration
- total visit events
- total created messages
- process RSS memory

### Load Testing

The `loadtest/` service generates mixed traffic against the app:

- `GET /`
- `GET /api/visits`
- `POST /api/messages`

It prints a JSON summary with:

- total requests
- errors
- effective requests per second
- latency statistics
- status code distribution
- endpoint distribution

### Backups

The `scripts/backup_postgres.sh` script creates a compressed PostgreSQL dump in the local `backups/` directory using `pg_dump` executed inside the running database container.

## Project Structure

```text
.
|-- app/
|   |-- Dockerfile
|   |-- main.py
|   `-- requirements.txt
|-- database/
|   `-- init/
|       `-- 01-init.sql
|-- loadtest/
|   |-- Dockerfile
|   |-- load_test.py
|   `-- requirements.txt
|-- monitoring/
|   |-- grafana/
|   |   |-- dashboards/
|   |   |   `-- flask-app.json
|   |   |-- dashboards.yml
|   |   `-- datasources.yml
|   |-- loki/
|   |   `-- local-config.yaml
|   |-- prometheus/
|   |   `-- prometheus.yml
|   |-- promtail/
|   |   `-- config.yml
|   `-- README.md
|-- nginx/
|   |-- conf.d/
|   |   |-- default.conf
|   |   `-- metrics.conf
|   |-- upstreams/
|   |   |-- least-connections.conf
|   |   `-- round-robin.conf
|   `-- nginx.conf
|-- scripts/
|   `-- backup_postgres.sh
|-- backups/
|-- docker-compose.yml
|-- docker-compose.leastconn.yml
|-- .env.example
`-- LICENSE
```

## Requirements

Before starting, make sure you have:

- Docker
- Docker Compose v2
- free local ports for `80`, `3000`, `3100`, `9090`, and `9113`

## Environment Variables

Copy the example environment file first:

```bash
cp .env.example .env
```

The main variables are:

| Variable | Default | Purpose |
|---|---|---|
| `APP_NAME` | `sna-demo-app` | Logical application name returned by the API |
| `PORT` | `8000` | Internal Flask/Gunicorn port |
| `POSTGRES_DB` | `app_db` | PostgreSQL database name |
| `POSTGRES_USER` | `app_user` | PostgreSQL user |
| `POSTGRES_PASSWORD` | `app_password` | PostgreSQL password |
| `POSTGRES_HOST` | `postgres` | Database hostname inside Docker network |
| `POSTGRES_PORT` | `5432` | Database port |
| `DB_CONNECT_RETRIES` | `20` | Number of DB connection retry attempts |
| `DB_CONNECT_DELAY` | `2` | Delay between DB retries in seconds |
| `DB_POOL_MAX_SIZE` | `10` | Max size of the app DB pool |

Additional variables in `.env.example` are useful for manual load-test runs, but the load generator itself reads `TARGET_URL` and the `LOAD_*` variables when the container starts.

## How to Run the Project

### 1. Start the default stack

This starts PostgreSQL, three app replicas, NGINX, Prometheus, Grafana, Loki, Promtail, and the NGINX exporter.

```bash
docker compose up -d --build
```

### 2. Open the services

| Service | URL | Notes |
|---|---|---|
| Application entrypoint | `http://localhost/` | Goes through NGINX |
| Grafana | `http://localhost:3000` | Login: `admin` / `admin` |
| Prometheus | `http://localhost:9090` | Scrape targets and PromQL |
| Loki | `http://localhost:3100` | Usually consumed through Grafana |
| NGINX exporter | `http://localhost:9113/metrics` | Exported NGINX metrics |

### 3. Check that the stack is healthy

```bash
curl http://localhost/health
curl http://localhost/ready
curl http://localhost/api/visits
curl http://localhost/api/messages
```

## Using the Least-Connections Balancer

Round robin is the default. To switch to least connections, start Compose with the override file:

```bash
docker compose -f docker-compose.yml -f docker-compose.leastconn.yml up -d --build
```

That override only changes the mounted upstream file used by NGINX.

## API Reference

### `GET /`

Returns general service information, including:

- application name
- replica instance ID
- hostname
- current UTC timestamp
- available endpoints

### `GET /health`

Simple liveness endpoint. It confirms that the application process is running.

### `GET /ready`

Readiness endpoint. It checks whether the app can successfully connect to PostgreSQL. If the database is unavailable, it returns HTTP `503`.

### `GET /metrics`

Prometheus metrics endpoint exposed by each Flask replica.

### `GET /api/visits`

Creates a new row in `visit_events` and returns:

- the created visit record
- the total number of recorded visits

This endpoint is intentionally state-changing so that dashboards have write activity to observe.

### `GET /api/messages?limit=N`

Returns the most recent messages ordered by `created_at DESC`.

Rules:

- default limit is `10`
- maximum limit is `100`
- non-integer values return HTTP `400`

### `POST /api/messages`

Stores a message in PostgreSQL.

Example:

```bash
curl -X POST http://localhost/api/messages \
  -H 'Content-Type: application/json' \
  -d '{"message":"hello from reviewer"}'
```

Behavior:

- empty or missing input becomes an auto-generated message
- messages are trimmed to 500 characters
- successful creation returns HTTP `201`

## How Load Balancing Works

The public endpoint is NGINX. It proxies requests to the upstream group named `flask_backend`, which contains:

- `app1:8000`
- `app2:8000`
- `app3:8000`

To help demonstrate which replica handled a request, the Flask app adds:

- `X-Request-ID`
- `X-App-Instance`

You can verify balancing with:

```bash
for i in $(seq 1 6); do
  curl -s -D - http://localhost/ -o /dev/null | grep X-App-Instance
done
```

## Rate Limiting

NGINX applies two request-rate policies:

- general traffic: `50r/s` with `burst=100`
- `/api/` traffic: `10r/s` with `burst=20`

When a limit is exceeded, NGINX returns HTTP `429`.

The `/health` location is intentionally lightweight and does not apply `limit_req`.

## Observability Guide

### Metrics

Prometheus scrapes:

- `app1:8000/metrics`
- `app2:8000/metrics`
- `app3:8000/metrics`
- `nginx-exporter:9113/metrics`

Useful metric families include:

- `flask_http_request_total`
- `flask_http_request_duration_seconds_*`
- `app_visit_events_total`
- `app_messages_created_total`
- `process_resident_memory_bytes`

### Dashboards

Grafana is preconfigured automatically. After login:

1. Open the default dashboard list.
2. Select `Flask App Dashboard`.
3. Generate a little traffic if the panels are empty at first.

### Logs

Promtail reads Docker container logs from `/var/run/docker.sock` and sends them to Loki.

The Flask app writes JSON logs with fields such as:

- log level
- logger name
- message
- request path
- request method
- response status
- request duration
- forwarded client IP

In Grafana Explore, you can inspect logs with queries such as:

```logql
{compose_service="app1"}
{compose_service="nginx"}
{level="INFO"}
```

## Load Testing

The load generator is optional and attached to the `loadtest` profile.

### Run with defaults

```bash
docker compose --profile loadtest run --rm loadtester
```

### Run with custom parameters

```bash
docker compose --profile loadtest run --rm \
  -e TARGET_URL=http://nginx \
  -e LOAD_DURATION=120 \
  -e LOAD_CONCURRENCY=20 \
  -e LOAD_INTERVAL=0.05 \
  -e LOAD_WRITE_RATIO=0.35 \
  loadtester
```

Parameter meaning:

| Variable | Meaning |
|---|---|
| `TARGET_URL` | Base URL to attack, usually `http://nginx` inside Compose |
| `LOAD_DURATION` | Test duration in seconds |
| `LOAD_CONCURRENCY` | Number of concurrent async workers |
| `LOAD_INTERVAL` | Sleep time between worker requests |
| `LOAD_WRITE_RATIO` | Probability of sending `POST /api/messages` |

This is useful for:

- populating Grafana charts
- testing rate limits
- generating logs for Loki
- showing behavior under concurrent traffic

## Database Backups

Create a compressed SQL backup with:

```bash
bash scripts/backup_postgres.sh
```

The script:

- detects the Compose file automatically
- runs `pg_dump` inside the `postgres` service
- compresses the dump with `gzip`
- stores the result in `backups/`

Common override variables:

| Variable | Purpose |
|---|---|
| `BACKUP_DIR` | Where the backup file will be written |
| `POSTGRES_SERVICE_NAME` | Compose service name of PostgreSQL |
| `POSTGRES_DB` | Database name |
| `POSTGRES_USER` | Database user |
| `POSTGRES_PASSWORD` | Database password |
| `COMPOSE_FILE_PATH` | Explicit Compose file path |

## Data Persistence

Docker named volumes are used for:

- PostgreSQL data
- Prometheus TSDB data
- Grafana state
- Loki data

Local files in `backups/` are stored on the host so they remain available outside the containers.

## Stop and Clean Up

Stop the stack:

```bash
docker compose down
```

Stop the least-connections variant:

```bash
docker compose -f docker-compose.yml -f docker-compose.leastconn.yml down
```

Remove containers and volumes:

```bash
docker compose down -v
```

## Troubleshooting

### `docker compose up` fails because a port is already in use

Free the conflicting local port or override the published ports before starting the stack.

### `/ready` returns `503`

The app is reachable, but PostgreSQL is not ready yet or the DB settings are incorrect. Wait a few seconds and try again.

### Grafana opens but panels are empty

This usually means there has not been enough traffic yet. Call the API a few times or run the load generator.

### You receive HTTP `429`

That means NGINX rate limiting is working. Slow down the request rate or reduce concurrency.

### No logs appear in Loki

Make sure Promtail is running and still has access to `/var/run/docker.sock`.

## Why a Reviewer Should Have Confidence in This Project

This repository demonstrates more than a basic Flask app:

- it is containerized end to end
- it runs multiple replicas behind a real reverse proxy
- it persists data in PostgreSQL
- it exposes health, readiness, and metrics endpoints
- it includes built-in observability for both metrics and logs
- it supports two balancing strategies
- it includes a repeatable load generator
- it includes an operational backup script

In other words, the project shows both application functionality and the operational concerns required to run and observe it like a small real-world service.

## License

This project is licensed under the MIT License. See [`LICENSE`](./LICENSE).
