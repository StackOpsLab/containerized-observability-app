# Member C Deliverables

This repository contains the application and data-layer artifacts for the team project:

- A Flask demo app with PostgreSQL integration.
- A production-ready application Dockerfile.
- PostgreSQL persistence and initialization assets.
- A simple backup script based on `pg_dump`.
- A containerized load generator for dashboards and log aggregation.

## Project layout

- `app/`: Flask application source and Dockerfile.
- `loadtest/`: Async HTTP load generator and Dockerfile.
- `database/init/`: SQL executed by the PostgreSQL container on first boot.
- `scripts/backup_postgres.sh`: Creates compressed SQL backups into `./backups`.
- `compose.member-c.yml`: Compose fragment for Member A to merge into the final stack.

## Application endpoints

- `GET /`: service info, hostname, instance id, and exposed routes.
- `GET /health`: liveness endpoint.
- `GET /ready`: readiness endpoint with live PostgreSQL probe.
- `GET /api/visits`: persists a visit event and returns the running total.
- `GET /api/messages`: returns the most recent messages.
- `POST /api/messages`: inserts a new message row.
- `GET /metrics`: Prometheus scrape endpoint for request and app metrics.

The app writes JSON logs to stdout, which makes it easy for Promtail/Loki or ELK to collect and index container logs.

## Local run

1. Copy `.env.example` values into your local shell or a `.env` file.
2. Start the app and database:

```bash
docker compose -f compose.member-c.yml up --build
```

3. Generate traffic for dashboards:

```bash
docker compose -f compose.member-c.yml --profile loadtest up --build loadtester
```

4. Create a PostgreSQL backup:

```bash
./scripts/backup_postgres.sh
```

## Handoff notes

- Member A can merge `compose.member-c.yml` into the final `docker-compose.yml`.
- The PostgreSQL persistence volume is `postgres_data`.
- The PostgreSQL initialization scripts live in `./database/init`.
- Member B can scrape the Flask app at `http://app:8000/metrics`.
- The load generator is meant to target NGINX in the final topology, so `TARGET_URL` defaults should point to the reverse proxy in the team compose file.
