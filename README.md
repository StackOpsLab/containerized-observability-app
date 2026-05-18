# Student Project: Containerized Observability App

## Project Topic

**Highly Available Containerized Web App with Centralized Monitoring and Logging**

This is a student project for Docker and observability practice.  
We built a simple Flask web app with PostgreSQL, ran multiple replicas with Docker Compose, used NGINX as a reverse proxy, and added monitoring, logging, and CI/CD.

## Stack

- Python Flask
- PostgreSQL
- Docker Compose
- NGINX
- Prometheus
- Grafana
- Loki
- Promtail
- Node Exporter
- cAdvisor
- GitHub Actions

## What is included

- Flask API
- PostgreSQL database
- 3 app replicas
- NGINX load balancing and rate limiting
- Prometheus and Grafana for metrics
- Loki and Promtail for logs
- Node Exporter and cAdvisor for host/container metrics
- GitHub Actions CI/CD
- PostgreSQL backup script

## Run the project

```bash
cp .env.example .env
docker compose up -d --build
```

## Useful links

- App: `http://127.0.0.1/`
- Grafana: `http://127.0.0.1:3000`
- Prometheus: `http://127.0.0.1:9090`
- Loki health check: `http://127.0.0.1:3100/ready`
- NGINX exporter: `http://127.0.0.1:9113/metrics`

Grafana login:

- user: `admin`
- password: `admin`

## Quick check

```bash
curl http://127.0.0.1/health
curl http://127.0.0.1/ready
curl http://127.0.0.1/api/visits
curl http://127.0.0.1/api/messages
```

You can also run:

```bash
bash scripts/smoke_test.sh
```

## Load balancing

Default mode is `round robin`.

Check:

```bash
for i in $(seq 1 6); do
  curl -s -D - http://127.0.0.1/ -o /dev/null | grep X-App-Instance
done
```

PowerShell alternative:

```powershell
1..6 | ForEach-Object { (Invoke-WebRequest http://127.0.0.1/ -UseBasicParsing).Headers["X-App-Instance"] }
```

If you want `least connections`:

```bash
docker compose -f docker-compose.yml -f docker-compose.leastconn.yml up -d --build
```

After that, run the load balancing check again, because Docker Compose recreates containers when switching the mode.

To return to the default `round robin` mode:

```bash
docker compose up -d --build
```

## Monitoring and logs

Prometheus collects metrics from:

- `app1`
- `app2`
- `app3`
- `nginx-exporter`
- `node-exporter`
- `cadvisor`

Grafana dashboards:

- `Flask App Dashboard`
- `Infrastructure Overview`

Logs are viewed in Grafana Explore through the Loki datasource.

Example Loki query in Grafana Explore:

```logql
{container=~"containerized-observability-app.*"}
```

## Load test

```bash
docker compose --profile loadtest run --rm --no-deps loadtester
```

## Database backup

```bash
bash scripts/backup_postgres.sh
```

## CI/CD

Workflow file:

`.github/workflows/ci-cd.yml`

The pipeline:

- validates the project
- starts the stack
- runs the smoke test
- publishes the app image on push to `main`

## Stop the project

```bash
docker compose down
```

Full cleanup:

```bash
docker compose down -v
```
